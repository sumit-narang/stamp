#!/usr/bin/env python3
"""Resolve fileIds via IIIF manifests and download full-resolution stamp images.

Reads data/metadata/records.jsonl (from oai_harvest.py). For each record:
  1. GET /iiif/{id}/manifest.json        -> fileId(s) + width/height per canvas
  2. GET /iiif/2/{id}:{fileId}/full/full/0/default.jpg  -> the image

All these /iiif/ endpoints are open (not Cloudflare-gated). Stdlib only.

Outputs:
  - data/images/{id}/{fileId}.jpg
  - data/metadata/images.jsonl   (record -> [{file_id,width,height,path,bytes}])

Idempotent / resumable: skips images already on disk, and skips records
already present in images.jsonl (unless --force).
"""
import argparse
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
ROOT = Path(__file__).resolve().parent.parent
META = ROOT / "data" / "metadata"
IMG_DIR = ROOT / "data" / "images"
RECORDS = META / "records.jsonl"
OUT = META / "images.jsonl"
IMG_DIR.mkdir(parents=True, exist_ok=True)


def get(url, binary=False, attempt=1):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = r.read()
            return data if binary else data.decode("utf-8")
    except Exception as e:  # noqa: BLE001
        if attempt >= 4:
            raise
        time.sleep(2 ** attempt)
        return get(url, binary, attempt + 1)


def manifest_files(rec_id):
    """Return list of (file_id, width, height) for a record."""
    url = f"https://repository.dri.ie/iiif/{rec_id}/manifest.json"
    d = json.loads(get(url))
    out = []
    for seq in d.get("sequences", []):
        for c in seq.get("canvases", []):
            for img in c.get("images", []):
                res = img.get("resource", {})
                svc = res.get("service", {}).get("@id", "")
                # svc looks like .../loris/{rec_id}:{file_id}
                fid = svc.rsplit(":", 1)[-1] if ":" in svc.rsplit("/", 1)[-1] else None
                if fid:
                    out.append((fid, res.get("width"), res.get("height")))
    return out


def download_record(rec_id):
    try:
        files = manifest_files(rec_id)
    except Exception as e:  # noqa: BLE001
        return {"id": rec_id, "error": f"manifest: {e}", "files": []}
    saved = []
    rec_dir = IMG_DIR / rec_id
    for fid, w, h in files:
        dest = rec_dir / f"{fid}.jpg"
        try:
            if dest.exists() and dest.stat().st_size > 0:
                nbytes = dest.stat().st_size
            else:
                rec_dir.mkdir(parents=True, exist_ok=True)
                img_url = (f"https://repository.dri.ie/iiif/2/"
                           f"{rec_id}:{fid}/full/full/0/default.jpg")
                blob = get(img_url, binary=True)
                dest.write_bytes(blob)
                nbytes = len(blob)
            saved.append({"file_id": fid, "width": w, "height": h,
                          "path": str(dest.relative_to(ROOT)), "bytes": nbytes})
        except Exception as e:  # noqa: BLE001
            saved.append({"file_id": fid, "error": str(e)})
    return {"id": rec_id, "files": saved}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    ids = [json.loads(l)["id"] for l in RECORDS.read_text().splitlines() if l.strip()]
    done = set()
    if OUT.exists() and not args.force:
        for l in OUT.read_text().splitlines():
            if l.strip():
                done.add(json.loads(l)["id"])
    todo = [i for i in ids if i not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(ids)} records, {len(done)} already done, {len(todo)} to fetch", flush=True)

    n_ok = n_err = n_imgs = 0
    mode = "a" if (OUT.exists() and not args.force) else "w"
    with OUT.open(mode, encoding="utf-8") as fout, \
            ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(download_record, i): i for i in todo}
        for k, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            fout.write(json.dumps(res, ensure_ascii=False) + "\n")
            fout.flush()
            ok_files = [f for f in res["files"] if "path" in f]
            n_imgs += len(ok_files)
            if res.get("error") or any("error" in f for f in res["files"]):
                n_err += 1
            else:
                n_ok += 1
            if k % 50 == 0 or k == len(todo):
                print(f"  {k}/{len(todo)} records | {n_imgs} images | {n_err} with errors",
                      flush=True)
    print(f"DONE: {n_ok} ok, {n_err} with errors, {n_imgs} images -> {IMG_DIR}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
