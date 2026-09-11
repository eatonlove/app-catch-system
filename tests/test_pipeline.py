import copy
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from app_catch.core import number, safe_url, ContractError, normalize_row, validate_bundle
from app_catch.storage import connect, ingest, bundles, backup
from app_catch.analysis import analyze, export_report
from app_catch.browser import validate_recipe


def sample(day="2026-09-11", value="100", status="SUCCEEDED"):
    return {"schema_version": 1, "source": "diandian", "source_url": "https://app.diandian.com/test-fixture",
            "collected_at": day+"T12:00:00+00:00", "status": status, "context_verified": True,
            "context": {"market": "appstore", "country": "US", "store": "appstore", "device": "iphone",
                        "category": "工具", "chart": "grossing", "data_date": day},
            "rows": [{"listing_key": "fixture-only", "name": "TEST ONLY", "metrics": [
                {"name": "revenue", "value": value, "raw": value, "unit": "money", "currency": "USD",
                 "basis": "net", "scope": "iap", "period": "daily", "is_estimate": True}]}]}


def request():
    return {"market": "appstore", "country": "US", "store": "appstore", "device": "iphone",
            "category": "工具", "chart": "grossing", "metric": "revenue", "currency": "USD",
            "basis": "net", "scope": "iap", "as_of": "2026-09-11", "windows": [7, 28, 90],
            "baseline_floor": 10, "sort_window": 7}


def history():
    end = date(2026, 9, 11)
    return [sample((end-timedelta(days=i)).isoformat(), "200" if i < 7 else "100") for i in range(14)]


class PipelineTests(unittest.TestCase):
    def test_units_and_unknowns(self):
        self.assertEqual(number("$1.25万"), "12500.00")
        self.assertEqual(number("2.5M"), "2500000.0")
        self.assertEqual(number("0"), "0")
        for x in ["--", "<100", "1-5万", "100+", "20%", "NaN", True]:
            self.assertIsNone(number(x))

    def test_urls_strip_credentials_and_reject_external(self):
        self.assertEqual(safe_url("https://app.diandian.com/x?id=1&token=secret#secret"), "https://app.diandian.com/x?id=1")
        for url in ["https://evil.com/a", "javascript:alert(1)", "https://user:pass@app.diandian.com/a"]:
            with self.assertRaises(ContractError): safe_url(url)

    def test_unverified_context_rejected(self):
        b = sample()
        b["context_verified"] = False
        with self.assertRaises(ContractError): validate_bundle(b)

    def test_global_not_a_country(self):
        b = sample()
        b["context"]["country"] = "global"
        with self.assertRaises(ContractError): validate_bundle(b)

    def test_money_requires_currency(self):
        b = sample()
        del b["rows"][0]["metrics"][0]["currency"]
        with self.assertRaises(ContractError): validate_bundle(b)

    def test_import_idempotent_and_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            con = connect(Path(temp)/"a.sqlite")
            self.assertTrue(ingest(con, sample())["new_run"])
            self.assertFalse(ingest(con, sample())["new_run"])
            self.assertEqual(len(bundles(con)), 1)
            backup(con, Path(temp)/"b.sqlite")
            restored = connect(Path(temp)/"b.sqlite")
            self.assertEqual(bundles(restored), bundles(con))
            restored.close()
            con.close()

    def test_duplicate_identity_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            con = connect(Path(temp)/"a.sqlite")
            b = sample()
            b["rows"].append(copy.deepcopy(b["rows"][0]))
            with self.assertRaises(ValueError): ingest(con, b)
            self.assertEqual(len(bundles(con)), 0)
            con.close()

    def test_growth_and_missing_history(self):
        report = analyze(history(), request())
        win = report["leads"][0]["windows"]
        self.assertEqual(win["7"]["growth"], 1)
        self.assertEqual(win["28"]["reason"], "INCOMPLETE_HISTORY")
        self.assertEqual(win["90"]["reason"], "INCOMPLETE_HISTORY")

    def test_partial_not_used_as_zero(self):
        hs = history()
        hs[0]["status"] = "PARTIAL"
        report = analyze(hs, request())
        self.assertIsNone(report["leads"][0]["windows"]["7"]["growth"])
        self.assertEqual(report["excluded"]["partial_bundle"], 1)

    def test_revision_missing_supersedes_old(self):
        hs = history()
        b = sample(value=None)
        b["collected_at"] = "2026-09-11T13:00:00+00:00"
        hs.append(b)
        self.assertIsNone(analyze(hs, request())["leads"][0]["windows"]["7"]["growth"])

    def test_currency_and_basis_isolation(self):
        hs = history()
        hs[0]["rows"][0]["metrics"][0]["currency"] = "CNY"
        hs[1]["rows"][0]["metrics"][0]["basis"] = "gross"
        report = analyze(hs, request())
        self.assertEqual(report["excluded"]["incomparable_metric"], 2)
        self.assertIsNone(report["leads"][0]["windows"]["7"]["growth"])

    def test_low_base(self):
        hs = history()
        req = request()
        req["baseline_floor"] = 101
        self.assertEqual(analyze(hs, req)["leads"][0]["windows"]["7"]["reason"], "LOW_BASELINE")

    def test_rank_cannot_be_revenue(self):
        req = request()
        req["metric"] = "rank"
        with self.assertRaises(ContractError): analyze(history(), req)

    def test_unverified_recipe_will_not_launch_browser(self):
        with self.assertRaises(ContractError): validate_recipe({"version": 1, "verified": False})

    def test_export_outputs_and_formula_injection(self):
        hs = history()
        for b in hs: b["rows"][0]["name"] = '=HYPERLINK("bad")'
        with tempfile.TemporaryDirectory() as temp:
            export_report(analyze(hs, request()), temp)
            self.assertTrue((Path(temp)/"analysis.json").exists())
            self.assertIn("'=HYPERLINK", (Path(temp)/"analysis.csv").read_text())
            self.assertIn("不是机会排名", (Path(temp)/"analysis.md").read_text())

    def test_no_data_is_explicit(self):
        report = analyze([], request())
        self.assertEqual(report["data_status"], "NO_COMPARABLE_DATA")
        self.assertEqual(report["leads"], [])


if __name__ == "__main__":
    unittest.main()
