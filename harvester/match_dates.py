#!/usr/bin/env python3
"""Match external dated issues (PDF / Wikipedia) onto DRI stamp records.

DRI records have a title + era range but no date. External sources have
title + exact date + year. DRI rewords titles ("Death of X" vs
"Death Centenary of X"), so we match on:
  - the source's year must fall inside the DRI stamp's era range
  - fuzzy title similarity (significant-token Jaccard + sequence ratio)

A single source issue (e.g. a 2-value set) maps to several DRI stamps, which
all receive the same issue_date. Results are written to data/sources/
matched_dates.jsonl and applied to data/stamps.db.

Usage: match_dates.py [--min-year 1995] [--max-year 2019] [--threshold 0.45]
"""
import argparse
import difflib
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data" / "sources"
STAMPS = ROOT / "data" / "stamps.json"
DB = ROOT / "data" / "stamps.db"
OUT = SRC_DIR / "matched_dates.jsonl"

STOP = set("""the of and a an to in on for st nd rd th anniversary centenary
birth death year years issue commemorative commemoration of bi tri cent
centenaries new series death-centenary""".split())


def norm_tokens(t):
    t = re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())
    return [w for w in t.split() if w and w not in STOP and len(w) > 1]


def sim(a, b):
    ta, tb = set(norm_tokens(a)), set(norm_tokens(b))
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    ratio = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return 0.6 * jac + 0.4 * ratio


def load_sources():
    issues = []
    for fn, src in [("pdf_issues.jsonl", "irishphil_pdf"),
                    ("wikipedia_issues.jsonl", "wikipedia")]:
        p = SRC_DIR / fn
        if p.exists():
            for l in p.read_text().splitlines():
                if l.strip():
                    d = json.loads(l)
                    d["_src"] = src
                    issues.append(d)
    return issues


def explicit_year(title):
    """A DRI title sometimes embeds the issue year, e.g. '... 1795-1995'."""
    ys = re.findall(r"\b(19\d{2}|20\d{2})\b", title or "")
    return int(ys[-1]) if ys else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-year", type=int, default=1900)
    ap.add_argument("--max-year", type=int, default=2001)
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--margin", type=float, default=0.04,
                    help="issues within this of the best are 'tied'")
    args = ap.parse_args()

    # load ALL source issues (full ambiguity detection across years)
    sources = load_sources()
    stamps = json.loads(STAMPS.read_text())
    cand = [s for s in stamps if (s.get("year_range") or [None])[0]]
    print(f"{len(sources)} source issues, {len(cand)} DRI stamps with an era")

    # recurring titles (Christmas, Love, Greetings, ...) appear across many
    # years; a title-only match to them can't pin the year, so never date by it.
    from collections import defaultdict
    title_years = defaultdict(set)
    for iss in sources:
        key = " ".join(sorted(norm_tokens(iss["title"])))
        title_years[key].add(iss["year"])
    recurring = {k for k, ys in title_years.items() if len(ys) >= 2}

    matches = []
    ambiguous = 0
    for s in cand:
        lo, hi = s["year_range"]
        # candidate issues must fall inside this stamp's era range
        scored = [(sim(s["title"], iss["title"]), iss)
                  for iss in sources if lo <= iss["year"] <= hi]
        scored = [x for x in scored if x[0] >= args.threshold]
        if not scored:
            continue
        scored.sort(key=lambda x: -x[0])
        best_score = scored[0][0]
        # all issues effectively tied with the best
        tied = [iss for sc, iss in scored if sc >= best_score - args.margin]
        tied_years = {iss["year"] for iss in tied}
        chosen = None
        best_key = " ".join(sorted(norm_tokens(scored[0][1]["title"])))
        ey = explicit_year(s["title"])
        if best_key in recurring:
            # recurring title (Christmas, Love, ...): only datable if the DRI
            # title states a year AND a candidate issue is from exactly that year
            agree = [iss for iss in tied if iss["year"] == ey] if ey else []
            chosen = agree[0] if len(agree) == 1 else None
        elif len(tied_years) == 1:
            chosen = scored[0][1]                       # unambiguous unique title
        else:
            # non-recurring but spans years: rescue only via matching explicit year
            agree = [iss for iss in tied if iss["year"] == ey] if ey else []
            chosen = agree[0] if len(agree) == 1 else None
        if chosen is None:
            ambiguous += 1
            continue
        matches.append({
            "stamp_id": s["id"], "stamp_title": s["title"],
            "issue_date": chosen["issue_date"], "year": chosen["year"],
            "matched_title": chosen["title"], "source": chosen["_src"],
            "confidence": round(best_score, 3),
        })

    print(f"assigned {len(matches)} dates; skipped {ambiguous} as year-ambiguous")
    with OUT.open("w", encoding="utf-8") as f:
        for m in matches:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    # apply to DB (clear prior DRI enrichment first so it's re-runnable)
    con = sqlite3.connect(DB)
    con.execute("UPDATE stamps SET issue_date=NULL, year=NULL, date_source=NULL "
                "WHERE id NOT LIKE 'anpost-%' "
                "AND (date_source IS NULL OR date_source != 'stamp_image')")
    con.execute("DELETE FROM date_sources")
    for m in matches:
        con.execute(
            "UPDATE stamps SET issue_date=?, year=?, date_source=? WHERE id=?",
            (m["issue_date"], m["year"], m["source"], m["stamp_id"]))
        con.execute(
            "INSERT OR REPLACE INTO date_sources VALUES (?,?,?,?,?,?)",
            (m["stamp_id"], m["source"], m["issue_date"], m["year"],
             m["confidence"], m["matched_title"]))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM stamps WHERE issue_date IS NOT NULL").fetchone()[0]
    con.close()
    print(f"matched {len(matches)} stamps; DB now has {n} stamps with exact dates")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
