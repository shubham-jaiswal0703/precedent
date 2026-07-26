# Precedent

**Playable testimony for law schools.** Turn courtroom archives into a
searchable library of real advocacy. Students watch how lawyers actually argued,
the objection, the cross examination, the moment a witness broke, instead of
reading about it in a casebook.

**Live: https://precedent-production-900c.up.railway.app/**

Built on [VideoDB](https://videodb.io).

## What it does

1. **A browsable library.** Cases arrive as cards showing their shape: how many
   sessions, who speaks, what kinds of moments they contain. Open one and you
   get recommended sections instead of an empty search box.
2. **Ask about a case.** "Why did counsel concede that point?" returns an answer
   built only from the transcript, with every claim carrying a playable
   citation. No source, no sentence.
3. **Search like a professor.** Objections, rulings, and Federal Rules of
   Evidence numbers resolve against a structured index of courtroom events.
   Everything else falls back to semantic search, narrowed to the sentences that
   actually answer the question, with matched words highlighted and clickable.
4. **Legal moment indexing.** Objections and their rulings, impeachment with a
   prior statement, sidebars, motions, expert qualification for trials.
   Hypotheticals from the bench, standard of review, concessions, stare decisis
   for appellate argument.
5. **Named speakers.** Supreme Court arguments carry ground truth attribution,
   so a result reads "Neil Gorsuch questioning Eric R. Olson" rather than
   "speaker C". For unlabeled footage the roles of judge, attorney, witness, and
   broadcast voiceover are inferred from how each speaker talks.
6. **Contradiction finder.** Compare a witness across days or against a
   deposition and get side by side playable clips where the statements conflict.
7. **Teaching reels and case packs.** Ask for every leading question objection
   in the archive and get one stitched compilation. Or a structured trial
   breakdown where every entry links to its clip.
8. **Add a link.** Paste any YouTube URL of a trial, hearing, or argument and it
   joins the searchable library.

## The corpus

Roughly 45 hours across three archives, all public record:

* **US Supreme Court oral arguments** via Oyez, including Dobbs, Students for
  Fair Admissions v. Harvard, Sackett v. EPA, 303 Creative, Ramos v. Louisiana
* **Federal appellate arguments** via CourtListener, which holds over 100,000
  recordings
* **Depp v. Heard trial footage**, which supplies the objections, cross
  examination, and contradiction material that appellate audio cannot

See [SOURCES.md](SOURCES.md) for the ingestion endpoints and the sources we
evaluated and rejected.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # add your VideoDB API key
.venv/bin/python -m uvicorn precedent.api.app:app --port 8321
```

Grow the library:

```bash
.venv/bin/python scripts/bulk_ingest.py oyez --terms 2022,2021 --per-term 8
.venv/bin/python scripts/bulk_ingest.py courtlistener --limit 10
```

Both accept `--dry-run`, which lists what would be ingested along with an
estimated transcription cost.

## Docs

* [ARCHITECTURE.md](ARCHITECTURE.md) for the system design and how each feature
  maps to VideoDB
* [SOURCES.md](SOURCES.md) for the footage corpus and bulk ingestion endpoints
* [HOSTING.md](HOSTING.md) for deployment
* [CONTEXT.md](CONTEXT.md) for decisions and current status
* [LEARNINGS.md](LEARNINGS.md) for running notes on VideoDB behavior
