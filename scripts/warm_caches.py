"""Precompute the expensive parts of the library so the UI never waits.

Moment extraction costs a transcript fetch per session and cover art costs a
few thumbnail generations, so the first request to /api/gallery after an ingest
can take minutes. Run this after any ingest, and before a demo.

    .venv/bin/python scripts/warm_caches.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from precedent.catalog import _load, sessions_for_case
from precedent.media import session_thumbnail
from precedent.moments.extractor import cached_moments


def main() -> None:
    t0 = time.time()
    cases = _load()["cases"]
    for case_id, case in cases.items():
        sessions = sessions_for_case(case_id)
        print(f"{case['name'][:52]:54s} {len(sessions)} sessions")
        for session in sessions:
            try:
                moments = cached_moments(session.video_id)
            except Exception as exc:
                print(f"   moments failed  {session.title[:40]:42s} {type(exc).__name__}")
                continue
            thumb = ""
            try:
                thumb = session_thumbnail(session.video_id)
            except Exception:
                pass
            print(f"   {len(moments):4d} moments  {'cover' if thumb else 'audio'}  "
                  f"{session.title[:46]}  ({time.time()-t0:.0f}s)")
    from precedent.moments.reactions import scenes, video_ids_with_reactions

    for vid in video_ids_with_reactions():
        try:
            print(f"reactions {vid[:22]}... {len(scenes(vid, refresh=True))} scene notes")
        except Exception as exc:
            print(f"reactions {vid[:22]}... failed: {type(exc).__name__}")

    from precedent.playbooks import PLAYBOOKS, build

    for book in PLAYBOOKS:
        try:
            result = build(book.id, per_step=5)
            clips = sum(1 for s in result["steps"] for m in s["moments"] if m["stream_url"])
            print(f"playbook {book.id[:36]:38s} {clips} clips ready  ({time.time()-t0:.0f}s)")
        except Exception as exc:
            print(f"playbook {book.id[:36]:38s} failed: {type(exc).__name__}")

    print(f"\nwarmed in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
