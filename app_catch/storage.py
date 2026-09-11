import json
import sqlite3
from pathlib import Path
from .core import validate_bundle, digest


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY, collected_at TEXT NOT NULL,
      status TEXT NOT NULL, context_json TEXT NOT NULL, bundle_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS rows (
      run_id TEXT NOT NULL REFERENCES runs(run_id), listing_key TEXT NOT NULL,
      row_json TEXT NOT NULL, PRIMARY KEY(run_id, listing_key));
    CREATE TABLE IF NOT EXISTS jobs (
      job_key TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL,
      checkpoint_json TEXT NOT NULL);
    """)
    return con


def ingest(con, bundle):
    validate_bundle(bundle)
    keys = [r["listing_key"] for r in bundle["rows"]]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate listing keys within bundle; fix extraction before import")
    run_id = digest(bundle)
    with con:
        cur = con.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?)",
                          (run_id, bundle["collected_at"], bundle["status"],
                           json.dumps(bundle["context"]), json.dumps(bundle, ensure_ascii=False)))
        inserted = cur.rowcount
        for row in bundle["rows"]:
            con.execute("INSERT OR IGNORE INTO rows VALUES (?,?,?)",
                        (run_id, row["listing_key"], json.dumps(row, ensure_ascii=False)))
    return {"run_id": run_id, "new_run": bool(inserted), "row_count": len(keys)}


def bundles(con):
    return [json.loads(row[0]) for row in con.execute("SELECT bundle_json FROM runs ORDER BY collected_at")]


def backup(con, destination):
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(destination)
    try:
        con.backup(target)
    finally:
        target.close()
