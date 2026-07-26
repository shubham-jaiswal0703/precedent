"""Precedent API: professor questions in, playable moments out."""
import json
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..casepacks.gallery import case_cards, case_detail
from ..playbooks import build as build_playbook, index as playbook_index
from ..casepacks.generator import generate_case_pack
from ..catalog import _load as load_catalog, sessions_for_case
from ..config import DATA_DIR, PROJECT_ROOT
from ..discuss import discuss
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


GALLERY_CACHE = DATA_DIR / "gallery.json"


@app.get("/api/gallery")
def gallery(refresh: bool = False):
    """Browsable shelf of cases in the library.

    Served from a disk cache, because assembling it walks every session's
    moments and cover art. Rebuild with ?refresh=1 after an ingest, or by
    running scripts/warm_caches.py.
    """
    if GALLERY_CACHE.exists() and not refresh:
        return json.loads(GALLERY_CACHE.read_text())
    cards = case_cards()
    GALLERY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GALLERY_CACHE.write_text(json.dumps(cards, indent=2))
    return cards


@app.get("/api/playbooks")
def playbooks():
    """What a student might be preparing to do."""
    return playbook_index()


@app.get("/api/playbook/{playbook_id}")
def playbook(playbook_id: str, per_step: int = 2):
    """One playbook, with real moments attached to every step."""
    try:
        return build_playbook(playbook_id, per_step=per_step)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.on_event("startup")
def warm_on_startup() -> None:
    """Build the gallery in the background so the first visitor never waits."""
    import threading

    def warm() -> None:
        try:
            cards = case_cards()
            GALLERY_CACHE.parent.mkdir(parents=True, exist_ok=True)
            GALLERY_CACHE.write_text(json.dumps(cards, indent=2))
            playbook_index()
        except Exception:
            pass  # a cold cache is slow, not broken

    threading.Thread(target=warm, daemon=True).start()


@app.get("/api/case/{case_id}")
def case(case_id: str, per_section: int = 4):
    """One case opened up: sessions, participants, recommended sections."""
    try:
        return case_detail(case_id, per_section=per_section)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/discuss")
def discuss_case(case: str, q: str, limit: int = 5):
    """Ask about a case; every claim carries a playable citation."""
    result = discuss(case, q, limit=limit)
    return {
        "question": result.question,
        "answer": result.answer,
        "citations": [m.__dict__ for m in result.citations],
    }


@app.get("/api/clip")
def clip(video_id: str, start: float, end: float):
    """A playable stream for an arbitrary span (used by section browsing)."""
    try:
        return {"stream_url": engine.clip_url(video_id, start, end)}
    except Exception as exc:
        raise HTTPException(400, str(exc))


class SavedClip(BaseModel):
    """One clip a student put in their prep set."""
    video_id: str
    start: float
    end: float
    label: str = ""
    session_title: str = ""
    text: str = ""
    note: str = ""


class ClipSet(BaseModel):
    name: str = "Prep set"
    clips: List[SavedClip]


@app.post("/api/export/reel")
def export_reel(payload: ClipSet):
    """Stitch a saved set into one continuous reel."""
    if not payload.clips:
        raise HTTPException(400, "The set is empty")
    moments = [
        engine.PlayableMoment(
            video_id=c.video_id, start=c.start, end=c.end, text=c.text,
            session_title=c.session_title,
            attrs={"label": c.label or c.session_title or payload.name},
        )
        for c in payload.clips
    ]
    try:
        return {"stream_url": build_reel(moments), "count": len(moments)}
    except Exception as exc:
        raise HTTPException(400, f"Could not build the reel: {exc}")


@app.post("/api/export/sheet", response_class=PlainTextResponse)
def export_sheet(payload: ClipSet):
    """A citable prep sheet: every clip with its source, timecode, and words.

    Markdown rather than JSON, because this is the artifact a student prints,
    marks up, and takes to practice.
    """
    def stamp(seconds: float) -> str:
        seconds = int(seconds)
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"

    lines = [f"# {payload.name}", "",
             f"{len(payload.clips)} clips from the Precedent library.", ""]
    for i, clip in enumerate(payload.clips, 1):
        lines.append(f"## {i}. {clip.label or clip.session_title or 'Moment'}")
        lines.append("")
        lines.append(f"- Source: {clip.session_title or clip.video_id}")
        lines.append(f"- Timecode: {stamp(clip.start)} to {stamp(clip.end)}")
        try:
            lines.append(f"- Clip: {engine.clip_url(clip.video_id, clip.start, clip.end)}")
        except Exception:
            pass
        if clip.text:
            lines.append("")
            lines.append("> " + clip.text.strip().replace("\n", " ")[:600])
        if clip.note:
            lines.append("")
            lines.append(f"**Note:** {clip.note}")
        lines.append("")
    return "\n".join(lines)


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
    """Drop in any YouTube/media URL: we ingest, transcribe, and index it."""
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
