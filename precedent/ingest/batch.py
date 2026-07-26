"""Bulk corpus building: turn the library from a demo into an archive.

Two bulk sources (see SOURCES.md):
  * Oyez: SCOTUS arguments with named-speaker aligned transcripts. We order a
    term by Oyez's own view_count, which is a decent proxy for "the cases law
    students actually study".
  * CourtListener: 100k+ federal/state appellate argument recordings.

Ingest is I/O-bound (upload, then wait on transcription), so we run a small
thread pool and report per-item outcomes rather than failing the whole batch.
"""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from ..catalog import SessionEntry, sessions_for_case, upsert_session
from ..indexing.indexer import index_spoken
from .oyez import API, UA, ingest_argument
from .pipeline import get_or_create_case_collection

CL_API = "https://www.courtlistener.com/api/rest/v4"


@dataclass
class BatchResult:
    label: str
    video_id: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.video_id and not self.error)


def _get(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _already_ingested(case_id: str) -> set:
    return {s.source_url for s in sessions_for_case(case_id)}


# ---------------------------------------------------------------- Oyez batch

def term_cases(term: str, per_page: int = 60) -> List[dict]:
    """Cases for a term, most-viewed first (a proxy for pedagogical weight)."""
    cases = _get(f"{API}/cases?per_page={per_page}&filter=term:{term}")
    if not isinstance(cases, list):
        return []
    return sorted(cases, key=lambda c: int(c.get("view_count") or 0), reverse=True)


def ingest_terms(
    terms: List[str],
    per_term: int = 8,
    workers: int = 3,
    case_id: str = "scotus-oral-arguments",
    case_name: str = "US Supreme Court: Oral Arguments",
    index: bool = True,
    on_result: Optional[Callable[[BatchResult], None]] = None,
) -> List[BatchResult]:
    """Ingest the most-studied arguments from each term."""
    get_or_create_case_collection(case_id, case_name)  # create once, not per thread
    targets: List[tuple] = []
    for term in terms:
        for case in term_cases(term)[: per_term * 2]:  # over-fetch: some lack audio
            docket = case.get("docket_number") or ""
            if docket and "-" in docket:
                targets.append((term, docket, case.get("name") or docket))
            if len([t for t in targets if t[0] == term]) >= per_term * 2:
                break

    results: List[BatchResult] = []
    per_term_ok: Dict[str, int] = {t: 0 for t in terms}

    def work(term: str, docket: str, name: str) -> BatchResult:
        try:
            entry = ingest_argument(term, docket, case_id=case_id, case_name=case_name)
            if not entry:
                return BatchResult(f"{name} ({term})", error="no argument audio")
            if index:
                index_spoken(entry.video_id)
            return BatchResult(f"{name} ({term})", entry.video_id, entry.duration)
        except Exception as exc:
            return BatchResult(f"{name} ({term})", error=str(exc)[:160])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for term, docket, name in targets:
            if per_term_ok[term] >= per_term:
                continue
            futures[pool.submit(work, term, docket, name)] = term
        for future in as_completed(futures):
            result = future.result()
            term = futures[future]
            if result.ok:
                per_term_ok[term] += 1
            results.append(result)
            if on_result:
                on_result(result)
    return results


# -------------------------------------------------------- CourtListener batch

CL_STORAGE = "https://storage.courtlistener.com"


def media_url(record: dict) -> str:
    """Best fetchable MP3 for a recording.

    Court websites (ca11.uscourts.gov and friends) refuse VideoDB's fetcher, so
    prefer CourtListener's own mirror and keep the court URL as a fallback.
    """
    local = record.get("local_path_mp3")
    if local:
        return f"{CL_STORAGE}/{local.lstrip('/')}"
    return record.get("download_url") or ""


def courtlistener_recordings(limit: int = 20, court: Optional[str] = None) -> List[dict]:
    """Recent oral-argument recordings with a usable MP3 URL."""
    url = f"{CL_API}/audio/?page_size={min(limit * 3, 100)}&order_by=-date_created"
    if court:
        url += f"&docket__court={court}"
    payload = _get(url)
    out = []
    for r in payload.get("results", []):
        if media_url(r).lower().endswith(".mp3") and (r.get("duration") or 0) > 300:
            out.append(r)
        if len(out) >= limit:
            break
    return out


def ingest_courtlistener(
    limit: int = 10,
    court: Optional[str] = None,
    case_id: str = "federal-appellate",
    case_name: str = "Federal Appellate: Oral Arguments",
    workers: int = 3,
    index: bool = True,
    on_result: Optional[Callable[[BatchResult], None]] = None,
) -> List[BatchResult]:
    coll = get_or_create_case_collection(case_id, case_name)
    seen = _already_ingested(case_id)
    records = [r for r in courtlistener_recordings(limit * 2, court) if media_url(r) not in seen][:limit]

    def work(record: dict) -> BatchResult:
        name = record.get("case_name") or f"CL {record.get('id')}"
        try:
            media = coll.upload(url=media_url(record), name=name)
            # VideoDB sometimes classifies an MP3 as an Audio asset ("a-z-..."),
            # which the video search and transcript APIs will not accept.
            if not str(media.id).startswith("m-"):
                return BatchResult(name, error=f"uploaded as audio asset ({media.id}), not indexable")
            entry = SessionEntry(
                video_id=media.id,
                case_id=case_id,
                title=name,
                session_type="oral_argument",
                source_url=media_url(record),
                date=(record.get("date_created") or "")[:10],
                witnesses=[],
                collection_id=coll.id,
                duration=getattr(media, "length", None) or record.get("duration"),
            )
            upsert_session(entry)
            if index:
                index_spoken(entry.video_id)
            return BatchResult(name, entry.video_id, entry.duration)
        except Exception as exc:
            return BatchResult(name, error=str(exc)[:160])

    results: List[BatchResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(work, r) for r in records]):
            result = future.result()
            results.append(result)
            if on_result:
                on_result(result)
    return results
