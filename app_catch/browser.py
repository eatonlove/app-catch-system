"""Recipe-based visible DOM collection. Recipes must be verified against a live page."""
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from .core import (ContractError, digest, now, normalize_row, read_json,
                   safe_url, valid_context, write_json, validate_bundle)


class CollectionError(RuntimeError):
    def __init__(self, state, message):
        self.state = state
        super().__init__(message)


@contextmanager
def session(profile, headless=False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise ContractError("Install browser extra: pip install -e '.[browser]'; python -m playwright install chromium") from error
    path = Path(profile).resolve()
    # Only use a project-owned dedicated profile, never Chrome's existing user data.
    if "Google/Chrome" in str(path) or path.name in {"Default", "Profile 1"}:
        raise ContractError("Use a dedicated collector profile, not an existing Chrome profile")
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(path), headless=headless,
                                                       accept_downloads=False, chromium_sandbox=True)
        context.set_default_timeout(15000)
        try:
            yield context
        finally:
            context.close()


def check_url(page):
    try:
        return safe_url(page.url)
    except ContractError as error:
        raise CollectionError("UNEXPECTED_NAVIGATION", "Page left allowed DianDian hosts") from error


def check_session(page, recipe):
    check_url(page)
    for selector in recipe.get("auth_selectors", []):
        if page.locator(selector).first.is_visible():
            raise CollectionError("AUTH_REQUIRED", "Login or verification screen detected; manual login required")


def assert_context(page, guards, context):
    required = {"market", "country", "store", "device", "category", "chart", "data_date"}
    if required - {g["context_key"] for g in guards}:
        raise ContractError("Context guards must cover all seven dimensions, not only page title")
    for guard in guards:
        locator = page.locator(guard["selector"])
        if locator.count() != 1:
            raise CollectionError("CONTEXT_MISMATCH", "Context selector is absent or ambiguous: " + guard["context_key"])
        actual = locator.inner_text().strip()
        expected = guard["equals"].format_map(context)
        if actual != expected:
            raise CollectionError("CONTEXT_MISMATCH", "Context mismatch: " + guard["context_key"])


def apply_steps(page, steps, context):
    for step in steps:
        loc = page.locator(step["selector"])
        kind = step["action"]
        if kind == "click":
            loc.click()
        elif kind == "fill":
            loc.fill(step["value"].format_map(context))
        elif kind == "select":
            loc.select_option(label=step["value"].format_map(context))
        elif kind == "wait":
            loc.wait_for(state="visible")
        else:
            raise ContractError("Unsupported recipe action: " + kind)
        check_url(page)


EXTRACT = """(rows, fields) => rows.filter(r => r.getClientRects().length).map(row => {
  const out = {};
  for (const [name, spec] of Object.entries(fields)) {
    const el = spec.selector === ':scope' ? row : row.querySelector(spec.selector);
    out[name] = !el ? null : spec.attribute === 'href' ? el.href :
      spec.attribute ? el.getAttribute(spec.attribute) : (el.innerText || el.textContent || '').trim();
  }
  return out;
})"""


def validate_recipe(recipe):
    if recipe.get("version") != 1 or recipe.get("verified") is not True:
        raise ContractError("Recipe is unverified. Inspect a real page, map selectors and guards, then mark verified")
    if not recipe.get("verification_evidence"):
        raise ContractError("A verified recipe must reference its inspection evidence")
    safe_url(recipe["start_url"])
    for key in ("ready_selector", "rows_selector", "scope_selector"):
        if not recipe.get(key):
            raise ContractError("Missing recipe selector: " + key)
    if "name" not in recipe["fields"] or not ({"detail_url", "listing_key"} & set(recipe["fields"])):
        raise ContractError("Row fields need name and identity")
    if not recipe.get("context_guards"):
        raise ContractError("Missing context guards")
    if not recipe.get("end_selector") and not recipe.get("expected_count") and not recipe.get("next_selector"):
        raise ContractError("Need an observed end marker, expected count or explicit next-page control")
    for fields in [recipe["fields"], recipe.get("detail", {}).get("fields", {})]:
        for spec in fields.values():
            if spec.get("attribute") not in (None, "href", "title", "data-id", "aria-label"):
                raise ContractError("Unsupported attribute extraction")


def inspect_page(profile, url, output, scope="body"):
    safe_url(url)
    with session(profile) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        print("请在专用浏览器正常登录并打开待探查榜单/详情页。不要在终端输入密码。")
        input("页面就绪后按回车保存 DOM 控件与链接清单：")
        check_url(page)
        target = page.locator(scope)
        if target.count() != 1:
            raise ContractError("Inspection scope must identify exactly one container")
        # Do not serialize HTML, inputs' values, scripts, storage, requests or auth headers.
        inventory = target.evaluate("""root => ({
          controls: [...root.querySelectorAll('button,select,input,[role=button],[role=combobox]')]
            .filter(e=>e.getClientRects().length).slice(0,300).map(e=>({
              tag:e.tagName, role:e.getAttribute('role'), type:e.type,
              label:e.getAttribute('aria-label'), placeholder:e.getAttribute('placeholder'),
              text:e.tagName==='INPUT'?'':(e.innerText||'').trim().slice(0,120),
              id:e.id, classes:e.className})),
          links: [...root.querySelectorAll('a[href]')].filter(e=>e.getClientRects().length)
            .slice(0,500).map(e=>({text:(e.innerText||'').trim().slice(0,120),href:e.href,classes:e.className})),
          containers: [...root.querySelectorAll('table,tbody,[role=table],[role=row],ul')]
            .slice(0,100).map(e=>({tag:e.tagName,role:e.getAttribute('role'),id:e.id,classes:e.className,children:e.children.length}))
        })""")
        links = []
        for link in inventory["links"]:
            try:
                link["href"] = safe_url(link["href"])
                links.append(link)
            except ContractError:
                pass
        inventory["links"] = links
        inventory.update(source_url=check_url(page), collected_at=now(), scope=scope,
                         status="INSPECTED_NOT_A_VERIFIED_RECIPE")
        write_json(output, inventory)
        print("已保存结构清单：", output)


def collect_page(page, context, recipe, params, output):
    validate_recipe(recipe)
    valid_context(params)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    job_key = digest({"recipe": recipe, "context": params})
    checkpoint = output/"checkpoint.json"
    rows, pages_seen, status = {}, 0, "RUNNING"
    started = now()
    # Restart discovery after interruption: never combine two different chart snapshots.
    # Checkpoints preserve evidence, not an unverified scroll position.
    def save(state, reason=None):
        write_json(checkpoint, {"job_key": job_key, "state": state, "updated_at": now(),
                               "pages_seen": pages_seen, "reason": reason, "rows": list(rows.values())})
    try:
        page.goto(recipe["start_url"], wait_until="domcontentloaded")
        check_session(page, recipe)
        apply_steps(page, recipe.get("steps", []), params)
        page.locator(recipe["ready_selector"]).wait_for(state="visible")
        assert_context(page, recipe["context_guards"], params)
        scope = page.locator(recipe["scope_selector"])
        if scope.count() != 1:
            raise CollectionError("SCHEMA_CHANGED", "Chart scope is missing or ambiguous")
        stagnant = 0
        for index in range(recipe.get("max_pages", 20)):
            check_session(page, recipe)
            assert_context(page, recipe["context_guards"], params)
            before = len(rows)
            raw_rows = page.locator(recipe["rows_selector"]).evaluate_all(EXTRACT, recipe["fields"])
            for raw in raw_rows:
                if raw.get("detail_url"):
                    raw["detail_url"] = urljoin(page.url, raw["detail_url"])
                row = normalize_row(raw, recipe.get("metrics", []))
                rows[row["listing_key"]] = row
            pages_seen += 1
            save("RUNNING")
            stagnant = stagnant+1 if len(rows) == before else 0
            end = recipe.get("end_selector")
            expected = recipe.get("expected_count")
            if (end and page.locator(end).first.is_visible()) or (expected and len(rows) >= expected):
                status = "SUCCEEDED"
                break
            if len(rows) >= recipe.get("max_rows", 500) or stagnant >= 3:
                status = "PARTIAL"
                break
            if recipe.get("next_selector"):
                button = page.locator(recipe["next_selector"])
                if button.count() == 1 and button.is_visible() and button.is_disabled():
                    status = "SUCCEEDED"
                    break
                button.click()
            elif recipe.get("scroll_selector"):
                page.locator(recipe["scroll_selector"]).evaluate("el => el.scrollBy(0, Math.max(300, el.clientHeight * .8))")
            else:
                page.evaluate("window.scrollBy(0, Math.max(300, window.innerHeight * .8))")
            page.wait_for_timeout(recipe.get("settle_ms", 1200))
        else:
            status = "PARTIAL"
        if not rows:
            raise CollectionError("SCHEMA_CHANGED", "No records extracted; not a successful empty chart")
        assert_context(page, recipe["context_guards"], params)
        source_url = check_url(page)
        detail_spec = recipe.get("detail")
        if detail_spec and detail_spec.get("enabled"):
            detail_dir = output/"details"
            for row in list(rows.values())[:detail_spec.get("limit", 10)]:
                if not row.get("detail_url"):
                    continue
                detail_page = context.new_page()
                try:
                    detail_page.goto(row["detail_url"], wait_until="domcontentloaded")
                    check_session(detail_page, recipe)
                    apply_steps(detail_page, detail_spec.get("steps", []), params)
                    detail_page.locator(detail_spec["ready_selector"]).wait_for(state="visible")
                    # No row metrics are promoted without independent detail-context guards.
                    root = detail_page.locator(detail_spec["scope_selector"])
                    values = root.evaluate_all(EXTRACT, detail_spec["fields"])
                    if len(values) != 1:
                        raise CollectionError("SCHEMA_CHANGED", "Detail scope must select one container")
                    artifact = {"listing_key": row["listing_key"], "source_url": check_url(detail_page),
                                "collected_at": now(), "fields": values[0], "context_verified": False,
                                "note": "Detail text evidence only; not a daily metric time series"}
                    path = detail_dir/(digest(row["listing_key"])[:16]+".json")
                    write_json(path, artifact)
                    row["detail_evidence"] = str(path)
                finally:
                    detail_page.close()
        bundle = {"schema_version": 1, "source": "diandian", "source_url": source_url,
                  "collected_at": started, "finished_at": now(), "context": params,
                  "context_verified": True, "status": status, "rows": list(rows.values()),
                  "recipe_hash": digest(recipe), "pages_seen": pages_seen,
                  "completeness_note": "bounded_or_stalled" if status == "PARTIAL" else "observed_end_or_expected_count"}
        validate_bundle(bundle)
        write_json(output/"bundle.json", bundle)
        # Selected scope avoids account/navigation area; optional to minimize artifacts.
        if recipe.get("screenshot", True):
            scope.screenshot(path=str(output/"chart.png"))
        save(status)
        return bundle
    except Exception as error:
        state = getattr(error, "state", "FAILED")
        save(state, type(error).__name__)
        raise


def collect(profile, recipe, params, output, headless=False):
    if recipe.get('adapter') == 'diandian-table-v1':
        from .diandian import collect_diandian
        return collect_diandian(profile, recipe, params, output, headless)
    validate_recipe(recipe)
    with session(profile, headless=headless) as context:
        page = context.pages[0] if context.pages else context.new_page()
        return collect_page(page, context, recipe, params, output)
