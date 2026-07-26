"""Ask the archive a question, get playable moments.

Usage:
    .venv/bin/python scripts/ask.py "objection hearsay" --case depp-v-heard
    .venv/bin/python scripts/ask.py "objection" --case depp-v-heard --mode keyword
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from precedent.search import engine


def fmt_ts(s: float) -> str:
    return f"{int(s)//3600:01d}:{int(s)%3600//60:02d}:{int(s)%60:02d}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--case", default="depp-v-heard")
    p.add_argument("--mode", default="semantic", choices=["semantic", "keyword", "scene"])
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--clip", action="store_true", help="generate a playable clip URL for the top hit")
    args = p.parse_args()

    if args.mode == "semantic":
        moments = engine.semantic_search(args.case, args.query, limit=args.limit)
    elif args.mode == "keyword":
        moments = engine.keyword_search(args.case, args.query)
    else:
        moments = engine.scene_search(args.case, args.query, limit=args.limit)

    if not moments:
        print("No moments found.")
        return

    for i, m in enumerate(moments[: args.limit], 1):
        score = f" score={m.score:.2f}" if m.score is not None else ""
        print(f"{i}. [{fmt_ts(m.start)}, {fmt_ts(m.end)}] {m.session_title}{score}")
        print(f"   {m.text[:220]}")

    if args.clip:
        top = moments[0]
        print("\nTop-hit clip:", engine.clip_url(top.video_id, top.start, top.end))


if __name__ == "__main__":
    main()
