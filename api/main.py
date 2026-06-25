#!/usr/bin/env python3
"""Irish Stamp API — public REST service over data/stamps.db.

Run:  .venv/bin/uvicorn api.main:app --reload --port 8000
Docs: http://localhost:8000/docs   (auto-generated OpenAPI)
"""
import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "stamps.db"
IMG_ROOT = ROOT / "data" / "images"

# Browse buckets, newest first. An Post years 2020-2026 are lumped together;
# 1922-2019 use the four DRI era buckets.
BUCKETS = ["2020-2026", "2011-2019", "2001-2010", "1984-2000", "1922-1983"]

app = FastAPI(
    title="Irish Stamp API",
    version="0.1.0",
    description=(
        "Every Irish postage stamp (1922-present), harvested from the Digital "
        "Repository of Ireland (An Post Museum & Archive). Issue dates are "
        "currently era estimates; exact dates are being backfilled."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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


@app.get("/gallery", tags=["browse"])
def gallery():
    """Compact list of every stamp for the image gallery (id, bucket, has_image)."""
    with db() as con:
        rows = con.execute(
            "SELECT id, title, era, year, image_path FROM stamps").fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "title": r["title"],
            "bucket": bucket_of(r),
            "has_image": bool(r["image_path"]),
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
    with db() as con:
        row = con.execute("SELECT image_path FROM stamps WHERE id = ?", [stamp_id]).fetchone()
    if not row or not row["image_path"]:
        raise HTTPException(404, "no image")
    path = ROOT / row["image_path"]
    if not path.exists():
        raise HTTPException(404, "image file missing")
    return FileResponse(path, media_type="image/jpeg")


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


# serve downloaded images statically too: /images/{id}/{file}.jpg
if IMG_ROOT.exists():
    app.mount("/images", StaticFiles(directory=IMG_ROOT), name="images")
