"""Discussion: ask about a case and get an answer built only from the record.

VideoDB's own ask() needs a Search V2 index, which our corpus does not have
yet, so this is retrieve-then-generate: find the relevant moments, hand their
transcripts to the model as the only permitted source, and return the moments
alongside the answer as playable citations.

The rule is strict on purpose. In a teaching tool for lawyers, an assertion
about what was said in court is worthless unless you can press play on it.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .catalog import get_session
from .config import get_connection
from .llm import LlmUnavailable
from .search.engine import PlayableMoment, clip_url
from .search.router import search as routed_search

PROMPT = """You are a trial-advocacy professor discussing a real proceeding with a student.

Answer the question using ONLY the numbered excerpts below, which are verbatim transcript from the recording. Cite the excerpts you rely on as [1], [2], and so on. If the excerpts do not answer the question, say plainly what the record does not show rather than speculating. Be concrete about advocacy technique: what counsel did, why it works or fails.

Write two or three short paragraphs. Do not use dashes as punctuation.

QUESTION: {question}

EXCERPTS:
{excerpts}
"""


@dataclass
class Discussion:
    question: str
    answer: str
    citations: List[PlayableMoment] = field(default_factory=list)
    case_id: str = ""


def _llm(prompt: str, tag: str) -> str:
    from .llm import generate

    return generate(prompt, response_type="text", tag=tag)


def _excerpt(index: int, moment: PlayableMoment) -> str:
    att = (moment.attrs or {}).get("attribution") or {}
    who = att.get("label") or ""
    speaker = f" (speaking: {who})" if who else ""
    stamp = f"{int(moment.start)//60}:{int(moment.start)%60:02d}"
    quote = (moment.attrs.get("highlight", {}).get("quote") or moment.text or "").strip()
    return f"[{index}] {moment.session_title} at {stamp}{speaker}\n{quote[:700]}"


def discuss(
    case_id: str,
    question: str,
    limit: int = 5,
    with_clips: bool = True,
) -> Discussion:
    """Answer a question about a case, grounded in playable moments."""
    routed = routed_search(case_id, question, limit=limit, with_clips=False)
    moments: List[PlayableMoment] = routed["results"][:limit]
    if not moments:
        return Discussion(question, "Nothing in this case's transcripts matches that question yet.",
                          [], case_id)

    excerpts = "\n\n".join(_excerpt(i, m) for i, m in enumerate(moments, 1))
    try:
        answer = _llm(PROMPT.format(question=question, excerpts=excerpts),
                      tag="discuss.v1").strip()
    except LlmUnavailable as exc:
        # Say what actually went wrong. A model budget failure reading as "the
        # record has nothing to say" is the worst possible error message here.
        raise
    except Exception as exc:
        answer = f"Could not generate a discussion right now ({type(exc).__name__})."

    # Keep the prose dash-free. Escapes, not literals, so a source-wide dash
    # cleanup can never rewrite this character class into "match any space".
    answer = re.sub(r"\s*[\u2014\u2013]\s*", ", ", answer)
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    if with_clips:
        for i, m in enumerate(moments, 1):
            if cited and i not in cited:
                continue  # only pay for clips the answer actually leans on
            try:
                m.stream_url = m.stream_url or clip_url(m.video_id, m.start, m.end)
            except Exception:
                pass
    return Discussion(question, answer, moments, case_id)
