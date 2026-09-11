import argparse
import json
from pathlib import Path
from .core import read_json, ContractError
from .storage import connect, ingest, bundles, backup
from .analysis import analyze, export_report


def main():
    parser = argparse.ArgumentParser(description="点点榜单采集与可审计分析")
    parser.add_argument("--db", default="data/app-catch.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect", help="手动选好页面后，保存可见控件/链接结构")
    p.add_argument("--url", required=True)
    p.add_argument("--profile", default="data/browser-profile")
    p.add_argument("--scope", default="body")
    p.add_argument("--output", default="work/page-inventory.json")
    p = sub.add_parser("collect", help="执行已核验的页面采集配方")
    p.add_argument("--recipe", required=True)
    p.add_argument("--context", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--profile", default="data/browser-profile")
    p.add_argument("--headless", action="store_true")
    p = sub.add_parser("import", help="导入统一 JSON bundle，支持重复执行")
    p.add_argument("file")
    p = sub.add_parser("analyze", help="按显式口径分析日下载/收入趋势")
    p.add_argument("--request", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("backup")
    p.add_argument("destination")
    p = sub.add_parser("run-plan", help="顺序执行多个市场任务，带锁与成功任务去重")
    p.add_argument("--plan", required=True)
    p.add_argument("--output", default="data/runs")
    p.add_argument("--profile", default="data/browser-profile")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--force", action="store_true")
    sub.add_parser("status")
    args = parser.parse_args()
    try:
        if args.command == "run-plan":
            from .runner import run_plan
            results = run_plan(args.plan, args.db, args.output, args.profile, args.headless, args.force)
            print(json.dumps(results, ensure_ascii=False))
            if any(r["state"] not in {"SUCCEEDED", "ALREADY_COMPLETE", "DISABLED"} for r in results):
                parser.exit(2, "One or more jobs did not complete; inspect last-plan-run.json\n")
            return
        if args.command == "inspect":
            from .browser import inspect_page
            inspect_page(args.profile, args.url, args.output, args.scope)
            return
        if args.command == "collect":
            from .browser import collect
            bundle = collect(args.profile, read_json(args.recipe), read_json(args.context), args.output, args.headless)
            with connect(args.db) as con:
                print(json.dumps(ingest(con, bundle), ensure_ascii=False))
            return
        with connect(args.db) as con:
            if args.command == "import":
                print(json.dumps(ingest(con, read_json(args.file)), ensure_ascii=False))
            elif args.command == "analyze":
                result = analyze(bundles(con), read_json(args.request))
                export_report(result, args.output)
                print(json.dumps({"status": result["data_status"], "leads": len(result["leads"]), "output": args.output}))
            elif args.command == "backup":
                backup(con, args.destination)
                print("Backup complete")
            else:
                print(json.dumps({"runs": con.execute("SELECT status, COUNT(*) FROM runs GROUP BY status").fetchall(),
                                  "rows": con.execute("SELECT COUNT(*) FROM rows").fetchone()[0]}))
    except (ValueError, KeyError, RuntimeError) as error:
        parser.exit(2, "ERROR: " + str(error) + "\n")


if __name__ == "__main__":
    main()
