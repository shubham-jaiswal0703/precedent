"""Ingest trial footage into a per-case VideoDB collection + local catalog."""
from typing import List, Optional

from videodb import connect  # noqa: F401  (re-export convenience)

from ..catalog import SessionEntry, upsert_case, upsert_session
from ..config import get_connection


def get_or_create_case_collection(case_id: str, case_name: str):
    conn = get_connection()
    for coll in conn.get_collections():
        if coll.name == case_id:
            upsert_case(case_id, case_name, coll.id)
            return coll
    coll = conn.create_collection(name=case_id, description=case_name)
    upsert_case(case_id, case_name, coll.id)
    return coll


def ingest(
    case_id: str,
    case_name: str,
    title: str,
    session_type: str,
    url: Optional[str] = None,
    file_path: Optional[str] = None,
    date: str = "",
    day_number: Optional[int] = None,
    witnesses: Optional[List[str]] = None,
) -> SessionEntry:
    """Upload one session (trial day / deposition / hearing) and catalog it."""
    coll = get_or_create_case_collection(case_id, case_name)
    video = coll.upload(url=url, file_path=file_path, name=title)
    entry = SessionEntry(
        video_id=video.id,
        case_id=case_id,
        title=title,
        session_type=session_type,
        source_url=url or file_path or "",
        date=date,
        day_number=day_number,
        witnesses=witnesses or [],
        collection_id=coll.id,
        duration=getattr(video, "length", None),
    )
    upsert_session(entry)
    return entry
