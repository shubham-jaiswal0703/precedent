"""Precedent API: professor questions in, playable moments out."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import jobs, store
from ..casepacks.gallery import case_cards, case_detail
from ..playbooks import build as build_playbook, index as playbook_index
from ..casepacks.generator import generate_case_pack
from ..catalog import _load as load_catalog, sessions_for_case
from ..config import DATA_DIR, PROJECT_ROOT
from ..discuss import discuss
from ..reels.builder import ReelSpec, build_reel
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


@app.get("/api/gallery")
def gallery(refresh: bool = False):
    """Browsable shelf of cases in the library.

    Served from a disk cache, because assembling it walks every session's
    moments and cover art. Rebuild with ?refresh=1 after an ingest, or by
    running scripts/warm_caches.py.
    """
    if not refresh:
        cached = store.read("gallery")
        if cached:
            return cached
    cards = case_cards()
    store.write("gallery", cards)
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


@app.get("/api/health")
def health():
    """Where state lives and whether webhooks are wired, for debugging a deploy."""
    return {
        "storage": store.backend(),
        "webhooks": bool(jobs.webhook_base()),
        "public_base_url": jobs.webhook_base() or None,
    }


@app.on_event("startup")
def warm_on_startup() -> None:
    """Build the gallery in the background so the first visitor never waits."""
    import threading

    def warm() -> None:
        try:
            # On a fresh Postgres, start from the warm documents in the image.
            store.seed_from_files({
                "catalog": {"cases": {}, "sessions": {}},
                "thumbnails": {}, "clips": {}, "jobs": {},
            })
            store.write("gallery", case_cards())
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
    seconds_per_clip: float = 30.0
    max_total_seconds: Optional[float] = None
    subtitles: bool = False


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
    spec = ReelSpec(seconds_per_clip=payload.seconds_per_clip,
                    max_total_seconds=payload.max_total_seconds,
                    subtitles=payload.subtitles)
    try:
        result = build_reel(moments, spec=spec)
    except Exception as exc:
        raise HTTPException(400, f"Could not build the reel: {exc}")
    return {"stream_url": result.stream_url, "count": result.count,
            "total_seconds": result.total_seconds, "subtitles": result.subtitles,
            "subtitle_note": result.subtitle_note}


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
def reel(
    q: str = Query(..., description="what the reel should show"),
    case: Optional[str] = Query(None, description="one case, or omit to use the whole library"),
    cases: Optional[str] = Query(None, description="comma separated case ids"),
    limit: int = 8,
    seconds_per_clip: float = 30.0,
    max_total_seconds: Optional[float] = None,
    subtitles: bool = False,
    title_cards: bool = True,
):
    """Build a teaching reel across the library.

    A reel of five sustained objections from five different courtrooms teaches
    more than five from one, so the default scope is every case.
    """
    wanted = [c for c in (cases.split(",") if cases else []) if c.strip()]
    if case:
        wanted.append(case)
    if not wanted:
        wanted = list(load_catalog()["cases"])

    moments: List[Any] = []
    per_case = max(2, limit // max(1, len(wanted)) + 1)
    for case_id in wanted:
        try:
            found = router.search(case_id, q, limit=per_case, with_clips=False)["results"]
        except Exception:
            continue
        for m in found:
            m.attrs["label"] = m.attrs.get("label") or m.session_title
            moments.append(m)

    if not moments:
        raise HTTPException(404, "No moments matched anywhere in the library")

    # Interleave across cases so the reel compares courtrooms rather than
    # running through one case before reaching the next.
    by_case: Dict[str, list] = {}
    for m in moments:
        by_case.setdefault(m.attrs.get("case_id") or m.session_title, []).append(m)
    ordered: List[Any] = []
    while len(ordered) < limit and any(by_case.values()):
        for bucket in list(by_case.values()):
            if bucket and len(ordered) < limit:
                ordered.append(bucket.pop(0))

    spec = ReelSpec(seconds_per_clip=seconds_per_clip, max_total_seconds=max_total_seconds,
                    title_cards=title_cards, subtitles=subtitles)
    try:
        result = build_reel(ordered, spec=spec)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "stream_url": result.stream_url,
        "count": result.count,
        "total_seconds": result.total_seconds,
        "subtitles": result.subtitles,
        "subtitle_note": result.subtitle_note,
        "sources": result.sources,
        "scope": wanted,
    }


@app.get("/api/contributions")
def contributions(limit: int = 40):
    """Links added by anyone, shown publicly and credited to a pseudonym."""
    return {"contributions": jobs.contributions(limit)}


@app.post("/api/analyze")
def analyze(
    request: Request,
    url: str,
    title: str = "Untitled proceeding",
    case: str = "dropped-links",
    case_name: str = "Dropped links",
):
    """Drop in any YouTube or media URL: we ingest, transcribe, and index it.

    Returns straight away with a job id. Indexing completion arrives through
    VideoDB's webhook when PUBLIC_BASE_URL is configured, so the work is not
    tied to this process staying alive.
    """
    # Seed the pseudonym from the request origin so one person keeps one
    # credit, without storing anything identifying.
    seed = (request.headers.get("x-forwarded-for") or
            (request.client.host if request.client else "") or url)
    job = jobs.start(url=url, title=title, case_id=case, case_name=case_name,
                     contributor_seed=seed)
    return job


@app.get("/api/analyze/{job_id}")
def analyze_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job


@app.get("/api/jobs")
def job_log(limit: int = 20):
    """Recent ingests, which survive a restart now that they are persisted."""
    return {"webhooks": bool(jobs.webhook_base()), "jobs": jobs.recent(limit)}


@app.post("/api/webhooks/videodb")
async def videodb_webhook(request: Request, job: str = ""):
    """Called by VideoDB when an indexing job finishes.

    The payload shape is not contractual, so treat anything that does not look
    like an explicit failure as success and let the warm-up confirm it.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    status = str(payload.get("status") or payload.get("state") or "").lower()
    failed = status in ("failed", "error") or bool(payload.get("error"))
    if job:
        jobs.finish(job, ok=not failed, error=str(payload.get("error") or status))
    return {"received": True, "job": job, "failed": failed}


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
