"""Attribution: put a name on every moment.

Two sources of truth, in order of preference:
  1. Oyez's own speaker timeline (real names and roles: "Neil Gorsuch",
     scotus_justice). Ground truth, no inference.
  2. Inferred roles from VideoDB's diarization labels (judge / examiner /
     witness / narrator) for footage nobody has labeled for us.

A result that reads "Gorsuch questioning Waggoner" is worth far more to a
student than "speaker C".
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..ingest.oyez import load_speaker_timeline
from .speakers import ROLE_NAMES_BY_ROLE, role_map

_TIMELINE_CACHE: Dict[str, Optional[dict]] = {}
_ROLEMAP_CACHE: Dict[str, Dict[str, str]] = {}


@dataclass
class Attribution:
    """Who speaks in a moment, named where possible."""
    named: List[str] = field(default_factory=list)          # real names, in order of talk time
    roles: List[str] = field(default_factory=list)          # canonical roles present
    source: str = "none"                                    # oyez | inferred | none
    lead: Optional[str] = None                              # the dominant voice
    lead_role: Optional[str] = None

    @property
    def label(self) -> str:
        """A short human phrase for the UI."""
        if self.source == "oyez" and self.named:
            if len(self.named) == 1:
                return self.named[0]
            return f"{self.named[0]}: {self.named[1]}"
        if self.roles:
            pretty = [ROLE_NAMES_BY_ROLE.get(r, r) for r in self.roles if r != "other"]
            return " · ".join(pretty) if pretty else ""
        return ""


def _timeline(video_id: str) -> Optional[dict]:
    if video_id not in _TIMELINE_CACHE:
        _TIMELINE_CACHE[video_id] = load_speaker_timeline(video_id)
    return _TIMELINE_CACHE[video_id]


def _roles(video_id: str) -> Dict[str, str]:
    if video_id not in _ROLEMAP_CACHE:
        try:
            _ROLEMAP_CACHE[video_id] = role_map(video_id)
        except Exception:
            _ROLEMAP_CACHE[video_id] = {}
    return _ROLEMAP_CACHE[video_id]


def attribute(video_id: str, start: float, end: float,
              speaker_labels: Optional[List[str]] = None) -> Attribution:
    """Name the speakers active in a time window."""
    timeline = _timeline(video_id)
    if timeline:
        talk: Dict[str, float] = {}
        roles: Dict[str, str] = {}
        for turn in timeline["turns"]:
            overlap = min(end, turn["end"]) - max(start, turn["start"])
            if overlap > 0:
                talk[turn["speaker"]] = talk.get(turn["speaker"], 0.0) + overlap
                roles[turn["speaker"]] = turn["role"]
        if talk:
            ordered = sorted(talk, key=talk.get, reverse=True)
            return Attribution(
                named=ordered,
                roles=sorted({roles[s] for s in ordered}),
                source="oyez",
                lead=ordered[0],
                lead_role=roles[ordered[0]],
            )

    if speaker_labels:
        mapping = _roles(video_id)
        present = [mapping.get(label, "other") for label in speaker_labels]
        return Attribution(
            roles=sorted(set(present)),
            source="inferred",
            lead_role=present[0] if present else None,
        )
    return Attribution()


def speakers_in_session(video_id: str) -> List[dict]:
    """Everyone who speaks in a session, named where we know them."""
    timeline = _timeline(video_id)
    if timeline:
        seen: Dict[str, dict] = {}
        for turn in timeline["turns"]:
            entry = seen.setdefault(turn["speaker"], {"name": turn["speaker"], "role": turn["role"], "seconds": 0.0})
            entry["seconds"] += max(0.0, turn["end"] - turn["start"])
        return sorted(seen.values(), key=lambda s: -s["seconds"])
    return [{"name": label, "role": role, "seconds": None}
            for label, role in sorted(_roles(video_id).items())]


def find_speaker(video_id: str, name_fragment: str) -> Optional[str]:
    """Resolve a partial name ("gorsuch") to a full speaker name."""
    fragment = name_fragment.lower().strip()
    for speaker in speakers_in_session(video_id):
        if fragment in speaker["name"].lower():
            return speaker["name"]
    return None


def windows_for_speaker(video_id: str, name: str) -> List[tuple]:
    """Time ranges where a named speaker is talking (Oyez sessions only)."""
    timeline = _timeline(video_id)
    if not timeline:
        return []
    lowered = name.lower()
    return [(t["start"], t["end"]) for t in timeline["turns"] if lowered in t["speaker"].lower()]
