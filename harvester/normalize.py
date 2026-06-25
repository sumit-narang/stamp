#!/usr/bin/env python3
"""Consolidate harvested data into a clean dataset.

Merges:
  - data/metadata/records.jsonl   (OAI metadata)
  - data/metadata/images.jsonl    (downloaded image info)

Adds:
  - face value parsed from the "Value ..." description
  - currency system (predecimal / IEP decimal / EUR)
  - era + year range from the sub-collection
  - a narrowed year estimate where currency disambiguates the era
  - normalized issue_type (fixes the "Commorative" typo etc.)

Writes data/stamps.json (array) and data/stamps.jsonl.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META = ROOT / "data" / "metadata"

# sub-collection id -> (start_year, end_year)
ERA = {
    "pc28q7722": (1922, 1983),
    "pg15r456x": (1984, 2000),
    "pk02s1408": (2001, 2010),
    "pn89sx246": (2011, 2019),
}

FRAC = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}


def parse_value(desc_list):
    """Parse 'Value  1s 3d' / 'Value 60c' / 'Value 26p' -> structured value."""
    if not desc_list:
        return None
    raw = desc_list[0]
    s = re.sub(r"(?i)^\s*value\s*", "", raw).strip()
    if not s:
        return None
    txt = s
    for k, v in FRAC.items():
        txt = txt.replace(k, f"+{v}")

    out = {"raw": raw, "display": s, "currency": None, "amount": None}

    # dual-denominated transitional stamps, e.g. "30p/38c" (IEP->EUR, 1999-2002)
    if re.search(r"[\d.+]+\s*p\b", txt) and re.search(r"[\d.+]+\s*c\b", txt):
        mc = re.search(r"([\d.+]+)\s*c\b", txt)
        out.update(currency="dual-IEP-EUR", amount=round(_num(mc.group(1)) / 100, 4))
        return out

    # euro
    m = re.search(r"€\s*([\d.]+)", txt)
    if m:
        out.update(currency="EUR", amount=round(float(m.group(1)), 2))
        return out
    # cent (euro subunit)
    m = re.search(r"([\d.+]+)\s*c\b", txt)
    if m:
        out.update(currency="EUR", amount=round(_num(m.group(1)) / 100, 4))
        return out
    # pre-decimal shillings/pence: e.g. "1s 3d", "2½d", "6d", "3s"
    sh = re.search(r"([\d.+]+)\s*s", txt)
    pd = re.search(r"([\d.+]+)\s*d", txt)
    if sh or pd:
        shillings = _num(sh.group(1)) if sh else 0
        pence = _num(pd.group(1)) if pd else 0
        out.update(currency="GBP/IEP-predecimal",
                   amount=round(shillings + pence / 12, 4),  # in shillings
                   shillings=shillings, pence=pence)
        return out
    # decimal pence (Irish pound 1971-2001): "26p", "5p"
    m = re.search(r"([\d.+]+)\s*p\b", txt)
    if m:
        out.update(currency="IEP-decimal", amount=round(_num(m.group(1)) / 100, 4))
        return out
    return out


def _num(x):
    if "+" in x:
        return sum(float(p) for p in x.split("+") if p)
    try:
        return float(x)
    except ValueError:
        return 0.0


def narrow_years(era, currency):
    """Use currency system to narrow the era's year range."""
    if not era:
        return None
    lo, hi = era
    if currency == "EUR":            # euro from 2002
        lo = max(lo, 2002)
    elif currency == "dual-IEP-EUR":  # dual-denominated changeover 1999-2002
        lo, hi = max(lo, 1999), min(hi, 2002)
    elif currency == "IEP-decimal":  # decimal pence 1971-2001
        lo, hi = max(lo, 1971), min(hi, 2001)
    elif currency == "GBP/IEP-predecimal":  # pre-decimal up to 1970
        hi = min(hi, 1970)
    if lo > hi:  # currency/era disagree; fall back to full era range
        return list(era)
    return [lo, hi]


def norm_type(subjects):
    fix = {"commorative": "Commemorative"}
    return [fix.get(s.lower(), s) for s in subjects]


def main():
    images = {}
    img_path = META / "images.jsonl"
    if img_path.exists():
        for l in img_path.read_text().splitlines():
            if l.strip():
                d = json.loads(l)
                images[d["id"]] = [f for f in d.get("files", []) if "path" in f]

    out = []
    for l in (META / "records.jsonl").read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        sub = (r["set_specs"][0].split(":")[-1] if r.get("set_specs") else None)
        era = ERA.get(sub)
        value = parse_value(r.get("description"))
        currency = value["currency"] if value else None
        imgs = images.get(r["id"], [])
        primary = imgs[0] if imgs else None
        out.append({
            "id": r["id"],
            "title": r["title"],
            "value": value,
            "issue_type": norm_type(r.get("subject", [])),
            "creator": (r.get("creator") or [None])[0],
            "era_collection": sub,
            "year_range": list(era) if era else None,
            "year_estimate": narrow_years(era, currency),
            "image": (f"data/images/{r['id']}/{primary['file_id']}.jpg" if primary else None),
            "image_iiif": (f"https://repository.dri.ie/iiif/2/{r['id']}:{primary['file_id']}/full/full/0/default.jpg"
                           if primary else None),
            "image_dimensions": ([primary.get("width"), primary.get("height")] if primary else None),
            "n_images": len(imgs),
            "rights": r["rights"],
            "source_url": r["source_url"],
        })

    (ROOT / "data" / "stamps.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    with (ROOT / "data" / "stamps.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # quick report
    with_img = sum(1 for r in out if r["image"])
    print(f"{len(out)} stamps -> data/stamps.json ({with_img} with images)")
    from collections import Counter
    cur = Counter(r["value"]["currency"] if r["value"] else None for r in out)
    print("currency:", dict(cur))


if __name__ == "__main__":
    main()
