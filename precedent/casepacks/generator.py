"""Case packs — a playable casebook chapter per trial.

Structured JSON: sessions, witnesses, objection log (with rulings/grounds),
key exchanges, every entry linked to a playable clip.
"""
import json
from datetime import date
from typing import List, Optional

from ..catalog import get_case, sessions_for_case
from ..config import DATA_DIR
from ..moments.extractor import extract_moments
from ..search.engine import clip_url, semantic_search

KEY_EXCHANGE_QUERIES = [
    "witness confronted with her prior testimony or deposition",
    "heated exchange between attorney and witness",
    "witness describes the central allegations",
]


def _entry(video_id: str, start: float, end: float, text: str, make_clips: bool, **extra) -> dict:
    entry = {
        "video_id": video_id,
        "start": round(start, 1),
        "end": round(end, 1),
        "text": text.strip()[:400],
        **extra,
    }
    if make_clips:
        entry["stream_url"] = clip_url(video_id, start, end)
    return entry


def generate_case_pack(case_id: str, make_clips: bool = True, key_exchanges: Optional[List[str]] = None) -> dict:
    case = get_case(case_id)
    if not case:
        raise ValueError(f"Unknown case '{case_id}'")
    sessions = sessions_for_case(case_id)

    pack = {
        "case_id": case_id,
        "case_name": case["name"],
        "generated": date.today().isoformat(),
        "sessions": [],
        "witnesses": sorted({w for s in sessions for w in s.witnesses}),
        "objection_log": [],
        "key_exchanges": [],
        "event_timeline": [],
    }

    for session in sorted(sessions, key=lambda s: (s.day_number or 0, s.title)):
        pack["sessions"].append(
            {
                "video_id": session.video_id,
                "title": session.title,
                "session_type": session.session_type,
                "day_number": session.day_number,
                "witnesses": session.witnesses,
                "duration_seconds": session.duration,
                "source_url": session.source_url,
            }
        )
        for m in extract_moments(session.video_id):
            entry = _entry(
                m.video_id, m.start, m.end, m.text, make_clips,
                moment_type=m.moment_type, session=session.title, **m.attrs,
            )
            pack["event_timeline"].append(entry)
            if m.moment_type == "objection":
                pack["objection_log"].append(entry)

    for query in key_exchanges or KEY_EXCHANGE_QUERIES:
        for m in semantic_search(case_id, query, limit=2):
            pack["key_exchanges"].append(
                _entry(m.video_id, m.start, m.end, m.text, make_clips,
                       theme=query, session=m.session_title, score=m.score)
            )

    out_path = DATA_DIR / "casepacks" / f"{case_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(pack, indent=2))
    return pack
