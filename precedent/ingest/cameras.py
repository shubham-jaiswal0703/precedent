"""Cameras in Courts: complete federal trials, the best corpus we have found.

The federal judiciary's Cameras in Courts pilot published 990 recordings,
roughly 1,100 hours, of whole jury and bench trials from 2011 onward. Unlike
appellate audio, these contain the behavior a trial advocacy course is about:
opening statements, direct and cross examination, objections and rulings,
sidebars, and closings.

The archive sits on a Piksel tenant. The enumeration endpoint and media URLs
below were lifted from the player's own JavaScript, so they carry no
compatibility promise: cache what we fetch rather than resolving on demand,
and expect to fall back to scraping the case pages if this moves.

Each program's description is a fielded string we can parse into real case
metadata:

    Beckford et al v. The Children's Group, Inc., 3:24-cv-06468-CRB,
    Civil Rights, 03/27/2026, 10:00am, Phillip Burton Federal Building,
    San Francisco, CA, Judge Charles R. Breyer presiding
"""
import json
import re
import tempfile
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional
from xml.etree import ElementTree

from ..catalog import SessionEntry, sessions_for_case, upsert_session
from .pipeline import get_or_create_case_collection

PROJECT_UUID = "dae5e892-195f-11f0-8b80-0a9cbef903c7"
PROJECT_KEY = "d8125233"
LIST_URL = (f"https://player.piksel.tech/ws/ws_program/api/{PROJECT_UUID}"
            f"/mode/json/apiv/5?p={PROJECT_KEY}")
PAGE_SIZE = 21  # the endpoint caps here regardless of what we ask for
UA = {"User-Agent": "Precedent/0.1 (legal education research)"}

DOCKET_RE = re.compile(r"\b(\d+:\d{2}-[a-z]{2,3}-\d{3,6}(?:-[A-Za-z]{1,5})?)\b")
JUDGE_RE = re.compile(r"(?:Judge|Chief Judge|Magistrate Judge)\s+([A-Z][^,]{2,40}?)\s+presiding", re.I)
DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
PROCEEDING_WORDS = (
    "jury trial", "bench trial", "trial", "hearing", "motion", "sentencing",
    "argument", "conference", "arraignment", "naturalization",
)


@dataclass
class Program:
    uuid: str
    title: str
    description: str
    duration: float
    thumbnail: str = ""
    smil: str = ""
    asset_id: str = ""
    docket: str = ""
    judge: str = ""
    date: str = ""
    proceeding: str = ""
    courthouse: str = ""

    @property
    def case_slug(self) -> str:
        """Group parts of the same trial under one case."""
        if self.docket:
            return "trial-" + re.sub(r"[^a-z0-9]+", "-", self.docket.lower()).strip("-")
        return "trial-" + re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:48]


def _get(url: str, timeout: int = 90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_description(text: str) -> Dict[str, str]:
    """Pull case metadata out of the fielded description string."""
    out: Dict[str, str] = {}
    if not text:
        return out
    docket = DOCKET_RE.search(text)
    if docket:
        out["docket"] = docket.group(1)
    judge = JUDGE_RE.search(text)
    if judge:
        out["judge"] = judge.group(1).strip()
    date = DATE_RE.search(text)
    if date:
        month, day, year = date.group(1).split("/")
        out["date"] = f"{year}-{month}-{day}"
    lowered = text.lower()
    for word in PROCEEDING_WORDS:
        if word in lowered:
            out["proceeding"] = word
            break
    building = re.search(r"([A-Z][A-Za-z.\' ]+(?:Building|Courthouse|Court House|Courts))", text)
    if building:
        out["courthouse"] = building.group(1).strip()
    return out


def list_programs(start: int = 0, size: int = PAGE_SIZE) -> tuple:
    """One page of programs, plus the archive's total count."""
    payload = json.loads(_get(f"{LIST_URL}&size={size}&start={start}"))
    # The endpoint sometimes wraps its body in "response" and sometimes does not.
    resp = (payload.get("WsProgramResponse")
            or payload.get("response", {}).get("WsProgramResponse")
            or {})
    programs: List[Program] = []
    for raw in resp.get("programs", []):
        asset = raw.get("asset") or {}
        description = raw.get("Description") or asset.get("description") or ""
        title = raw.get("Title") or asset.get("title") or ""
        meta = parse_description(description)
        thumb = asset.get("thumbnailUrl") or raw.get("thumbnailUrl") or ""
        if thumb and "?" not in thumb:
            thumb += "?w=1280&h=720"
        programs.append(Program(
            uuid=raw.get("uuid") or "",
            title=title.strip(),
            description=description.strip(),
            duration=float(raw.get("duration") or 0),
            thumbnail=thumb,
            smil=asset.get("httpSmil") or "",
            asset_id=str(asset.get("assetid") or ""),
            docket=meta.get("docket", ""),
            judge=meta.get("judge", ""),
            date=meta.get("date", ""),
            proceeding=meta.get("proceeding", ""),
            courthouse=meta.get("courthouse", ""),
        ))
    return programs, int(resp.get("totalCount") or 0)


def iter_programs(limit: Optional[int] = None) -> Iterator[Program]:
    """Walk the archive. 990 programs is 48 requests at the enforced page size."""
    start, seen, total = 0, 0, None
    while total is None or start < total:
        programs, total = list_programs(start)
        if not programs:
            return
        for program in programs:
            yield program
            seen += 1
            if limit and seen >= limit:
                return
        start += len(programs)


def mp4_url(smil_url: str, prefer: str = "smallest") -> str:
    """A progressive MP4 from a SMIL manifest.

    Default to the smallest rendition. The top rendition of a three-hour trial
    is over a gigabyte, which VideoDB's fetcher gives up on, and we are indexing
    speech and cutting clips rather than mastering video.
    """
    if not smil_url:
        return ""
    root = ElementTree.fromstring(_get(smil_url))
    ns = {"s": "http://www.w3.org/2001/SMIL20/Language"}
    base = ""
    for meta in root.iterfind(".//s:meta", ns):
        if meta.get("name") == "base":
            base = meta.get("base") or meta.get("content") or ""
    candidates = []
    for video in root.iterfind(".//s:video", ns):
        src = video.get("src") or ""
        if ".mp4" not in src:
            continue  # skip the HLS renditions; VideoDB ingests files
        candidates.append((int(video.get("system-bitrate") or 0), src))
    if not candidates:
        return ""
    candidates.sort()
    _, src = candidates[0] if prefer == "smallest" else candidates[-1]
    return f"{base}{src}"


RELAY_DIR = Path(tempfile.gettempdir()) / "precedent-relay"
MAX_RELAY_BYTES = 1_600_000_000  # about 2.5 hours at the smallest rendition


def _upload_via_relay(coll, url: str, program: Program):
    """Download the file here, then hand it to VideoDB as a local upload."""
    RELAY_DIR.mkdir(parents=True, exist_ok=True)
    target = RELAY_DIR / f"{program.uuid or program.asset_id}.mp4"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=180) as resp:
            size = int(resp.headers.get("content-length") or 0)
            if size > MAX_RELAY_BYTES:
                return None
            with open(target, "wb") as handle:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
        return coll.upload(file_path=str(target), name=program.title[:110] or program.uuid)
    finally:
        target.unlink(missing_ok=True)


def ingest_program(program: Program, index: bool = True) -> Optional[SessionEntry]:
    """Upload one trial recording and catalog it under its docket."""
    case_id = program.case_slug
    case_name = program.title or program.docket or "Federal trial"
    if program.judge:
        case_name = f"{case_name}"
    existing = {s.source_url for s in sessions_for_case(case_id)}

    url = mp4_url(program.smil)
    if not url or url in existing:
        return None

    coll = get_or_create_case_collection(case_id, case_name)
    try:
        media = coll.upload(url=url, name=program.title[:110] or program.uuid)
    except Exception:
        # The court CDN serves us fine but refuses VideoDB's fetcher (these
        # programs carry geo-filter flags), so relay the file ourselves.
        media = _upload_via_relay(coll, url, program)
    if not media or not str(media.id).startswith("m-"):
        return None

    entry = SessionEntry(
        video_id=media.id,
        case_id=case_id,
        title=program.title or program.uuid,
        session_type="trial_day",
        source_url=url,
        date=program.date,
        witnesses=[],
        collection_id=coll.id,
        duration=getattr(media, "length", None) or program.duration,
    )
    entry.indexes["thumbnail"] = program.thumbnail
    entry.indexes["judge"] = program.judge
    entry.indexes["docket"] = program.docket
    entry.indexes["proceeding"] = program.proceeding
    entry.indexes["courthouse"] = program.courthouse
    upsert_session(entry)

    if index:
        from ..indexing.indexer import index_spoken

        index_spoken(entry.video_id)
    return entry


def find_trials(min_minutes: float = 60.0, scan: int = 200) -> List[Program]:
    """Long recordings, which is what a full trial session looks like."""
    found = [p for p in iter_programs(limit=scan)
             if p.duration >= min_minutes * 60 and p.smil]
    found.sort(key=lambda p: -p.duration)
    return found


def group_by_case(programs: List[Program]) -> Dict[str, List[Program]]:
    """Sessions of the same trial, so a case can span days."""
    grouped: Dict[str, List[Program]] = {}
    for program in programs:
        grouped.setdefault(program.case_slug, []).append(program)
    for parts in grouped.values():
        parts.sort(key=lambda p: (p.date, p.title))
    return grouped
