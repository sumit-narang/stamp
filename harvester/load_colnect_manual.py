#!/usr/bin/env python3
"""Load the manually-captured Colnect 2020-2026 dataset into stamps.db.

- Removes the old thin An Post 2020-2026 records (anpost-*).
- Reads data/colnect_manual/<year>.jsonl (parsed from screenshots).
- Copies the clean stamp scans into data/images_colnect/<year>/.
- Inserts rich records: exact date, designer, printer, series, catalogue refs,
  perforation, etc. These become the authoritative 2020-2026 stamps.
"""
import json
import re
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "stamps.db"
SRC_IMG_ROOT = Path("/Users/sumit/Downloads/2020 2026")
MANUAL = ROOT / "data" / "colnect_manual"
IMG_DIR = ROOT / "data" / "images_colnect"
IMG_DIR.mkdir(parents=True, exist_ok=True)

EXTRA_KEYS = ["catalog", "perforation", "size", "colors", "themes",
              "print_run", "description", "face_value", "emission",
              "format", "colnect_id", "colnect_slug"]


def ensure_columns(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(stamps)").fetchall()]
    for col in ("printer", "extra"):
        if col not in cols:
            con.execute(f"ALTER TABLE stamps ADD COLUMN {col} TEXT")


def value_display(face):
    if not face:
        return None
    face = re.sub(r"^[A-Z]\s*[°*]?\s*-\s*", "", face).strip()   # drop "N ° - "
    return face or None


def rec_id(r):
    if r.get("colnect_id"):
        return f"col-{r['colnect_id']}"
    stem = Path(r.get("image_file", r.get("screenshot", "x"))).stem
    return f"col-{r['year']}-{re.sub(r'[^A-Za-z0-9]+', '-', stem)[:40]}"


def main():
    con = sqlite3.connect(DB)
    ensure_columns(con)

    # 1. remove old An Post 2020-2026 records
    old = con.execute("SELECT COUNT(*) FROM stamps WHERE id LIKE 'anpost-%'").fetchone()[0]
    con.execute("DELETE FROM stamps WHERE id LIKE 'anpost-%'")
    con.execute("DELETE FROM stamps_fts WHERE id LIKE 'anpost-%'")
    con.execute("DELETE FROM date_sources WHERE stamp_id LIKE 'anpost-%'")
    # also clear any prior colnect load (idempotent)
    con.execute("DELETE FROM stamps WHERE id LIKE 'col-%'")
    con.execute("DELETE FROM stamps_fts WHERE id LIKE 'col-%'")
    print(f"removed {old} old An Post records")

    # 2. gather manual records, de-dupe by Colnect id (= one distinct stamp)
    records = []
    for f in sorted(MANUAL.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))

    def fields(r):
        return (1 if r.get("issued_on") else 0) + sum(
            1 for k in ("designers", "printers", "series", "catalog") if r.get(k))

    by_id = {}
    for r in records:
        key = r.get("colnect_id") or r.get("screenshot")
        cur = by_id.get(key)
        if not cur or fields(r) > fields(cur):
            by_id[key] = r
    uniq = list(by_id.values())

    # 3. assign a UNIQUE stamp scan to each record, per year (one-to-one, by
    #    title similarity) — sets share near-identical titles + "(2)/(3)" files,
    #    so greedy one-to-one keeps every distinct stamp with its own image.
    import difflib
    from collections import defaultdict

    def norm(t):
        return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()

    by_year = defaultdict(list)
    for r in uniq:
        by_year[r["year"]].append(r)
    for year, group in by_year.items():
        imgs = [p.name for p in (SRC_IMG_ROOT / str(year)).glob("*.jpg")]
        pairs = []
        for r in group:
            nt = norm(r.get("title"))
            for img in imgs:
                sc = difflib.SequenceMatcher(None, nt, norm(Path(img).stem)).ratio()
                pairs.append((sc, id(r), r, img))
        pairs.sort(key=lambda x: -x[0])
        taken_r, taken_img = set(), set()
        for sc, rid, r, img in pairs:
            if rid in taken_r or img in taken_img:
                continue
            r["image_file"] = img
            taken_r.add(rid)
            taken_img.add(img)

    inserted = imaged = 0
    for r in uniq:
        year = r["year"]
        sid = rec_id(r)
        # copy image
        image_path = None
        if r.get("image_file"):
            src = SRC_IMG_ROOT / str(year) / r["image_file"]
            if src.exists():
                dest_dir = IMG_DIR / str(year)
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / r["image_file"]
                if not dest.exists():
                    shutil.copy2(src, dest)
                image_path = str(dest.relative_to(ROOT))
                imaged += 1
        emission = r.get("emission") or "Commemorative"
        itypes = [emission]
        extra = {k: r.get(k) for k in EXTRA_KEYS if r.get(k)}
        con.execute(
            "INSERT OR REPLACE INTO stamps "
            "(id,title,value_display,issue_type,issue_types,designer,printer,"
            " series,era,year_start,year_end,issue_date,year,date_source,"
            " image_path,n_images,rights,source_url,extra) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, r.get("title"), value_display(r.get("face_value")),
             emission, json.dumps(itypes), r.get("designers"), r.get("printers"),
             r.get("series"), "2020-2026", year, year,
             r.get("issued_on"), year, "colnect_manual",
             image_path, 1 if image_path else 0,
             "© An Post. Metadata via Colnect (manually collected).",
             (f"https://colnect.com/en/stamps/stamp/{r['colnect_id']}"
              if r.get("colnect_id") else None),
             json.dumps(extra, ensure_ascii=False)))
        con.execute(
            "INSERT INTO stamps_fts (id,title,issue_type,value_display) VALUES (?,?,?,?)",
            (sid, r.get("title") or "", emission, value_display(r.get("face_value")) or ""))
        inserted += 1

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM stamps").fetchone()[0]
    col = con.execute("SELECT COUNT(*) FROM stamps WHERE id LIKE 'col-%'").fetchone()[0]
    con.close()
    print(f"inserted {inserted} Colnect records ({imaged} with images)")
    print(f"DB now: {total} total, {col} Colnect 2020-2026")


if __name__ == "__main__":
    main()
