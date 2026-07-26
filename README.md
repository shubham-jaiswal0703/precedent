# Precedent

**Playable testimony for law schools.** Courtroom archives turned into a
searchable library of real advocacy. Students watch how lawyers actually argued,
the objection, the cross examination, the moment a witness broke, instead of
reading about it in a casebook.

**Live: https://precedent-production-900c.up.railway.app/**

Built on [VideoDB](https://videodb.io).

## What it does

**Prepare.** The landing view asks what you are preparing, not what you want to
search. Five playbooks name a task (cross-examine a witness who changed her
story, make and meet objections, argue to a hot bench, frame the standard of
review, qualify and attack an expert), state what good looks like in the
vocabulary the course uses, cite the authority for it, and prove every step with
real moments from the record.

**Library.** Cases as browsable cards showing their shape: sessions, hours,
indexed moments, who speaks. Open one for recommended sections grouped by what
happens in the record, plus a grounded question box: ask why counsel conceded a
point and the answer is built only from the transcript, with every claim carrying
a playable citation.

**Search.** Objections, rulings, and Federal Rules of Evidence numbers resolve
against a structured index of courtroom events, because nobody says "403" out
loud. Everything else falls back to semantic search narrowed to the sentences
that answer the question, with matched words highlighted and clickable.

**Read the Room.** The transcript says what was said. A vision index over the
same footage says what the camera saw while it was being said: expressions,
posture, composure. Ask how a witness reacted when she was accused of lying and
the answer arrives beside the clip.

**Teaching Reel.** Draws from every case and interleaves them, so a reel compares
courtrooms instead of replaying one trial. Choose clip count, seconds per clip,
a total length cap, one stitched reel or separate clips, 16:9 or 9:16, burned in
subtitles, and a spoken intro. A stitched reel comes with a clickable chapter
list that follows playback.

**Contradictions.** Compare a witness across days or against a deposition and
get side by side playable clips where the statements conflict, exportable as one
rendered clip. Surfaced inside the case that has them.

**My Set.** Save clips into your own set, reorder them, attach a practice note,
then play the set as one reel or download a prep sheet with every source,
timecode, transcript, and playable link. Stored in your browser, so no account
and no loss on redeploy.

**Add a Link.** Paste any YouTube URL of a trial, hearing, or argument and it
joins the searchable library. Contributed links appear publicly, credited to a
pseudonym.

## The corpus

Roughly 47 hours across seven cases, all public record. Scale is deliberately
capped: every mechanic is demonstrated, and more footage would mean more surface
to keep correct rather than a better story.

* **US Supreme Court oral arguments** via Oyez, including Dobbs, Students for
  Fair Admissions v. Harvard, Sackett v. EPA, 303 Creative, Ramos v. Louisiana.
  Oyez ships speaker-labelled aligned transcripts, so results name the actual
  justice rather than "speaker C".
* **Federal appellate arguments** via CourtListener, which holds over 100,000
  recordings.
* **Federal trials** via the judiciary's Cameras in Courts archive, including
  In re Roundup Products Liability Litigation before Judge Chhabria.
* **Depp v. Heard trial footage**, which supplies the objections, cross
  examination, and contradiction material that appellate audio cannot, and the
  only footage with faces close enough to read.

See [SOURCES.md](SOURCES.md) for ingestion endpoints and the sources evaluated
and rejected.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # add your VideoDB API key
.venv/bin/python -m uvicorn precedent.api.app:app --port 8321
```

Grow the library, then warm the caches so nothing is computed during a demo:

```bash
.venv/bin/python scripts/bulk_ingest.py oyez --terms 2022,2021 --per-term 8
.venv/bin/python scripts/bulk_ingest.py courtlistener --limit 10
.venv/bin/python scripts/bulk_ingest.py cameras --limit 3 --parts 3
.venv/bin/python scripts/warm_caches.py
```

All three ingesters accept `--dry-run`, which lists what would be ingested with
an estimated transcription cost.

## Docs

* [ARCHITECTURE.md](ARCHITECTURE.md) for how it works and which VideoDB feature
  does what
* [SOURCES.md](SOURCES.md) for the footage corpus and bulk ingestion endpoints
