"""Build a teaching reel from legal moments across the whole case archive.

Usage:
    .venv/bin/python scripts/build_reel.py --case depp-v-heard --type objection
    .venv/bin/python scripts/build_reel.py --case depp-v-heard --query "cross-examination about the op-ed"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from precedent.catalog import sessions_for_case
from precedent.moments.extractor import extract_moments
from precedent.reels.builder import build_reel
from precedent.search.engine import PlayableMoment, semantic_search


def moments_by_type(case_id: str, moment_type: str, limit: int):
    collected = []
    for session in sessions_for_case(case_id):
        for m in extract_moments(session.video_id):
            if m.moment_type != moment_type:
                continue
            collected.append(
                PlayableMoment(
                    video_id=m.video_id,
                    start=m.start,
                    end=m.end,
                    text=m.text,
                    session_title=session.title,
                    session_type=session.session_type,
                    attrs={"label": f"{moment_type.replace('_', ' ').title()} — {session.title}", **m.attrs},
                )
            )
    return collected[:limit]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--case", default="depp-v-heard")
    p.add_argument("--type", default=None, help="moment type, e.g. objection")
    p.add_argument("--query", default=None, help="semantic query instead of moment type")
    p.add_argument("--limit", type=int, default=8)
    args = p.parse_args()

    if args.query:
        moments = semantic_search(args.case, args.query, limit=args.limit)
        for m in moments:
            m.attrs["label"] = m.session_title
    elif args.type:
        moments = moments_by_type(args.case, args.type, args.limit)
    else:
        p.error("pass --type or --query")

    print(f"Compiling {len(moments)} moments into a reel...")
    for m in moments:
        print(f"  [{m.start:7.1f}s] {m.session_title}: {m.text[:80]}")
    url = build_reel(moments)
    print("\nReel stream URL:", url)


if __name__ == "__main__":
    main()
