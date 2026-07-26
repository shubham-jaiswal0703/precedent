# Hosting

The good news: **VideoDB carries all the heavy weight**: storage, transcoding,
indexing, search, clip generation, and HLS streaming all happen on their
infrastructure, and the browser streams video directly from
`play.videodb.io` / `stream.videodb.io`. Our server only routes JSON. No GPU,
no video egress, no large disk. It fits on the smallest instance any host sells.

## Recommendation

**For the hackathon and first pilots: Railway or Render.** Deploy straight from
the GitHub repo, HTTPS and a domain included, ~$5-7/month, no infra work. Set
`VIDEO_DB_API_KEY` as an environment variable: never commit it.

**If you want the setup you already know: a GCP `e2-small` VM with systemd +
Caddy** (the same pattern as the AEO Tracker deploy). ~$13/month, full control,
easy to attach a persistent disk for the catalog.

**Cloud Run is tempting but has a catch.** Scale-to-zero is ideal for demo
traffic, but our ingest jobs run 2+ minutes and job state currently lives in an
in-process dict: a container that scales down mid-ingest loses it. Use Cloud
Run only after the two fixes below.

## What survives a redeploy, and what does not

Railway builds from the repo, so all code and the committed `data/` caches
(catalog, moments, thumbnails, clip URLs, gallery) ship with the image and the
deployed site is fast on first visit.

What does not survive: anything the deployed app writes at runtime. A video
ingested through "Add a Link" on the live site, and any cache it warms, lives
only in that container. Saved prep sets are deliberately kept in the browser's
localStorage for this reason, so a student never loses their set to a deploy.
To grow the hosted library, ingest locally and push the updated `data/`.

## Two things to fix before real multi-user hosting

1. **State is on local disk.** `data/catalog.json`, `data/casepacks/`, and
   `data/contradictions/` are files. On ephemeral or multi-instance hosting they
   vanish or diverge. Move the catalog and moment records to Postgres (managed PG
   is one click on Railway/Render).
2. **Long jobs run in-process.** `/api/analyze` uses FastAPI background tasks and
   an in-memory `JOBS` dict. Replace with VideoDB's `callback_url` webhooks, every long-running SDK call accepts one: so indexing survives restarts and
   scales across instances.

## Cost shape

Our hosting is the rounding error; VideoDB usage is the real cost:
transcription ~$0.01/min, scene indexing ~$0.003/scene, search ~$1.50/1k
queries, storage ~$0.03/GB/month, streaming ~$0.07/GB. A 200-item appellate
corpus (~400 hours of audio) is roughly $240 of transcription, one time. Worth
budgeting deliberately before bulk-ingesting CourtListener.

## Docker

A `Dockerfile` is included, so any container host works:

```bash
docker build -t precedent .
docker run -p 8321:8321 -e VIDEO_DB_API_KEY=sk-... precedent
```
