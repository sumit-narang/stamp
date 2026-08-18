#!/usr/bin/env python3
"""Irish Stamp API — public REST service over data/stamps.db.

Run:  .venv/bin/uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs   (auto-generated OpenAPI)
"""
import json
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "stamps.db"
IMG_ROOT = ROOT / "data" / "images"
THUMB_DIR = ROOT / "data" / "thumbs"
THUMB_DIR.mkdir(parents=True, exist_ok=True)

# Browse buckets, newest first. An Post years 2020-2026 are lumped together;
# 1922-2019 use the four DRI era buckets.
BUCKETS = ["2020-2026", "2011-2019", "2001-2010", "1984-2000", "1922-1983"]

# production mode (STAMP_ENV=production): disables the interactive API docs and
# gates the raw full-resolution image routes (only perforated thumbnails served).
PROD = os.environ.get("STAMP_ENV") == "production"

app = FastAPI(
    title="Irish Stamp API",
    version="0.1.0",
    description=(
        "Every Irish postage stamp (1922-present), harvested from the Digital "
        "Repository of Ireland (An Post Museum & Archive). Issue dates are "
        "currently era estimates; exact dates are being backfilled."
    ),
    # hide the API surface + schema in production
    docs_url=None if PROD else "/docs",
    redoc_url=None if PROD else "/redoc",
    openapi_url=None if PROD else "/openapi.json",
)

# CORS: locked to specific origins in production via STAMP_CORS_ORIGINS
# (comma-separated); defaults to "*" for local dev. The deployed site is
# same-origin (served behind the same nginx via /stamp-api), so CORS is moot
# there — this just avoids leaving it wide open when hit cross-origin.
_origins = os.environ.get("STAMP_CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",")] if _origins != "*" else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def bucket_of(row):
    """The browse bucket for a stamp (lumps An Post 2020-2026)."""
    yr = row["year"] if "year" in row.keys() else None
    if str(row["id"]).startswith("anpost-") or (yr and yr >= 2020):
        return "2020-2026"
    return row["era"] if "era" in row.keys() else None


def db():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def to_stamp(row):
    d = dict(row)
    d["bucket"] = bucket_of(row)
    d["issue_types"] = json.loads(d.get("issue_types") or "[]")
    d["year_estimate"] = [d.pop("year_est_lo"), d.pop("year_est_hi")]
    d["year_range"] = [d.pop("year_start"), d.pop("year_end")]
    d["image_dimensions"] = [d.pop("image_w"), d.pop("image_h")]
    d["image_api"] = f"/stamps/{d['id']}/image"
    return d


GRID_SIZE = 360          # the thumb size the gallery grid requests


def _safe_id(stamp_id):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(stamp_id))


@lru_cache(maxsize=1)
def _grid_dims():
    """Real, post-trim dimensions of every grid thumb, keyed by sanitised id.

    The DB stores the *untrimmed* source size, but the thumb has its white
    scanner margin cropped — and how much margin there was differs per scan. For
    ~9% of stamps the two aspect ratios disagree by >3%, which is enough that a
    tile reserves the wrong height and visibly resizes when its image lands. The
    grid needs the size it will actually render, so read it from the cached WebP
    headers (~0.6s for the whole cache, once per process; PIL reads the header
    only, it does not decode). Anything not yet generated falls back to the DB
    dimensions, which is close enough until the cache warms."""
    dims = {}
    suffix = f"_{GRID_SIZE}_perf1.webp"
    for path in THUMB_DIR.glob(f"*{suffix}"):
        try:
            with Image.open(path) as im:
                dims[path.name[: -len(suffix)]] = im.size
        except Exception:
            continue                       # a truncated/half-written thumb
    return dims


@app.get("/gallery", tags=["browse"])
def gallery():
    """Compact list of every stamp for the image gallery (id, bucket, has_image)."""
    with db() as con:
        rows = con.execute(
            "SELECT id, title, era, year, image_path, image_w, image_h "
            "FROM stamps").fetchall()
    dims = _grid_dims()
    items = []
    for r in rows:
        # tw/th = what the grid tile will actually be; w/h = untrimmed original
        tw, th = dims.get(_safe_id(r["id"]), (r["image_w"], r["image_h"]))
        items.append({
            "id": r["id"],
            "title": r["title"],
            "year": r["year"],
            "bucket": bucket_of(r),
            "has_image": bool(r["image_path"]),
            "w": r["image_w"],
            "h": r["image_h"],
            "tw": tw,
            "th": th,
            "image_api": f"/stamps/{r['id']}/image",
        })
    order = {b: i for i, b in enumerate(BUCKETS)}
    items.sort(key=lambda x: (order.get(x["bucket"], 99), x["title"]))
    counts = {}
    for it in items:
        counts[it["bucket"]] = counts.get(it["bucket"], 0) + 1
    return {"buckets": BUCKETS, "counts": counts, "total": len(items), "stamps": items}


@app.get("/", tags=["meta"])
def root():
    return {
        "name": "Irish Stamp API",
        "docs": "/docs",
        "endpoints": [
            "/stamps", "/stamps/{id}", "/stamps/{id}/image",
            "/stamps/year/{year}", "/stamps/theme/{theme}",
            "/search?q=", "/series", "/years", "/stats",
        ],
    }


@app.get("/stamps", tags=["stamps"])
def list_stamps(
    issue_type: str | None = None,
    currency: str | None = None,
    year: int | None = None,
    has_exact_date: bool | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
):
    where, params = [], []
    if issue_type:
        where.append("issue_type = ?")
        params.append(issue_type)
    if currency:
        where.append("currency = ?")
        params.append(currency)
    if year is not None:
        where.append("(year = ? OR (year IS NULL AND year_start <= ? AND year_end >= ?))")
        params += [year, year, year]
    if has_exact_date is not None:
        where.append("issue_date IS NOT NULL" if has_exact_date else "issue_date IS NULL")
    sql = "SELECT * FROM stamps"
    if where:
        sql += " WHERE " + " AND ".join(where)
    csql = "SELECT COUNT(*) FROM stamps" + ((" WHERE " + " AND ".join(where)) if where else "")
    sql += " ORDER BY COALESCE(year, year_start), title LIMIT ? OFFSET ?"
    with db() as con:
        total = con.execute(csql, params).fetchone()[0]
        rows = con.execute(sql, params + [limit, offset]).fetchall()
    return {"total": total, "limit": limit, "offset": offset,
            "stamps": [to_stamp(r) for r in rows]}


@app.get("/search", tags=["stamps"])
def search(q: str = Query(..., min_length=1), limit: int = Query(50, le=500), offset: int = 0):
    # FTS5 query; escape by quoting tokens to allow phrases/partial safely
    match = " ".join(f'"{t}"' for t in q.split())
    sql = """
        SELECT s.* FROM stamps_fts f JOIN stamps s ON s.id = f.id
        WHERE stamps_fts MATCH ? ORDER BY rank LIMIT ? OFFSET ?
    """
    csql = "SELECT COUNT(*) FROM stamps_fts WHERE stamps_fts MATCH ?"
    with db() as con:
        total = con.execute(csql, [match]).fetchone()[0]
        rows = con.execute(sql, [match, limit, offset]).fetchall()
    return {"query": q, "total": total, "stamps": [to_stamp(r) for r in rows]}


@app.get("/stamps/year/{year}", tags=["stamps"])
def by_year(year: int, limit: int = Query(200, le=1000), offset: int = 0):
    return list_stamps(year=year, limit=limit, offset=offset)


@app.get("/stamps/theme/{theme}", tags=["stamps"])
def by_theme(theme: str, limit: int = Query(200, le=1000), offset: int = 0):
    return list_stamps(issue_type=theme, limit=limit, offset=offset)


@app.get("/stamps/{stamp_id}", tags=["stamps"])
def get_stamp(stamp_id: str):
    with db() as con:
        row = con.execute("SELECT * FROM stamps WHERE id = ?", [stamp_id]).fetchone()
    if not row:
        raise HTTPException(404, "stamp not found")
    return to_stamp(row)


@app.get("/stamps/{stamp_id}/image", tags=["stamps"])
def get_image(stamp_id: str):
    # raw full-resolution originals are not served in production (licensing) —
    # only perforated thumbnails via /thumb are public
    if PROD:
        raise HTTPException(404, "not available")
    with db() as con:
        row = con.execute("SELECT image_path FROM stamps WHERE id = ?", [stamp_id]).fetchone()
    if not row or not row["image_path"]:
        raise HTTPException(404, "no image")
    path = ROOT / row["image_path"]
    if not path.exists():
        raise HTTPException(404, "image file missing")
    return FileResponse(path, media_type="image/jpeg")


def _trim_white(im, light=210, sat_thresh=25, pad=1):
    """Crop the light/grey scanner-paper margin evenly on every side.

    The old approach used a single corner pixel + fixed tolerance, which left
    uneven margins when a scan's border shade drifted (→ stray white lines on
    random edges). Instead, build a "real content" mask — a pixel counts as
    content if it is dark (brightness < `light`) OR saturated (max-min channel >
    `sat_thresh`) — and crop to its bounding box. Light-grey margins of any shade
    are ignored; dark text and coloured artwork anchor the crop, so genuine white
    design bands (e.g. an 'ÉIRE' header) are kept."""
    im = im.convert("RGB")
    r, g, b = im.split()
    mx = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mn = ImageChops.darker(ImageChops.darker(r, g), b)
    sat = ImageChops.difference(mx, mn)                    # per-pixel max-min
    dark = im.convert("L").point(lambda v: 255 if v < light else 0)
    color = sat.point(lambda v: 255 if v > sat_thresh else 0)
    content = ImageChops.lighter(dark, color)
    bbox = content.getbbox()
    if not bbox:
        return im
    l, t, r2, b2 = bbox
    w, h = im.size
    l, t = max(0, l - pad), max(0, t - pad)
    r2, b2 = min(w, r2 + pad), min(h, b2 + pad)
    if r2 - l < 8 or b2 - t < 8:                           # safety: don't over-crop
        return im
    return im.crop((l, t, r2, b2))


def _perforate(im, border, hole_r, hole_gap):
    """Bake the perforation into the image and punch evenly-spaced transparent
    holes around the edge (supersampled → antialiased, corner-aligned → no seam).

    If `border > 0`, a white paper border is first drawn *over* the outer pixels
    (the framed 'stamp on white paper' look, used by the detail view). If
    `border == 0`, no border is added — the perforation cuts straight into the
    artwork, so nothing white is introduced (used by the grid, works on any
    background)."""
    im = im.convert("RGB").copy()
    w, h = im.size
    if border > 0:
        white = (255, 255, 255)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, w, border], fill=white)          # top
        d.rectangle([0, h - border, w, h], fill=white)      # bottom
        d.rectangle([0, 0, border, h], fill=white)          # left
        d.rectangle([w - border, 0, w, h], fill=white)      # right

    # punch the holes into an alpha mask, supersampled 4x then downscaled so the
    # scallop edges are smooth (antialiased) instead of blocky.
    ss = 4
    alpha = Image.new("L", (w * ss, h * ss), 255)
    da = ImageDraw.Draw(alpha)

    def centers(length):
        n = max(2, round(length / hole_gap))
        return [round(i * length / n) for i in range(n + 1)]

    r = hole_r * ss
    for cx in centers(w):
        x = cx * ss
        da.ellipse([x - r, -r, x + r, r], fill=0)                    # top
        da.ellipse([x - r, h * ss - r, x + r, h * ss + r], fill=0)   # bottom
    for cy in centers(h):
        y = cy * ss
        da.ellipse([-r, y - r, r, y + r], fill=0)                    # left
        da.ellipse([w * ss - r, y - r, w * ss + r, y + r], fill=0)   # right
    alpha = alpha.resize((w, h), Image.LANCZOS)

    out = im.convert("RGBA")
    out.putalpha(alpha)
    return out


def _row_image(stamp_id):
    with db() as con:
        row = con.execute(
            "SELECT image_path FROM stamps WHERE id = ?", [stamp_id]).fetchone()
    if not row or not row["image_path"]:
        raise HTTPException(404, "no image")
    src = ROOT / row["image_path"]
    if not src.exists():
        raise HTTPException(404, "image file missing")
    return src


# Thumbnails are deterministic for a given (id, size, perf, frame) — the URL is
# the identity, so they can be cached forever. Without this the responses carried
# only etag/last-modified, and Safari revalidated on every open (a round trip per
# image on cellular).
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


@app.get("/stamps/{stamp_id}/thumb", tags=["stamps"])
def get_thumb(stamp_id: str, size: int = 420, perf: int = 0, frame: int = 1):
    """Trimmed, downscaled stamp image (cached per size).

    Default = plain JPEG. With perf=1 the perforation is baked into a transparent
    WebP (no CSS mask → no sub-pixel seam at any zoom). frame=1 also paints a white
    paper border (framed look, detail view); frame=0 cuts the perforation straight
    into the artwork with nothing white added (the grid — works on any theme).

    perf output is WebP, not PNG: these are photographic scans, so PNG was ~11x
    larger (a 360px grid tile went 186KB → 17KB, a 1600px detail 2.0MB → 151KB).
    That size was the whole reason mobile detail opens took 5-7s. Served
    unconditionally rather than negotiated on Accept — every browser with alpha
    WebP support is Safari 14+/2020, and a `Vary: Accept` would fragment the
    browser cache we are relying on here."""
    size = max(64, min(size, 1600))
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", stamp_id)
    if perf:
        dest = THUMB_DIR / f"{safe}_{size}_perf{frame}.webp"
        if not dest.exists():
            im = _trim_white(Image.open(_row_image(stamp_id)))
            im.thumbnail((size, size))
            dim = max(im.size)               # actual size (source may be smaller)
            grid = size <= 500               # grid tiles show ~half size, so the
            r_ratio = 0.013 if grid else 0.006   # perforation must be proportionally
            gap_ratio = 0.042 if grid else 0.021  # larger than the big detail view
            b_ratio = 0.024 if grid else 0.017
            border = max(6, round(dim * b_ratio)) if frame else 0
            hole_r = max(3, round(dim * r_ratio))
            hole_gap = max(8, round(dim * gap_ratio))
            _perforate(im, border, hole_r, hole_gap).save(
                dest, "WEBP", quality=82, method=4)
        return FileResponse(dest, media_type="image/webp", headers=IMMUTABLE)
    # non-perf stays JPEG — it is what the og:image meta tag points at, and social
    # scrapers are far less reliable about WebP than browsers are.
    dest = THUMB_DIR / f"{safe}_{size}.jpg"
    if not dest.exists():
        im = _trim_white(Image.open(_row_image(stamp_id)))
        im.thumbnail((size, size))
        im.save(dest, "JPEG", quality=88)
    return FileResponse(dest, media_type="image/jpeg", headers=IMMUTABLE)


@app.get("/series", tags=["browse"])
def series():
    with db() as con:
        rows = con.execute(
            "SELECT series, COUNT(*) n FROM stamps WHERE series IS NOT NULL "
            "GROUP BY series ORDER BY n DESC").fetchall()
    return {"note": "series filled as Colnect/enrichment data lands",
            "series": [dict(r) for r in rows]}


@app.get("/years", tags=["browse"])
def years():
    with db() as con:
        eras = con.execute(
            "SELECT era, year_start, year_end, COUNT(*) n FROM stamps "
            "GROUP BY era ORDER BY year_start").fetchall()
        exact = con.execute(
            "SELECT year, COUNT(*) n FROM stamps WHERE year IS NOT NULL "
            "GROUP BY year ORDER BY year").fetchall()
    return {"eras": [dict(r) for r in eras], "exact_years": [dict(r) for r in exact]}


@app.get("/stats", tags=["meta"])
def stats():
    with db() as con:
        total = con.execute("SELECT COUNT(*) FROM stamps").fetchone()[0]
        with_img = con.execute("SELECT COUNT(*) FROM stamps WHERE image_path IS NOT NULL").fetchone()[0]
        with_date = con.execute("SELECT COUNT(*) FROM stamps WHERE issue_date IS NOT NULL").fetchone()[0]
        by_type = con.execute(
            "SELECT issue_type, COUNT(*) n FROM stamps GROUP BY issue_type ORDER BY n DESC").fetchall()
        by_cur = con.execute(
            "SELECT currency, COUNT(*) n FROM stamps GROUP BY currency ORDER BY n DESC").fetchall()
    return {
        "total_stamps": total,
        "with_image": with_img,
        "with_exact_date": with_date,
        "exact_date_coverage": f"{round(100*with_date/total,1)}%",
        "by_issue_type": [dict(r) for r in by_type],
        "by_currency": [dict(r) for r in by_cur],
    }


# serve raw images statically (dev only — not exposed in production)
if not PROD and IMG_ROOT.exists():
    app.mount("/images", StaticFiles(directory=IMG_ROOT), name="images")
