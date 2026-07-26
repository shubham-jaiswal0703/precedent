"""Cover art for sessions and cases.

Three sources, in order of preference:

1. A thumbnail the source archive already published (Cameras in Courts ships
   1280x720 stills, so there is nothing to compute).
2. A frame pulled from the video itself via VideoDB.
3. Nothing, for audio-only proceedings. Most of the library is Supreme Court
   and appellate argument, which has no picture at all, so the UI draws a
   typographic cover from the case metadata instead. That is deliberate: an
   invented courtroom image next to a real docket number would imply footage
   that does not exist.
"""
import json
from typing import Dict, List, Optional

from .catalog import get_session, sessions_for_case, upsert_session
from .config import DATA_DIR, get_connection

CACHE = DATA_DIR / "thumbnails.json"  # the file copy shipped in the image


def _cache() -> Dict[str, str]:
    from . import store

    return store.read("thumbnails", {}) or {}


def _save(cache: Dict[str, str]) -> None:
    from . import store

    store.write("thumbnails", cache)


def _candidate_times(video_id: str, duration: Optional[float]) -> List[float]:
    """Timestamps worth grabbing a cover frame from.

    Prefer the middle of indexed moments, since a moment is by definition a
    point where someone is speaking on the record, rather than a slate or an
    empty courtroom.
    """
    times: List[float] = []
    try:
        from .moments.extractor import cached_moments

        for moment in cached_moments(video_id)[:3]:
            times.append((moment.start + moment.end) / 2)
    except Exception:
        pass
    span = duration or 600.0
    times.extend([span * 0.25, span * 0.5])
    return times[:4]


def _jpeg_weight(url: str) -> int:
    """Byte size of a JPEG, used as a cheap proxy for how much is in the frame.

    A black or blank frame compresses to almost nothing, so the largest of a
    few candidates is reliably the most interesting picture. This avoids
    pulling in an image library just to measure brightness.
    """
    import urllib.request

    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return int(resp.headers.get("content-length") or 0)
    except Exception:
        return 1  # unknown size still beats no candidate at all


def session_thumbnail(video_id: str, at_seconds: Optional[float] = None) -> str:
    """A still for one session, or an empty string when the media has no frames."""
    cache = _cache()
    if video_id in cache:
        return cache[video_id]

    session = get_session(video_id)
    published = (session.indexes.get("thumbnail") if session else "") or ""
    if published:
        cache[video_id] = published
        _save(cache)
        return published

    url = ""
    try:
        conn = get_connection()
        coll = conn.get_collection(session.collection_id) if session else conn.get_collection()
        video = coll.get_video(video_id)
        candidates = ([at_seconds] if at_seconds is not None
                      else _candidate_times(video_id, session.duration if session else None))
        best_bytes = 0
        for moment in candidates:
            result = video.generate_thumbnail(time=float(moment))
            candidate = result if isinstance(result, str) else getattr(result, "url", "") or ""
            if not candidate:
                continue
            weight = _jpeg_weight(candidate)
            if weight > best_bytes:
                url, best_bytes = candidate, weight
    except Exception:
        url = ""  # audio-only proceedings have no frame to grab

    cache[video_id] = url
    _save(cache)
    if session and url:
        session.indexes["thumbnail"] = url
        upsert_session(session)
    return url


def case_thumbnail(case_id: str) -> str:
    """Cover art for a case: the most substantial still across its sessions."""
    best, best_weight = "", 0
    for session in sessions_for_case(case_id):
        url = session_thumbnail(session.video_id)
        if not url:
            continue
        weight = _jpeg_weight(url)
        if weight > best_weight:
            best, best_weight = url, weight
    return best


def case_cover(case_id: str, name: str, kind: str) -> dict:
    """Everything the UI needs to render a cover, image or not."""
    return {
        "image": case_thumbnail(case_id),
        "kind": kind,
        "seal": "trial record" if kind == "trial" else "oral argument",
        "monogram": _monogram(name),
    }


def _monogram(name: str) -> str:
    """Initials for a typographic cover: 'Dobbs v. Jackson' becomes 'D v J'."""
    cleaned = name.replace("&", "and")
    parts = [p for p in cleaned.replace(",", " ").split() if p]
    versus = next((i for i, p in enumerate(parts) if p.lower() in ("v.", "v", "vs.", "vs")), None)
    if versus and versus > 0 and versus + 1 < len(parts):
        return f"{parts[0][0].upper()} v {parts[versus + 1][0].upper()}"
    letters = [p[0].upper() for p in parts if p[0].isalpha()][:3]
    return "".join(letters) or "PR"


def warm_thumbnails(case_ids: Optional[List[str]] = None) -> Dict[str, str]:
    """Precompute stills so the gallery never waits on VideoDB."""
    from .catalog import _load

    ids = case_ids or list(_load()["cases"])
    out: Dict[str, str] = {}
    for case_id in ids:
        for session in sessions_for_case(case_id):
            out[session.video_id] = session_thumbnail(session.video_id)
    return out
