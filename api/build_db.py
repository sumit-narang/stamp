#!/usr/bin/env python3
"""Load data/stamps.json into a SQLite database with full-text search.

Creates data/stamps.db with:
  - stamps           : one row per stamp (flattened value, era, year estimate)
  - stamps_fts       : FTS5 index over title / issue_type / value for search
  - date_sources     : (empty for now) external exact-date enrichment, by source

Re-runnable: drops and rebuilds from stamps.json each time.
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "stamps.json"
DB = ROOT / "data" / "stamps.db"

SCHEMA = """
DROP TABLE IF EXISTS stamps;
DROP TABLE IF EXISTS stamps_fts;
DROP TABLE IF EXISTS date_sources;

CREATE TABLE stamps (
  id            TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  value_display TEXT,
  value_amount  REAL,
  currency      TEXT,
  issue_type    TEXT,          -- primary issue type (e.g. Commemorative)
  issue_types   TEXT,          -- JSON array of all
  designer      TEXT,          -- filled by later enrichment
  series        TEXT,          -- filled by later enrichment
  era           TEXT,          -- e.g. "1922-1983"
  year_start    INTEGER,
  year_end      INTEGER,
  year_est_lo   INTEGER,       -- currency-narrowed estimate
  year_est_hi   INTEGER,
  issue_date    TEXT,          -- exact date, NULL until enriched
  year          INTEGER,       -- exact year, NULL until enriched
  date_source   TEXT,          -- where issue_date came from
  image_path    TEXT,
  image_iiif    TEXT,
  image_w       INTEGER,
  image_h       INTEGER,
  n_images      INTEGER,
  rights        TEXT,
  source_url    TEXT,
  -- appended (positional INSERT above fills the first 24; these stay NULL for
  -- DRI records and are populated by load_colnect_manual.py for 2020-2026)
  printer       TEXT,
  extra         TEXT            -- JSON: catalogue refs, perforation, size, etc.
);

CREATE INDEX idx_year_start ON stamps(year_start);
CREATE INDEX idx_issue_type ON stamps(issue_type);
CREATE INDEX idx_year ON stamps(year);

CREATE VIRTUAL TABLE stamps_fts USING fts5(
  id UNINDEXED, title, issue_type, value_display,
  tokenize = 'porter unicode61'
);

CREATE TABLE date_sources (
  stamp_id   TEXT,
  source     TEXT,
  issue_date TEXT,
  year       INTEGER,
  confidence REAL,
  raw        TEXT,
  PRIMARY KEY (stamp_id, source)
);
"""


def main():
    stamps = json.loads(SRC.read_text())
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    rows = []
    fts = []
    for s in stamps:
        v = s.get("value") or {}
        yr = s.get("year_range") or [None, None]
        ye = s.get("year_estimate") or [None, None]
        dims = s.get("image_dimensions") or [None, None]
        itypes = s.get("issue_type") or []
        rows.append((
            s["id"], s["title"], v.get("display"), v.get("amount"), v.get("currency"),
            (itypes[0] if itypes else None), json.dumps(itypes),
            None, None,
            ("-".join(map(str, yr)) if yr[0] else None),
            yr[0], yr[1], ye[0], ye[1],
            None, None, None,
            s.get("image"), s.get("image_iiif"), dims[0], dims[1],
            s.get("n_images"), s.get("rights"), s.get("source_url"),
        ))
        fts.append((s["id"], s["title"], " ".join(itypes), v.get("display") or ""))
    con.executemany(
        "INSERT INTO stamps VALUES (" + ",".join("?" * 24) + ")", rows)
    con.executemany(
        "INSERT INTO stamps_fts (id,title,issue_type,value_display) VALUES (?,?,?,?)", fts)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM stamps").fetchone()[0]
    con.close()
    print(f"Loaded {n} stamps into {DB}")


if __name__ == "__main__":
    main()
