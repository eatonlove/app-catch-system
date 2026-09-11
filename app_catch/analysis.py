"""Comparable daily growth leads, not opportunity/paid-user predictions."""
import csv
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from .core import ContractError, write_json


def analyze(bundles, request):
    needed = {"market", "country", "store", "device", "category", "chart", "metric",
              "currency", "basis", "scope", "as_of", "windows", "baseline_floor"}
    if not needed.issubset(request):
        raise ContractError("Analysis request missing fields: " + str(sorted(needed-set(request))))
    if request["metric"] not in {"revenue", "downloads"}:
        raise ContractError("Growth analysis only supports daily revenue/downloads, never ranks or prices")
    if request["basis"] == "unknown" or request["scope"] == "unknown" or request["currency"] == "UNKNOWN":
        raise ContractError("Unknown metric basis/scope/currency must be resolved before comparison")
    windows = request["windows"]
    if not windows or any(type(w) is not int or w < 1 or w > 365 for w in windows):
        raise ContractError("windows must contain integers in 1..365")
    floor = float(request["baseline_floor"])
    if floor <= 0:
        raise ContractError("baseline_floor must be positive")
    end = date.fromisoformat(request["as_of"])
    series, labels, evidence = defaultdict(dict), {}, defaultdict(set)
    rejected = defaultdict(int)
    for bundle in sorted(bundles, key=lambda b: b["collected_at"]):
        ctx = bundle["context"]
        if any(ctx[k] != request[k] for k in ("market", "country", "store", "device", "category", "chart")):
            continue
        if bundle["status"] != "SUCCEEDED":
            rejected["partial_bundle"] += 1
            continue
        day = date.fromisoformat(ctx["data_date"])
        if day > end:
            continue
        for row in bundle["rows"]:
            key = row["listing_key"]
            labels[key] = row["name"]
            for metric in row.get("metrics", []):
                if metric["name"] != request["metric"]:
                    continue
                if metric["period"] != "daily" or any(metric.get(k) != request[k] for k in ("currency", "basis", "scope")):
                    rejected["incomparable_metric"] += 1
                    continue
                value = metric.get("value")
                # Latest revision, including missing, replaces older observation.
                series[key][day] = float(value) if value is not None else None
                evidence[key].add(bundle["source_url"])
    leads = []
    for key, values in series.items():
        result = {"listing_key": key, "name": labels[key], "windows": {},
                  "evidence_urls": sorted(evidence[key]), "qualification": "UNREVIEWED"}
        for w in windows:
            cur_days = [end-timedelta(days=i) for i in range(w)]
            prev_days = [end-timedelta(days=i) for i in range(w, 2*w)]
            cur = [values.get(d) for d in cur_days]
            prev = [values.get(d) for d in prev_days]
            valid = [v for v in cur+prev if v is not None]
            stats = {"coverage": len(valid)/(2*w), "growth": None,
                     "absolute_daily_change": None, "current_daily_mean": None,
                     "previous_daily_mean": None, "reason": None}
            if any(v is None for v in cur+prev):
                stats["reason"] = "INCOMPLETE_HISTORY"
            elif any(v < 0 for v in valid):
                stats["reason"] = "NEGATIVE_REVENUE_REVIEW"
            else:
                a, b = sum(cur)/w, sum(prev)/w
                stats.update(current_daily_mean=a, previous_daily_mean=b, absolute_daily_change=a-b)
                if b < floor:
                    stats["reason"] = "LOW_BASELINE"
                else:
                    stats["growth"] = a/b-1
            result["windows"][str(w)] = stats
        leads.append(result)
    main = str(request.get("sort_window", windows[0]))
    if int(main) not in windows:
        raise ContractError("sort_window must appear in windows")
    leads.sort(key=lambda r: (r["windows"][main]["growth"] is not None,
                             r["windows"][main]["growth"] or 0), reverse=True)
    return {"schema_version": 1, "kind": "competitor_growth_leads_not_opportunity_rank",
            "request": request, "data_status": "AVAILABLE" if leads else "NO_COMPARABLE_DATA",
            "warnings": ["收入不是付费人数；本输出未进行行业资格、目标需求或机会评分。",
                         "全窗口观测齐全才计算增长；缺失值不会补零。"],
            "excluded": dict(rejected), "leads": leads[:request.get("limit", 100)]}


def export_report(report, directory):
    dest = Path(directory)
    dest.mkdir(parents=True, exist_ok=True)
    write_json(dest/"analysis.json", report)
    with (dest/"analysis.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "listing_key", "window", "growth", "coverage", "reason"])
        for lead in report["leads"]:
            for window, item in lead["windows"].items():
                # Prevent spreadsheet formula execution on third-party text.
                safe = lambda v: "'"+v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v
                writer.writerow([safe(lead["name"]), safe(lead["listing_key"]), window,
                                 item["growth"], item["coverage"], item["reason"]])
    lines = ["# 竞品增长线索", "", "这不是机会排名，也不是付费人数排名。", "",
             "数据状态："+report["data_status"], "", "```json", json.dumps(report["request"], ensure_ascii=False, indent=2), "```", ""]
    for lead in report["leads"]:
        name = lead["name"].replace("\n", " ").replace("<", "&lt;")
        lines += ["- " + name + "：" + json.dumps(lead["windows"], ensure_ascii=False)]
    (dest/"analysis.md").write_text("\n".join(lines)+"\n")
