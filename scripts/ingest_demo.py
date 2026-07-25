"""Ingest + index a demo segment end-to-end.

Usage:
    .venv/bin/python scripts/ingest_demo.py <youtube_url> --title "..." \
        --case depp-v-heard --case-name "Depp v. Heard (2022)" \
        --type trial_day --witnesses "Amber Heard"
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from precedent.indexing.indexer import index_spoken
from precedent.ingest.pipeline import ingest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--title", required=True)
    p.add_argument("--case", default="depp-v-heard")
    p.add_argument("--case-name", default="Depp v. Heard (2022)")
    p.add_argument("--type", default="trial_day", choices=["trial_day", "deposition", "hearing"])
    p.add_argument("--date", default="")
    p.add_argument("--day", type=int, default=None)
    p.add_argument("--witnesses", default="", help="comma-separated")
    p.add_argument("--skip-index", action="store_true")
    args = p.parse_args()

    witnesses = [w.strip() for w in args.witnesses.split(",") if w.strip()]

    t0 = time.time()
    print(f"Uploading: {args.url}")
    entry = ingest(
        case_id=args.case,
        case_name=args.case_name,
        title=args.title,
        session_type=args.type,
        url=args.url,
        date=args.date,
        day_number=args.day,
        witnesses=witnesses,
    )
    print(f"Uploaded video_id={entry.video_id} ({time.time()-t0:.0f}s), duration={entry.duration}")

    if not args.skip_index:
        print("Indexing spoken words (blocking)...")
        index_spoken(entry.video_id)
        print(f"Spoken index done ({time.time()-t0:.0f}s total)")

    print("Done.")


if __name__ == "__main__":
    main()
