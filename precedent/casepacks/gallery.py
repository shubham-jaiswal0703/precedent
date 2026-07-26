"""Gallery: the library as a browsable shelf of cases.

A student who does not yet know what to search for needs to browse. Each case
becomes a card with its shape visible at a glance (how many sessions, who
speaks, what kinds of moments it contains), and opening a case surfaces
recommended sections rather than an empty search box.
"""
from collections import Counter
from typing import Dict, List, Optional

from ..catalog import SessionEntry, _load as load_catalog, sessions_for_case
from ..media import case_cover, session_thumbnail
from ..moments.attribution import speakers_in_session
from ..moments.extractor import cached_moments

# How a moment type reads to a student, and where it belongs in a case view.
MOMENT_LABELS: Dict[str, str] = {
    "objection": "Objections",
    "ruling_sustained": "Sustained rulings",
    "ruling_overruled": "Overruled rulings",
    "impeachment_prior_statement": "Impeachment with a prior statement",
    "cross_examination_marker": "Cross-examination",
    "redirect_marker": "Redirect",
    "sidebar": "Sidebars",
    "motion_to_strike": "Motions to strike",
    "examination_end": "Ends of examination",
    "witness_sworn": "Witnesses sworn",
    "witness_dismissed": "Witnesses excused",
    "verdict": "Verdict",
    "exhibit": "Exhibits",
    "refreshing_recollection": "Refreshing recollection",
    "offer_of_proof": "Offers of proof",
    "motion_in_limine": "Motions in limine",
    "dispositive_motion": "Dispositive motions",
    "motion_for_mistrial": "Mistrial motions",
    "curative_instruction": "Curative instructions",
    "expert_qualification": "Expert qualification",
    "witness_sequestration": "Witness sequestration",
    "opening_or_closing": "Opening and closing",
    "argument_opening": "Opening lines of argument",
    "case_called": "Case called",
    "standard_of_review": "Standard of review",
    "hypothetical_from_bench": "Hypotheticals from the bench",
    "best_case_question": "Best-case questions",
    "concession": "Concessions",
    "refusal_to_concede": "Refusals to concede",
    "line_drawing": "Line-drawing questions",
    "interruption_recovery": "Recovering from interruption",
    "time_expired": "Time expiring",
    "rebuttal": "Rebuttal",
    "justiciability_colloquy": "Standing and jurisdiction",
    "stare_decisis_argument": "Stare decisis",
    "interpretive_method": "Interpretive method",
    "record_citation": "Citations to the record",
}

# Sections worth putting in front of a student first, in teaching order.
FEATURED_ORDER = [
    "impeachment_prior_statement", "objection", "ruling_sustained", "cross_examination_marker",
    "hypothetical_from_bench", "concession", "refusal_to_concede", "standard_of_review",
    "best_case_question", "stare_decisis_argument", "sidebar", "expert_qualification",
]


def _kind(case_id: str, sessions: List[SessionEntry]) -> str:
    types = {s.session_type for s in sessions}
    if types == {"oral_argument"}:
        return "appellate"
    if "oral_argument" in types:
        return "mixed"
    return "trial"


def case_cards() -> List[dict]:
    """One card per case: enough shape to decide what to open."""
    catalog = load_catalog()
    cards = []
    for case_id, case in catalog["cases"].items():
        sessions = sessions_for_case(case_id)
        if not sessions:
            continue
        counts: Counter = Counter()
        for session in sessions:
            try:
                counts.update(m.moment_type for m in cached_moments(session.video_id))
            except Exception:
                continue
        people: List[str] = []
        for session in sessions[:4]:
            try:
                people.extend(p["name"] for p in speakers_in_session(session.video_id)[:4]
                              if not p["name"].isupper() and len(p["name"]) > 2)
            except Exception:
                continue
        kind = _kind(case_id, sessions)
        cards.append({
            "case_id": case_id,
            "name": case["name"],
            "kind": kind,
            "cover": case_cover(case_id, case["name"], kind),
            "sessions": len(sessions),
            "hours": round(sum(s.duration or 0 for s in sessions) / 3600, 1),
            "moments": sum(counts.values()),
            "highlights": [{"type": t, "label": MOMENT_LABELS.get(t, t.replace('_', ' ')), "count": n}
                           for t, n in counts.most_common(4)],
            "people": sorted(set(people))[:6],
            "titles": [s.title for s in sessions[:5]],
        })
    cards.sort(key=lambda c: -c["moments"])
    return cards


def case_detail(case_id: str, per_section: int = 4) -> dict:
    """A case opened up: sessions, participants, and recommended sections."""
    catalog = load_catalog()
    case = catalog["cases"].get(case_id)
    if not case:
        raise ValueError(f"Unknown case '{case_id}'")
    sessions = sessions_for_case(case_id)

    by_type: Dict[str, List[dict]] = {}
    for session in sessions:
        try:
            moments = cached_moments(session.video_id)
        except Exception:
            continue
        for m in moments:
            entry = {
                "video_id": m.video_id, "start": round(m.start, 1), "end": round(m.end, 1),
                "text": m.text[:320], "session": session.title, "attrs": m.attrs,
            }
            by_type.setdefault(m.moment_type, []).append(entry)

    ordered_types = ([t for t in FEATURED_ORDER if t in by_type]
                     + sorted(t for t in by_type if t not in FEATURED_ORDER))
    sections = [{
        "type": t,
        "label": MOMENT_LABELS.get(t, t.replace("_", " ").title()),
        "total": len(by_type[t]),
        "moments": by_type[t][:per_section],
    } for t in ordered_types]

    participants: List[dict] = []
    for session in sessions:
        try:
            for person in speakers_in_session(session.video_id):
                participants.append({**person, "session": session.title})
        except Exception:
            continue

    kind = _kind(case_id, sessions)
    return {
        "case_id": case_id,
        "name": case["name"],
        "kind": kind,
        "cover": case_cover(case_id, case["name"], kind),
        "hours": round(sum(s.duration or 0 for s in sessions) / 3600, 1),
        "sessions": [{
            "video_id": s.video_id, "title": s.title, "session_type": s.session_type,
            "duration": s.duration, "date": s.date, "source_url": s.source_url,
            "thumbnail": session_thumbnail(s.video_id),
            "judge": s.indexes.get("judge", ""), "docket": s.indexes.get("docket", ""),
        } for s in sessions],
        "participants": participants[:24],
        "sections": sections,
        "suggested_questions": suggested_questions(case_id, sessions, by_type),
    }


def suggested_questions(case_id: str, sessions: List[SessionEntry],
                        by_type: Optional[Dict[str, list]] = None) -> List[str]:
    """Questions worth asking about this case, based on what it contains."""
    by_type = by_type or {}
    kind = _kind(case_id, sessions)
    questions: List[str] = []
    if kind == "appellate":
        questions += [
            "What was the advocate's central argument?",
            "Which questions from the bench gave the advocate the most trouble?",
            "Where did the advocate concede a point, and why?",
        ]
        if "standard_of_review" in by_type:
            questions.append("How did the parties frame the standard of review?")
        if "stare_decisis_argument" in by_type:
            questions.append("How was stare decisis argued on each side?")
    else:
        questions += [
            "What was the theory of the case on cross-examination?",
            "Which objections changed the course of the testimony?",
            "How did the witness's answers shift under pressure?",
        ]
        if "impeachment_prior_statement" in by_type:
            questions.append("How did counsel impeach the witness with a prior statement?")
    return questions[:5]
