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

## Persistence, and the two switches that turn it on

Both of the things that used to break on ephemeral hosting are fixed, and each
is controlled by one environment variable.

**1. State.** The catalog, caches, and job log used to be files, which vanish on
redeploy and diverge across instances. They now go through `precedent/store.py`,
which keeps them as JSON documents in Postgres when `DATABASE_URL` is set and in
files otherwise. On first boot against an empty database it seeds itself from the
documents committed in `data/`, so a fresh deploy starts with the warm library
rather than an empty one.

On Railway: add a Postgres service, then reference its connection string from the
app service. Railway exposes it as `DATABASE_URL` automatically when you add the
variable reference. Nothing else changes; `GET /api/health` reports which backend
is live.

**2. Long jobs.** Ingesting used to run in a FastAPI background task with an
in-memory dict, so a restart lost the job. Now `POST /api/analyze` returns a job
id immediately, job state lives in the store, and VideoDB calls
`POST /api/webhooks/videodb?job=<id>` when indexing finishes.

That needs a public address to call back to, so set `PUBLIC_BASE_URL` to the
deployment's own origin, for example
`https://precedent-production-900c.up.railway.app`. Without it the app falls back
to waiting in a background thread, which is still correct on a single instance,
just not restart-proof. `GET /api/health` also reports whether webhooks are wired,
and `GET /api/jobs` shows the persisted job log.

### Railway variables

```
VIDEO_DB_API_KEY   required
DATABASE_URL       reference the Postgres service, enables durable state
PUBLIC_BASE_URL    this deployment's origin, enables indexing webhooks
```

Deploys are automatic from `main`, so pushing is redeploying.

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
