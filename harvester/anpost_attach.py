#!/usr/bin/env python3
"""Attach An Post product images to the 96 An Post issue records (2020-2026).

Matches programme issue titles ("Bicentenary of the RNLI") to scraped product
titles ("Bicentenary of the RNLI") by fuzzy significant-token similarity, then
sets image_path (+ source_url) on the matching anpost-* rows in stamps.db.
"""
import difflib
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "stamps.db"
PROD = ROOT / "data" / "sources" / "anpost_products.jsonl"

STOP = set("the of and a an to in on for st nd rd th pair stamps stamp".split())


def toks(t):
    t = re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())
    return {w for w in t.split() if w and w not in STOP and len(w) > 1}


def sim(a, b):
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    ratio = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return 0.6 * jac + 0.4 * ratio


def main():
    products = [json.loads(l) for l in PROD.read_text().splitlines() if l.strip()]
    products = [p for p in products if p.get("image_path")]
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("UPDATE stamps SET image_path=NULL WHERE id LIKE 'anpost-%'")  # idempotent
    rows = con.execute("SELECT id, title, year FROM stamps WHERE id LIKE 'anpost-%'").fetchall()

    attached = 0
    for r in rows:
        best, best_sc = None, 0.0
        for p in products:
            sc = sim(r["title"], p["title"])
            # year-aware: a year in the product title must agree with the record
            pyear = re.search(r"\b(20[12]\d)\b", p["title"] + " " + p["slug"])
            if pyear:
                if int(pyear.group(1)) == r["year"]:
                    sc += 0.15          # same-year evidence -> boost
                else:
                    sc = 0.0            # different year -> reject outright
            if sc > best_sc:
                best, best_sc = p, sc
        if best and best_sc >= 0.55:
            con.execute(
                "UPDATE stamps SET image_path=?, source_url=?, n_images=? WHERE id=?",
                (best["image_path"],
                 f"https://www.anpost.com/Shop/Special-issue-stamps/{best['slug']}",
                 max(1, len(best["images"])), r["id"]))
            attached += 1
    con.commit()
    with_img = con.execute(
        "SELECT COUNT(*) FROM stamps WHERE id LIKE 'anpost-%' AND image_path IS NOT NULL").fetchone()[0]
    con.close()
    print(f"attached images to {attached}/{len(rows)} An Post issue records "
          f"(now {with_img} with an image)")


if __name__ == "__main__":
    main()
