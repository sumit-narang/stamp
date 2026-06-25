#!/usr/bin/env python3
"""Download Colnect images for the An Post records that lacked one, and attach.

Reads data/sources/colnect_details.jsonl (id -> og_image), downloads each image
from the i.colnect.net CDN into data/images_anpost/, and sets image_path +
designer (where captured) on the matching anpost-* row in stamps.db.
"""
import json
import sqlite3
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "sources" / "colnect_details.jsonl"
IMG_DIR = ROOT / "data" / "images_anpost"
DB = ROOT / "data" / "stamps.db"
IMG_DIR.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Referer": "https://colnect.com/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    recs = [json.loads(l) for l in SRC.read_text().splitlines() if l.strip()]
    con = sqlite3.connect(DB)
    ok = 0
    for r in recs:
        img = r.get("og_image")
        if not img:
            continue
        dest = IMG_DIR / f"colnect-{r['id']}.jpg"
        try:
            if not dest.exists():
                blob = get(img)
                if len(blob) < 1000:
                    print(f"  tiny/blocked: {r['id']}")
                    continue
                dest.write_bytes(blob)
                time.sleep(1.0)
            rel = str(dest.relative_to(ROOT))
            designer = r.get("designer")
            if designer in (None, "Detail", "from colnect.com"):
                designer = None
            con.execute(
                "UPDATE stamps SET image_path=?, n_images=COALESCE(NULLIF(n_images,0),1), "
                "designer=COALESCE(?, designer) WHERE id=? AND image_path IS NULL",
                (rel, designer, r["id"]))
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {r['id']}: {e}")
    con.commit()
    # report
    tot = con.execute("SELECT COUNT(*) FROM stamps").fetchone()[0]
    img = con.execute("SELECT COUNT(*) FROM stamps WHERE image_path IS NOT NULL").fetchone()[0]
    ap_img = con.execute("SELECT COUNT(*) FROM stamps WHERE id LIKE 'anpost-%' AND image_path IS NOT NULL").fetchone()[0]
    ap_tot = con.execute("SELECT COUNT(*) FROM stamps WHERE id LIKE 'anpost-%'").fetchone()[0]
    con.close()
    print(f"downloaded/attached {ok} Colnect images")
    print(f"An Post records with image: {ap_img}/{ap_tot}")
    print(f"OVERALL image coverage: {img}/{tot} ({round(100*img/tot)}%)")


if __name__ == "__main__":
    main()
