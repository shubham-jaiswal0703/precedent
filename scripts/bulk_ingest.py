"""Build the corpus in bulk.

    # 8 most-studied arguments from each of three terms
    .venv/bin/python scripts/bulk_ingest.py oyez --terms 2022,2021,2020 --per-term 8

    # recent federal appellate arguments
    .venv/bin/python scripts/bulk_ingest.py courtlistener --limit 10

Transcription costs ~$0.01/min, so 20 hours of audio is roughly $12. Use
--dry-run to see what would be ingested and the estimated cost first.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from precedent.ingest import batch


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("source", choices=["oyez", "courtlistener"])
    p.add_argument("--terms", default="2022", help="comma-separated Oyez terms")
    p.add_argument("--per-term", type=int, default=8)
    p.add_argument("--limit", type=int, default=10, help="CourtListener recordings")
    p.add_argument("--court", default=None, help="CourtListener court id, e.g. ca9")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--no-index", action="store_true", help="upload only, skip transcription")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    t0 = time.time()
    done = {"ok": 0, "failed": 0, "seconds": 0.0}

    def report(r: batch.BatchResult) -> None:
        if r.ok:
            done["ok"] += 1
            done["seconds"] += r.duration or 0
            print(f"  ok   {r.label[:62]:64s} {(r.duration or 0)/60:6.1f} min  ({time.time()-t0:.0f}s)")
        else:
            done["failed"] += 1
            print(f"  skip {r.label[:62]:64s} {r.error}")

    if args.source == "oyez":
        terms = [t.strip() for t in args.terms.split(",") if t.strip()]
        if args.dry_run:
            for term in terms:
                cases = batch.term_cases(term)[: args.per_term]
                print(f"term {term}: {len(cases)} candidates")
                for c in cases:
                    print(f"   {c.get('docket_number'):12s} {(c.get('name') or '')[:70]}")
            return
        print(f"Ingesting up to {args.per_term} arguments/term for terms: {', '.join(terms)}")
        batch.ingest_terms(terms, per_term=args.per_term, workers=args.workers,
                           index=not args.no_index, on_result=report)
    else:
        if args.dry_run:
            for r in batch.courtlistener_recordings(args.limit, args.court):
                print(f"   {(r.get('duration') or 0)/60:6.1f} min  {(r.get('case_name') or '')[:70]}")
            return
        print(f"Ingesting {args.limit} CourtListener recordings"
              + (f" from {args.court}" if args.court else ""))
        batch.ingest_courtlistener(limit=args.limit, court=args.court, workers=args.workers,
                                  index=not args.no_index, on_result=report)

    hours = done["seconds"] / 3600
    print(f"\n{done['ok']} ingested, {done['failed']} skipped, {hours:.1f} h of audio "
          f"(~${done['seconds']/60*0.01:.2f} transcription) in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
