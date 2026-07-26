"""Output formats: separate clips, and vertical reframing.

Two things a professor actually asks for that a single stitched landscape reel
cannot give them.

*Separate clips* because a reel is one artifact but a class needs eight. You
play clip three, talk over it, then play clip four when you are ready. Stitching
is a convenience, not the only useful shape.

*Vertical* because a clip that travels (a phone, a slide, a social post) has to
be 9:16. VideoDB does this with `video.reframe(target="vertical", mode="smart")`,
which tracks the speaker rather than centre-cropping, and it costs real time:
roughly five minutes of processing for twenty seconds of footage. So it runs as
a background job and every result is cached forever, because the same teaching
clip gets asked for again and again.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .. import store
from ..catalog import get_session
from ..config import get_connection
from ..media import session_thumbnail
from ..search.engine import PlayableMoment, clip_url

VERTICAL_CACHE = "verticals"   # key -> {"video_id", "stream_url"}
VERTICAL_JOBS = "vertical_jobs"  # key -> {"state", "error", "updated"}


@dataclass
class ClipOut:
    """One standalone clip, ready to play or hand out."""
    index: int
    label: str
    session_title: str
    video_id: str
    start: float
    end: float
    seconds: float
    stream_url: str = ""
    poster: str = ""
    text: str = ""
    aspect: str = "16:9"
    vertical_key: str = ""
    vertical_state: str = ""      # "", "queued", "processing", "ready", "failed"
    vertical_stream_url: str = ""
    vertical_error: str = ""


def key_for(video_id: str, start: float, end: float) -> str:
    return f"{video_id}:{round(start, 1)}:{round(end, 1)}"


VERTICAL_CACHE_INSTANT = "verticals_instant"


def vertical_instant(video_id: str, start: float, end: float) -> str:
    """A 9:16 clip built by setting the output size, not by reframing.

    The editor timeline's output resolution is ours to choose, so a single-clip
    timeline at 1080x1920 with a centre crop returns immediately. Smart
    reframing tracks the speaker and looks better on an off-centre subject, but
    it costs minutes per clip, so this is the default and that is the upgrade.
    """
    key = key_for(video_id, start, end)
    cache = store.read(VERTICAL_CACHE_INSTANT, {}) or {}
    if key in cache:
        return cache[key]

    from videodb.editor import Clip, Fit, Position, Timeline, Track
    from videodb.editor import VideoAsset as EditorVideoAsset

    from ..reels.builder import VERTICAL

    editor = Timeline(get_connection())
    editor.resolution = VERTICAL
    editor.background = "#000000"
    track = Track(z_index=0)
    editor.add_track(track)
    track.add_clip(
        0,
        Clip(EditorVideoAsset(video_id, start=start), duration=max(1.0, end - start),
             fit=Fit.crop, position=Position.center),
    )
    url = editor.generate_stream()
    cache[key] = url
    store.write(VERTICAL_CACHE_INSTANT, cache)
    return url


def separate_clips(moments: List[PlayableMoment], seconds_per_clip: float = 30.0,
                   max_total_seconds: Optional[float] = None,
                   aspect: str = "16:9", vertical_mode: str = "instant") -> List[ClipOut]:
    """Each moment as its own playable clip, in order, nothing stitched."""
    out: List[ClipOut] = []
    spent = 0.0
    for moment in moments:
        if max_total_seconds is not None and max_total_seconds - spent <= 2:
            break
        span = min(moment.end - moment.start, seconds_per_clip)
        if max_total_seconds is not None:
            span = min(span, max_total_seconds - spent)
        if span < 2:
            continue
        end = moment.start + span
        attrs = moment.attrs or {}
        label_bits = [str(attrs.get("label") or attrs.get("moment_type") or "").replace("_", " ")]
        if attrs.get("ground"):
            label_bits.append(str(attrs["ground"]).replace("_", " "))
        if attrs.get("ruling"):
            label_bits.append(str(attrs["ruling"]))
        clip = ClipOut(
            index=len(out) + 1,
            label=" | ".join(b for b in label_bits if b.strip()) or (moment.session_title or "Moment"),
            session_title=moment.session_title,
            video_id=moment.video_id,
            start=round(moment.start, 1),
            end=round(end, 1),
            seconds=round(span, 1),
            poster=moment.poster or session_thumbnail(moment.video_id),
            text=(attrs.get("highlight", {}).get("quote") or moment.text or "")[:300],
            aspect=aspect,
            vertical_key=key_for(moment.video_id, moment.start, end),
        )
        try:
            clip.stream_url = clip_url(moment.video_id, moment.start, end)
        except Exception:
            pass
        spent += span
        out.append(clip)

    if aspect == "9:16":
        for clip in out:
            if vertical_mode == "instant":
                try:
                    clip.vertical_stream_url = vertical_instant(clip.video_id, clip.start, clip.end)
                    clip.vertical_state = "ready"
                    continue
                except Exception as exc:
                    clip.vertical_state = "failed"
                    clip.vertical_error = str(exc)[:160]
                    continue
            cached = (store.read(VERTICAL_CACHE, {}) or {}).get(clip.vertical_key)
            if cached:
                clip.vertical_state = "ready"
                clip.vertical_stream_url = cached.get("stream_url", "")
            else:
                clip.vertical_state = request_vertical(clip.video_id, clip.start, clip.end)["state"]
    return out


def vertical_status(keys: List[str]) -> Dict[str, dict]:
    """Where each requested vertical clip has got to."""
    cache = store.read(VERTICAL_CACHE, {}) or {}
    jobs = store.read(VERTICAL_JOBS, {}) or {}
    out: Dict[str, dict] = {}
    for key in keys:
        if key in cache:
            out[key] = {"state": "ready", "stream_url": cache[key].get("stream_url", "")}
        else:
            out[key] = {"state": (jobs.get(key) or {}).get("state", "unknown"),
                        "error": (jobs.get(key) or {}).get("error", "")}
    return out


def request_vertical(video_id: str, start: float, end: float) -> dict:
    """Start (or join) a vertical reframe for one clip."""
    key = key_for(video_id, start, end)
    cache = store.read(VERTICAL_CACHE, {}) or {}
    if key in cache:
        return {"state": "ready", "stream_url": cache[key].get("stream_url", ""), "key": key}

    jobs = store.read(VERTICAL_JOBS, {}) or {}
    current = (jobs.get(key) or {}).get("state")
    if current in ("queued", "processing"):
        return {"state": current, "key": key}

    jobs[key] = {"state": "queued", "updated": time.time()}
    store.write(VERTICAL_JOBS, jobs)
    threading.Thread(target=_reframe, args=(key, video_id, start, end), daemon=True).start()
    return {"state": "queued", "key": key}


def _set_job(key: str, patch: dict) -> None:
    jobs = store.read(VERTICAL_JOBS, {}) or {}
    job = jobs.get(key, {})
    job.update(patch)
    job["updated"] = time.time()
    jobs[key] = job
    store.write(VERTICAL_JOBS, jobs)


def _reframe(key: str, video_id: str, start: float, end: float) -> None:
    """Smart vertical reframe. Slow, so this always runs off the request path."""
    _set_job(key, {"state": "processing"})
    try:
        session = get_session(video_id)
        conn = get_connection()
        coll = conn.get_collection(session.collection_id) if session else conn.get_collection()
        video = coll.get_video(video_id)
        reframed = video.reframe(start=start, end=end, target="vertical", mode="smart")
        if not reframed:
            raise RuntimeError("reframe returned nothing")
        stream_url = reframed.generate_stream()
        cache = store.read(VERTICAL_CACHE, {}) or {}
        cache[key] = {"video_id": reframed.id, "stream_url": stream_url,
                      "source": video_id, "start": start, "end": end}
        store.write(VERTICAL_CACHE, cache)
        _set_job(key, {"state": "ready"})
    except Exception as exc:
        _set_job(key, {"state": "failed", "error": str(exc)[:300]})
