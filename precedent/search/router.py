"""Query router — read the question like a law professor, then pick the index.

Half of what a law student asks is a *filter*, not a similarity search:
"every sustained hearsay objection", "FRE 403 arguments", "the cross-examination
on the DNA". Vector search answers none of those well, because nobody in a
courtroom says "403" out loud and "objection" is a structural event rather than
a topic. So we classify the question first and route it:

    objections/rulings/rules  -> the structured legal-moment layer
    verbatim phrases          -> keyword search
    everything else           -> semantic search, narrowed by precision.py

The detected interpretation is returned alongside the results, so the UI can
show *why* these clips came back.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..catalog import sessions_for_case
from ..moments.extractor import Moment, extract_moments
from .engine import (PlayableMoment, attribute_moments, clip_url, keyword_search,
                     semantic_search)

INTENT_OBJECTION = "find_objection"
INTENT_MOMENT = "find_moment"
INTENT_RULE = "find_by_rule"
INTENT_VERBATIM = "find_verbatim"
INTENT_SPEAKER = "find_by_speaker"
INTENT_SEMANTIC = "find_semantic"

# Named speakers worth recognising in a query without hitting the corpus first.
# Surnames only: students type "how did Gorsuch press her", not the full name.
KNOWN_SPEAKERS = (
    "roberts", "thomas", "alito", "sotomayor", "kagan", "gorsuch", "kavanaugh",
    "barrett", "jackson", "breyer", "ginsburg", "scalia", "kennedy", "souter",
    "stevens", "o'connor", "rehnquist", "prelogar", "vasquez", "rottenborn",
)

# Objection grounds as students name them -> spoken-word cues.
GROUNDS: Dict[str, Sequence[str]] = {
    "hearsay": ("hearsay",),
    "leading": ("leading",),
    "relevance": ("relevance", "relevant", "irrelevant"),
    "speculation": ("speculation", "speculate"),
    "foundation": ("foundation",),
    "argumentative": ("argumentative",),
    "asked_and_answered": ("asked and answered",),
    "nonresponsive": ("non responsive", "nonresponsive", "not responsive"),
    "scope": ("beyond the scope", "outside the scope"),
    "compound": ("compound",),
    "narrative": ("narrative",),
    "privilege": ("privilege", "privileged"),
    "best_evidence": ("best evidence",),
    "authentication": ("authentication", "authenticate"),
    "prejudice": ("prejudicial", "prejudice"),
    "character": ("character",),
    "badgering": ("badgering", "harassing"),
}

# Federal Rules of Evidence -> the objection ground actually spoken in court.
FRE_RULES: Dict[str, Tuple[str, str]] = {
    "402": ("relevance", "FRE 402 — relevance"),
    "403": ("prejudice", "FRE 403 — unfair prejudice / 403 balancing"),
    "404": ("character", "FRE 404 — character and prior bad acts"),
    "602": ("speculation", "FRE 602 — lack of personal knowledge"),
    "608": ("character", "FRE 608 — character for truthfulness"),
    "609": ("character", "FRE 609 — impeachment by conviction"),
    "611": ("leading", "FRE 611 — leading questions / mode of examination"),
    "612": ("foundation", "FRE 612 — refreshing recollection"),
    "613": ("hearsay", "FRE 613 — witness's prior statement"),
    "701": ("speculation", "FRE 701 — improper lay opinion"),
    "702": ("foundation", "FRE 702 — expert testimony / Daubert"),
    "801": ("hearsay", "FRE 801 — hearsay definition and exemptions"),
    "802": ("hearsay", "FRE 802 — rule against hearsay"),
    "803": ("hearsay", "FRE 803 — hearsay exceptions"),
    "804": ("hearsay", "FRE 804 — declarant unavailable"),
    "901": ("authentication", "FRE 901 — authenticating evidence"),
    "1002": ("best_evidence", "FRE 1002 — best evidence rule"),
}

# Moment types the extractor already labels, by how students ask for them.
MOMENT_PHRASES: Dict[str, Sequence[str]] = {
    "objection": ("objection",),
    "sidebar": ("sidebar", "bench conference", "approach the bench"),
    "examination_end": ("no further questions", "pass the witness", "nothing further"),
    "cross_examination_marker": ("cross examination", "cross-examination", "cross exam"),
    "redirect_marker": ("redirect",),
    "witness_sworn": ("sworn", "oath", "raise your right hand"),
    "witness_dismissed": ("step down", "excused"),
    "verdict": ("verdict", "jury finds"),
    "exhibit": ("exhibit", "publish", "marked for identification"),
    "motion_to_strike": ("move to strike", "motion to strike", "strike that"),
}

RULING_WORDS = {"sustained": "sustained", "overruled": "overruled",
                "granted": "sustained", "denied": "overruled"}


@dataclass
class QueryPlan:
    intent: str
    explanation: str
    ground: Optional[str] = None
    ruling: Optional[str] = None
    moment_type: Optional[str] = None
    rule: Optional[str] = None
    phrase: Optional[str] = None
    speaker: Optional[str] = None
    residual: str = ""


def plan_query(query: str) -> QueryPlan:
    """Classify a professor-style question into a retrieval plan."""
    q = query.lower()

    ruling = next((canonical for word, canonical in RULING_WORDS.items() if re.search(rf"\b{word}\b", q)), None)
    ground = next((name for name, cues in GROUNDS.items() if any(cue in q for cue in cues)), None)

    quoted = re.search(r'"([^"]{4,})"', query)
    if quoted:
        return QueryPlan(INTENT_VERBATIM, f'Exact phrase: "{quoted.group(1)}"', phrase=quoted.group(1))

    rule_match = re.search(r"\b(?:fre|rule|f\.r\.e\.?)\s*(\d{3,4})|\b(\d{3,4})\s*(?:objection|argument)", q)
    if rule_match:
        number = rule_match.group(1) or rule_match.group(2)
        if number in FRE_RULES:
            mapped_ground, label = FRE_RULES[number]
            bits = [label]
            if ruling:
                bits.append(f"{ruling} only")
            return QueryPlan(INTENT_RULE, " · ".join(bits), ground=mapped_ground,
                             ruling=ruling, rule=number, moment_type="objection")

    if ground or ruling or re.search(r"\bobjection|\bobject\b", q):
        parts = ["Objections"]
        if ground:
            parts.append(f"on {ground.replace('_', ' ')} grounds")
        if ruling:
            parts.append(f"that were {ruling}")
        return QueryPlan(INTENT_OBJECTION, " ".join(parts), ground=ground,
                         ruling=ruling, moment_type="objection")

    for moment_type, phrases in MOMENT_PHRASES.items():
        if any(p in q for p in phrases):
            return QueryPlan(INTENT_MOMENT, f"Courtroom events: {moment_type.replace('_', ' ')}",
                             moment_type=moment_type)

    named = next((s for s in KNOWN_SPEAKERS if re.search(rf"\b{re.escape(s)}\b", q)), None)
    if named:
        residual = re.sub(r"\s+", " ", re.sub(rf"\b{re.escape(named)}\b", " ", q)).strip()
        # "how did Gorsuch press the advocate" -> topic is "press the advocate"
        topic = re.sub(r"^(?:how|what|when|where|why|show me|find|did|does|do)\b\s*", "",
                       residual, flags=re.I).strip()
        return QueryPlan(INTENT_SPEAKER,
                         f"Spoken by {named.title()}" + (f" · about “{topic}”" if topic else ""),
                         speaker=named, residual=residual or query)

    return QueryPlan(INTENT_SEMANTIC, "Semantic search across the archive", residual=query)


def _moment_to_playable(m: Moment, session_title: str, session_type: str) -> PlayableMoment:
    return PlayableMoment(
        video_id=m.video_id, start=m.start, end=m.end, text=m.text,
        session_title=session_title, session_type=session_type,
        attrs={"moment_type": m.moment_type, **m.attrs},
    )


def _structured_search(case_id: str, plan: QueryPlan, limit: int) -> List[PlayableMoment]:
    """Filter the legal-moment layer — no vector search involved."""
    found: List[PlayableMoment] = []
    for session in sessions_for_case(case_id):
        for m in extract_moments(session.video_id):
            if plan.moment_type and m.moment_type != plan.moment_type:
                continue
            if plan.ground and m.attrs.get("ground") != plan.ground:
                continue
            if plan.ruling and m.attrs.get("ruling") != plan.ruling:
                continue
            found.append(_moment_to_playable(m, session.title, session.session_type))
    # Objections carrying an identified ground/ruling teach more; surface them first.
    found.sort(key=lambda p: (bool(p.attrs.get("ruling")), bool(p.attrs.get("ground"))), reverse=True)
    return found[:limit]


def _speaker_search(case_id: str, plan: QueryPlan, limit: int) -> List[PlayableMoment]:
    """Semantic search, then keep only moments the named speaker actually spoke in.

    Oyez gives us real names per turn, so "how did Gorsuch press the advocate"
    becomes a genuine speaker filter rather than a hope that the transcript
    happens to contain his name.
    """
    from ..moments.attribution import windows_for_speaker

    moments = semantic_search(case_id, plan.residual or plan.speaker, limit=limit * 3)
    kept: List[PlayableMoment] = []
    for m in moments:
        windows = windows_for_speaker(m.video_id, plan.speaker)
        if not windows:
            continue
        if any(min(m.end, w_end) - max(m.start, w_start) > 0 for w_start, w_end in windows):
            kept.append(m)
    return (kept or moments)[:limit]


def search(
    case_id: str,
    query: str,
    limit: int = 8,
    with_clips: bool = True,
    role: Optional[str] = None,
) -> dict:
    """Route a question to the right index and return playable answers."""
    plan = plan_query(query)

    if plan.intent in (INTENT_OBJECTION, INTENT_RULE, INTENT_MOMENT):
        moments = _structured_search(case_id, plan, limit)
        if not moments:  # nothing labeled — fall back rather than answer nothing
            moments = semantic_search(case_id, query, limit=limit, speaker_role=role)
            plan.explanation += " — none labeled, showing closest spoken matches"
    elif plan.intent == INTENT_VERBATIM:
        moments = keyword_search(case_id, plan.phrase)[:limit]
    elif plan.intent == INTENT_SPEAKER:
        moments = _speaker_search(case_id, plan, limit)
    else:
        moments = semantic_search(case_id, query, limit=limit, speaker_role=role)

    attribute_moments(moments)  # name the voices before we hand results out
    if with_clips:
        for m in moments:
            if not m.stream_url:
                try:
                    m.stream_url = clip_url(m.video_id, m.start, m.end)
                except Exception:
                    pass

    return {
        "intent": plan.intent,
        "interpretation": plan.explanation,
        "filters": {k: v for k, v in
                    {"ground": plan.ground, "ruling": plan.ruling,
                     "moment_type": plan.moment_type, "rule": plan.rule,
                     "speaker": plan.speaker}.items() if v},
        "results": moments,
    }
