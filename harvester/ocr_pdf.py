#!/usr/bin/env python3
"""OCR the irishphil commemoratives PDF and extract issue date + title headers.

The catalogue prints each issue as a bold header like:
    "29 December 1937 - Constitution Day"
We render each page (PyMuPDF), OCR it (tesseract), and regex out those headers.

Output: data/sources/pdf_issues.jsonl  -> {issue_date, year, title, page, raw}
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "data" / "irishphil_commem.pdf"
OUT_DIR = ROOT / "data" / "sources"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "pdf_issues.jsonl"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

# "29 December 1937 - Constitution Day"  (allow OCR noise around the dash)
DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(19\d{2}|20\d{2})\s*[-–—:]\s*(.+)",
    re.IGNORECASE)


def ocr_page(page) -> str:
    pix = page.get_pixmap(dpi=300)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    pix.save(tmp)
    try:
        res = subprocess.run(
            ["tesseract", tmp, "stdout", "--psm", "4", "-l", "eng"],
            capture_output=True, text=True, timeout=120)
        return res.stdout
    finally:
        Path(tmp).unlink(missing_ok=True)


def clean_title(t):
    t = re.sub(r"\s+", " ", t).strip()
    # cut trailing junk after common separators / page noise
    t = re.split(r"\s{2,}|Design by|Typograph|Lithograph|Sheet format|Issued", t)[0]
    return t.strip(" .-–—")


def main():
    doc = fitz.open(PDF)
    issues = []
    for i, page in enumerate(doc):
        txt = ocr_page(page)
        for line in txt.splitlines():
            m = DATE_RE.search(line)
            if not m:
                continue
            day, mon, year, title = m.groups()
            mon_n = MONTHS[mon.capitalize()]
            try:
                iso = f"{int(year):04d}-{mon_n:02d}-{int(day):02d}"
            except ValueError:
                continue
            title = clean_title(title)
            if len(title) < 3:
                continue
            issues.append({"issue_date": iso, "year": int(year),
                           "title": title, "page": i + 1, "raw": line.strip()})
        if (i + 1) % 20 == 0:
            print(f"  OCR'd {i+1}/{len(doc)} pages, {len(issues)} issues so far", flush=True)
    # de-dupe by (date,title)
    seen, uniq = set(), []
    for it in issues:
        k = (it["issue_date"], it["title"].lower())
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    with OUT.open("w", encoding="utf-8") as f:
        for it in uniq:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    yrs = sorted({it["year"] for it in uniq})
    print(f"DONE: {len(uniq)} unique issues, years {min(yrs)}-{max(yrs)} -> {OUT}")


if __name__ == "__main__":
    main()
