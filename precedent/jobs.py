"""Ingest jobs that outlive the process that started them.

Ingesting a proceeding takes minutes: upload, then transcription. Holding that
in a FastAPI background task and an in-memory dict works on one long-lived
machine and fails everywhere else. A container restart loses the job, and a
second instance cannot see it.

So job state lives in the store, and VideoDB tells us when indexing finishes
rather than us waiting on it. Every long-running SDK call accepts a
callback_url, so we hand it a webhook and return immediately.

Set PUBLIC_BASE_URL to the deployment's own origin to enable the webhook path.
Without it there is nowhere for VideoDB to call back, so we fall back to
waiting in a background thread, which is still correct on a single instance.
"""
import hashlib
import os
import threading
import uuid
from typing import Dict, List, Optional

from . import store

JOBS = "jobs"
STATES = ("queued", "uploading", "indexing", "ready", "failed")

# Anyone can add a link and the library is public, so contributions are
# credited under a stable pseudonym rather than asking for a name.
ADJECTIVES = ("Diligent", "Learned", "Careful", "Patient", "Candid", "Steady",
              "Astute", "Measured", "Dogged", "Composed", "Exacting", "Quiet")
ROLES = ("Advocate", "Clerk", "Junior", "Counsel", "Scholar", "Recorder",
         "Associate", "Registrar", "Reader", "Marshal")


def pseudonym(seed: str) -> str:
    """A stable, friendly credit for whoever pasted a link."""
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return f"{ADJECTIVES[digest % len(ADJECTIVES)]} {ROLES[(digest // 97) % len(ROLES)]}"


def _all() -> Dict[str, dict]:
    return store.read(JOBS, {}) or {}


def _put(job_id: str, patch: dict) -> dict:
    jobs = _all()
    job = jobs.get(job_id, {"id": job_id})
    job.update(patch)
    jobs[job_id] = job
    # Keep the log bounded; a demo does not need every job ever run.
    if len(jobs) > 200:
        for stale in sorted(jobs, key=lambda k: jobs[k].get("updated", 0))[:50]:
            jobs.pop(stale, None)
    store.write(JOBS, jobs)
    return job


def get(job_id: str) -> Optional[dict]:
    return _all().get(job_id)


def recent(limit: int = 20) -> List[dict]:
    jobs = list(_all().values())
    jobs.sort(key=lambda j: j.get("updated", 0), reverse=True)
    return jobs[:limit]


def contributions(limit: int = 40) -> List[dict]:
    """Links people have added, as a public shelf.

    Every proceeding here is public record and the library is shared, so a
    contributed link is shown to everyone, credited to a pseudonym.
    """
    from .catalog import get_session

    out: List[dict] = []
    for job in recent(200):
        if job.get("state") not in ("ready", "indexing", "uploading", "queued", "failed"):
            continue
        session = get_session(job.get("video_id", "")) if job.get("video_id") else None
        out.append({
            "job_id": job.get("id"),
            "contributor": job.get("contributor") or "Anonymous",
            "url": job.get("url"),
            "title": (session.title if session else job.get("title")) or "Untitled",
            "state": job.get("state"),
            "case_id": job.get("case_id"),
            "video_id": job.get("video_id"),
            "duration": job.get("duration") or (session.duration if session else None),
            "added": job.get("updated"),
            "error": job.get("error"),
        })
        if len(out) >= limit:
            break
    return out


def webhook_base() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def start(url: str, title: str, case_id: str, case_name: str, session_type: str = "trial_day",
          contributor_seed: str = "") -> dict:
    """Begin an ingest. Returns immediately with a job to poll."""
    job_id = uuid.uuid4().hex[:12]
    _put(job_id, {"state": "queued", "url": url, "title": title, "case_id": case_id,
                  "contributor": pseudonym(contributor_seed or job_id),
                  "updated": _now()})
    threading.Thread(target=_run, args=(job_id, url, title, case_id, case_name, session_type),
                     daemon=True).start()
    return get(job_id) or {"id": job_id, "state": "queued"}


def _now() -> float:
    import time

    return time.time()


def _run(job_id: str, url: str, title: str, case_id: str, case_name: str, session_type: str) -> None:
    """Upload, then either register a webhook or wait, depending on config."""
    from .indexing.indexer import index_spoken
    from .ingest.pipeline import ingest

    try:
        _put(job_id, {"state": "uploading", "updated": _now()})
        entry = ingest(case_id=case_id, case_name=case_name, title=title,
                       session_type=session_type, url=url)
        _put(job_id, {"state": "indexing", "video_id": entry.video_id,
                      "duration": entry.duration, "updated": _now()})

        base = webhook_base()
        if base:
            # VideoDB calls us back, so nothing here has to stay alive.
            from .config import get_connection

            conn = get_connection()
            coll = conn.get_collection(entry.collection_id)
            video = coll.get_video(entry.video_id)
            video.index_spoken_words(callback_url=f"{base}/api/webhooks/videodb?job={job_id}")
            return

        index_spoken(entry.video_id)  # single instance fallback: wait it out
        finish(job_id)
    except Exception as exc:
        _put(job_id, {"state": "failed", "error": str(exc)[:400], "updated": _now()})


def finish(job_id: str, ok: bool = True, error: str = "") -> Optional[dict]:
    """Mark a job done and warm what the UI will immediately ask for."""
    if not ok:
        return _put(job_id, {"state": "failed", "error": error[:400], "updated": _now()})
    job = _put(job_id, {"state": "ready", "updated": _now()})
    video_id = job.get("video_id")
    if video_id:
        threading.Thread(target=_warm, args=(video_id,), daemon=True).start()
    return job


def _warm(video_id: str) -> None:
    """A freshly indexed session should be searchable and browsable at once."""
    try:
        from .media import session_thumbnail
        from .moments.extractor import cached_moments

        cached_moments(video_id)
        session_thumbnail(video_id)
    except Exception:
        pass
