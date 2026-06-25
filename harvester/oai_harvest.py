#!/usr/bin/env python3
"""Harvest stamp metadata from the DRI OAI-PMH feed (open, no Cloudflare).

Pages through ListRecords for the Post Office Irish Postage Stamp Collection
(set collection:p841pb88f) using resumption tokens, parses oai_dc into clean
JSON, and writes:
  - data/raw/oai_page_NNN.xml   (raw responses, for re-parsing later)
  - data/metadata/records.jsonl (one parsed record per line)

Stdlib only: urllib + xml.etree. No external deps.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "https://repository.dri.ie/oai"
SET = "collection:p841pb88f"
PREFIX = "oai_dc"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
META_DIR = ROOT / "data" / "metadata"
RAW_DIR.mkdir(parents=True, exist_ok=True)
META_DIR.mkdir(parents=True, exist_ok=True)
OUT = META_DIR / "records.jsonl"

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}


def fetch(params, attempt=1):
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001
        if attempt >= 5:
            raise
        wait = 2 ** attempt
        print(f"  ! fetch error ({e}); retry {attempt} in {wait}s", flush=True)
        time.sleep(wait)
        return fetch(params, attempt + 1)


def parse_record(rec):
    header = rec.find("oai:header", NS)
    ident = header.findtext("oai:identifier", default="", namespaces=NS)
    datestamp = header.findtext("oai:datestamp", default="", namespaces=NS)
    setspecs = [s.text for s in header.findall("oai:setSpec", NS)]
    dc = rec.find(".//oai_dc:dc", NS)
    fields = {}
    if dc is not None:
        for el in dc:
            tag = el.tag.split("}")[-1]
            val = (el.text or "").strip()
            if not val:
                continue
            fields.setdefault(tag, []).append(val)
    pid = ident.split(":")[-1] if ident else ""
    return {
        "id": pid,
        "oai_identifier": ident,
        "datestamp": datestamp,
        "set_specs": setspecs,
        "title": (fields.get("title") or [None])[0],
        "description": fields.get("description", []),
        "creator": fields.get("creator", []),
        "subject": fields.get("subject", []),
        "type": fields.get("type", []),
        "date": fields.get("date", []),
        "format": fields.get("format", []),
        "rights": (fields.get("rights") or [None])[0],
        "source_url": f"https://repository.dri.ie/catalog/{pid}",
    }


def main():
    params = {"verb": "ListRecords", "metadataPrefix": PREFIX, "set": SET}
    page = 0
    total = 0
    seen = set()
    with OUT.open("w", encoding="utf-8") as fout:
        while True:
            page += 1
            data = fetch(params)
            (RAW_DIR / f"oai_page_{page:03d}.xml").write_bytes(data)
            root = ET.fromstring(data)
            err = root.find("oai:error", NS)
            if err is not None:
                print(f"OAI error: {err.get('code')}: {err.text}", flush=True)
                break
            records = root.findall(".//oai:record", NS)
            for rec in records:
                r = parse_record(rec)
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                total += 1
            fout.flush()
            token_el = root.find(".//oai:resumptionToken", NS)
            size = token_el.get("completeListSize") if token_el is not None else "?"
            print(f"page {page}: +{len(records)} records (total {total}/{size})", flush=True)
            token = token_el.text.strip() if (token_el is not None and token_el.text) else None
            if not token:
                break
            params = {"verb": "ListRecords", "resumptionToken": token}
            time.sleep(0.5)
    print(f"DONE: {total} unique records -> {OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
