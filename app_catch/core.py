"""Pure data contracts. No cookies, browser internals or network requests."""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class ContractError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


ALLOWED_HOSTS = {"app.diandian.com", "www.diandian.com", "vip.diandian.com"}
SAFE_QUERY_KEYS = {"id", "country", "market", "device", "date", "start", "end", "lang", "time", "timetype"}


def safe_url(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in ALLOWED_HOSTS or p.username or p.password:
        raise ContractError("Only HTTPS DianDian page URLs are supported")
    if p.port not in (None, 443):
        raise ContractError("Unexpected page port")
    return urlunsplit((p.scheme, p.netloc, p.path,
                      urlencode([(k, v) for k, v in parse_qsl(p.query) if k in SAFE_QUERY_KEYS]), ""))


def number(raw):
    """Parse a single display value; ranges, percentages, estimates '<N' stay unknown."""
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip().replace(",", "")
    if text.lower() in {"", "--", "—", "-", "n/a", "null", "未知", "暂无数据"}:
        return None
    match = re.fullmatch(r"(?:US\$|USD|CNY|RMB|[$¥￥€£])?\s*([+-]?\d+(?:\.\d+)?)\s*(万|亿|[kKmMbB])?", text)
    if not match:
        return None
    scale = {None: 1, "万": 10000, "亿": 100000000,
             "k": 1000, "m": 1000000, "b": 1000000000}
    try:
        return str(Decimal(match[1]) * scale.get((match[2] or "").lower(), scale.get(match[2], 1)))
    except InvalidOperation:
        return None


def valid_context(context):
    required = {"market", "country", "store", "device", "category", "chart", "data_date"}
    if not required.issubset(context):
        raise ContractError("Missing context fields: " + str(sorted(required - set(context))))
    if context["market"] not in {"appstore", "googleplay", "android_cn"}:
        raise ContractError("Unsupported market")
    if not re.fullmatch(r"[A-Z]{2}", context["country"]):
        raise ContractError("country must be a two-letter uppercase code, not 'global'")
    if context["market"] == "android_cn" and context["country"] != "CN":
        raise ContractError("Domestic Android requires CN")
    if not all(isinstance(context[k], str) and context[k] for k in required):
        raise ContractError("Context values must be nonempty strings")
    date.fromisoformat(context["data_date"])


def validate_bundle(bundle):
    if bundle.get("schema_version") != 1 or bundle.get("source") != "diandian":
        raise ContractError("Unsupported bundle contract/source")
    valid_context(bundle["context"])
    datetime.fromisoformat(bundle["collected_at"])
    if bundle.get("status") not in {"SUCCEEDED", "PARTIAL"}:
        raise ContractError("Only successful or explicitly partial bundles can be imported")
    if bundle.get("context_verified") is not True:
        raise ContractError("Unverified page context cannot enter the data store")
    if not isinstance(bundle.get("rows"), list) or not bundle["rows"]:
        raise ContractError("Empty result is not a successful chart")
    safe_url(bundle["source_url"])
    for row in bundle["rows"]:
        if not row.get("name") or not row.get("listing_key"):
            raise ContractError("Each row needs name and listing_key")
        if row.get("detail_url"):
            safe_url(row["detail_url"])
        for metric in row.get("metrics", []):
            if metric.get("name") not in {"revenue", "downloads", "price", "rating", "rating_count", "rank"}:
                raise ContractError("Unknown metric name")
            for key in ("unit", "basis", "scope", "period"):
                if not metric.get(key):
                    raise ContractError("Metric requires unit, basis, scope and period")
            if metric["name"] in {"price", "revenue"} and not metric.get("currency"):
                raise ContractError("Money metric needs explicit currency, including UNKNOWN")
            value = metric.get("value")
            if value is not None and number(value) is None:
                raise ContractError("Invalid numeric value")
            if value is not None and Decimal(str(value)) < 0 and metric["name"] != "revenue":
                raise ContractError("Negative value is not valid for this metric")
    return bundle


def normalize_row(raw, metric_specs):
    url = safe_url(raw["detail_url"]) if raw.get("detail_url") else None
    key = raw.get("listing_key") or url
    if not key or not raw.get("name", "").strip():
        raise ContractError("Row missing identity/name")
    metrics = []
    for spec in metric_specs:
        original = raw.get(spec["field"])
        metric = {k: spec.get(k) for k in ("name", "unit", "currency", "basis", "scope", "period")}
        metric.update(raw=original, value=number(original),
                      missing_reason=None if number(original) is not None else "missing_or_unparseable",
                      is_estimate=spec.get("is_estimate", False))
        metrics.append(metric)
    return {"listing_key": key, "name": raw["name"].strip(), "detail_url": url,
            "metrics": metrics, "raw_fields": raw}
