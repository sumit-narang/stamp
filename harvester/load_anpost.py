#!/usr/bin/env python3
"""Add An Post 2020-2026 programme issues to the database as new records.

DRI's collection ends in 2019, so these extend coverage. They are issue-level
(no per-stamp image yet) and flagged with source='anpost'. Re-runnable: clears
prior anpost rows first.
"""
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "sources" / "anpost_issues.jsonl"
DB = ROOT / "data" / "stamps.db"
PROG_URL = "https://www.anpost.com/Shop/Stamp-Collecting/Stamp-Programme"


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40]


def main():
    issues = [json.loads(l) for l in SRC.read_text().splitlines() if l.strip()]
    con = sqlite3.connect(DB)
    con.execute("DELETE FROM stamps WHERE id LIKE 'anpost-%'")
    con.execute("DELETE FROM stamps_fts WHERE id LIKE 'anpost-%'")
    rows = 0
    for it in issues:
        sid = f"anpost-{it['issue_date']}-{slug(it['title'])}"
        con.execute(
            "INSERT OR REPLACE INTO stamps "
            "(id,title,issue_type,issue_types,era,year_start,year_end,"
            " issue_date,year,date_source,n_images,rights,source_url) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, it["title"], "Commemorative", json.dumps(["Commemorative"]),
             str(it["year"]), it["year"], it["year"],
             it["issue_date"], it["year"], "anpost", it.get("n_stamps") or 0,
             "© An Post. Programme data via An Post / Wayback Machine.", PROG_URL))
        con.execute(
            "INSERT INTO stamps_fts (id,title,issue_type,value_display) VALUES (?,?,?,?)",
            (sid, it["title"], "Commemorative", ""))
        rows += 1
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM stamps").fetchone()[0]
    con.close()
    print(f"added {rows} An Post issue records; DB total now {total}")


if __name__ == "__main__":
    main()
