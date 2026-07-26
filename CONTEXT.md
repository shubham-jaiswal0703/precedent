# Precedent: Project Context

Living log of decisions, state, and next steps. Update this whenever anything
material changes.

## What we're building

Playable testimony for law schools: ingest real courtroom footage into
VideoDB, index legal moments (objections/rulings, cross-examination, expert
testimony, sidebars), answer professor-style questions with playable clips,
find contradictions in a witness's testimony across days/deposition-vs-trial
(signature feature), auto-cut teaching reels, and generate playable case packs.

Full design: [ARCHITECTURE.md](ARCHITECTURE.md). Footage: [SOURCES.md](SOURCES.md).
Running notes on VideoDB behavior: [LEARNINGS.md](LEARNINGS.md).

## Demo script (2 min)

1. Load a famous public trial (Depp v. Heard segments).
2. "Show me every objection that was sustained" → clips appear.
3. "Where does the witness contradict her deposition?" → two clips side by side.
4. "Build me a teaching reel on cross-examination technique" → stitched reel.
5. Close: "Students used to read this in a book; now they watch the moment."

## Stack decisions

- Python 3.9 venv, `videodb` SDK 0.5.1, FastAPI backend, React UI later
  (VideoDB `player_url`/embed: we never serve video ourselves).
- Legacy SDK surface primary (index_spoken_words / index_scenes / search /
  timeline.Timeline); new surface (ask/clip/semantic_search/query/editor)
  behind wrappers where it helps. Rationale in ARCHITECTURE.md §1.
- Local catalog (data/catalog.json → SQLite if needed) for what VideoDB
  doesn't model: case metadata, session type, witness lists, day ordering,
  moment records.
- Speaker attribution via transcript structure + LLM tagging (VideoDB has no
  diarization on uploads).

## Infra / accounts

- VideoDB: key in `.env` (gitignored), account collection
  `c-35765392-fc14-4cee-bb76-89c8b78bf2c2` verified working. Plenty of credits.
  NOTE: rotate key after hackathon (it was shared in chat).
- GitHub: repo to be created under https://github.com/shubham-jaiswal0703
  (issues/PM live there). Local repo initialized on `main`; remote not yet
  added: needs repo creation + confirmation before first push.

## Status log

- 2026-07-25: Project kicked off. VideoDB docs + GitHub org researched;
  footage sources evaluated (Depp v. Heard primary, Gates deposition
  secondary); API key verified against live account; repo scaffolded
  (package layout, pyproject, venv); ARCHITECTURE.md, SOURCES.md,
  CONTEXT.md, LEARNINGS.md written. Full github.com/video-db org sweep done
  (43 repos): reusable assets logged in LEARNINGS.md; headline finds:
  deepsearch (retrieval architecture), skills repo (new-SDK reference docs),
  rts-intruder-detection (React UI skeleton), PromptClip (reel prototype).

- 2026-07-26: Core pipeline built and validated end-to-end against live
  VideoDB: ingest (per-case collections + catalog), spoken-word indexing,
  semantic/keyword/scene search wrappers (normalized PlayableMoment), instant
  clip URLs, rule-based legal-moment extractor (objections found in real
  footage), contradiction finder (claims → cross-search → LLM judge →
  side-by-side clips), teaching-reel builder (Timeline add_inline + text
  overlays). First corpus video: Kate James testimony (83 min) indexed in
  `depp-v-heard` collection.
- 2026-07-26: GitHub live: https://github.com/shubham-jaiswal0703/precedent
  (gh auth added for shubham-jaiswal0703; repo created + pushed).
- 2026-07-26: Contradiction finder validated on real footage: Heard cross
  (May 16, found via conn.youtube_search) vs rebuttal (May 26) → "evolved"
  testimony pair with two playable clips. Archive now has 3 videos (~2.7 h).
  Demo beats 1 (search→clips) and 3 (contradiction) proven; reels and case
  packs still to exercise.

- 2026-07-26 (later): All five product surfaces working. Teaching reel
  (8 objections stitched cross-video), case pack (19-objection log with
  grounds/rulings + 29-event timeline + key exchanges, every entry playable),
  contradictions precomputed + cached, FastAPI + single-page UI (hls.js)
  verified in browser: search → playable moments, side-by-side contradiction
  players, reel builder tab. Server: `uvicorn precedent.api.app:app --port
  8321` (preview launcher can't exec under Desktop due to macOS TCC: run
  from a normal shell). GitHub issues used as work log (#1, #8; #2 and #6
  open: VO-contamination filter, Search V2 migration).

- 2026-07-26 (session 2): Pivoted the corpus strategy and rebuilt search.
  * Corpus: added **SCOTUS oral arguments via Oyez** (named speakers +
    time-aligned transcripts, public-domain MP3s): appellate advocacy is core
    law-school curriculum, and CourtListener offers 102k more recordings for
    scale. Trials stay for objections/cross-examination.
  * Search precision: `search/precision.py` (sentence-level narrowing + word
    highlighting + core-term re-ranking) and `search/router.py` (intent
    classification → structured moment filters for objections/rulings/FRE
    rules, keyword for quoted phrases, semantic otherwise).
  * Speakers: `moments/speakers.py` infers judge/examiner/witness/narrator from
    VideoDB's speaker labels; narrator detection closes the broadcaster-VO
    contamination issue.
  * UI: transcript panel with highlighted matches, click-a-word-to-seek,
    follow-along highlighting, "Read as:" interpretation banner with filter
    chips, role filter, and an "Analyze a Link" tab (drop any YouTube URL).
  * Hosting: see HOSTING.md: Railway/Render recommended; two blockers noted
    (local-file state, in-process jobs) before multi-instance hosting.
  * Query-layer research: full moment taxonomy, FRE mapping, and 60+ realistic
    student queries captured (see the research notes in this file's history and
    router.py's tables, which implement the first slice).

- 2026-07-26 (session 3): Reoriented the product around preparation rather
  than search, which is what the audience actually does.
  * playbooks.py: five task-first playbooks (cross-examine a witness who
    changed her story, make and meet objections, argue to a hot bench, frame
    the standard of review, qualify and attack an expert). Each names the task,
    states what good looks like in course vocabulary with attribution
    (Younger, FRE 613, Daubert), and proves every step with real moments.
    This is now the landing view.
  * Cameras in Courts ingest working (ingest/cameras.py), so the library has
    real trial video including In re Roundup before Judge Chhabria.
  * Cover art everywhere: real frames for video, typographic plates for
    audio-only argument.
  * Performance: gallery cached to disk, moment pool memoized on catalog
    mtime, clip URLs cached in data/clips.json, warm-up on server startup.
    First load went from minutes to ~2.8s; warm loads are ~3ms.
  * Clips never render blank now: playbook clips are pre-generated with
    posters, and lazy clips show their cover with a play button.

- 2026-07-26 (session 4): Live on Railway with Postgres. Round of fixes from
  testing the deployed app:
  * Teaching reels now draw from the whole library by default and interleave
    cases, so a reel compares courtrooms instead of replaying one trial. Added
    controls for clip count, seconds per clip, a total length cap, and burned in
    subtitles via the editor timeline's CaptionAsset.
  * Removed the global Contradictions tab, which only ever had one case in it.
    Contradictions now appear inside the case that has them, and the Search tab
    carries labelled example questions explaining what each one exercises.
  * Add a Link shows a public shelf of contributed links, credited to a stable
    pseudonym derived from the request origin. The library is public record, so
    a contributed link is visible to everyone.
  * Railway: Postgres provisioned and referenced, PUBLIC_BASE_URL set, so
    /api/health reports storage=postgres and webhooks=true. Deploys go out with
    `railway up` because automatic deploys from main are still not enabled.

- 2026-07-26 (session 5): Vision layer shipped. Three video sessions carry a
  "reactions" scene index (8s sampling, courtroom-demeanor vision prompt,
  ~$3 total): Heard cross, Heard rebuttal, Roundup part 3. New find_reaction
  intent joins spoken moments with what the camera saw; moment cards show a
  "What the camera saw" panel. Gate test confirmed the vision model reads real
  expressions at broadcast resolution and says explicitly when faces are
  unreadable. Reels gained styled chapter cards, an optional TTS spoken intro
  (generate_voice), and contradiction pairs can render as one side-by-side
  clip via the editor timeline (volume lives on the asset, not the Clip).
  RTStream verified: connects and creates a live scene index; VOD test streams
  end and produce zero scenes, so scripts/live_demo.py exists for a real
  camera feed (rtsp.me) and the pitch, not the main demo. Auto-deploy from
  main is finally on (service source had never been connected to the repo;
  fixed via railway service source connect).

## Scope decision (2026-07-26)

Corpus scale is deliberately capped. This is a hackathon demo, and more clips
means more surface to keep correct, not a better story. ~47 hours across six
cases is enough to demonstrate every mechanic. Scaling to the full 1,100-hour
Cameras in Courts archive is filed as issue #15 rather than done.

## Next steps (build order)

1. `ingest` + catalog + `indexing` wrappers: one trial segment searchable end-to-end
2. `search` query router → playable shots
3. `moments` extractor → objection log
4. `contradictions` pipeline (the aha)
5. `reels` + `casepacks`
6. FastAPI + minimal player UI (CLI demos everything first)
