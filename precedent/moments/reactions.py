"""Reactions: what the camera saw while the words were being said.

The spoken-word index answers when something was said. A second scene index,
built with a vision prompt about courtroom demeanor, answers what every visible
face and body was doing in that same window. Joining the two turns "how did the
witness react when she was confronted with her deposition" into an answerable
query.

Only sessions with actual video carry a "reactions" index. Audio-only argument
has no faces, and pretending otherwise would be inventing evidence, so sessions
without the index simply do not offer this.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .. import store
from ..catalog import _load as load_catalog, get_session
from ..config import get_connection

CACHE = "reactions"  # store document: video_id -> list of scene records


@dataclass
class SceneNote:
    start: float
    end: float
    description: str


def has_reactions(video_id: str) -> bool:
    session = get_session(video_id)
    return bool(session and session.indexes.get("reactions"))


def video_ids_with_reactions() -> List[str]:
    return [vid for vid, s in load_catalog()["sessions"].items()
            if s.get("indexes", {}).get("reactions")]


def scenes(video_id: str, refresh: bool = False) -> List[SceneNote]:
    """The reaction scene records for a session, cached in the store."""
    cache: Dict[str, list] = store.read(CACHE, {}) or {}
    if video_id in cache and not refresh:
        return [SceneNote(**s) for s in cache[video_id]]

    session = get_session(video_id)
    index_id = session.indexes.get("reactions") if session else None
    if not index_id:
        return []
    try:
        conn = get_connection()
        video = conn.get_collection(session.collection_id).get_video(video_id)
        raw = video.get_scene_index(index_id)
    except Exception:
        return []
    notes = [SceneNote(start=float(s["start"]), end=float(s["end"]),
                       description=(s.get("description") or "").strip())
             for s in raw]
    if notes:  # an empty result usually means the index is still processing,
        cache[video_id] = [n.__dict__ for n in notes]  # so never cache it
        store.write(CACHE, cache)
    return notes


# Markers that mean the WHOLE frame has nothing to read (title cards, document
# close-ups). A wide shot whose background faces are "too small" still has a
# readable foreground, so partial-readability phrases must not filter it.
NO_FACES_MARKERS = ("no courtroom people", "no people are visibly",
                    "graphic/title", "title card", "appears to be a graphic",
                    "close-up of a document")


def _readable(note: SceneNote) -> bool:
    head = note.description.lower()[:160]
    return not any(marker in head for marker in NO_FACES_MARKERS)


def during(video_id: str, start: float, end: float, pad: float = 4.0) -> List[SceneNote]:
    """Scene notes overlapping a spoken moment, blank frames filtered out."""
    hits = [n for n in scenes(video_id)
            if min(end + pad, n.end) - max(start - pad, n.start) > 0]
    return [n for n in hits if _readable(n)]


def summarize(notes: List[SceneNote], max_chars: int = 420) -> str:
    """One compact 'what the camera saw' line for a moment card."""
    if not notes:
        return ""
    # The note closest to the middle of the window usually is the reaction.
    text = " ".join(n.description.replace("\n", " ") for n in notes[:2])
    text = " ".join(text.split())
    for noise in ("**", "- "):
        text = text.replace(noise, "")
    return text[:max_chars]


def attach(moments: List) -> List:
    """Put a camera_saw note on every moment whose session has the index."""
    for m in moments:
        try:
            notes = during(m.video_id, m.start, m.end)
        except Exception:
            continue
        if notes:
            m.attrs["camera_saw"] = summarize(notes)
    return moments


def search_reactions(case_id: str, query: str, limit: int = 8) -> List:
    """Reaction-first search: spoken moments joined with what was visible.

    Collection search mostly lands on whichever session semantically dominates,
    which may have no video. So search inside each session that actually has a
    reactions index, then join and rank what can show its demeanor.
    """
    from videodb import IndexType, SearchType

    from ..catalog import sessions_for_case
    from ..search.engine import _to_moment
    from ..search.precision import refine_many

    eligible = [s for s in sessions_for_case(case_id) if s.indexes.get("reactions")]
    if not eligible:
        return []

    conn = get_connection()
    moments: List = []
    for session in eligible:
        try:
            video = conn.get_collection(session.collection_id).get_video(session.video_id)
            result = video.search(query=query, search_type=SearchType.semantic,
                                  index_type=IndexType.spoken_word,
                                  result_threshold=max(3, limit))
            moments.extend(_to_moment(shot) for shot in result.get_shots())
        except Exception:
            continue  # zero hits raise; a session with no match just drops out

    moments = refine_many(moments, query, drop_unmatched=False)
    attach(moments)
    annotated = [m for m in moments if m.attrs.get("camera_saw")]
    return (annotated or moments)[:limit]
