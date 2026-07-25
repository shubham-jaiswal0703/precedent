# Learnings — VideoDB & build notes

Running log of everything we learn about VideoDB (and anything else) while
building. Append as we go; newest findings at the bottom of each section.

## VideoDB SDK — key facts (from docs + SDK source research, 2026-07-25)

### Two API generations coexist
- Legacy (all cookbooks + Director use this): `index_spoken_words()`,
  `index_scenes()`, `video.search()/coll.search()`, `videodb.timeline.Timeline`
  (`add_inline`/`add_overlay`). Proven; old Timeline warns deprecated.
- New: `understand(analyzers=[...])` → `index(source=...)` →
  `semantic_search()/query()/aggregate()/ask()`, plus `video.clip(prompt)` and
  `videodb.editor.Timeline` (multi-track, z-index, transitions, filters,
  CaptionAsset). Analyzers: spoken_words, vlm, object_detection, ocr,
  brand_detection, activity_recognition, location_detection.

### Search scope matrix (legacy)
- semantic → video + collection scope
- keyword → video scope ONLY (collection raises NotImplementedError) — fan out
  ourselves for archive-wide exact-phrase search
- scene index search → video scope only

### Results = Shots
`Shot(video_id, start, end, text, score, stream_url, player_url)`;
`SearchResult.compile()` stitches all shots into one stream (works cross-video
on collection search). This is the whole "playable answer" mechanic for free.

### Clips are instant, no re-encode
`video.generate_stream(timeline=[(start, end), ...])` → HLS URL immediately.
`conn.download(stream_link, name)` for MP4 export of any compiled stream.

### Transcripts have word-level timestamps
`video.get_transcript(segmenter=Segmenter.word|sentence|time, start=, end=)`
→ `[{start, end, text}]`. Windowed retrieval — pull the exact transcript under
any clip.

### Scene indexing
- `SceneExtractionType.shot_based` (visual-change/cut detection) vs
  `time_based` (`{"time": N, "select_frames": ["first"|"middle"|"last"]}`).
  Static courtroom cameras → use time_based; shot_based will under-segment.
- Custom vision prompt per index; multiple named scene indexes per video.
- Advanced path: `video.extract_scenes()` → annotate `scene.description` /
  `scene.describe(prompt)` yourself → `video.index_scenes(scenes=..., name=...)`.
- Scene `metadata` dict is indexable + filterable via `search(filter=[...])` —
  our legal-moment structured fields ride on this.

### Gaps to design around
- No speaker diarization on uploaded footage (only Meeting recordings have
  `speaker_timeline`). Mitigation: courtroom speech is ritualized
  ("Objection" / "Sustained" / "Pass the witness") — rules + LLM tagging.
- Side-by-side is not a one-call primitive — compose in UI (two players) or
  editor Timeline (two tracks, position/scale). Director has a comparison
  agent to crib from.

### Misc surface worth remembering
- `conn.youtube_search(query)`; `video.add_subtitle(SubtitleStyle(...))` burns
  captions; `video.generate_thumbnail(time=)`; `coll.generate_voice(text)` TTS;
  `translate_transcript(language)`; `callback_url` on every long-running call;
  `video.reframe(target="vertical", mode=smart)` for social cuts; RTStream for
  live feeds (future "live courtroom" feature).
- Pricing: $20 free credits; transcription $0.01/min; scenes $0.003/scene;
  search $1.50/1k queries; upload $0.09/GB.
- Director (MIT) has ~27 agents incl. prompt_clip, comparison, subtitle —
  liftable.

## github.com/video-db org sweep (43 repos, 2026-07-25)

Full survey done; the assets worth reusing, in priority order:

1. **deepsearch** (Python, LangGraph) — stateful multi-turn video retrieval:
   LLM-planned multi-index subqueries, validator loop, reranking, session
   memory, explainable ranked clips. The closest architecture to our
   contradiction finder ("find the objection... now find where the witness
   said the opposite"). Lift its retrieval design.
2. **skills** repo (112★, pushed 2026-07-25) — Claude Code plugin
   (`npx skills add video-db/skills`) whose `python/reference/*.md` is the
   best current map of the NEW SDK surface (indexing, search, editor,
   sandbox GPU models, rtstream, legacy→new migration). Use as dev-time
   grounding docs.
3. **rts-intruder-detection** (Next.js/React) — the org's only React UI:
   HLS player + time-synced alert overlays + scene-index panel + copilot
   chat. ~80% of a courtroom-footage viewer layout; APIs are mocked →
   forkable skeleton for our UI.
4. **worldcup-video-agent** (Next.js + Postgres) — end-to-end production
   reference: NL request → scene-index events on clock timestamps →
   compiled playable reels → gallery. Same shape as our reel pipeline.
5. **PromptClip** (174★) — "prompt → supercut" notebooks (text/visual/
   multimodal); quickest prototype path for teaching reels (legacy SDK).
6. **fact-checker** — claim-extraction → verification loop over live
   transcript buffers; repurpose the loop for testimony-vs-testimony
   contradiction judgment.
7. **agent-toolkit** — `llms-full.txt` (auto-generated full SDK context, feed
   to codegen) + MCP server `uvx videodb-director-mcp --api-key=...`.
8. **videodb-player / videodb-chat** (Vue) — `SearchInsideMedia` overlay and
   contentType message handlers (text/video/image) are the interaction
   patterns to replicate in React; not drop-in (Vue).
9. **Node SDK caution** — videodb-node is active but documents only the
   legacy surface; keep backend Python, React talks to our FastAPI.

Cookbook recipes to crib (of 64 notebooks): `custom_annotations` (custom
scene labels = our legal moments), `Keyword_Search_Counter` (objection
counting), `scene_level_metadata_indexing` (filterable metadata),
`advanced_visual_search`, `Beep Curse Words` (keyword→timestamp→audio edit =
redaction), `Interview_Evaluation_To_Slack` (testimony → structured eval),
`automated_video_copyright_detection` (cross-video matching),
`Multicam_Public_Surveillance` (multi-angle sync), all `editor/feature/*`
(stitched reels), `lecture_notes_1` (hearing summaries).

Also noted: managed GPU **sandboxes** (Whisper/Gemma/Qwen/FLUX/RT-DETR) exist
in the new surface — a possible in-platform route for diarization-ish audio
work later; webhook/real-time canon lives in videodb-capture-quickstart.

## Environment / build notes

- 2026-07-25: macOS system Python is 3.9.6 — pinned `requires-python >=3.9`.
  urllib3 warns about LibreSSL on 3.9; harmless. Consider brew Python 3.12 if
  it becomes annoying.
- 2026-07-25: API key connects; default collection
  `c-35765392-fc14-4cee-bb76-89c8b78bf2c2` ("shubham jaiswal's collection"),
  0 videos.

## End-to-end validation (2026-07-26)

- Ingested Kate James testimony segment (83 min, YouTube URL) into a
  dedicated `depp-v-heard` collection: upload 68s, spoken-word index ~2 min
  total. Fast enough to ingest live during a demo if needed.
- Collection-level semantic search returns scored, timestamped shots; SDK
  shows a progress bar during blocking index calls; legacy search emits a
  UserWarning pointing at Search V2 (`semantic_search/query/aggregate/ask`)
  — consider migrating wrappers to V2 later.
- `generate_stream(timeline=[(start,end)])` → instant playable
  `play.videodb.io/...m3u8` URL. Confirmed working.
- Rule-based moment extractor found 3 objections in the segment (plausible:
  it's mostly a video deposition played in court — sparse objections).
  Ruling detection (sustained/overruled) needs a wider context window or the
  judge is off-mic in deposition playback; revisit on a live-courtroom
  segment like the Heard cross.
- Transcript segments come back as short phrase-level chunks — anchor+window
  approach works well with them.

## Contradiction pipeline validation (2026-07-26)

- `conn.youtube_search()` works (SerpAPI-backed) — found the Heard cross
  segment programmatically; nice demo beat ("the system found its own
  footage").
- `coll.generate_text()` returns `{'output': '<text>'}` (dict), NOT a plain
  string — unwrap `.output`. LLM output needs tolerant JSON parsing (code
  fences/prose around JSON).
- First live run: cross (May 16) vs rebuttal (May 26), Amber Heard →
  1 "evolved" pair with two instant playable clips. Pipeline: claims (LLM via
  VideoDB generate_text) → semantic search in the other video → judge →
  generate_stream clips. Quality tuning to do: witness-only claim filtering
  (broadcaster VO contaminates claims), more windows, stricter judge prompt,
  richer pair selection from catalog.
- Cost/perf: three videos (~2.7 h total footage) uploaded + spoken-indexed in
  under 5 min combined; contradiction run over an 18-min segment ≈ 2 min.

## API/UI build (2026-07-26)

- `video.search()` RAISES `InvalidRequestError("No results found")` on zero
  hits instead of returning an empty result — wrap every search call.
- Reel stitching returns `stream.videodb.io/v3/published/manifests/...m3u8`
  (different host than single-video `play.videodb.io` clips); both play fine
  in hls.js.
- Precomputing contradictions to `data/contradictions/<case>.json` keeps the
  UI snappy — the finder takes ~2 min per witness pair, too slow for a
  request/response cycle.
- macOS TCC blocks the Claude preview launcher from exec-ing binaries under
  ~/Desktop; run uvicorn from a regular shell and attach the browser to the
  URL instead.

## Footage notes

- 2026-07-25: Depp v. Heard chosen as primary corpus (see SOURCES.md).
  Broadcaster streams include anchor commentary at recesses — timestamp around
  it or trim at ingest. Sidebar white noise is actually a nice demo of
  "inaudible" handling.
