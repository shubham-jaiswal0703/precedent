"""Search engine — professor questions in, playable moments out.

Every result path normalizes to PlayableMoment so the API/UI/reel layers
never touch raw SDK objects.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from videodb import IndexType, SearchType

from ..catalog import get_session, sessions_for_case
from ..config import get_connection


@dataclass
class PlayableMoment:
    video_id: str
    start: float
    end: float
    text: str
    score: Optional[float] = None
    session_title: str = ""
    session_type: str = ""
    stream_url: str = ""
    player_url: str = ""
    attrs: dict = field(default_factory=dict)


def _to_moment(shot) -> PlayableMoment:
    session = get_session(shot.video_id)
    return PlayableMoment(
        video_id=shot.video_id,
        start=shot.start,
        end=shot.end,
        text=shot.text or "",
        score=getattr(shot, "search_score", None) or getattr(shot, "score", None),
        session_title=session.title if session else "",
        session_type=session.session_type if session else "",
        stream_url=getattr(shot, "stream_url", "") or "",
        player_url=getattr(shot, "player_url", "") or "",
    )


def _case_collection(case_id: str):
    conn = get_connection()
    sessions = sessions_for_case(case_id)
    if not sessions:
        raise ValueError(f"No ingested sessions for case '{case_id}'")
    return conn.get_collection(sessions[0].collection_id), sessions


def semantic_search(case_id: str, query: str, limit: int = 10) -> List[PlayableMoment]:
    """Archive-wide semantic search over spoken words."""
    coll, _ = _case_collection(case_id)
    result = coll.search(
        query=query,
        search_type=SearchType.semantic,
        index_type=IndexType.spoken_word,
        result_threshold=limit,
    )
    return [_to_moment(s) for s in result.get_shots()]


def keyword_search(case_id: str, phrase: str) -> List[PlayableMoment]:
    """Exact-phrase search; keyword is video-scope only, so fan out."""
    coll, sessions = _case_collection(case_id)
    moments: List[PlayableMoment] = []
    for session in sessions:
        video = coll.get_video(session.video_id)
        try:
            result = video.search(
                query=phrase,
                search_type=SearchType.keyword,
                index_type=IndexType.spoken_word,
            )
        except Exception:
            continue  # video may lack a spoken index yet
        moments.extend(_to_moment(s) for s in result.get_shots())
    return moments


def scene_search(case_id: str, query: str, limit: int = 10) -> List[PlayableMoment]:
    """Search visual courtroom-events scene descriptions (video-scope fan-out)."""
    coll, sessions = _case_collection(case_id)
    moments: List[PlayableMoment] = []
    for session in sessions:
        index_id = session.indexes.get("courtroom_events")
        if not index_id:
            continue
        video = coll.get_video(session.video_id)
        result = video.search(
            query=query,
            search_type=SearchType.semantic,
            index_type=IndexType.scene,
            index_id=index_id,
            result_threshold=limit,
        )
        moments.extend(_to_moment(s) for s in result.get_shots())
    moments.sort(key=lambda m: (m.score or 0), reverse=True)
    return moments[:limit]


def clip_url(video_id: str, start: float, end: float, pad: float = 2.0) -> str:
    """Instant playable HLS clip for a moment (with a little context padding)."""
    session = get_session(video_id)
    conn = get_connection()
    coll = conn.get_collection(session.collection_id) if session else conn.get_collection()
    video = coll.get_video(video_id)
    clip_start = max(0.0, start - pad)
    clip_end = end + pad
    duration = (session.duration if session else None) or getattr(video, "length", None)
    if duration:
        clip_end = min(clip_end, float(duration))
        clip_start = min(clip_start, max(0.0, clip_end - 1.0))
    return video.generate_stream(timeline=[(clip_start, clip_end)])
