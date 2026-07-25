"""Indexing wrappers — spoken word + courtroom-events scene index.

Thin layer over the VideoDB SDK so the rest of the codebase never calls the
SDK's indexing surface directly (lets us migrate legacy -> new API in one
place).
"""
from typing import Optional

from videodb import IndexType, SceneExtractionType

from ..catalog import get_session, upsert_session
from ..config import get_connection

COURTROOM_SCENE_PROMPT = (
    "This is footage from a courtroom proceeding. Describe what is happening: "
    "who appears to be speaking (judge, attorney at podium, witness on the "
    "stand), whether an objection or sidebar seems to be occurring, whether "
    "an exhibit or document is being displayed, and the witness's demeanor "
    "(calm, agitated, tearful, evasive). Be specific and factual."
)


def _get_video(video_id: str):
    session = get_session(video_id)
    conn = get_connection()
    coll = conn.get_collection(session.collection_id) if session else conn.get_collection()
    return coll.get_video(video_id), session


def index_spoken(video_id: str) -> None:
    """Transcribe + index spoken words (blocking)."""
    video, session = _get_video(video_id)
    video.index_spoken_words()
    if session:
        session.indexes["spoken_word"] = "default"
        upsert_session(session)


def index_scenes(video_id: str, time_step: int = 20, prompt: Optional[str] = None) -> str:
    """Time-based visual scene index with a courtroom prompt (blocking)."""
    video, session = _get_video(video_id)
    index_id = video.index_scenes(
        extraction_type=SceneExtractionType.time_based,
        extraction_config={"time": time_step, "select_frames": ["middle"]},
        prompt=prompt or COURTROOM_SCENE_PROMPT,
        name="courtroom_events",
    )
    if session:
        session.indexes["courtroom_events"] = index_id
        upsert_session(session)
    return index_id


def get_transcript(video_id: str, start: Optional[float] = None, end: Optional[float] = None):
    """Word/sentence-timestamped transcript segments for a window."""
    video, _ = _get_video(video_id)
    return video.get_transcript(start=start, end=end)


def get_transcript_text(video_id: str, start=None, end=None) -> str:
    video, _ = _get_video(video_id)
    return video.get_transcript_text(start=start, end=end)


__all__ = [
    "index_spoken",
    "index_scenes",
    "get_transcript",
    "get_transcript_text",
    "IndexType",
    "COURTROOM_SCENE_PROMPT",
]
