#!/usr/bin/env python3
"""Read the issue YEAR printed on each stamp image (OCR).

Many Irish stamps print the issue year on the design or in the bottom margin.
We OCR every image, keep 4-digit years, and accept a year only if EXACTLY ONE
of them falls inside the stamp's DRI era bucket -- that filters out depicted /
historical years (e.g. a 1963 death year on a stamp issued in 2013).

Assigns a year-only date (issue_date stays NULL, so precision is "year") to
stamps that do NOT already have an exact date. Existing exact dates are kept and
cross-checked for QA.

Source tag: date_source='stamp_image'.  Output: data/sources/image_years.jsonl
"""
import json
import re
import sqlite3
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "stamps.db"
OUT = ROOT / "data" / "sources" / "image_years.jsonl"
YEAR_RE = re.compile(r"\b(19[2-9]\d|20[0-2]\d)\b")


def ocr_years(path):
    try:
        img = Image.open(path).convert("L")
        if max(img.size) < 1400:          # upscale so small margin text is legible
            img = img.resize((img.width * 2, img.height * 2))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
            tmp = t.name
        img.save(tmp)
        txt = subprocess.run(["tesseract", tmp, "stdout", "--psm", "11"],
                             capture_output=True, text=True, timeout=90).stdout
        Path(tmp).unlink(missing_ok=True)
        return sorted({int(y) for y in YEAR_RE.findall(txt)})
    except Exception:  # noqa: BLE001
        return []


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id,title,image_path,year_start,year_end,issue_date,year "
        "FROM stamps WHERE image_path IS NOT NULL").fetchall()
    con.close()
    print(f"OCR-ing {len(rows)} stamp images for printed years...", flush=True)

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(ocr_years, ROOT / r["image_path"]): r for r in rows}
        for fut in as_completed(futs):
            r = futs[fut]
            ys = fut.result()
            inb = [y for y in ys if r["year_start"] <= y <= r["year_end"]]
            results.append((r, ys, inb))
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(rows)}", flush=True)

    con = sqlite3.connect(DB)
    # clear any prior image-OCR assignments (idempotent)
    con.execute("UPDATE stamps SET year=NULL, date_source=NULL "
                "WHERE date_source='stamp_image'")
    assigned = ambiguous = none = has_exact = qa_ok = qa_bad = 0
    with OUT.open("w", encoding="utf-8") as f:
        for r, ys, inb in results:
            rec = {"id": r["id"], "title": r["title"],
                   "ocr_years": ys, "in_bucket": inb}
            if r["issue_date"] is not None:           # already exact -> QA only
                has_exact += 1
                rec["status"] = "has_exact_date"
                if inb:
                    if r["year"] in inb:
                        qa_ok += 1
                    else:
                        qa_bad += 1
                        rec["qa_mismatch"] = {"stored": r["year"], "image": inb}
            elif len(inb) == 1:                        # confident year
                con.execute(
                    "UPDATE stamps SET year=?, date_source='stamp_image' WHERE id=?",
                    (inb[0], r["id"]))
                assigned += 1
                rec["status"] = "assigned"
                rec["assigned_year"] = inb[0]
            elif len(inb) > 1:
                ambiguous += 1
                rec["status"] = "ambiguous"
            else:
                none += 1
                rec["status"] = "no_year_found"
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    con.commit()
    total_year = con.execute(
        "SELECT COUNT(*) FROM stamps WHERE year IS NOT NULL").fetchone()[0]
    con.close()

    print(f"\nDONE over {len(results)} images:")
    print(f"  assigned year (was undated): {assigned}")
    print(f"  ambiguous (>1 in-bucket year): {ambiguous}")
    print(f"  no year found on image:        {none}")
    print(f"  already had exact date:        {has_exact} "
          f"(QA: {qa_ok} agree, {qa_bad} mismatch)")
    print(f"  -> stamps with at least a YEAR now: {total_year}")
    print(f"  -> details: {OUT}")


if __name__ == "__main__":
    main()
