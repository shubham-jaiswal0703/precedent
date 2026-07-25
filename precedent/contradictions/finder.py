"""Contradiction finder — the signature feature.

Given one witness across two sessions (deposition vs trial, or day N vs M):
  1. extract factual claims from session A's transcript (LLM),
  2. for each claim, semantic-search session B for the same topic (VideoDB
     does the temporal alignment),
  3. judge claim-vs-candidate pairs (LLM): consistent | contradictory | evolved,
  4. emit side-by-side playable clip pairs.

The LLM calls go through VideoDB's own `collection.generate_text()` so the
whole pipeline stays on one API key. Swappable later.
"""
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from videodb import IndexType, SearchType

from ..catalog import get_session
from ..config import get_connection
from ..indexing.indexer import get_transcript
from ..search.engine import PlayableMoment, _to_moment, clip_url

CLAIM_PROMPT = """You are analyzing sworn witness testimony. Extract the witness's distinct FACTUAL claims from this transcript excerpt (things asserted as fact: dates, events, amounts, who did what). Ignore attorney questions, procedural talk, and opinions.

Return STRICT JSON: a list of objects {{"claim": "<one-sentence factual claim>", "quote": "<short verbatim supporting quote>"}}. Max {max_claims} claims. Transcript:

{transcript}"""

JUDGE_PROMPT = """You are comparing two pieces of sworn testimony from the SAME witness for a law-school teaching tool.

Statement A ({label_a}): "{text_a}"
Statement B ({label_b}): "{text_b}"

Do these statements conflict? Answer STRICT JSON:
{{"verdict": "contradictory" | "consistent" | "evolved" | "unrelated", "reasoning": "<one sentence>"}}
"contradictory" = they cannot both be true. "evolved" = same topic, materially changed emphasis/details. "unrelated" = not about the same fact."""


@dataclass
class Claim:
    claim: str
    quote: str
    start: float
    end: float


@dataclass
class Contradiction:
    witness: str
    verdict: str
    reasoning: str
    moment_a: PlayableMoment
    moment_b: PlayableMoment
    clip_a: str = ""
    clip_b: str = ""


def _llm(prompt: str) -> str:
    conn = get_connection()
    coll = conn.get_collection()
    return str(coll.generate_text(prompt=prompt, response_type="text"))


def _parse_json(raw: str):
    match = re.search(r"\[.*\]|\{.*\}", raw, re.DOTALL)
    return json.loads(match.group(0)) if match else None


def extract_claims(video_id: str, window_seconds: float = 300.0, max_claims: int = 5) -> List[Claim]:
    """Chunk the transcript into windows and extract claims per window."""
    segments = get_transcript(video_id)
    claims: List[Claim] = []
    window: List[dict] = []
    w_start = 0.0
    for seg in segments + [None]:
        flush = seg is None or (window and float(seg["start"]) - w_start > window_seconds)
        if flush and window:
            text = " ".join(s["text"] for s in window if s.get("text"))
            w_end = float(window[-1]["end"])
            raw = _llm(CLAIM_PROMPT.format(transcript=text[:8000], max_claims=max_claims))
            parsed = _parse_json(raw) or []
            for item in parsed:
                if isinstance(item, dict) and item.get("claim"):
                    claims.append(Claim(item["claim"], item.get("quote", ""), w_start, w_end))
            window = []
        if seg is not None:
            if not window:
                w_start = float(seg["start"])
            window.append(seg)
    return claims


def find_contradictions(
    video_a: str,
    video_b: str,
    witness: str,
    max_pairs: int = 10,
    make_clips: bool = True,
) -> List[Contradiction]:
    conn = get_connection()
    session_b = get_session(video_b)
    coll = conn.get_collection(session_b.collection_id)
    vid_b = coll.get_video(video_b)
    label_a = (get_session(video_a) or session_b).title
    label_b = session_b.title

    results: List[Contradiction] = []
    for claim in extract_claims(video_a):
        search = vid_b.search(
            query=claim.claim,
            search_type=SearchType.semantic,
            index_type=IndexType.spoken_word,
            result_threshold=2,
        )
        for shot in search.get_shots():
            verdict_raw = _llm(
                JUDGE_PROMPT.format(
                    label_a=label_a, text_a=f"{claim.claim} — quote: {claim.quote}",
                    label_b=label_b, text_b=shot.text or "",
                )
            )
            parsed = _parse_json(verdict_raw) or {}
            if parsed.get("verdict") not in ("contradictory", "evolved"):
                continue
            moment_a = PlayableMoment(
                video_id=video_a, start=claim.start, end=claim.end,
                text=claim.quote or claim.claim, session_title=label_a,
            )
            moment_b = _to_moment(shot)
            contradiction = Contradiction(
                witness=witness,
                verdict=parsed["verdict"],
                reasoning=parsed.get("reasoning", ""),
                moment_a=moment_a,
                moment_b=moment_b,
            )
            if make_clips:
                contradiction.clip_a = clip_url(video_a, moment_a.start, min(moment_a.end, moment_a.start + 60))
                contradiction.clip_b = clip_url(video_b, moment_b.start, moment_b.end)
            results.append(contradiction)
            if len(results) >= max_pairs:
                return results
    return results
