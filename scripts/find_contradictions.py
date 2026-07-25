"""Precompute contradictions for a witness pair and cache for the API/UI.

Usage:
    .venv/bin/python scripts/find_contradictions.py --case depp-v-heard \
        --witness "Amber Heard" --video-a <id> --video-b <id>

Without --video-a/--video-b, picks the first two catalog sessions listing the
witness (ordered by day number).
"""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from precedent.catalog import sessions_for_witness
from precedent.config import DATA_DIR
from precedent.contradictions.finder import find_contradictions


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--case", default="depp-v-heard")
    p.add_argument("--witness", required=True)
    p.add_argument("--video-a", default=None)
    p.add_argument("--video-b", default=None)
    p.add_argument("--max-pairs", type=int, default=6)
    args = p.parse_args()

    video_a, video_b = args.video_a, args.video_b
    if not (video_a and video_b):
        sessions = sorted(
            sessions_for_witness(args.case, args.witness),
            key=lambda s: (s.day_number or 0),
        )
        if len(sessions) < 2:
            sys.exit(f"Need 2 sessions with witness '{args.witness}'; found {len(sessions)}")
        video_a, video_b = sessions[0].video_id, sessions[1].video_id
        print(f"Comparing: {sessions[0].title}  vs  {sessions[1].title}")

    results = find_contradictions(video_a, video_b, witness=args.witness, max_pairs=args.max_pairs)
    print(f"{len(results)} pair(s) found")

    out_path = DATA_DIR / "contradictions" / f"{args.case}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = json.loads(out_path.read_text()) if out_path.exists() else []
    existing = [e for e in existing if e["witness"] != args.witness] + [asdict(r) for r in results]
    out_path.write_text(json.dumps(existing, indent=2))
    print(f"Cached -> {out_path}")


if __name__ == "__main__":
    main()
