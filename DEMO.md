# Precedent: 2 minute live demo

**Live:** https://precedent-production-900c.up.railway.app/

## Before you start (5 minutes, do not skip)

```bash
.venv/bin/python scripts/warm_demo.py --base https://precedent-production-900c.up.railway.app
```

Every beat below is a cached request afterwards. Cold, some of them take up to
**56 seconds**; warm they are all under one second. The script prints a second
pass so you can see exactly what the demo will feel like. Run it after any
deploy.

Then:

* Open the site, click through all five beats once. This puts the video segments
  in the browser cache too.
* Confirm `/api/health` reports the commit you expect. Railway can hold a
  rollout queued for several minutes after a push.
* Volume up. Beat 4 is audio only.
* Have a second tab already on `/room` in case beat 4 needs to be reached fast.

## The script

**Opening line, before you touch anything (0:00 to 0:12)**

> "Law is taught from books, but advocacy is a performance. Thousands of hours of
> real courtroom footage are public, and nobody can watch forty hours of trial to
> find the three minutes that matter. This is Precedent."

---

### Beat 1: The library exists (0:12 to 0:30)

Land on **Prepare**, then click **Library**.

> "Forty seven hours of real proceedings: Supreme Court arguments, federal
> appellate arguments, and full federal trials, all public record. Fourteen
> hundred indexed courtroom moments."

Point at one card's chips: *Objections 19, Sustained rulings 7*.

> "Every case arrives labelled by what actually happens inside it."

---

### Beat 2: Ask like a professor (0:30 to 0:55)

Go to **Search**, archive **Depp v. Heard**, type:

```
show me every sustained objection
```

Wait for the banner, then read it out.

> "Read as: objections that were sustained. That is not a keyword match. Nobody
> in a courtroom says the word 'sustained objection', so this is a structured
> index of courtroom events, filtered by how the judge ruled."

Press play on the first clip. Let two seconds of audio run.

> "The answer is the moment, not a page citation."

Then, without clearing the box, type:

```
FRE 611 leading question
```

> "And this is the one that convinces a law professor. Nobody says 'Rule 611'
> out loud in a trial. The system knows 611 means leading questions and goes to
> the objection log."

---

### Beat 3: Read the room (0:55 to 1:20) — the moment that lands

Click **Read the Room**, then the example chip **witness under accusation**.

> "The transcript tells you what was said. A vision model over the same footage
> tells you what the camera saw while it was being said."

Point at the observation list under the player.

> "Thirty four seconds, broken down every few seconds: her expression, her
> posture, where her eyes go. Click any line and it jumps to the exact second it
> describes, so you can check the claim against the footage."

Click the `+18s` observation. Let it play briefly.

---

### Beat 4: Contradiction across time (1:20 to 1:40)

Click **Library**, open **Depp v. Heard**, expand **Contradictions in this
witness's testimony**.

> "Same witness, ten days apart. The system extracted her factual claims from
> one session, searched the other for the same topic, and judged the pair. Two
> clips, side by side, and it tells you the testimony evolved rather than
> claiming a lie it cannot prove."

---

### Beat 5: A reel a professor can teach from (1:40 to 1:55)

Click **Teaching Reel**. The query is already there, or type `sustained
objection`. Leave scope on **the whole library**. Click **Build reel**.

> "Eight objections from eight different courtrooms, stitched, chaptered, with
> burned in subtitles. Every chapter is clickable, so you can jump between
> examples mid class."

Click chapter 3 to prove the navigation.

---

### Close (1:55 to 2:00)

> "Students used to read this in a book. Now they watch the moment."

## If something goes wrong

| Problem | What to do |
|---|---|
| A search hangs past 3 seconds | You skipped the warm-up. Switch to a chip you already clicked; they are cached. |
| A clip will not play | Reload the page once; hls.js occasionally needs a fresh attach. Move to the next beat rather than debugging on stage. |
| A SCOTUS clip shows no picture | Correct behaviour. Say it: cameras are banned in the Supreme Court, so the record is audio and the UI says so. |
| Reel build is slow | Drop `Clips` to 4 and untick subtitles. Subtitles add a caption pass. |
| The whole site is down | Have `/api/health` open in a tab. If Railway is mid rollout, talk through the architecture slide until it returns. |

## Questions judges will ask, and honest answers

**"Is this just transcript search?"** No. Half the queries are filters over a
structured index of courtroom events, not similarity search. That is why "every
sustained objection" and "FRE 611" work at all, and why a plain vector search
returns a judge adjourning for the day instead.

**"Does the expression analysis work on everything?"** No, and it cannot. Three
sessions have it, because they are the only ones with faces. The Supreme Court
and the appellate courts ban cameras, so most of the library is audio. We show
that limit in the interface rather than hiding it.

**"How do you know the AI is not making things up?"** Every claim carries a
playable citation to the second. The grounded answers are built only from
transcript excerpts we retrieved, and if the record does not answer the
question the system says so. The expression descriptions sit next to the clip
precisely so they can be checked.

**"Could this scale?"** The ingest path already handles three bulk sources.
Cameras in Courts alone is 990 recordings, about 1,100 hours of complete federal
trials, and the ingester works today. We capped the corpus deliberately: for a
demo, depth beats volume.

**"What is genuinely hard here?"** Making the retrieval unit a *pedagogically
complete* moment. An objection clip is useless unless it contains the question,
the objection, the ground, and the ruling. That boundary logic, plus knowing
which index answers which question, is the actual work.
