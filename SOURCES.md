# Footage sources

## Bulk sources (verified live, 2026-07-26): the real library

These are the scale answer, and pedagogically stronger than celebrity trials:
appellate advocacy is core 1L/2L curriculum.

### 1. Oyez: US Supreme Court oral arguments (BEST quality-per-item)

Verified working, no auth, public S3 media:
- Case list: `https://api.oyez.org/cases?per_page=30&filter=term:2022`
- Case detail carries `oral_argument_audio[].href` →
  `https://api.oyez.org/case_media/oral_argument_audio/<id>`
- That returns `media_file[]` with **direct MP3** (and OGG, and HLS `.m3u8`):
  `https://s3.amazonaws.com/oyez.case-media.mp3/case_data/2022/21-476/21-476_20221205-argument.delivery.mp3`

**The killer feature: Oyez ships a speaker-labeled, time-aligned transcript.**
`transcript.sections[].turns[]` gives `speaker.name` ("John G. Roberts, Jr.")
with `speaker.roles[].type` ("scotus_justice") and `text_blocks[]` carrying
`start`/`stop`/`text`. So for SCOTUS we get named-justice attribution for free, no diarization inference. Volume: ~60-70 arguments/term, back to the 1950s
(thousands of hours). Rights: US government work, public domain.

### 2. CourtListener / Free Law Project: 102,864 oral-argument recordings

`https://www.courtlistener.com/api/rest/v4/audio/?count=on` → **102864**.
Each record has `download_url` (the court's own MP3, e.g.
`ca11.uscourts.gov/.../25-10656_07242026.mp3`), `local_path_mp3`, `duration`,
`case_name`, `docket`, `panel`/`judges`, and an `stt_transcript` field (they run
their own speech-to-text). Federal circuit + state appellate coverage, updated
daily. No auth needed for reads; note the API rejects unknown filter params, use documented ones (`docket__court`, `date_created__gte`, etc.).

This is the volume play: tens of thousands of real arguments, keyed to courts,
judges, and dockets: exactly the facets the query-layer research says
practitioners expect.

### 3. Trial footage (for cross-examination/objection material)

Court TV and Law&Crime YouTube channels remain the best trial-video source
(see the Depp v. Heard corpus below). Trials are where objections,
impeachment, and witness examination live; appellate audio covers advocacy
under questioning. Precedent wants both.

---

# Demo footage sources

Evaluated for: clean audio, objection density, cross-examination material, and
same-witness-across-time contradiction potential. All ingestable via VideoDB's
native YouTube URL upload.

## Evaluated 2026-07-26: four more archives

### Cameras in Courts (uscourts.gov): the best remaining source, 990 videos

`.../cameras-courts/case-video-archive?page=0|1|2` lists 140 case pages, each
embedding a Piksel player. An undocumented project-wide endpoint enumerates the
whole corpus (`totalCount: 990`, page size capped at 21):

```
https://player.piksel.tech/ws/ws_program/api/dae5e892-195f-11f0-8b80-0a9cbef903c7/mode/json/apiv/5?p=d8125233&size=21&start=N
```

Media resolves to open MP4s on `uscourts.cdn.piksel.tech` with no tokens and no
expiry (verified 200, `video/mp4`, 4 renditions plus HLS).

Why it matters more than anything else on this list: these are **complete jury
and bench trials**, roughly 1,100 hours, 2011 to 2026. One case alone runs 16.7
hours across 6 parts with opening statements, direct, cross, objections,
sidebars, and closings. That is precisely the advocacy behavior Precedent
indexes, and it is not available at this volume anywhere else. Descriptions
carry case number, proceeding type, courthouse, and presiding judge. No
captions exist, so we transcribe everything.

Caveat: the enumeration endpoint is an internal API lifted from page JavaScript.
It works today and is unauthenticated, but cache the raw JSON and the media
rather than resolving on demand, and keep HTML scraping as a fallback.

### Ninth Circuit: deterministic audio, awkward enumeration

Their site is a shell over an AWS API Gateway. Audio URLs are fully predictable:
`https://cdn.ca9.uscourts.gov/datastore/media/{YYYY}/{MM}/{DD}/{case_num}.mp3`
(older hearings use `.wma`). Audio goes back to 2003; YouTube video starts
around 2016. The API hard-caps at 50 results with no working pagination, so
enumerate through the YouTube channel (`UCeIMdiBTNTpeA84wmSRPDPg`) or their
sitemap, then use the CA9 API for authoritative metadata such as panel
composition, which YouTube titles do not carry.

### C-SPAN: excluded, and we should not revisit it

Two independent blockers. Their `robots.txt` disallows a named list of AI
crawlers including `ClaudeBot`, `Claude-Web`, and `anthropic-ai`. Their terms
then prohibit using any content "in connection with any training, prompting,
development, modification, validation" of an AI system without a license, and
they claim their whole library as Content even where the underlying government
feed is public domain. Separately, the Supreme Court bans cameras, so C-SPAN's
Supreme Court coverage is audio over stills rather than courtroom video. Maximum
legal exposure for the least usable video. Use the Court's own MP3s or Oyez.

### IRMCT Unified Court Records: exceptional content, permission first

Video does exist (ICTY, ICTR, and Mechanism hearings, four audio channels each,
with professional verbatim transcripts already aligned, meaning near-zero
transcription cost). But the site is an ASP.NET app behind mandatory
registration and reCAPTCHA with no public API, no sitemap, and no feed. Building
an authenticated crawler is exactly what that gate exists to prevent, so the
correct move is to email `UCRSupport@irmct.org` and ask for bulk or archival
access. They are a UN body with a public-access mandate, the lead time is free,
and a dump would be cheaper than scraping. Note the procedure is civil-law and
hybrid international, so it teaches comparative practice rather than American
trial technique.

### Bonus verified: UN Web TV

Kaltura-backed with unsigned public manifests:
`https://cdnapisec.kaltura.com/p/2503451/sp/250345100/playManifest/entryId/{id}/format/applehttp/protocol/https/a.m3u8`
(verified 1080p master playlist). Holds ICJ hearings, though the site skews
heavily to Security Council and General Assembly meetings, so it needs
filtering. The ICC publishes hearings to YouTube `@intlcriminalcourt` in
per-case playlists, which is the stable path there.

### Build order

1. Cameras in Courts, for full US trials. Self-sufficient and the best content match.
2. Ninth Circuit, for appellate argument technique.
3. UN Web TV and ICC, for international material.
4. IRMCT, only if they grant access.

One flag worth a counsel review before commercial use: these are federal
judiciary recordings with no usage restriction we could find, but "no
restriction found" is not a cleared license, especially for footage showing
identifiable jurors, witnesses, or minors.

## Primary corpus: Depp v. Heard (Fairfax County, VA, 2022)

Best single archive: fully livestreamed pool feed, very clean audio, dense
objection activity, long cross-examinations, and three kinds of contradiction
material in one case:
- Same witness across days: Depp testified Days 6-9 (Apr 19-25) AND in rebuttal
  (May 25); Heard testified May 4-5, May 16-17, and rebuttal May 26-27.
- Video depositions played in open court (inside the trial streams), e.g.
  Kate James (Heard's ex-assistant).
- Cross built on prior-statement impeachment (Heard confronted with her own
  deposition): ground truth for the contradiction finder.

Links (Law&Crime Network pool feed):
- Full playlist "Johnny Depp v. Amber Heard | Complete Coverage":
  https://www.youtube.com/playlist?list=PLsbUyvZas7gKWqg9kHsVUYZ3amSMwoyk0
- Day 17 full day (~7-9 h): https://www.youtube.com/watch?v=QT0MRSJ33EA
- Depp rebuttal cross (archive.org mirror): https://archive.org/details/youtube-cJ5sDMdzVRs
- Heard rebuttal testimony (segment): https://www.youtube.com/watch?v=FfnXPXVPKJk
- Kate James testimony (segment): https://www.youtube.com/watch?v=iPSvDxcBqIQ

Ingest plan: 2-3 targeted segments (one direct, one cross, one rebuttal), not
full 8-hour days: keeps indexing cost/time bounded while covering all demo
beats.

## Backup 1: State v. Alex Murdaugh (SC, 2023)

~9-hour cross-examination of the defendant across two days (Feb 23-24);
prosecutor repeatedly confronts him with prior police interviews: built-in
same-witness contradiction. Softer speech + Southern accents = ASR stress test.
- Feb 23 full cross: https://www.youtube.com/watch?v=YRujbqLiXFc
- Court TV cross Pt. 1: https://www.youtube.com/watch?v=op4Hbd7iJ_0
- Pt. 2: https://www.youtube.com/watch?v=MaHs3DM-WmM
- Night-of-murders segment: https://www.youtube.com/watch?v=HPSY9dCNol4

## Backup 2: Minnesota v. Derek Chauvin (2021)

Cleanest audio (court-ordered pool broadcast), textbook direct/cross structure,
strong expert testimony (Dr. Tobin). Caution: emotionally heavy content for a
demo audience.
- Day 1: https://www.youtube.com/watch?v=1g-xhoo-9Ac
- Day 2 (3/30): https://www.youtube.com/watch?v=sZ92-geeYBo
- Day 3 (3/31): https://www.youtube.com/watch?v=GZMdt1RDGVE
- Day 4 (4/1): https://www.youtube.com/watch?v=qz_BwDvd6Cw

## Secondary corpus: Bill Gates deposition (US v. Microsoft, 1998)

Pure deposition footage, DOJ-released court exhibit → cleanest rights profile
of everything here (public record). VHS-era audio: good "handles archival
quality" demonstration. Trial itself wasn't filmed, so contradiction would be
deposition-vs-transcript only.
- 12-part playlist: https://www.youtube.com/playlist?list=PL96F5PDvO1HGU_ww5qATtfOifbVYKnKoO
- Part 1: https://www.youtube.com/watch?v=elz6Yj6qgG4
- Highlights: https://www.youtube.com/watch?v=gRelVFm7iJE
- DOJ records: https://www.justice.gov/atr/cases/ms_depos.htm

## Ruled out

- Johnson v. Monsanto: footage paywalled at CVN, not YouTube-ingestable.
- Rittenhouse: politically charged; no angle Depp/Murdaugh don't cover better.
- OJ Simpson: 1995 SD quality, fragmented uploads, murkier network rights.

## Rights note

Court pool feeds are public record; broadcaster logo bugs / lower-thirds /
anchor commentary at recesses are present on Law&Crime/Court TV uploads, trim
or timestamp around commentary. The Gates deposition is the cleanest option if
rights questions come up at judging.
