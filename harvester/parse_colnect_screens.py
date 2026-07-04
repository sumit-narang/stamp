#!/usr/bin/env python3
"""Extract stamp metadata from manually-captured Colnect screenshots.

The user captured Colnect detail pages (PNG) for every 2020-2026 stamp. Each
screenshot's metadata panel OCRs cleanly. This reads every screenshot in a
year's folder, parses the label/value fields, and also matches each to the
clean stamp image in the same year folder (by title similarity).

Usage: parse_colnect_screens.py <year>   (e.g. 2022)
Output: data/colnect_manual/<year>.jsonl
"""
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

SRC_ROOT = Path("/Users/sumit/Downloads/2020 2026")
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "colnect_manual"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# single-value labels -> output key
LABELS = {
    "Country": "country", "Series": "series", "Themes": "themes",
    "Issued on": "issued_on", "Size": "size", "Colors": "colors",
    "Designers": "designers", "Designer": "designers",
    "Printers": "printers", "Printer": "printers",
    "Format": "format", "Emission": "emission", "Perforation": "perforation",
    "Printing": "printing", "Watermark": "watermark", "Gum": "gum",
    "Face value": "face_value", "Print run": "print_run",
    "Description": "description",
}
CATALOGS = ["Michel", "Stanley Gibbons", "Scott", "Yvert et Tellier",
            "Stamp Number", "Unificato", "AFA", "Facit"]


def strip_noise(v):
    """Drop trailing OCR garbage (stray 1-2 char tokens / symbols)."""
    v = re.sub(r'(\s+([^\sA-Za-z0-9]+|[a-zA-Z]{1,2}))+$', '', v).strip()
    return v


def ocr(path):
    return subprocess.run(["tesseract", str(path), "stdout", "--psm", "4"],
                          capture_output=True, text=True, timeout=120).stdout


def clean(v):
    return re.sub(r"\s+", " ", v).strip(" .:-")


def parse(text):
    rec = {"catalog": {}}
    # title from breadcrumb "Stamp » <title>"  (fall back to URL slug)
    m = re.search(r"Stamp\s*[»>]\s*(.+)", text)
    if m:
        rec["title"] = clean(m.group(1))
    url = re.search(r"colnect\.com/en/stamps/stamp/(\d+)-([^\s?]+)", text)
    if url:
        rec["colnect_id"] = url.group(1)
        rec["colnect_slug"] = url.group(2)
        if not rec.get("title"):
            rec["title"] = url.group(2).split("-")[0].replace("_", " ")

    for line in text.splitlines():
        line = line.strip()
        # catalog code lines
        for cat in CATALOGS:
            m = re.match(rf"{re.escape(cat)}\s+((?:IE|Ei|E1)?\s*[\w./\-]+)", line)
            if m:
                rec["catalog"][cat] = clean(m.group(1))
        # labelled fields
        m = re.match(r"([A-Za-z ]+?):\s*(.+)", line)
        if m:
            label, val = m.group(1).strip(), clean(m.group(2))
            if label in LABELS and val:
                key = LABELS[label]
                if key in ("designers", "printers", "series", "perforation",
                           "printing", "gum", "colors", "size"):
                    val = strip_noise(val)
                rec.setdefault(key, val)

    # normalise issue date to YYYY-MM-DD if present
    if rec.get("issued_on"):
        d = re.search(r"(\d{4})-(\d{2})-(\d{2})", rec["issued_on"])
        rec["issued_on"] = d.group(0) if d else rec["issued_on"]
    return rec


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def main():
    year = sys.argv[1] if len(sys.argv) > 1 else "2022"
    folder = SRC_ROOT / year
    shots = sorted((folder / "screenshots").glob("*.png"))
    images = [p for p in folder.glob("*.jpg")]
    img_norm = [(p, norm(p.stem)) for p in images]

    out = []
    for i, shot in enumerate(shots, 1):
        text = ocr(shot)
        rec = parse(text)
        rec["screenshot"] = shot.name
        rec["year"] = int(year)
        # match to a stamp image by title similarity
        if rec.get("title"):
            nt = norm(rec["title"])
            best, best_sc = None, 0.0
            for p, pn in img_norm:
                sc = difflib.SequenceMatcher(None, nt, pn).ratio()
                if sc > best_sc:
                    best, best_sc = p, sc
            if best and best_sc >= 0.5:
                rec["image_file"] = best.name
                rec["image_match"] = round(best_sc, 2)
        out.append(rec)
        if i % 20 == 0:
            print(f"  {i}/{len(shots)}", flush=True)

    dest = OUT_DIR / f"{year}.jsonl"
    with dest.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dated = sum(1 for r in out if r.get("issued_on"))
    matched = sum(1 for r in out if r.get("image_file"))
    print(f"DONE {year}: {len(out)} screenshots parsed, {dated} with dates, "
          f"{matched} matched to an image -> {dest}")


if __name__ == "__main__":
    main()
