"""Legal-moment extraction — rule-first pass over word-timestamped transcripts.

Courtroom discourse is ritualized; the formal language of court gives exact,
reliable anchors ("objection", "sustained", "pass the witness") with word-level
timestamps. An LLM enrichment pass can later classify grounds and phases on
top of these anchors.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

from ..indexing.indexer import get_transcript

# Anchor patterns -> moment type. Order matters: rulings checked near objections.
ANCHORS = [
    (r"\bobjection\b", "objection"),
    (r"\bsustained\b", "ruling_sustained"),
    (r"\boverruled\b", "ruling_overruled"),
    (r"\bmove to strike\b", "motion_to_strike"),
    (r"\bsidebar\b|\bapproach the bench\b|\bmay we approach\b", "sidebar"),
    (r"\bno further questions\b|\bnothing further\b|\bpass the witness\b", "examination_end"),
    (r"\bcross[- ]examination\b", "cross_examination_marker"),
    (r"\bredirect\b", "redirect_marker"),
    (r"\byou may step down\b", "witness_dismissed"),
    (r"\bplease raise your right hand\b|\bdo you solemnly swear\b|\bsolemnly affirm\b", "witness_sworn"),
    (r"\bwe the jury\b|\bthe jury finds\b", "verdict"),
    (r"\bpermission to publish\b|\bmark(?:ed)? (?:as|for) (?:exhibit|identification)\b", "exhibit"),
]

OBJECTION_GROUNDS = [
    (r"\bhearsay\b", "hearsay"),
    (r"\bleading\b", "leading"),
    (r"\brelevance\b|\birrelevant\b", "relevance"),
    (r"\bspeculation\b|\bcalls for speculation\b", "speculation"),
    (r"\bfoundation\b", "foundation"),
    (r"\bargumentative\b", "argumentative"),
    (r"\basked and answered\b", "asked_and_answered"),
    (r"\bnon[- ]?responsive\b", "nonresponsive"),
    (r"\bbeyond the scope\b|\boutside the scope\b", "scope"),
    (r"\bcompound\b", "compound"),
]


@dataclass
class Moment:
    video_id: str
    start: float
    end: float
    moment_type: str
    text: str
    attrs: dict = field(default_factory=dict)


def _window_text(segments: List[dict], i: int, after: int = 8) -> str:
    """Text of segments i..i+after (context following an anchor)."""
    return " ".join(s["text"] for s in segments[i : i + after] if s.get("text"))


def extract_moments(video_id: str, context_seconds: float = 20.0) -> List[Moment]:
    """Rule-first scan. Returns anchored moments with clip-ready windows."""
    segments = get_transcript(video_id)  # [{start, end, text}]
    moments: List[Moment] = []

    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").lower()
        if not text:
            continue
        for pattern, mtype in ANCHORS:
            if not re.search(pattern, text):
                continue
            start = float(seg["start"])
            end = float(seg["end"])
            attrs = {}
            context = _window_text(segments, i).lower()
            if mtype == "objection":
                for gp, ground in OBJECTION_GROUNDS:
                    if re.search(gp, context):
                        attrs["ground"] = ground
                        break
                # look ahead for the ruling in the next few segments
                if re.search(r"\bsustained\b", context):
                    attrs["ruling"] = "sustained"
                elif re.search(r"\boverruled\b", context):
                    attrs["ruling"] = "overruled"
            moments.append(
                Moment(
                    video_id=video_id,
                    start=max(0.0, start - context_seconds / 2),
                    end=end + context_seconds,
                    moment_type=mtype,
                    text=_window_text(segments, max(0, i - 2), after=10),
                    attrs=attrs,
                )
            )
            break  # one moment per segment
    return _dedupe(moments)


def _dedupe(moments: List[Moment], min_gap: float = 5.0) -> List[Moment]:
    """Collapse same-type moments anchored within min_gap seconds."""
    out: List[Moment] = []
    for m in sorted(moments, key=lambda x: (x.moment_type, x.start)):
        prev: Optional[Moment] = out[-1] if out else None
        if prev and prev.moment_type == m.moment_type and m.start - prev.start < min_gap:
            prev.end = max(prev.end, m.end)
            prev.attrs.update({k: v for k, v in m.attrs.items() if k not in prev.attrs})
            continue
        out.append(m)
    out.sort(key=lambda x: x.start)
    return out


def objection_log(video_id: str) -> List[Moment]:
    """Just the objections (with ruling/ground attrs where detected)."""
    return [m for m in extract_moments(video_id) if m.moment_type == "objection"]
