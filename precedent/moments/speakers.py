"""Speaker roles — who is talking: judge, examiner, witness.

VideoDB's word-level transcript carries diarization labels ("A", "B", ...).
Those letters mean nothing to a law student, but courtroom speech is
role-marked: the examiner asks questions, the witness answers them, the judge
rules on objections. That's enough signal to name the speakers, which turns
"find X" into "find X *said by the witness*".
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from videodb import Segmenter

from ..catalog import get_session
from ..config import get_connection

ROLE_JUDGE = "judge"
ROLE_EXAMINER = "examiner"
ROLE_WITNESS = "witness"
ROLE_NARRATOR = "narrator"
ROLE_OTHER = "other"

RULING_RE = re.compile(r"\b(sustained|overruled|i'?ll allow it|the objection is)\b", re.I)
OBJECTION_RE = re.compile(r"\bobjection\b", re.I)
HONORIFIC_RE = re.compile(r"\b(your honor|may it please the court)\b", re.I)
JUDGE_SELF_RE = re.compile(
    r"\b(the court will|this court|counsel,|ladies and gentlemen of the jury|"
    r"next question|you may (?:step down|proceed|answer)|approach the bench)\b", re.I
)
# Broadcast narration: third-person commentary about the proceeding, not in it.
NARRATION_RE = re.compile(
    r"\b(court tv|law ?& ?crime|welcome back|we'?re back|joining us|coming up|"
    r"our coverage|the trial (?:resumes|continues)|testified (?:that|earlier)|"
    r"claiming (?:she|he)|according to (?:her|his) testimony|took the stand)\b", re.I
)
COURTROOM_ADDRESS_RE = re.compile(r"\b(your honor|objection|yes,? sir|no,? sir|ma'?am|the witness)\b", re.I)


@dataclass
class Turn:
    speaker: str
    start: float
    end: float
    text: str
    role: str = ROLE_OTHER


@dataclass
class SpeakerProfile:
    speaker: str
    role: str
    turns: int
    words: int
    question_ratio: float
    objections: int
    rulings: int
    talk_seconds: float
    sample: str = ""


def _video(video_id: str):
    session = get_session(video_id)
    conn = get_connection()
    coll = conn.get_collection(session.collection_id) if session else conn.get_collection()
    return coll.get_video(video_id)


def build_turns(video_id: str, start: Optional[float] = None, end: Optional[float] = None) -> List[Turn]:
    """Group the word-level transcript into speaker turns."""
    video = _video(video_id)
    words = video.get_transcript(start=start, end=end, segmenter=Segmenter.word)
    turns: List[Turn] = []
    for w in words:
        text = (w.get("text") or "").strip()
        speaker = w.get("speaker")
        if not text or text == "-" or not speaker:
            continue
        if turns and turns[-1].speaker == speaker and float(w["start"]) - turns[-1].end < 2.0:
            turns[-1].end = float(w["end"])
            turns[-1].text += " " + text
        else:
            turns.append(Turn(speaker=speaker, start=float(w["start"]), end=float(w["end"]), text=text))
    return turns


def profile_speakers(turns: List[Turn]) -> Dict[str, SpeakerProfile]:
    """Assign courtroom roles to diarization labels using speech behavior."""
    stats: Dict[str, dict] = defaultdict(
        lambda: {"turns": 0, "questions": 0, "words": 0, "objections": 0, "rulings": 0,
                 "honorifics": 0, "judgeisms": 0, "narration": 0, "address": 0,
                 "seconds": 0.0, "sample": ""}
    )
    for turn in turns:
        s = stats[turn.speaker]
        s["turns"] += 1
        s["words"] += len(turn.text.split())
        s["seconds"] += max(0.0, turn.end - turn.start)
        if "?" in turn.text:
            s["questions"] += 1
        s["objections"] += len(OBJECTION_RE.findall(turn.text))
        s["rulings"] += len(RULING_RE.findall(turn.text))
        s["honorifics"] += len(HONORIFIC_RE.findall(turn.text))
        s["judgeisms"] += len(JUDGE_SELF_RE.findall(turn.text))
        s["narration"] += len(NARRATION_RE.findall(turn.text))
        s["address"] += len(COURTROOM_ADDRESS_RE.findall(turn.text))
        if not s["sample"] and len(turn.text.split()) > 8:
            s["sample"] = turn.text[:180]

    profiles: Dict[str, SpeakerProfile] = {}
    for speaker, s in stats.items():
        ratio = s["questions"] / s["turns"] if s["turns"] else 0.0
        profiles[speaker] = SpeakerProfile(
            speaker=speaker, role=ROLE_OTHER, turns=s["turns"], words=s["words"],
            question_ratio=round(ratio, 3), objections=s["objections"],
            rulings=s["rulings"], talk_seconds=round(s["seconds"], 1), sample=s["sample"],
        )
    if not profiles:
        return profiles

    # Narrator: broadcast commentary *about* the proceeding, never inside it.
    # Broadcaster voiceover otherwise pollutes claim extraction and search hits.
    for sp, p in profiles.items():
        if stats[sp]["narration"] >= 2 and stats[sp]["address"] == 0 and stats[sp]["honorifics"] == 0:
            p.role = ROLE_NARRATOR

    def open_speakers():
        return [sp for sp, p in profiles.items() if p.role == ROLE_OTHER]

    # Judge: rules on objections and runs the room, in few words.
    for sp in sorted(open_speakers(), key=lambda x: -(stats[x]["rulings"] * 3 + stats[x]["judgeisms"])):
        if stats[sp]["rulings"] >= 2 or (stats[sp]["rulings"] >= 1 and stats[sp]["judgeisms"] >= 2):
            profiles[sp].role = ROLE_JUDGE
        break

    # Examiners: attorneys ask questions — there are usually several.
    for sp in open_speakers():
        if profiles[sp].question_ratio >= 0.4 or stats[sp]["objections"] >= 2:
            profiles[sp].role = ROLE_EXAMINER

    # Witness: answers at length, rarely asks.
    rest = [sp for sp in open_speakers() if profiles[sp].question_ratio < 0.3]
    if rest:
        profiles[max(rest, key=lambda sp: stats[sp]["words"])].role = ROLE_WITNESS
    return profiles


def label_turns(video_id: str, start: Optional[float] = None, end: Optional[float] = None):
    """Turns with roles attached, plus the speaker profiles used."""
    turns = build_turns(video_id, start, end)
    profiles = profile_speakers(turns)
    for turn in turns:
        turn.role = profiles[turn.speaker].role if turn.speaker in profiles else ROLE_OTHER
    return turns, profiles


def role_map(video_id: str) -> Dict[str, str]:
    """speaker label -> role, computed over the whole session."""
    _, profiles = label_turns(video_id)
    return {sp: p.role for sp, p in profiles.items()}
