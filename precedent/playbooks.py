"""Playbooks: the library organised around what a student has to do tomorrow.

A search box assumes you already know what to look for. A 2L on a trial team
does not think "impeachment_prior_statement", they think "I have to cross a
witness who changed her story and I have never done it before".

So each playbook names a task, states what good looks like in the vocabulary the
course uses, and then proves each step with real moments from the record. The
teaching notes are written here rather than generated, because the craft is
settled and attributed: Younger's commandments, the commit-credit-confront
sequence, Mauet on foundations. The clips are the evidence.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .catalog import _load as load_catalog, sessions_for_case
from .moments.extractor import cached_moments
from .search.engine import PlayableMoment
from .search.router import _moment_to_playable


@dataclass
class Step:
    """One move in a technique, with the moment types that demonstrate it."""
    title: str
    note: str
    moment_types: List[str] = field(default_factory=list)
    watch_for: str = ""


@dataclass
class Playbook:
    id: str
    task: str                    # what the student is about to do
    audience: str                # trial or appellate
    summary: str
    steps: List[Step]
    pitfalls: List[str] = field(default_factory=list)
    authority: str = ""


PLAYBOOKS: List[Playbook] = [
    Playbook(
        id="cross-examine-a-witness",
        task="Cross-examine a witness who changed her story",
        audience="trial",
        summary=(
            "Impeachment by prior inconsistent statement is the most tested skill in "
            "trial advocacy and the easiest to botch. The goal is not to argue with the "
            "witness. It is to make her adopt the earlier version, establish that the "
            "earlier version was reliable, and then let the jury see the contradiction "
            "without you explaining it."
        ),
        steps=[
            Step(
                title="Commit the witness to today's answer",
                note=(
                    "Ask a short, closed question that locks in the current testimony. "
                    "No preamble. If she can wriggle, you have not committed her."
                ),
                moment_types=["cross_examination_marker"],
                watch_for="Short declarative questions with a tag such as 'isn't that right?'",
            ),
            Step(
                title="Credit the prior statement",
                note=(
                    "Before you spring the inconsistency, make the earlier occasion sound "
                    "reliable: she was under oath, she had counsel, her memory was fresher. "
                    "Skip this and the witness escapes by attacking the deposition."
                ),
                moment_types=["impeachment_prior_statement"],
                watch_for="Counsel setting the scene of the deposition or earlier testimony",
            ),
            Step(
                title="Confront with the exact words",
                note=(
                    "Read the prior statement verbatim and stop. Do not ask her to explain "
                    "the difference. That is Younger's one question too many, and the "
                    "explanation belongs to your closing, not her mouth."
                ),
                moment_types=["impeachment_prior_statement"],
                watch_for="A quoted prior answer followed by silence or the next topic",
            ),
            Step(
                title="Handle the objection that follows",
                note=(
                    "Expect an objection on form or hearsay. Know that a prior inconsistent "
                    "statement offered to impeach is not hearsay, and that FRE 613 lets you "
                    "use it without showing it to the witness first."
                ),
                moment_types=["objection", "ruling_sustained", "ruling_overruled"],
                watch_for="The ground counsel states and how the court rules",
            ),
        ],
        pitfalls=[
            "Arguing with the witness instead of moving on once the contradiction lands",
            "Asking 'were you lying then or are you lying now', which invites a speech",
            "Reading a long passage when one line does the work",
        ],
        authority="FRE 613, FRE 801(d)(1)(A); Younger's Ten Commandments of Cross-Examination",
    ),
    Playbook(
        id="handle-objections",
        task="Make and meet objections without losing the jury",
        audience="trial",
        summary=(
            "An objection is a two sentence event: the ground, and nothing else. Watch how "
            "often the ground alone wins, and how the record shows which grounds the court "
            "actually sustains."
        ),
        steps=[
            Step(
                title="State the ground and stop",
                note=(
                    "'Objection, hearsay.' The court knows the rule. Argument comes only if "
                    "the judge asks for it or you need the record for appeal."
                ),
                moment_types=["objection"],
                watch_for="How few words competent counsel uses",
            ),
            Step(
                title="Learn which grounds land",
                note=(
                    "Compare sustained against overruled in the same trial. Non-responsive "
                    "and speculation tend to succeed because they are about the answer. "
                    "Relevance alone rarely does."
                ),
                moment_types=["ruling_sustained", "ruling_overruled"],
                watch_for="The ground stated, then the ruling",
            ),
            Step(
                title="Cure the damage",
                note=(
                    "Winning the objection is half the job. Ask to strike the answer and for "
                    "an instruction to disregard, or the jury keeps what it heard."
                ),
                moment_types=["motion_to_strike", "curative_instruction"],
                watch_for="Whether counsel follows a sustained objection with a motion to strike",
            ),
            Step(
                title="Take it out of the jury's hearing",
                note=(
                    "When the argument is long or prejudicial, ask to approach. A sidebar "
                    "protects the record and the jury at the same time."
                ),
                moment_types=["sidebar"],
                watch_for="The request itself, which is a small set phrase",
            ),
        ],
        pitfalls=[
            "Speaking objections that tell the jury what you do not want them to hear",
            "Forgetting to move to strike after the objection is sustained",
            "Objecting so often that the jury reads it as obstruction",
        ],
        authority="FRE 103 (preserving error), FRE 105 (limiting instructions), FRE 611",
    ),
    Playbook(
        id="answer-a-hot-bench",
        task="Argue to a bench that will not let you finish a sentence",
        audience="appellate",
        summary=(
            "At argument the questions are the argument. The advocates worth copying answer "
            "the question first, in one word if possible, then return to their own ground. "
            "The ones who suffer are the ones who defer the answer."
        ),
        steps=[
            Step(
                title="Open with the ground you must hold",
                note=(
                    "You get one or two sentences before the first question. Spend them on "
                    "the proposition the case turns on, not on procedural history."
                ),
                moment_types=["argument_opening", "case_called"],
                watch_for="What the advocate chooses to say in the opening breath",
            ),
            Step(
                title="Answer the hypothetical, then qualify",
                note=(
                    "A hypothetical is a test of whether your rule has a limit. Answer it "
                    "directly, then explain why the answer does not hurt you. Fighting the "
                    "hypothetical reads as evasion and the bench will repeat it."
                ),
                moment_types=["hypothetical_from_bench"],
                watch_for="Whether the advocate answers before explaining",
            ),
            Step(
                title="Draw the line on purpose",
                note=(
                    "When asked where your rule stops, have a line ready and say it plainly. "
                    "An advocate without a line invites the court to draw one against them."
                ),
                moment_types=["line_drawing"],
                watch_for="A stated limiting principle rather than a refusal to answer",
            ),
            Step(
                title="Concede the small point to keep the large one",
                note=(
                    "A well chosen concession buys credibility for the argument you cannot "
                    "give up. Notice what the advocate refuses to concede immediately after."
                ),
                moment_types=["concession", "refusal_to_concede"],
                watch_for="What is traded away, and what is defended",
            ),
            Step(
                title="Recover the roadmap",
                note=(
                    "After a run of questions, name where you are: 'if I may return to the "
                    "second point'. Do it before your time expires."
                ),
                moment_types=["interruption_recovery", "time_expired", "rebuttal"],
                watch_for="How the advocate reclaims the structure without talking over the court",
            ),
        ],
        pitfalls=[
            "Saying 'I will come to that' to a direct question",
            "Reading from notes while the bench is asking about the record",
            "Spending rebuttal on everything rather than the one point that moved the court",
        ],
        authority="Standard of review framing; hot bench management in appellate advocacy",
    ),
    Playbook(
        id="frame-the-standard-of-review",
        task="Win on the standard of review before you argue the merits",
        audience="appellate",
        summary=(
            "Most appeals are decided by the standard of review, and most students argue it "
            "last. De novo, abuse of discretion, and clear error each hand the case to a "
            "different party. Watch advocates fight over the frame itself."
        ),
        steps=[
            Step(
                title="Name the standard early and own it",
                note=(
                    "State the standard in the opening and tie it to what the court below "
                    "actually did. The party who defines the standard usually defines the case."
                ),
                moment_types=["standard_of_review"],
                watch_for="Whether the standard arrives before or after the merits",
            ),
            Step(
                title="Anchor every claim in the record",
                note=(
                    "Under clear error or abuse of discretion you win on the record, not on "
                    "theory. Cite the page. The bench notices who can."
                ),
                moment_types=["record_citation"],
                watch_for="Specific citations rather than characterisations",
            ),
            Step(
                title="Meet stare decisis head on",
                note=(
                    "If you need the court to depart from precedent, address reliance "
                    "interests directly. If you are defending precedent, make the cost of "
                    "overruling concrete."
                ),
                moment_types=["stare_decisis_argument", "interpretive_method"],
                watch_for="How reliance and workability are argued",
            ),
        ],
        pitfalls=[
            "Conceding the standard by arguing the facts de novo",
            "Treating jurisdiction and mootness as throwaway questions",
        ],
        authority="De novo, clear error, abuse of discretion; stare decisis factors",
    ),
    Playbook(
        id="qualify-and-attack-an-expert",
        task="Qualify your expert, and take apart theirs",
        audience="trial",
        summary=(
            "Expert testimony is won at the foundation. Qualification is a performance of "
            "competence, and cross is an attack on method rather than on the person."
        ),
        steps=[
            Step(
                title="Tender the expert",
                note=(
                    "Walk the qualifications in ascending order and tender formally. The "
                    "point is to make the jury trust the witness before any opinion lands."
                ),
                moment_types=["expert_qualification"],
                watch_for="The order in which credentials are elicited",
            ),
            Step(
                title="Lay the foundation for the opinion",
                note=(
                    "Under FRE 702 the opinion needs a reliable method reliably applied. "
                    "Establish the method before the conclusion, or invite the objection."
                ),
                moment_types=["expert_qualification", "objection"],
                watch_for="Foundation objections and how they are cured",
            ),
            Step(
                title="Cross on method, fees, and assumptions",
                note=(
                    "Do not fight the credentials. Attack what the expert was asked to "
                    "assume, what they were paid, and what they did not test."
                ),
                moment_types=["cross_examination_marker", "impeachment_prior_statement"],
                watch_for="Questions about assumptions rather than about the person",
            ),
        ],
        pitfalls=[
            "Attacking a well credentialed expert's résumé in front of a jury",
            "Eliciting the opinion before the method is in evidence",
        ],
        authority="FRE 702 and Daubert; FRE 703 on bases of opinion",
    ),
]

BY_ID: Dict[str, Playbook] = {p.id: p for p in PLAYBOOKS}


_POOL_CACHE: Dict[str, object] = {"stamp": None, "pool": None}


def _catalog_stamp() -> float:
    """Change marker for the catalog, so the pool rebuilds only after an ingest."""
    from .catalog import stamp

    return stamp()


def _pool() -> Dict[str, List[PlayableMoment]]:
    """Every indexed moment in the library, grouped by type.

    Memoized: assembling it parses every session's cached moments, which is
    fast per session and slow across forty of them.
    """
    stamp = _catalog_stamp()
    if _POOL_CACHE["stamp"] == stamp and _POOL_CACHE["pool"] is not None:
        return _POOL_CACHE["pool"]  # type: ignore[return-value]
    pool: Dict[str, List[PlayableMoment]] = {}
    for case_id in load_catalog()["cases"]:
        for session in sessions_for_case(case_id):
            try:
                moments = cached_moments(session.video_id)
            except Exception:
                continue
            for m in moments:
                playable = _moment_to_playable(m, session.title, session.session_type)
                playable.attrs["case_id"] = case_id
                pool.setdefault(m.moment_type, []).append(playable)
    _POOL_CACHE.update({"stamp": stamp, "pool": pool})
    return pool


def _rank(moments: List[PlayableMoment]) -> List[PlayableMoment]:
    """Put the most teachable moments first.

    Richer labels mean the moment carries more of the lesson: an objection whose
    ground and ruling are both known shows the whole exchange, and a clip with
    enough room to breathe beats a fragment.
    """
    def score(m: PlayableMoment) -> tuple:
        attrs = m.attrs or {}
        return (
            bool(attrs.get("ruling")),
            bool(attrs.get("ground")),
            len((m.text or "").split()) > 25,
            m.end - m.start,
        )
    return sorted(moments, key=score, reverse=True)


def build(playbook_id: str, per_step: int = 2, audience_case: Optional[str] = None,
          with_clips: bool = True) -> dict:
    """A playbook with real moments attached to every step."""
    book = BY_ID.get(playbook_id)
    if not book:
        raise ValueError(f"Unknown playbook '{playbook_id}'")
    pool = _pool()

    steps = []
    used = set()
    for step in book.steps:
        candidates: List[PlayableMoment] = []
        for moment_type in step.moment_types:
            candidates.extend(pool.get(moment_type, []))
        if audience_case:
            candidates = [m for m in candidates if m.attrs.get("case_id") == audience_case]
        picked = []
        for m in _rank(candidates):
            key = (m.video_id, round(m.start))
            if key in used:
                continue  # never show the same clip twice inside one playbook
            used.add(key)
            picked.append(m)
            if len(picked) >= per_step:
                break
        if with_clips:
            from .search.engine import clip_url

            for m in picked:
                try:
                    m.stream_url = m.stream_url or clip_url(m.video_id, m.start, m.end)
                except Exception:
                    pass
        steps.append({
            "title": step.title,
            "note": step.note,
            "watch_for": step.watch_for,
            "moment_types": step.moment_types,
            "moments": [m.__dict__ for m in picked],
            "available": len(candidates),
        })

    return {
        "id": book.id,
        "task": book.task,
        "audience": book.audience,
        "summary": book.summary,
        "authority": book.authority,
        "pitfalls": book.pitfalls,
        "steps": steps,
    }


def index() -> List[dict]:
    """Playbook cards, with how much of the library backs each one."""
    pool = _pool()
    cards = []
    for book in PLAYBOOKS:
        available = sum(len(pool.get(t, []))
                        for step in book.steps for t in step.moment_types)
        cards.append({
            "id": book.id,
            "task": book.task,
            "audience": book.audience,
            "summary": book.summary,
            "steps": len(book.steps),
            "clips": available,
            "authority": book.authority,
        })
    return cards
