# Submission checklist

The three components the hackathon requires, and where each one is. An entry
missing any of them is disqualified before it reaches judges.

| Requirement | Where |
|---|---|
| Working demo on real archived media | https://precedent-production-900c.up.railway.app |
| Public code repository | https://github.com/shubham-jaiswal0703/precedent |
| Description, 200 words max | [README.md](README.md#in-200-words), 198 words |

The description lives in the README rather than here, so there is one copy of it
and the repo's front page is the first thing a judge reads.

## Demo notes

The two-minute run of show is in `DEMO.md`, kept local rather than in the repo.
Sources and their terms of use are in [SOURCES.md](SOURCES.md): C-SPAN was
deliberately excluded because its robots.txt names AI crawlers and its terms
prohibit this use, and IRMCT footage requires written permission.

Warm the caches before demoing. A cold case pack takes minutes to build and under
a second once cached:

```bash
.venv/bin/python scripts/warm_caches.py
```
