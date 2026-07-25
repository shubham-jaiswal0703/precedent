"""Precedent API — professor questions in, playable moments out."""
import json
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..casepacks.generator import generate_case_pack
from ..catalog import _load as load_catalog, sessions_for_case
from ..config import DATA_DIR, PROJECT_ROOT
from ..reels.builder import build_reel
from ..search import engine, router

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
def search(
    case: str,
    q: str,
    mode: str = "auto",
    limit: int = 8,
    clips: bool = True,
    precise: bool = True,
    role: Optional[str] = None,
):
    """Ask like a professor. `auto` routes by intent; the rest force an index."""
    if mode == "auto":
        routed = router.search(case, q, limit=limit, with_clips=clips, role=role)
        return {
            "intent": routed["intent"],
            "interpretation": routed["interpretation"],
            "filters": routed["filters"],
            "results": [m.__dict__ for m in routed["results"]],
        }

    if mode == "semantic":
        moments = engine.semantic_search(case, q, limit=limit, precise=precise, speaker_role=role)
        interpretation = "Semantic search across the archive"
    elif mode == "keyword":
        moments = engine.keyword_search(case, q)[:limit]
        interpretation = f'Exact phrase: "{q}"'
    else:
        raise HTTPException(400, "mode must be auto|semantic|keyword")

    results = []
    for m in moments:
        item = m.__dict__.copy()
        if clips and not item.get("stream_url"):
            try:
                item["stream_url"] = engine.clip_url(m.video_id, m.start, m.end)
            except Exception:
                pass
        results.append(item)
    return {"intent": mode, "interpretation": interpretation, "filters": {}, "results": results}


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


JOBS: Dict[str, dict] = {}


def _ingest_and_index(job_id: str, url: str, title: str, case_id: str, case_name: str) -> None:
    from ..indexing.indexer import index_spoken
    from ..ingest.pipeline import ingest

    try:
        JOBS[job_id] = {"state": "uploading", "url": url}
        entry = ingest(case_id=case_id, case_name=case_name, title=title,
                       session_type="trial_day", url=url)
        JOBS[job_id] = {"state": "indexing", "video_id": entry.video_id,
                        "duration": entry.duration, "url": url}
        index_spoken(entry.video_id)
        JOBS[job_id] = {"state": "ready", "video_id": entry.video_id,
                        "duration": entry.duration, "case_id": case_id, "url": url}
    except Exception as exc:  # surfaced to the UI rather than swallowed
        JOBS[job_id] = {"state": "failed", "error": str(exc), "url": url}


@app.post("/api/analyze")
def analyze(
    background: BackgroundTasks,
    url: str,
    title: str = "Untitled proceeding",
    case: str = "dropped-links",
    case_name: str = "Dropped links",
):
    """Drop in any YouTube/media URL — we ingest, transcribe, and index it."""
    job_id = uuid4().hex[:12]
    JOBS[job_id] = {"state": "queued", "url": url}
    background.add_task(_ingest_and_index, job_id, url, title, case, case_name)
    return {"job_id": job_id, "state": "queued"}


@app.get("/api/analyze/{job_id}")
def analyze_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job


@app.get("/api/speakers/{video_id}")
def speakers(video_id: str):
    """Speaker roles for a session (named speakers when Oyez provided them)."""
    from ..ingest.oyez import load_speaker_timeline
    from ..moments.speakers import label_turns

    timeline = load_speaker_timeline(video_id)
    if timeline:
        return {"source": "oyez", "speakers": sorted(
            {t["speaker"]: t["role"] for t in timeline["turns"]}.items()
        )}
    _, profiles = label_turns(video_id)
    return {"source": "inferred", "speakers": [
        {"label": sp, "role": p.role, "turns": p.turns, "words": p.words,
         "question_ratio": p.question_ratio, "sample": p.sample}
        for sp, p in sorted(profiles.items())
    ]}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
