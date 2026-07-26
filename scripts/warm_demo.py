"""Warm exactly the queries the live demo will run.

A speaker-filtered search fans out across every session and takes about half a
minute cold, which is fatal in a two minute slot. Every beat of the demo is
requested here once so it is served from cache on stage.

    .venv/bin/python scripts/warm_demo.py                      # local
    .venv/bin/python scripts/warm_demo.py --base https://...   # the deployed site

Run it after any deploy, because a deploy does not clear the cache but a fresh
database would start empty.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request

# Each entry is a beat of the demo, in the order it will be performed.
BEATS = [
    ("library", "/api/gallery", {}),
    ("playbooks", "/api/playbooks", {}),
    ("playbook: cross-examine", "/api/playbook/cross-examine-a-witness", {}),
    ("playbook: hot bench", "/api/playbook/answer-a-hot-bench", {}),
    ("search: sustained objections", "/api/search",
     {"case": "depp-v-heard", "q": "show me every sustained objection", "limit": 4}),
    ("search: hearsay", "/api/search",
     {"case": "depp-v-heard", "q": "objection hearsay", "limit": 4}),
    ("search: FRE 611", "/api/search",
     {"case": "depp-v-heard", "q": "FRE 611 leading question", "limit": 3}),
    ("search: impeachment", "/api/search",
     {"case": "depp-v-heard", "q": "impeachment with a prior statement", "limit": 4}),
    ("search: Gorsuch", "/api/search",
     {"case": "scotus-oral-arguments", "q": "how did Gorsuch press the advocate", "limit": 3}),
    ("search: hypotheticals", "/api/search",
     {"case": "scotus-oral-arguments", "q": "hypothetical from the bench", "limit": 3}),
    ("search: standard of review", "/api/search",
     {"case": "scotus-oral-arguments", "q": "standard of review argument", "limit": 3}),
    ("room: accused of lying", "/api/reactions/search",
     {"q": "how did the witness react when she was accused of lying", "limit": 3}),
    ("room: body language", "/api/reactions/search",
     {"q": "body language during cross examination", "limit": 3}),
    ("room: confronted with deposition", "/api/reactions/search",
     {"q": "what was the witness's demeanor while being confronted with her deposition",
      "limit": 3}),
    ("contradictions", "/api/contradictions/depp-v-heard", {}),
    ("case: Depp v. Heard", "/api/case/depp-v-heard", {}),
    ("case: SCOTUS", "/api/case/scotus-oral-arguments", {}),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8321")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    slow = []
    for name, path, params in BEATS:
        url = args.base.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        started = time.time()
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as resp:
                resp.read()
            elapsed = time.time() - started
            flag = "  <-- still slow" if elapsed > 4 else ""
            print(f"  {elapsed:6.2f}s  {name}{flag}")
            if elapsed > 4:
                slow.append((name, elapsed))
        except Exception as exc:
            print(f"  FAILED   {name}: {type(exc).__name__} {str(exc)[:70]}")

    print("\nsecond pass, this is what the demo will actually feel like:")
    for name, path, params in BEATS:
        url = args.base.rstrip("/") + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        started = time.time()
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as resp:
                resp.read()
            print(f"  {time.time() - started:6.2f}s  {name}")
        except Exception as exc:
            print(f"  FAILED   {name}: {type(exc).__name__}")


if __name__ == "__main__":
    main()
