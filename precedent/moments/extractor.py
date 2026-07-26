"""Legal-moment extraction: rule-first pass over word-timestamped transcripts.

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
MIN_MOMENT_SECONDS = 12.0  # shortest clip worth showing a student

SUSTAIN_RE = r"\bsustain(?:ed|s|ing)?\b"
OVERRULE_RE = r"\boverrul(?:ed|e|es|ing)\b|\bi'?ll allow it\b|\bthe answer (?:may )?stands?\b"

# Trial-court events. Courtroom speech is ritualized, so the words that mark
# each event are stable enough to anchor on.
TRIAL_ANCHORS = [
    (r"\bobjection\b", "objection"),
    (SUSTAIN_RE, "ruling_sustained"),
    (OVERRULE_RE, "ruling_overruled"),
    (r"\bmove to strike\b|\bstrike (?:that|the answer)\b", "motion_to_strike"),
    (r"\bsidebar\b|\bapproach the bench\b|\bmay we approach\b", "sidebar"),
    (r"\bno further questions\b|\bnothing further\b|\bpass the witness\b", "examination_end"),
    (r"\bcross[- ]examination\b", "cross_examination_marker"),
    (r"\bredirect\b", "redirect_marker"),
    (r"\byou may step down\b", "witness_dismissed"),
    (r"\bplease raise your right hand\b|\bdo you solemnly swear\b|\bsolemnly affirm\b", "witness_sworn"),
    (r"\bwe the jury\b|\bthe jury finds\b", "verdict"),
    (r"\bpermission to publish\b|\bmark(?:ed)? (?:as|for) (?:exhibit|identification)\b", "exhibit"),
    # Impeachment and prior statements: the heart of cross-examination teaching.
    (r"\byou testified (?:earlier|previously|before)\b|\bin your deposition\b|"
     r"\bdo you remember (?:your|giving) testimony\b|\bthat was your testimony\b",
     "impeachment_prior_statement"),
    (r"\brefresh your (?:recollection|memory)\b", "refreshing_recollection"),
    (r"\boffer of proof\b", "offer_of_proof"),
    (r"\bmotion in limine\b", "motion_in_limine"),
    (r"\bdirected verdict\b|\bjudgment as a matter of law\b|\bjudgment of acquittal\b",
     "dispositive_motion"),
    (r"\bmistrial\b", "motion_for_mistrial"),
    (r"\bdisregard (?:that|the (?:last )?(?:answer|question|statement))\b|"
     r"\blimiting instruction\b", "curative_instruction"),
    (r"\byour expert\b|\bqualified as an expert\b|\btender (?:him|her|the witness) as an expert\b|"
     r"\bdaubert\b", "expert_qualification"),
    (r"\binvoke the rule\b|\bsequester(?:ed|ing)? the witness(?:es)?\b", "witness_sequestration"),
    (r"\bladies and gentlemen of the jury\b.{0,40}\b(?:opening|closing)\b|"
     r"\bin (?:my|our) opening statement\b", "opening_or_closing"),
]

# Appellate argument events. A different craft with its own ritual language,
# and the reason the SCOTUS corpus needs its own anchors.
APPELLATE_ANCHORS = [
    (r"\bmay it please the court\b", "argument_opening"),
    (r"\bwe'?ll hear (?:argument|the case)\b|\bwe will hear argument\b", "case_called"),
    (r"\bstandard of review\b|\bde novo\b|\babuse of discretion\b|\bclear(?:ly)? erroneous\b|"
     r"\brational basis\b|\bstrict scrutiny\b|\bintermediate scrutiny\b", "standard_of_review"),
    (r"\bsuppose (?:that )?(?:i|we|a|the)\b|\bwhat if\b|\bhypothetical\b|"
     r"\blet'?s (?:say|assume)\b|\bimagine (?:that|a)\b", "hypothetical_from_bench"),
    (r"\bwhat(?:'s| is) your best case\b|\byour best authority\b", "best_case_question"),
    (r"\b(?:i|we) (?:would )?concede\b|\bwe don'?t (?:dispute|contest)\b|"
     r"\bthat'?s (?:right|correct), your honor\b", "concession"),
    (r"\bi (?:would )?(?:respectfully )?disagree\b|\bno, your honor\b|"
     r"\bi (?:can'?t|cannot|won'?t) concede\b", "refusal_to_concede"),
    (r"\bwhere (?:would you|do we) draw the line\b|\bline[- ]drawing\b|"
     r"\bhow far does (?:that|this) go\b", "line_drawing"),
    (r"\bmay i finish\b|\bif i (?:may|could) finish\b|\blet me finish\b", "interruption_recovery"),
    (r"\byour time (?:has expired|is up)\b|\bthank you,? counsel\b", "time_expired"),
    (r"\brebuttal\b", "rebuttal"),
    (r"\bstanding\b|\bjurisdiction(?:al)?\b|\bmoot(?:ness)?\b|\bripe(?:ness)?\b",
     "justiciability_colloquy"),
    (r"\bstare decisis\b|\boverrul(?:e|ing) (?:roe|casey|precedent|that case)\b|"
     r"\breliance interests\b", "stare_decisis_argument"),
    (r"\btext(?:ualism|ual)\b|\bplain (?:meaning|language|text)\b|\blegislative history\b|"
     r"\boriginal(?:ism|ist)\b|\bcanon of construction\b", "interpretive_method"),
    (r"\brecord (?:at|page|shows)\b|\bjoint appendix\b|\bin the record\b", "record_citation"),
]

# Which anchor set applies to which kind of proceeding.
ANCHORS_BY_SESSION = {
    "trial_day": TRIAL_ANCHORS,
    "deposition": TRIAL_ANCHORS,
    "hearing": TRIAL_ANCHORS + APPELLATE_ANCHORS,
    "oral_argument": APPELLATE_ANCHORS,
}

ANCHORS = TRIAL_ANCHORS  # default for callers that don't know the session type

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


def _join_segments(segments: List[dict]):
    """One searchable string plus a char-offset -> segment-index map.

    VideoDB returns transcripts as short phrase chunks, so a phrase like
    "may it please the court" is split across several of them. Matching has to
    happen over the continuous text, then map back to a timestamp.
    """
    parts: List[str] = []
    offsets: List[tuple] = []
    pos = 0
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        parts.append(text)
        offsets.append((pos, i))
        pos += len(text) + 1
    return " ".join(parts).lower(), offsets


def _segment_for_offset(offsets: List[tuple], char_pos: int) -> int:
    """Segment index containing a character position (binary search)."""
    lo, hi = 0, len(offsets) - 1
    found = offsets[0][1] if offsets else 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if offsets[mid][0] <= char_pos:
            found = offsets[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return found


def _cache_path(video_id: str):
    from ..config import DATA_DIR

    return DATA_DIR / "moments" / f"{video_id}.json"


def cached_moments(video_id: str, refresh: bool = False) -> List[Moment]:
    """Extracted moments, memoized on disk.

    Extraction costs a full transcript fetch per session, and the gallery and
    case packs ask for it repeatedly across a growing corpus.
    """
    import json

    path = _cache_path(video_id)
    if path.exists() and not refresh:
        try:
            return [Moment(**m) for m in json.loads(path.read_text())]
        except Exception:
            pass  # stale or malformed cache: fall through and rebuild
    moments = extract_moments(video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([m.__dict__ for m in moments], indent=2))
    return moments


def extract_moments(video_id: str, context_seconds: float = 20.0) -> List[Moment]:
    """Rule-first scan. Returns anchored moments with clip-ready windows.

    The anchor set follows the kind of proceeding: a SCOTUS argument has no
    objections to find, and a trial has no standard-of-review colloquy.
    """
    from ..catalog import get_session

    session = get_session(video_id)
    anchors = ANCHORS_BY_SESSION.get(session.session_type if session else "", TRIAL_ANCHORS)

    segments = get_transcript(video_id)  # [{start, end, text}]
    haystack, offsets = _join_segments(segments)
    if not haystack:
        return []

    moments: List[Moment] = []
    for pattern, mtype in anchors:
        for match in re.finditer(pattern, haystack):
            i = _segment_for_offset(offsets, match.start())
            seg = segments[i]
            start, end = float(seg["start"]), float(seg["end"])
            attrs = {}
            if mtype == "objection":
                context = _window_text(segments, i).lower()
                for gp, ground in OBJECTION_GROUNDS:
                    if re.search(gp, context):
                        attrs["ground"] = ground
                        break
                # the ruling follows the objection: "Objection. Hearsay." / "Sustained."
                if re.search(SUSTAIN_RE, context):
                    attrs["ruling"] = "sustained"
                elif re.search(OVERRULE_RE, context):
                    attrs["ruling"] = "overruled"
            window_start = max(0.0, start - context_seconds / 2)
            # A moment has to be long enough to watch. Transcript chunks are
            # short, and an anchor landing on a one-word chunk would otherwise
            # produce a zero-length clip.
            window_end = max(end + context_seconds, window_start + MIN_MOMENT_SECONDS)
            moments.append(
                Moment(
                    video_id=video_id,
                    start=window_start,
                    end=window_end,
                    moment_type=mtype,
                    text=_window_text(segments, max(0, i - 2), after=12),
                    attrs=attrs,
                )
            )
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
