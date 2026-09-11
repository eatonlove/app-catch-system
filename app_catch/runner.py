"""Bounded multi-market run; usable by launchd after live recipe verification."""
import fcntl
import json
from datetime import date, timedelta
from pathlib import Path
from .core import read_json, now, digest, write_json, ContractError
from .storage import connect, ingest
from .browser import collect, validate_recipe


def run_plan(plan_file, database, output_root, profile, headless=False, force=False):
    plan_path = Path(plan_file).resolve()
    plan = read_json(plan_path)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    profile_path = Path(profile).resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    results = []
    # Serialize all scheduled runs using this profile, including different plans.
    with (profile_path/"collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ContractError("Collector profile is already in use by another scheduled run")
        for job in plan["jobs"]:
            if not job.get("enabled", False):
                results.append({"job": job["name"], "state": "DISABLED"})
                continue
            recipe = read_json(plan_path.parent/job["recipe"])
            params = dict(job["context"])
            if "data_date" not in params:
                # Date is a request, not proof the provider has published it; guards must confirm.
                params["data_date"] = (date.today()-timedelta(days=job.get("lag_days", 1))).isoformat()
            key = digest({"recipe": recipe, "context": params})
            dest = root/params["data_date"]/key[:16]
            status = dest/"checkpoint.json"
            if status.exists() and read_json(status).get("state") == "SUCCEEDED" and not force:
                # A crash can occur between bundle creation and database commit.
                if (dest/"bundle.json").exists():
                    with connect(database) as con:
                        ingest(con, read_json(dest/"bundle.json"))
                    results.append({"job": job["name"], "state": "ALREADY_COMPLETE"})
                    continue
            try:
                bundle = collect(profile, recipe, params, dest, headless)
                with connect(database) as con:
                    ingest(con, bundle)
                results.append({"job": job["name"], "state": bundle["status"], "rows": len(bundle["rows"])})
            except Exception as error:
                state = getattr(error, "state", "CONFIG_OR_RUNTIME_ERROR")
                results.append({"job": job["name"], "state": state, "error_type": type(error).__name__})
                # Do not repeat auth/rate-limit failures across markets using the same account.
                if state in {"AUTH_REQUIRED", "RATE_LIMITED"}:
                    break
        write_json(root/"last-plan-run.json", {"at": now(), "results": results})
    return results
