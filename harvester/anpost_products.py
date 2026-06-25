#!/usr/bin/env python3
"""Scrape An Post shop stamp product pages for images + metadata.

The live An Post HTML is bot-blocked, but:
  - the archived product pages (Wayback) carry title / og:image / images /
    description, and
  - the getapmedia image CDN serves images directly to plain requests.

So: enumerate archived product URLs (Wayback CDX) -> fetch each archived page
(decompressed) -> extract metadata + image URLs -> download images from the
live CDN (fallback to Wayback).

Output: data/sources/anpost_products.jsonl + images in data/images_anpost/.
"""
import html
import json
import re
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sources" / "anpost_products.jsonl"
IMG_DIR = ROOT / "data" / "images_anpost"
IMG_DIR.mkdir(parents=True, exist_ok=True)
OUT.parent.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")


def get(url, binary=False, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw if binary else raw.decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            if a == tries - 1:
                return None
            time.sleep(2 ** a)


def list_products():
    """Latest archived snapshot timestamp per product URL."""
    cdx = ("http://web.archive.org/cdx/search/cdx?url=anpost.com/Shop/"
           "Special-issue-stamps*&output=json&filter=statuscode:200"
           "&fl=timestamp,original&collapse=urlkey")
    data = json.loads(get(cdx))
    out = {}
    for ts, original in data[1:]:
        # keep only real product pages (have a slug after the section)
        if re.search(r"/Special-issue-stamps/.+", original):
            out[original] = max(out.get(original, ""), ts)
    return out


def parse(htmltxt):
    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)="{prop}"[^>]*content="([^"]*)"',
                      htmltxt, re.I)
        return html.unescape(m.group(1)).strip() if m else None
    title = (meta("og:title") or "").replace("Shop ", "").replace(" at An Post", "")
    desc = meta("og:description") or meta("description")
    # image URLs on the getapmedia CDN
    imgs = re.findall(r'(?:src|data-src|content)="((?:https?://www\.anpost\.com)?'
                      r'/getapmedia/[^"]+\.(?:jpg|jpeg|png|webp))"', htmltxt, re.I)
    norm = []
    for i in dict.fromkeys(imgs):
        if i.startswith("/"):
            i = "https://www.anpost.com" + i
        norm.append(i)
    # prefer the actual stamp image over sheet / FDC / pack
    def rank(u):
        u = u.lower()
        return (0 if "stamp" in u and not any(x in u for x in
                ("sheet", "fdc", "cover", "pack", "booklet")) else 1)
    norm.sort(key=rank)
    return {"title": title, "description": desc, "images": norm}


def slug(u):
    return u.rstrip("/").rsplit("/", 1)[-1]


def main():
    products = list_products()
    print(f"{len(products)} archived product pages", flush=True)
    n_img = 0
    with OUT.open("w", encoding="utf-8") as f:
        for k, (url, ts) in enumerate(sorted(products.items()), 1):
            page = get(f"http://web.archive.org/web/{ts}id_/{url}")
            if not page:
                continue
            info = parse(page)
            info["url"] = url
            info["slug"] = slug(url)
            info["snapshot"] = ts
            info["image_path"] = None
            if info["images"]:
                dest = IMG_DIR / f"{info['slug']}.jpg"
                if not dest.exists():
                    blob = get(info["images"][0], binary=True)
                    if not blob or len(blob) < 1000:  # fallback to wayback copy
                        blob = get(f"http://web.archive.org/web/{ts}im_/{info['images'][0]}",
                                   binary=True)
                    if blob and len(blob) > 1000:
                        dest.write_bytes(blob)
                if dest.exists():
                    info["image_path"] = str(dest.relative_to(ROOT))
                    n_img += 1
            f.write(json.dumps(info, ensure_ascii=False) + "\n")
            f.flush()
            if k % 25 == 0:
                print(f"  {k}/{len(products)} pages, {n_img} images", flush=True)
            time.sleep(0.4)
    print(f"DONE: {len(products)} products, {n_img} images -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
