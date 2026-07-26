"""Local case catalog: the metadata VideoDB doesn't model.

Maps VideoDB video ids to legal context: case, session type, date, witnesses.
JSON-file backed; small enough for a hackathon archive.
"""
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from . import store


@dataclass
class SessionEntry:
    video_id: str
    case_id: str
    title: str
    session_type: str  # trial_day | deposition | hearing
    source_url: str = ""
    date: str = ""  # ISO date of the proceeding, if known
    day_number: Optional[int] = None
    witnesses: List[str] = field(default_factory=list)
    collection_id: str = ""
    duration: Optional[float] = None
    indexes: Dict[str, str] = field(default_factory=dict)  # name -> index_id


CATALOG = "catalog"


def _load() -> dict:
    return store.read(CATALOG, {"cases": {}, "sessions": {}}) or {"cases": {}, "sessions": {}}


def _save(data: dict) -> None:
    store.write(CATALOG, data)


def stamp() -> float:
    """Change marker for the catalog, so caches know when to rebuild."""
    return store.stamp(CATALOG)


def upsert_case(case_id: str, name: str, collection_id: str) -> None:
    data = _load()
    data["cases"][case_id] = {"name": name, "collection_id": collection_id}
    _save(data)


def upsert_session(entry: SessionEntry) -> None:
    data = _load()
    data["sessions"][entry.video_id] = asdict(entry)
    _save(data)


def get_case(case_id: str) -> Optional[dict]:
    return _load()["cases"].get(case_id)


def get_session(video_id: str) -> Optional[SessionEntry]:
    raw = _load()["sessions"].get(video_id)
    return SessionEntry(**raw) if raw else None


def sessions_for_case(case_id: str) -> List[SessionEntry]:
    return [
        SessionEntry(**s)
        for s in _load()["sessions"].values()
        if s["case_id"] == case_id
    ]


def sessions_for_witness(case_id: str, witness: str) -> List[SessionEntry]:
    witness = witness.lower()
    return [
        s
        for s in sessions_for_case(case_id)
        if any(witness in w.lower() for w in s.witnesses)
    ]
