# Precedent — Architecture

> Playable testimony for law schools. Turn courtroom archives into a searchable
> library of real advocacy: the objection, the cross-examination, the moment a
> witness broke.

Built on [VideoDB](https://docs.videodb.io/). This document maps every product
feature to the concrete VideoDB primitives that implement it, and defines the
system layers we build on top.

---

## 1. System overview

```
                        ┌──────────────────────────────────────────────┐
                        │                 VideoDB Cloud                │
                        │  Collections · Videos · Indexes · Streaming │
                        └──────▲───────────────▲───────────────▲──────┘
                               │ upload         │ index/search  │ HLS streams
┌───────────────┐      ┌───────┴───────┐ ┌──────┴───────┐ ┌─────┴────────┐
│ Trial sources │──────▶   INGEST      │ │  INDEXING    │ │  DELIVERY    │
│ YouTube/files │      │ ingest/       │ │  indexing/   │ │  reels/      │
└───────────────┘      └───────────────┘ └──────┬───────┘ │  casepacks/  │
                                                │         └─────▲────────┘
                                         ┌──────┴───────┐       │
                                         │ LEGAL-MOMENT │       │
                                         │ LAYER        │───────┤
                                         │ moments/     │       │
                                         │ contradictions/      │
                                         └──────┬───────┘       │
                                                │               │
                                         ┌──────┴───────────────┴──────┐
                                         │        API (FastAPI)        │
                                         │  api/  →  web player UI     │
                                         └─────────────────────────────┘
```

Six pipeline stages, one Python package (`precedent/`), VideoDB as the only
media infrastructure — no ffmpeg, no local video files, no vector DB. Every
"answer" the system gives is a **Shot** (`video_id`, `start`, `end`, `text`,
`score`) rendered as an instantly playable HLS `stream_url`.

### API-generation note

The VideoDB Python SDK has two coexisting generations. We use the **proven
legacy surface** (`index_spoken_words`, `index_scenes`, `search`,
`videodb.timeline.Timeline`) as the primary path — it's what all cookbooks and
Director use — and adopt new-surface calls (`video.ask()`, `video.clip()`,
`semantic_search`, `query`/`aggregate`, editor `Timeline`) where they buy us
something, behind thin wrappers in `precedent/indexing/` and
`precedent/search/` so we can swap generations without touching product code.

---

## 2. Stage 1 — Ingest (`precedent/ingest/`)

**Product:** load full trials, depositions, hearings — days of footage as one
queryable archive.

| Concern | VideoDB primitive |
|---|---|
| Archive namespace | One `Collection` per case (`conn.create_collection`) |
| YouTube ingestion | `coll.upload(url="https://youtube.com/...")` — native |
| Local files | `coll.upload(file_path=...)` |
| Finding footage | `conn.youtube_search(query)` (optional helper) |
| Async ingest | `callback_url` on upload/transcode for job tracking |

Each uploaded video gets a **manifest entry** in our local catalog
(`data/catalog.json` → SQLite later): case, session type
(`trial_day | deposition | hearing`), date, witnesses on the stand, source URL.
This is the metadata VideoDB doesn't know and the contradiction finder needs
(deposition-vs-trial pairing, day ordering).

## 3. Stage 2 — Indexing (`precedent/indexing/`)

**Product:** index spoken word plus courtroom *events*.

Three indexes per video, built concurrently (all support `callback_url`):

1. **Spoken-word index** — `video.index_spoken_words()`. Powers semantic +
   keyword search and word-level transcripts
   (`video.get_transcript(segmenter=Segmenter.word)`).
2. **Courtroom-events scene index** — `video.index_scenes(...)` with a custom
   legal prompt ("Describe courtroom activity: who is at the podium, is an
   objection occurring, is an exhibit displayed, witness demeanor..."). Trial
   footage is mostly static-camera, so we use `time_based` extraction
   (`{"time": 20, "select_frames": ["middle"]}`), not shot-based cut detection.
3. **Legal-moment annotations** (our layer, stored back INTO VideoDB) — see §4.
   Via the advanced pipeline: `video.extract_scenes()` → annotate each scene →
   `video.index_scenes(scenes=annotated, name="legal_moments")`, with
   `metadata={"witness": ..., "moment_type": ..., "ruling": ...}` so search can
   *filter* by structured fields, not just match text.

Speaker attribution: VideoDB has no diarization for uploaded footage (meetings
only), so witness/attorney attribution comes from (a) the transcript itself —
courtroom speech is highly structured ("Objection, Your Honor" / "Sustained" /
"Pass the witness") — and (b) LLM tagging of transcript windows, written into
scene `metadata`. This is a deliberate scope cut for the hackathon.

## 4. Stage 3 — Legal-moment layer (`precedent/moments/`)

**Product:** objections (and rulings), cross-examination exchanges, expert
testimony, sidebars, verdicts, emotional shifts.

This is our core IP on top of VideoDB. A **moment extractor** walks the
word-level transcript in windows and classifies legal events:

- **Rule-first pass** (cheap, reliable): regex/keyword detection of the ritual
  language of court — "objection", "sustained"/"overruled", "sidebar",
  "no further questions", "pass the witness", "please rise", oath
  administration, "move to strike". Courtroom discourse is formulaic enough
  that this pass alone catches most objection events with exact timestamps.
- **LLM enrichment pass**: classify each candidate window (objection ground:
  hearsay/leading/relevance; examination phase: direct/cross/redirect; witness
  on stand; emotional register) using transcript context.

Output: `Moment` records `{video_id, start, end, moment_type, attrs, text}` —
persisted (a) locally in the catalog and (b) into VideoDB as the
`legal_moments` scene index with `metadata`, so professors' queries can hit
them via `coll.search(..., filter=[...])` and results come back as playable
Shots.

## 5. Stage 4 — Ask like a professor (`precedent/search/`)

**Product:** natural-language questions → playable moments.

| Query shape | Implementation |
|---|---|
| "Find the cross-examination on the DNA evidence" | `coll.search(query, SearchType.semantic, IndexType.spoken_word)` → Shots |
| "Show me every sustained objection" | structured: filter `legal_moments` index (`moment_type=objection, ruling=sustained`) → Shots; also `video.query()`/`aggregate()` on the new surface |
| "What did the witness say about the photos?" | `video.ask(question, include_sources=True)` — grounded QA with source shots |
| Exact-phrase lookups | `video.search(SearchType.keyword)` (video-scope only — we fan out across the collection ourselves) |
| One-shot prompt→clips | `video.clip(prompt, content_type="spoken")` |

A small **query router** classifies the professor's question into
structured-filter vs semantic vs QA and dispatches. Every result path
normalizes to `list[Shot]` → each shot playable via `shot.stream_url` /
`player_url`, with transcript context from `get_transcript(start, end)`.

## 6. Stage 5 — Contradiction finder (`precedent/contradictions/`)

**Product (signature feature):** same witness, different day or
deposition-vs-trial → side-by-side playable clips where statements conflict.

Pipeline:
1. **Pair selection** — catalog metadata picks the video pair (witness X:
   deposition vid + trial-day vid, or day N vs day M).
2. **Claim extraction** — LLM extracts factual claims per witness segment from
   word-timestamped transcripts: `{claim, start, end, quote}`.
3. **Cross-matching** — for each claim in A, semantic-search video B for the
   same topic (`video.search(claim_text, semantic)`), giving candidate
   opposing segments *with timestamps* — VideoDB does the alignment work.
4. **Conflict judgment** — LLM compares claim A vs candidate B transcripts:
   `consistent | contradictory | evolved`, with reasoning.
5. **Side-by-side render** — for each contradiction:
   `video.generate_stream(timeline=[(a_start, a_end)])` +
   same for B → two instant clips presented in a split player UI. Optional
   stitched A-then-B version via `Timeline.add_inline(VideoAsset(A), VideoAsset(B))`
   with `TextAsset` overlays ("Deposition, Jan 12" / "Trial, Day 4").

## 7. Stage 6 — Teaching reels & case packs (`precedent/reels/`, `precedent/casepacks/`)

**Reels** ("every leading-question objection in the archive, stitched"):
- Query the moments layer → shots across many videos.
- `videodb.timeline.Timeline`: `add_inline(VideoAsset(...))` per shot,
  `add_overlay(TextAsset(...))` chapter cards between segments; optional
  `coll.generate_voice()` TTS intro as an `AudioAsset`.
- `timeline.generate_stream()` → one playable reel URL; `conn.download()` for
  an MP4 the professor can keep. Quick path: `search_result.compile()`.
- Burned captions where useful: `video.add_subtitle(SubtitleStyle(...))`.

**Case packs** (playable casebook chapter): structured JSON per trial —
witness list, examination timeline, objection log (with rulings + grounds),
key exchanges, verdict — every entry carrying `{start, end, stream_url,
player_url, transcript}`. Generated from catalog + moments + `video.ask()`
summaries; exported to `data/casepacks/<case>.json` and rendered by the UI.
Thumbnails per entry via `video.generate_thumbnail(time=...)`.

## 8. API + UI (`precedent/api/`)

- **FastAPI** backend: `/cases`, `/cases/{id}/ingest`, `/search`,
  `/moments`, `/contradictions/{witness}`, `/reels`, `/casepacks/{id}`.
  Long jobs (ingest/index) run async; VideoDB `callback_url` webhooks update
  job state.
- **Frontend**: React + VideoDB `player_url`/embed codes — no video serving on
  our side. Split-screen component for contradiction pairs.
- **Later/optional:** lift agents from [Director](https://github.com/video-db/Director)
  (MIT) — `prompt_clip`, `comparison`, `subtitle` — as a chat interface over
  the archive.

## 9. VideoDB feature coverage checklist

Used: collections · YouTube + file upload · youtube_search · spoken-word index
· scene index (time-based, custom prompt) · custom-annotated scene index with
metadata filters · semantic search (video + collection) · keyword search ·
`ask()` grounded QA · `clip()` · Shots/compile · `generate_stream(timeline)` ·
Timeline + Video/Text/Audio assets · `add_subtitle` · transcripts
(word/sentence/windowed) · thumbnails · `callback_url` async jobs ·
`conn.download` MP4 export · `generate_voice` TTS (reel narration) ·
`translate_transcript` (stretch: multilingual case packs).

Known gaps we design around: no speaker diarization on uploads (transcript
structure + LLM tagging), keyword search is video-scope (we fan out),
side-by-side is composed in the UI / editor-Timeline (no one-call primitive).

## 10. Demo corpus

Primary: **Depp v. Heard (2022)** — pool-feed audio is clean; objection-dense;
same witnesses across days *and* video depositions played in open court →
contradiction pairs inside one archive. Ingest 2–3 targeted segments (one
direct, one cross, one rebuttal) rather than full 8-hour days.
Secondary (stretch): **Bill Gates 1998 deposition** — public-record government
exhibit, demonstrates archival-quality handling.

## 11. Build order

1. `ingest` + catalog + `indexing` wrappers — get one trial segment searchable end-to-end
2. `search` query router → playable shots (demo beat 1)
3. `moments` extractor (rule-first, then LLM) → objection log (demo beat 2)
4. `contradictions` pipeline (demo beat 3 — the aha)
5. `reels` + `casepacks` (demo beats 4–5)
6. FastAPI + minimal player UI last — CLI demos everything before the UI exists
