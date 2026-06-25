#!/usr/bin/env python3
"""Extract An Post annual stamp programmes (2020-2026) from the Wayback Machine.

Each yearly snapshot of the Stamp Programme page lists that year's issues as
table rows: "<day month> | <description> | <n stamps>". We attach the
programme year to each row to form an exact issue date.

Output: data/sources/anpost_issues.jsonl -> {issue_date, year, title, n_stamps}
"""
import html
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sources"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT = OUT_DIR / "anpost_issues.jsonl"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
URL = "https://www.anpost.com/Shop/Stamp-Collecting/Stamp-Programme"

# one snapshot per programme year
SNAPSHOTS = {
    2020: "20200805024703", 2021: "20210126064755", 2022: "20220129232017",
    2023: "20230331171107", 2024: "20240228040048", 2025: "20250219224215",
    2026: "20260125035655",
}
MON = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def fetch(ts):
    url = f"http://web.archive.org/web/{ts}id_/{URL}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "ignore")


def parse(htmltxt, year):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", htmltxt, re.S | re.I):
        cells = [html.unescape(re.sub("<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        m = re.match(r"(\d{1,2})\s*([A-Za-z]{3})", cells[0])
        if not m:
            continue
        day, mon = int(m.group(1)), MON.get(m.group(2).lower())
        if not mon:
            continue
        title = cells[1]
        n = None
        for c in cells[2:]:
            if c.isdigit():
                n = int(c)
                break
        out.append({"issue_date": f"{year:04d}-{mon:02d}-{day:02d}",
                    "year": year, "title": title, "n_stamps": n})
    return out


def main():
    allrows = []
    for year, ts in sorted(SNAPSHOTS.items()):
        try:
            rows = parse(fetch(ts), year)
            print(f"  {year}: {len(rows)} issues")
            allrows += rows
        except Exception as e:  # noqa: BLE001
            print(f"  {year}: ERROR {e}")
    with OUT.open("w", encoding="utf-8") as f:
        for r in allrows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"DONE: {len(allrows)} An Post issues -> {OUT}")


if __name__ == "__main__":
    main()
