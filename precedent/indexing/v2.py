"""Search V2: the index that unlocks grounded ask() and server-side counts.

Everything else in this codebase talks to the legacy search surface, which works
but has three costs. It cannot answer `ask()`, so our grounded answers are
retrieve-then-generate with our own citation discipline. It cannot
`aggregate()`, so the objection counts on every gallery card are recomputed
locally. And it warns on every call.

The migration is per session and additive: build a V2 index alongside the legacy
one, and prefer it where it exists.

One trap worth stating loudly, because it is silent: passing any legacy keyword
(`index_id`, `search_type`, `result_threshold`) to a V2 search call downgrades
the whole call back to `legacy_search()` without complaint. V2 calls here pass
V2 arguments only.
"""
from typing import List, Optional

from .. import store
from ..catalog import get_session
from ..config import get_connection

INDEX_NAME = "precedent_v2"        # raw transcript, for ask()
# The version suffix is load bearing. An index name is scoped to the collection
# and pinned to the exact field set of the first video indexed under it; a later
# video with one field fewer is rejected with "already exists in this collection
# with a different scene structure". So changing MOMENT_FIELDS means bumping this
# name, not editing in place.
MOMENTS_INDEX = "precedent_moments_v2"  # our own taxonomy, for filter and aggregate
STATE_DOC = "v2_indexes"  # video_id -> {"index_id", "state"}
MOMENTS_DOC = "v2_moment_indexes"

# The fields a moment record carries, split by what the server should be able to
# do with each. Only names declared here are filterable or aggregatable; an
# undeclared field fails with "field is not aggregatable on index", which is the
# error that made this mapping necessary in the first place.
MOMENT_FIELDS = {
    "semantic": ["text"],
    # Speaker role is deliberately absent: it is resolved at query time by
    # moments/attribution.py, not stored on the extracted moment, so declaring it
    # here would index a field that is always empty.
    "filter": ["moment_type", "ground", "ruling", "case_id"],
    "aggregate": ["moment_type", "ground", "ruling"],
    "sort": ["start"],
}


def _video(video_id: str):
    session = get_session(video_id)
    conn = get_connection()
    coll = conn.get_collection(session.collection_id) if session else conn.get_collection()
    return coll.get_video(video_id)


def state() -> dict:
    return store.read(STATE_DOC, {}) or {}


def index_id_for(video_id: str) -> Optional[str]:
    entry = state().get(video_id) or {}
    return entry.get("index_id")


def build(video_id: str, wait: bool = True) -> dict:
    """Understand, then index for semantic search, filtering and aggregation.

    Records are queryable while the index is still building; only semantic
    search needs it ready, so this returns as soon as there is an index id.
    """
    existing = state()
    if video_id in existing and existing[video_id].get("index_id"):
        return existing[video_id]

    video = _video(video_id)
    # The key is `type`, not `name`. `name` is optional and only needed when a
    # second analyzer references this one through `inputs`.
    understanding = video.understand(analyzers=[{"type": "spoken_words"}])
    if wait and hasattr(understanding, "wait_until_complete"):
        understanding.wait_until_complete()

    # index() wants an *analyzer*, not the Understanding container that holds
    # them; the container has no to_index_source().
    analyzers = list(getattr(understanding, "analyzers", None) or [])
    if not analyzers:
        raise RuntimeError(f"understanding for {video_id} produced no analyzers")

    index = video.index(
        source=analyzers[0],
        name=INDEX_NAME,
        use_for=["semantic", "query"],
    )
    entry = {
        "index_id": getattr(index, "index_id", None) or getattr(index, "id", None),
        "state": getattr(index, "status", "building"),
    }
    existing[video_id] = entry
    store.write(STATE_DOC, existing)
    return entry


def _records(video_id: str) -> List[dict]:
    """Our extracted moments as V2 temporal records.

    Indexing our own taxonomy rather than the raw transcript is the point. The
    transcript index answers open questions; this one answers "how many hearsay
    objections did this judge sustain", server side, with no local scan.
    """
    from ..catalog import get_session as _session
    from ..moments.extractor import cached_moments

    session = _session(video_id)
    records = []
    for moment in cached_moments(video_id):
        attrs = moment.attrs or {}
        records.append({
            "start": float(moment.start),
            "end": float(moment.end),
            "text": (moment.text or "")[:2000],
            "moment_type": moment.moment_type or "",
            "ground": str(attrs.get("ground") or ""),
            "ruling": str(attrs.get("ruling") or ""),
            "case_id": (session.case_id if session else ""),
        })
    return records


def build_moments(video_id: str, refresh: bool = False) -> dict:
    """Push this session's moments up as their own queryable index."""
    existing = store.read(MOMENTS_DOC, {}) or {}
    if not refresh and (existing.get(video_id) or {}).get("index_id"):
        return existing[video_id]

    records = _records(video_id)
    if not records:
        return {"index_id": None, "records": 0, "state": "no moments"}

    index = _video(video_id).index(
        source={"scenes": records},
        name=MOMENTS_INDEX,
        use_for=["semantic", "query", "aggregate"],
        fields=MOMENT_FIELDS,
    )
    entry = {
        "index_id": getattr(index, "index_id", None) or getattr(index, "id", None),
        "records": len(records),
        "state": getattr(index, "status", "building"),
    }
    existing[video_id] = entry
    store.write(MOMENTS_DOC, existing)
    return entry


def counts(video_id: str, group_by: str = "moment_type") -> Optional[dict]:
    """Server-side counts for one session, or None if it has no moment index."""
    if not (store.read(MOMENTS_DOC, {}) or {}).get(video_id, {}).get("index_id"):
        return None
    try:
        result = _video(video_id).aggregate(
            index_name=MOMENTS_INDEX, group_by=group_by, metric="count", limit=60)
    except Exception as exc:
        print(f"[v2] aggregate failed for {video_id}: {str(exc)[:160]}")
        return None
    rows = result if isinstance(result, list) else (result or {}).get("results", [])
    out = {}
    for row in rows or []:
        label = str(row.get(group_by) or row.get("key") or "").strip()
        if label:
            out[label] = int(row.get("count") or row.get("value") or 0)
    return out or None


def ask(video_id: str, question: str, top_k: int = 12) -> Optional[dict]:
    """VideoDB's own grounded answer, with its own sources.

    Returns None when this session has no V2 index, so callers fall back to our
    retrieve-then-generate path rather than failing.

    Worth knowing before trusting the citations: the spoken_words analyzer
    segments this footage very coarsely, so a returned source can span ten
    minutes. That is useful as corroboration and useless as a clip, which is why
    this supplements our own moment windows instead of replacing them. It also
    declines the premise of a loaded question rather than playing along, which is
    the behaviour we want here.
    """
    if not index_id_for(video_id):
        return None
    try:
        response = _video(video_id).ask(question, top_k=top_k, include_sources=True)
    except Exception as exc:
        print(f"[v2] ask failed for {video_id}: {str(exc)[:160]}")
        return None

    answer = getattr(response, "answer", None) or getattr(response, "output", None) or ""
    sources = []
    for source in (getattr(response, "sources", None) or []):
        sources.append({
            "start": float(getattr(source, "start", 0) or 0),
            "end": float(getattr(source, "end", 0) or 0),
            "text": str(getattr(source, "text", "") or "")[:400],
        })
    if not str(answer).strip():
        return None
    return {"answer": str(answer), "sources": sources, "video_id": video_id}


def build_for_case(case_id: str, limit: int = 2) -> List[dict]:
    """Index a few sessions of a case. Giving every session the same index name
    is how V2 groups them, since there is no collection-level index() call."""
    from ..catalog import sessions_for_case

    built = []
    for session in sessions_for_case(case_id)[:limit]:
        try:
            built.append({"video_id": session.video_id, **build(session.video_id)})
        except Exception as exc:
            built.append({"video_id": session.video_id, "error": str(exc)[:200]})
    return built
