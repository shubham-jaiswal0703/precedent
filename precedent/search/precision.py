"""Search precision — tighten a matched region to the words that matter.

VideoDB returns shots whose windows are wider than the answer. A law student
searching "impeachment with a prior inconsistent statement" wants the ten
seconds where it happens, with the words on screen — not a 90-second block.

This module:
  * pulls sentence- and word-level transcript for a shot window,
  * scores sentences against the query (lexical + legal-synonym expansion),
  * tightens the clip to the best contiguous run of sentences,
  * returns per-word match flags so the UI can highlight and seek.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from videodb import Segmenter

from ..catalog import get_session
from ..config import get_connection

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for",
    "from", "had", "has", "have", "he", "her", "his", "how", "i", "in", "is",
    "it", "its", "me", "my", "of", "on", "or", "s", "she", "show", "that",
    "the", "their", "them", "there", "they", "this", "to", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "you",
    "your", "find", "every", "all", "any", "get", "give", "moment", "moments",
    "clip", "clips", "example", "examples", "part", "parts", "video",
    "about", "during", "into", "over", "under", "between", "before", "after",
    "while", "said", "say", "tell", "show", "just", "very", "some",
    "where", "whose", "been", "being", "than", "then", "also", "made", "make",
}

# Query terms a law student uses -> words actually spoken in a courtroom.
LEGAL_SYNONYMS: Dict[str, Sequence[str]] = {
    "impeach": ("prior", "testified", "deposition", "inconsistent", "statement", "earlier"),
    "impeachment": ("prior", "testified", "deposition", "inconsistent", "statement"),
    "objection": ("objection", "object", "sustained", "overruled"),
    "sustained": ("sustained",),
    "overruled": ("overruled",),
    "hearsay": ("hearsay", "out of court", "statement"),
    "leading": ("leading", "suggests", "answer"),
    "relevance": ("relevance", "relevant", "irrelevant", "403", "402"),
    "foundation": ("foundation", "personal knowledge", "authenticate"),
    "speculation": ("speculation", "speculate", "guess"),
    "cross": ("cross", "examination", "isn't that right", "correct"),
    "crossexamination": ("cross", "examination"),
    "direct": ("direct", "examination", "tell the jury", "describe"),
    "redirect": ("redirect",),
    "expert": ("expert", "opinion", "qualified", "methodology", "daubert", "702"),
    "sidebar": ("sidebar", "approach the bench", "may we approach"),
    "exhibit": ("exhibit", "marked", "publish", "identification"),
    "contradiction": ("contradict", "inconsistent", "different", "earlier", "prior"),
    "contradict": ("contradict", "inconsistent", "prior", "earlier"),
    "credibility": ("credibility", "believe", "truthful", "lied", "lie"),
    "demeanor": ("demeanor",),
    "verdict": ("verdict", "jury finds"),
    "strike": ("strike", "stricken", "disregard"),
    "oath": ("oath", "swear", "affirm", "truth"),
    "privilege": ("privilege", "privileged", "attorney client"),
    "authentication": ("authenticate", "authentication", "901", "identify"),
    "standard": ("standard", "review", "de novo", "abuse of discretion"),
}


@dataclass
class Word:
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    match: bool = False


@dataclass
class Highlight:
    """A precise, playable, highlightable region of testimony."""
    start: float
    end: float
    quote: str
    words: List[Word] = field(default_factory=list)
    speakers: List[str] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)
    score: float = 0.0
    core_hits: int = 0  # matches on the user's own words, not expansions


@dataclass
class QuerySpec:
    """A query split into the words the user typed and their courtroom expansions."""
    core: Set[str] = field(default_factory=set)
    expanded: Set[str] = field(default_factory=set)

    @property
    def all_terms(self) -> Set[str]:
        return self.core | self.expanded


def _norm(token: str) -> str:
    token = re.sub(r"[^a-z0-9]", "", token.lower())
    for suffix in ("ing", "ed", "es", "s"):
        if len(token) > 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _useful(token: str) -> bool:
    return len(token) > 2 and token not in STOPWORDS


def analyze_query(query: str) -> QuerySpec:
    """Split a query into the user's own content words and courtroom expansions."""
    spec = QuerySpec()
    for token in re.split(r"\W+", query.lower()):
        normed = _norm(token)
        if not normed or normed in STOPWORDS or len(normed) < 3:
            continue
        spec.core.add(normed)
        for phrase in LEGAL_SYNONYMS.get(normed, ()):  # legal vocabulary bridge
            for part in phrase.split():
                expanded = _norm(part)
                # never let a phrase like "out of court" leak "of" into matching
                if _useful(expanded) and expanded not in spec.core:
                    spec.expanded.add(expanded)
    return spec


def query_terms(query: str) -> Set[str]:
    """Back-compat helper: every term a query should match on."""
    return analyze_query(query).all_terms


def _sentence_score(text: str, spec: QuerySpec) -> float:
    """Score a sentence, weighting the user's own words above expansions."""
    tokens = [_norm(t) for t in re.split(r"\W+", text) if t]
    if not tokens:
        return 0.0
    core_hits = sum(1 for t in tokens if t in spec.core)
    exp_hits = sum(1 for t in tokens if t in spec.expanded)
    distinct_core = len({t for t in tokens if t in spec.core})
    distinct_exp = len({t for t in tokens if t in spec.expanded})
    weighted = (distinct_core * 4 + core_hits * 2) + (distinct_exp * 1.5 + exp_hits * 0.5)
    return weighted / (1 + len(tokens) ** 0.5)


def _video(video_id: str):
    session = get_session(video_id)
    conn = get_connection()
    coll = conn.get_collection(session.collection_id) if session else conn.get_collection()
    return coll.get_video(video_id), session


def fetch_sentences(video_id: str, start: float, end: float) -> List[dict]:
    video, _ = _video(video_id)
    try:
        return video.get_transcript(start=start, end=end, segmenter=Segmenter.sentence)
    except Exception:
        return []


def fetch_words(video_id: str, start: float, end: float) -> List[Word]:
    video, _ = _video(video_id)
    try:
        raw = video.get_transcript(start=start, end=end, segmenter=Segmenter.word)
    except Exception:
        return []
    return [
        Word(start=float(w["start"]), end=float(w["end"]), text=w.get("text", ""),
             speaker=w.get("speaker"))
        for w in raw
        if (w.get("text") or "").strip() not in ("", "-")
    ]


def refine(
    video_id: str,
    start: float,
    end: float,
    query: str,
    max_seconds: float = 40.0,
    context_sentences: int = 1,
) -> Optional[Highlight]:
    """Narrow a shot window to the best-matching run of sentences."""
    spec = analyze_query(query)
    terms = spec.all_terms
    sentences = fetch_sentences(video_id, start, end)
    if not sentences:
        return None

    scored = [(_sentence_score(s.get("text", ""), spec), i) for i, s in enumerate(sentences)]
    best_score, best_i = max(scored, key=lambda pair: pair[0])
    if best_score <= 0:
        best_i = 0  # nothing lexically matched; keep the opening of the shot

    lo = max(0, best_i - context_sentences)
    hi = min(len(sentences) - 1, best_i + context_sentences)
    # grow while the run stays inside the clip budget and keeps adding matches
    while hi + 1 < len(sentences) and float(sentences[hi + 1]["end"]) - float(sentences[lo]["start"]) <= max_seconds:
        if scored[hi + 1][0] <= 0 and hi >= best_i + context_sentences:
            break
        hi += 1

    span_start = float(sentences[lo]["start"])
    span_end = min(float(sentences[hi]["end"]), span_start + max_seconds)
    quote = " ".join((sentences[i].get("text") or "").strip() for i in range(lo, hi + 1))

    words = fetch_words(video_id, span_start, span_end)
    matched: List[str] = []
    core_hits = 0
    for word in words:
        normed = _norm(word.text)
        if normed in terms:
            word.match = True
            matched.append(re.sub(r"[^\w'-]", "", word.text))
            if normed in spec.core:
                core_hits += 1

    return Highlight(
        start=span_start,
        end=span_end,
        quote=quote.strip(),
        words=words,
        speakers=sorted({w.speaker for w in words if w.speaker}),
        matched_terms=sorted({m.lower() for m in matched if m}),
        score=round(best_score, 3),
        core_hits=core_hits,
    )


def refine_many(
    moments: Iterable,
    query: str,
    max_seconds: float = 40.0,
    drop_unmatched: bool = True,
) -> List:
    """Tighten and highlight each moment, then re-rank by what actually matched.

    VideoDB's semantic score alone puts topically-adjacent-but-wrong moments on
    top (a judge adjourning for the day scores well on "objection hearsay
    sustained"). Ranking on the user's own words, verified in the transcript,
    is what makes results defensible.
    """
    refined = []
    for moment in moments:
        highlight = refine(moment.video_id, moment.start, moment.end, query, max_seconds)
        if highlight:
            moment.start, moment.end = highlight.start, highlight.end
            moment.text = highlight.quote or moment.text
            moment.attrs["highlight"] = {
                "quote": highlight.quote,
                "matched_terms": highlight.matched_terms,
                "speakers": highlight.speakers,
                "words": [
                    {"start": w.start, "end": w.end, "text": w.text,
                     "speaker": w.speaker, "match": w.match}
                    for w in highlight.words
                ],
            }
            moment.attrs["precision_score"] = highlight.score
            moment.attrs["core_hits"] = highlight.core_hits
        refined.append(moment)

    # If any moment contains the words the user actually typed, the ones that
    # don't are noise — keep them only when nothing matched at all.
    matched = [m for m in refined if m.attrs.get("core_hits", 0) > 0]
    ranked = matched if (drop_unmatched and matched) else refined
    ranked.sort(
        key=lambda m: (
            m.attrs.get("core_hits", 0),
            m.attrs.get("precision_score", 0.0),
            m.score or 0.0,
        ),
        reverse=True,
    )
    return ranked
