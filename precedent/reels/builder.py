"""Teaching reels: stitch moments from anywhere in the library into one stream.

A reel drawn from a single case is a clip show. The point of a teaching reel is
comparison, so these are built across cases by default: five sustained
objections from five different courtrooms teach more than five from one.

Two knobs matter to a professor building one: how long each clip runs, and how
long the whole thing runs, because a reel has to fit the slot in a class.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from videodb.asset import TextAsset, VideoAsset
from videodb.timeline import Timeline

from ..config import get_connection
from ..search.engine import PlayableMoment


@dataclass
class ReelSpec:
    """What the reel should look like."""
    seconds_per_clip: float = 30.0
    max_total_seconds: Optional[float] = None
    title_cards: bool = True
    subtitles: bool = False
    label_seconds: float = 3.5


@dataclass
class ReelResult:
    stream_url: str
    count: int
    total_seconds: float
    subtitles: bool = False
    subtitle_note: str = ""
    sources: List[str] = field(default_factory=list)


def _label_for(moment: PlayableMoment) -> str:
    attrs = moment.attrs or {}
    bits = []
    if attrs.get("label"):
        bits.append(str(attrs["label"]))
    elif attrs.get("moment_type"):
        bits.append(str(attrs["moment_type"]).replace("_", " ").title())
    if attrs.get("ground"):
        bits.append(str(attrs["ground"]).replace("_", " "))
    if attrs.get("ruling"):
        bits.append(str(attrs["ruling"]))
    if moment.session_title:
        bits.append(moment.session_title[:44])
    return " | ".join(bits) or "Precedent"


def build_reel(
    moments: List[PlayableMoment],
    spec: Optional[ReelSpec] = None,
    download_name: Optional[str] = None,
    # kept for older callers that passed these positionally
    title_cards: Optional[bool] = None,
    max_clip_seconds: Optional[float] = None,
) -> ReelResult:
    """Compile moments into one playable teaching reel."""
    spec = spec or ReelSpec()
    if title_cards is not None:
        spec.title_cards = title_cards
    if max_clip_seconds is not None:
        spec.seconds_per_clip = max_clip_seconds
    if not moments:
        raise ValueError("No moments to compile")

    conn = get_connection()
    timeline = Timeline(conn)
    offset = 0.0
    used: List[PlayableMoment] = []

    for moment in moments:
        remaining = None
        if spec.max_total_seconds is not None:
            remaining = spec.max_total_seconds - offset
            if remaining <= 2:
                break
        span = min(moment.end - moment.start, spec.seconds_per_clip)
        if remaining is not None:
            span = min(span, remaining)
        if span < 2:
            continue
        end = moment.start + span

        timeline.add_inline(VideoAsset(asset_id=moment.video_id, start=moment.start, end=end))
        if spec.title_cards:
            timeline.add_overlay(
                offset,
                TextAsset(text=_label_for(moment), duration=min(spec.label_seconds, span)),
            )
        offset += span
        used.append(moment)

    if not used:
        raise ValueError("Every moment was shorter than the minimum clip length")

    stream_url = timeline.generate_stream()

    note = ""
    if spec.subtitles:
        captioned, note = _with_captions(conn, used, spec)
        if captioned:
            stream_url = captioned

    if download_name:
        try:
            conn.download(stream_url, download_name)
        except Exception:
            pass

    return ReelResult(
        stream_url=stream_url,
        count=len(used),
        total_seconds=round(offset, 1),
        subtitles=spec.subtitles and not note,
        subtitle_note=note,
        sources=sorted({m.session_title for m in used if m.session_title}),
    )


def _with_captions(conn, moments: List[PlayableMoment], spec: ReelSpec):
    """Rebuild the reel on the editor timeline so captions can be burned in.

    The legacy timeline has no caption track, so subtitles need the newer
    editor API. If that path fails we return the uncaptioned reel and say so,
    rather than failing the whole request over a nice-to-have.
    """
    try:
        from videodb.editor import CaptionAsset, Clip, Timeline as EditorTimeline, Track
        from videodb.editor import VideoAsset as EditorVideoAsset

        editor = EditorTimeline(conn)
        video_track = Track(z_index=0)
        editor.add_track(video_track)

        offset = 0.0
        for moment in moments:
            span = min(moment.end - moment.start, spec.seconds_per_clip)
            if spec.max_total_seconds is not None:
                span = min(span, max(0.0, spec.max_total_seconds - offset))
            if span < 2:
                break
            video_track.add_clip(
                offset,
                Clip(EditorVideoAsset(moment.video_id, start=moment.start), duration=span),
            )
            offset += span

        caption_track = Track(z_index=1)
        editor.add_track(caption_track)
        caption_track.add_clip(0, Clip(CaptionAsset(src="auto"), duration=offset))
        return editor.generate_stream(), ""
    except Exception as exc:
        return "", f"Captions unavailable on this reel ({type(exc).__name__})"
