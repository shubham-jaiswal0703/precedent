# Precedent

**Playable testimony for law schools.** Turn courtroom archives into a
searchable library of real advocacy — students watch how lawyers actually
argued (the objection, the cross-examination, the moment a witness broke)
instead of reading it in a casebook.

Built on [VideoDB](https://videodb.io).

## What it does

1. **Ingest trial archives** — full trials, depositions, hearings from
   YouTube URLs or files, treated as one queryable archive per case.
2. **Legal-moment indexing** — objections (and rulings), cross-examination
   exchanges, expert testimony, sidebars, verdicts.
3. **Ask like a professor** — "Show me every sustained objection." Every
   answer is a playable moment, not a page citation.
4. **Contradiction finder** — compare a witness across days or
   deposition-vs-trial; side-by-side playable clips where statements conflict.
5. **Teaching reels** — "every leading-question objection in the archive,"
   stitched into one compilation automatically.
6. **Case packs** — structured trial breakdowns where every entry links to
   its clip: a playable casebook chapter.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # add your VideoDB API key
```

## Docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design & VideoDB feature mapping
- [SOURCES.md](SOURCES.md) — demo footage corpus
- [CONTEXT.md](CONTEXT.md) — decisions, status, next steps
- [LEARNINGS.md](LEARNINGS.md) — running VideoDB/build notes
