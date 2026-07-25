"""Oyez ingest — US Supreme Court oral arguments with named speakers.

Oyez publishes each argument as a public MP3 plus a time-aligned transcript
where every turn names its speaker and their role ("scotus_justice",
"attorney"). That is ground-truth attribution we would otherwise have to infer,
so we ingest the audio into VideoDB for search/clipping and keep Oyez's
speaker timeline alongside it.
"""
import json
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..catalog import SessionEntry, upsert_session
from ..config import DATA_DIR
from .pipeline import get_or_create_case_collection

API = "https://api.oyez.org"
UA = {"User-Agent": "Precedent/0.1 (legal education research)"}


def _get(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


@dataclass
class SpeakerTurn:
    speaker: str
    role: str
    start: float
    end: float
    text: str


@dataclass
class Argument:
    case_name: str
    docket: str
    term: str
    audio_url: str
    argued: str = ""
    turns: List[SpeakerTurn] = field(default_factory=list)

    @property
    def speaker_names(self) -> List[str]:
        return sorted({t.speaker for t in self.turns})

    @property
    def advocates(self) -> List[str]:
        return sorted({t.speaker for t in self.turns if "justice" not in t.role})


def list_term_cases(term: str, per_page: int = 30) -> List[dict]:
    return _get(f"{API}/cases?per_page={per_page}&filter=term:{term}")


def fetch_argument(term: str, docket: str) -> Optional[Argument]:
    """Audio URL + speaker-labeled transcript for one argument."""
    case = _get(f"{API}/cases/{term}/{docket}")
    audios = case.get("oral_argument_audio") or []
    if not audios:
        return None
    media = _get(audios[0]["href"])

    audio_url = ""
    for f in media.get("media_file") or []:
        if f.get("mime") == "audio/mpeg":
            audio_url = f["href"]
            break
    if not audio_url:
        return None

    turns: List[SpeakerTurn] = []
    for section in (media.get("transcript") or {}).get("sections") or []:
        for turn in section.get("turns") or []:
            speaker = (turn.get("speaker") or {}).get("name") or "Unknown"
            roles = (turn.get("speaker") or {}).get("roles")
            role = "attorney"
            if isinstance(roles, list) and roles:
                role = roles[0].get("type") or role
            blocks = turn.get("text_blocks") or []
            if not blocks:
                continue
            turns.append(
                SpeakerTurn(
                    speaker=speaker,
                    role=role,
                    start=float(blocks[0].get("start") or 0),
                    end=float(blocks[-1].get("stop") or 0),
                    text=" ".join((b.get("text") or "") for b in blocks).strip(),
                )
            )

    argued = ""
    for event in case.get("timeline") or []:
        if "argument" in (event.get("event") or "").lower() and event.get("dates"):
            argued = str(event["dates"][0])
            break

    return Argument(
        case_name=case.get("name") or docket,
        docket=docket,
        term=str(term),
        audio_url=audio_url,
        argued=argued,
        turns=turns,
    )


def ingest_argument(
    term: str,
    docket: str,
    case_id: str = "scotus-oral-arguments",
    case_name: str = "US Supreme Court — Oral Arguments",
) -> Optional[SessionEntry]:
    """Upload one SCOTUS argument to VideoDB and catalog its speakers."""
    argument = fetch_argument(term, docket)
    if not argument:
        return None

    coll = get_or_create_case_collection(case_id, case_name)
    media = coll.upload(url=argument.audio_url, name=f"{argument.case_name} ({argument.term})")

    entry = SessionEntry(
        video_id=media.id,
        case_id=case_id,
        title=f"{argument.case_name} — oral argument",
        session_type="oral_argument",
        source_url=argument.audio_url,
        date=argument.argued,
        witnesses=argument.advocates,  # advocates are the performers here
        collection_id=coll.id,
        duration=getattr(media, "length", None),
    )
    upsert_session(entry)

    # Oyez's named speaker timeline beats any diarization we could infer.
    speaker_path = DATA_DIR / "speakers" / f"{media.id}.json"
    speaker_path.parent.mkdir(parents=True, exist_ok=True)
    speaker_path.write_text(
        json.dumps(
            {
                "source": "oyez",
                "case_name": argument.case_name,
                "docket": argument.docket,
                "term": argument.term,
                "turns": [t.__dict__ for t in argument.turns],
            },
            indent=2,
        )
    )
    return entry


def load_speaker_timeline(video_id: str) -> Optional[dict]:
    path = DATA_DIR / "speakers" / f"{video_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def speaker_at(video_id: str, timestamp: float) -> Optional[Dict[str, str]]:
    """Who was speaking at this moment, by name and role (Oyez sessions)."""
    timeline = load_speaker_timeline(video_id)
    if not timeline:
        return None
    for turn in timeline["turns"]:
        if turn["start"] <= timestamp <= turn["end"]:
            return {"speaker": turn["speaker"], "role": turn["role"]}
    return None
