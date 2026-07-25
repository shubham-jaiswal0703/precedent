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

## Environment / build notes

- 2026-07-25: macOS system Python is 3.9.6 — pinned `requires-python >=3.9`.
  urllib3 warns about LibreSSL on 3.9; harmless. Consider brew Python 3.12 if
  it becomes annoying.
- 2026-07-25: API key connects; default collection
  `c-35765392-fc14-4cee-bb76-89c8b78bf2c2` ("shubham jaiswal's collection"),
  0 videos.

## Footage notes

- 2026-07-25: Depp v. Heard chosen as primary corpus (see SOURCES.md).
  Broadcaster streams include anchor commentary at recesses — timestamp around
  it or trim at ingest. Sidebar white noise is actually a nice demo of
  "inaudible" handling.
