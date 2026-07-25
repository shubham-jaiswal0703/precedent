"""Precedent API — professor questions in, playable moments out."""
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..casepacks.generator import generate_case_pack
from ..catalog import _load as load_catalog, sessions_for_case
from ..config import DATA_DIR, PROJECT_ROOT
from ..reels.builder import build_reel
from ..search import engine

app = FastAPI(title="Precedent", description="Playable testimony for law schools")

STATIC_DIR = PROJECT_ROOT / "precedent" / "api" / "static"


@app.get("/api/cases")
def cases():
    data = load_catalog()
    return [
        {
            "case_id": cid,
            "name": c["name"],
            "sessions": [
                {
                    "video_id": s.video_id,
                    "title": s.title,
                    "session_type": s.session_type,
                    "witnesses": s.witnesses,
                    "duration": s.duration,
                }
                for s in sessions_for_case(cid)
            ],
        }
        for cid, c in data["cases"].items()
    ]


@app.get("/api/search")
def search(case: str, q: str, mode: str = "semantic", limit: int = 8, clips: bool = True):
    if mode == "semantic":
        moments = engine.semantic_search(case, q, limit=limit)
    elif mode == "keyword":
        moments = engine.keyword_search(case, q)[:limit]
    else:
        raise HTTPException(400, "mode must be semantic|keyword")
    results = []
    for m in moments:
        item = m.__dict__.copy()
        if clips and not item.get("stream_url"):
            try:
                item["stream_url"] = engine.clip_url(m.video_id, m.start, m.end)
            except Exception:
                pass
        results.append(item)
    return results


@app.get("/api/casepack/{case_id}")
def casepack(case_id: str, regenerate: bool = False):
    path = DATA_DIR / "casepacks" / f"{case_id}.json"
    if path.exists() and not regenerate:
        return json.loads(path.read_text())
    try:
        return generate_case_pack(case_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/contradictions/{case_id}")
def contradictions(case_id: str, witness: Optional[str] = None):
    """Serve precomputed contradictions (compute with scripts/find_contradictions.py)."""
    path = DATA_DIR / "contradictions" / f"{case_id}.json"
    if not path.exists():
        raise HTTPException(404, "No precomputed contradictions; run scripts/find_contradictions.py")
    items = json.loads(path.read_text())
    if witness:
        items = [i for i in items if witness.lower() in i["witness"].lower()]
    return items


@app.get("/api/reel")
def reel(case: str, q: str = Query(..., description="semantic query"), limit: int = 6):
    moments = engine.semantic_search(case, q, limit=limit)
    if not moments:
        raise HTTPException(404, "No moments matched")
    for m in moments:
        m.attrs["label"] = m.session_title
    return {"stream_url": build_reel(moments), "count": len(moments)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
