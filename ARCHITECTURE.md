# Precedent: Architecture

Every answer this system gives is a playable span of real footage. That
constraint drives the whole design: no assertion about what happened in a
courtroom exists in the product unless you can press play on it.

VideoDB holds the media, the indexes, and the streaming. Our code is the legal
layer on top: what counts as a courtroom moment, who is speaking, which index a
question should be routed to, and how moments become teaching material.

```
    ingest ──▶ index ──▶ legal-moment layer ──▶ routed search ──▶ delivery
   (sources)  (VideoDB)   (our taxonomy)        (intent first)    (clips, reels,
                                                                   playbooks,
                                                                   prep sets)
```

## Storage

`precedent/store.py` keeps every persisted document (catalog, caches, job log)
as JSON under a name. Postgres when `DATABASE_URL` is set, files otherwise, one
interface either way. On first boot against an empty database it seeds from the
files committed in `data/`, so a fresh deploy starts with a warm library rather
than an empty one. One table with a JSONB column, because the data is genuinely
document-shaped.

`GET /api/health` reports which backend is live, whether webhooks are wired, and
the deployed commit SHA.

## Stage 1: Ingest

One VideoDB **collection per case**, plus a local catalog holding what VideoDB
does not model: case, session type, date, docket, judge, witnesses, and which
indexes exist. Four ingesters, each in `precedent/ingest/`:

| Source | Module | Notes |
|---|---|---|
| Oyez (SCOTUS) | `oyez.py` | Public S3 MP3s plus a speaker-labelled aligned transcript, stored as ground-truth attribution |
| CourtListener | `batch.py` | 100k+ appellate recordings. Court sites refuse VideoDB's fetcher, so use CourtListener's own mirror |
| Cameras in Courts | `cameras.py` | 990 full federal trials. Metadata parsed from the fielded description; the CDN refuses VideoDB's fetcher, so files relay through the local machine |
| Any URL | `pipeline.py` | The "Add a Link" path, including YouTube |

Long ingests run as jobs (`precedent/jobs.py`): `POST /api/analyze` returns a job
id immediately and VideoDB calls `POST /api/webhooks/videodb` when indexing
finishes, so an ingest never depends on one process staying alive.

## Stage 2: Index

Up to three VideoDB indexes per session, each answering a different question:

1. **Spoken word** (`index_spoken_words`). Powers semantic and keyword search.
   Its transcript carries **word-level timestamps and speaker labels**, which is
   what makes precise highlighting and role inference possible.
2. **Courtroom events** (`index_scenes`, time-based, custom prompt). Visual
   context for trial footage.
3. **Reactions** (`index_scenes` with a demeanor prompt, 8s sampling). What every
   visible face and body was doing. Only on sessions that have video: audio-only
   argument has no faces, and inventing them would be inventing evidence.

## Stage 3: The legal-moment layer

`precedent/moments/extractor.py` is the core IP. Courtroom speech is ritualised,
so the language of court gives reliable anchors with exact timestamps. Two anchor
sets, selected by session type, because a SCOTUS argument has no objections to
find and a trial has no standard-of-review colloquy:

* **Trial**: objections and their grounds and rulings, impeachment by prior
  statement, motions to strike, sidebars, offers of proof, motions in limine,
  dispositive motions, curative instructions, expert qualification, sequestration.
* **Appellate**: opening lines, hypotheticals from the bench, standard of review,
  concessions and refusals to concede, line-drawing, interruption recovery, time
  expiring, rebuttal, justiciability, stare decisis, interpretive method, record
  citations.

Matching runs over the **joined** transcript with an offset map back to
timestamps. VideoDB returns roughly five-word chunks, so per-chunk matching can
never see a phrase like "may it please the court". Fixing this took one argument
from 3 moments to 65. Results are cached per session.

**Attribution** (`moments/attribution.py`) names the voices, preferring Oyez's
real names over inference. Where there is no ground truth,
`moments/speakers.py` infers judge, examiner, witness, and broadcast narrator
from how each speaker behaves: the examiner asks questions, the witness answers
at length, the judge rules on objections, and the narrator talks *about* the
proceeding in the third person and never says "your honor". That last one matters
because broadcaster voiceover otherwise contaminates the contradiction finder.

## Stage 4: Routed search

Half of what a law student asks is a filter, not a similarity search.
`precedent/search/router.py` classifies the question first:

| Intent | Goes to |
|---|---|
| objections, rulings, FRE rule numbers | the structured moment layer |
| quoted text | keyword search |
| a named justice or advocate | speaker timeline filter, then semantic |
| reactions, demeanor, expressions | spoken search joined with the vision index |
| anything else | semantic search, narrowed |

The detected interpretation is returned with the results, so the UI can show why
these clips came back.

`search/precision.py` then narrows each hit from a wide shot window to the run of
sentences that actually answers the question, flags matched words for
highlighting, and re-ranks on the user's own terms above synonym expansions.
Semantic score alone puts topically-adjacent-but-wrong moments first: a judge
adjourning for the day scores well on "objection hearsay sustained".

## Stage 5: Delivery

* **Playbooks** (`playbooks.py`) organise the library by task. Teaching notes are
  written and attributed, not generated, because the craft is settled and
  citable. The clips are the evidence.
* **Reels** (`reels/builder.py`) compose on a single editor timeline so video,
  chapter cards, and captions coexist as three tracks. Returns a segment manifest
  so a reel is navigable rather than one opaque block.
* **Formats** (`reels/formats.py`) give separate clips or 9:16. Vertical uses
  smart reframing that tracks the speaker, which costs minutes per clip, so it
  runs as a cached background job.
* **Contradictions** (`contradictions/finder.py`) extract claims from one
  session, cross-search another for the same topic, judge the pair, and return
  both clips. Exportable as one rendered side-by-side clip.
* **Case packs** (`casepacks/`) and the **gallery**, every entry playable.
* **Prep sets** live in the browser, exported as a stitched reel or a citable
  markdown sheet.

## Performance

Everything expensive is per-session work multiplied by the corpus: a transcript
fetch per session for moments, a thumbnail generation per cover, a
`generate_stream` per clip. None is slow alone; all are slow across forty
sessions. So each has a cache in the store, the moment pool is memoized against
the catalog's change marker, and a startup hook warms the gallery in a background
thread. `scripts/warm_caches.py` does the same offline and should be run after
any ingest. First load went from minutes to under three seconds; warm loads are
a few milliseconds.

## Known limits

* **Vertical reframing is slow and occasionally fails** upstream. It is cached
  and asynchronous, and a failure is surfaced rather than hidden.
* **Search still uses the legacy VideoDB surface.** Migrating to Search V2 would
  unlock VideoDB's own grounded `ask()`; today grounded answers are
  retrieve-then-generate, which keeps citations under our control.
* **Reactions cover three sessions.** The medium decides this, not the budget.
* **Expression descriptions are model output about a real recording.** They are
  presented as what the camera saw, next to the clip, so a reader can always
  check them against the footage.
