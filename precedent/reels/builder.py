"""Teaching reels: stitch moments from anywhere in the library into one stream.

A reel drawn from a single case is a clip show. The point of a teaching reel is
comparison, so these are built across cases by default: five sustained
objections from five different courtrooms teach more than five from one.

Two knobs matter to a professor building one: how long each clip runs, and how
long the whole thing runs, because a reel has to fit the slot in a class.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from videodb import TextStyle
from videodb.asset import AudioAsset, TextAsset, VideoAsset
from videodb.timeline import Timeline

# A chapter card should look deliberate, not like debug text on a video.
CARD_STYLE = TextStyle(
    fontsize=34,
    fontcolor="white",
    font="Georgia",
    box=True,
    boxcolor="black@0.65",
    boxborderw="18",
    y_align="text",
    text_align="C",
)

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
    voiceover: str = ""  # spoken intro text, read over the opening clip


@dataclass
class Segment:
    """One clip inside the reel, with where it sits in the finished stream."""
    index: int
    label: str
    session_title: str
    video_id: str
    source_start: float
    reel_start: float
    reel_end: float
    text: str = ""


@dataclass
class ReelResult:
    stream_url: str
    count: int
    total_seconds: float
    subtitles: bool = False
    subtitle_note: str = ""
    sources: List[str] = field(default_factory=list)
    segments: List[Segment] = field(default_factory=list)


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
    """Compile moments into one playable teaching reel.

    Everything is built on a single editor timeline: video, chapter cards, and
    captions are separate tracks on the same composition. An earlier version
    rebuilt the reel from scratch when captions were requested, which silently
    dropped every chapter card, so a subtitled reel arrived as one unbroken
    block with no visible structure.
    """
    spec = spec or ReelSpec()
    if title_cards is not None:
        spec.title_cards = title_cards
    if max_clip_seconds is not None:
        spec.seconds_per_clip = max_clip_seconds
    if not moments:
        raise ValueError("No moments to compile")

    plan: List[Segment] = []
    offset = 0.0
    for moment in moments:
        if spec.max_total_seconds is not None and spec.max_total_seconds - offset <= 2:
            break
        span = min(moment.end - moment.start, spec.seconds_per_clip)
        if spec.max_total_seconds is not None:
            span = min(span, spec.max_total_seconds - offset)
        if span < 2:
            continue
        plan.append(Segment(
            index=len(plan) + 1,
            label=_label_for(moment),
            session_title=moment.session_title,
            video_id=moment.video_id,
            source_start=round(moment.start, 1),
            reel_start=round(offset, 1),
            reel_end=round(offset + span, 1),
            text=((moment.attrs or {}).get("highlight", {}).get("quote") or moment.text or "")[:300],
        ))
        offset += span

    if not plan:
        raise ValueError("Every moment was shorter than the minimum clip length")

    conn = get_connection()
    note = ""
    try:
        stream_url = _compose(conn, moments, plan, spec)
    except Exception as exc:
        # The editor API is newer; fall back to the proven timeline rather than
        # failing the request, and say what was lost.
        stream_url = _compose_legacy(conn, moments, plan, spec)
        note = f"Built without captions ({type(exc).__name__})"

    if download_name:
        try:
            conn.download(stream_url, download_name)
        except Exception:
            pass

    return ReelResult(
        stream_url=stream_url,
        count=len(plan),
        total_seconds=round(offset, 1),
        subtitles=spec.subtitles and not note,
        subtitle_note=note,
        sources=sorted({s.session_title for s in plan if s.session_title}),
        segments=plan,
    )


def _compose(conn, moments: List[PlayableMoment], plan: List["Segment"], spec: ReelSpec) -> str:
    """One editor timeline: video, chapter cards, and captions as three tracks."""
    from videodb.editor import (Background, Clip, FontStyling, Position,
                                Timeline as EditorTimeline, Track)
    from videodb.editor import CaptionAsset, TextAsset as EditorTextAsset
    from videodb.editor import VideoAsset as EditorVideoAsset

    editor = EditorTimeline(conn)
    video_track = Track(z_index=0)
    editor.add_track(video_track)
    for segment in plan:
        video_track.add_clip(
            segment.reel_start,
            Clip(EditorVideoAsset(segment.video_id, start=segment.source_start),
                 duration=segment.reel_end - segment.reel_start),
        )

    if spec.title_cards:
        card_track = Track(z_index=1)
        editor.add_track(card_track)
        for segment in plan:
            span = min(spec.label_seconds, segment.reel_end - segment.reel_start)
            card_track.add_clip(
                segment.reel_start,
                Clip(
                    EditorTextAsset(
                        text=f"{segment.index}. {segment.label}",
                        font=FontStyling(name="Georgia", size=30, bold=True),
                        background=Background(color="#000000", opacity=0.62,
                                              border_width=14.0),
                    ),
                    duration=span,
                    position=Position.bottom,
                ),
            )

    if spec.subtitles:
        caption_track = Track(z_index=2)
        editor.add_track(caption_track)
        caption_track.add_clip(0, Clip(CaptionAsset(src="auto"),
                                       duration=plan[-1].reel_end))
    return editor.generate_stream()


def _compose_legacy(conn, moments: List[PlayableMoment], plan: List["Segment"], spec: ReelSpec) -> str:
    """The proven timeline: inline clips plus text overlays, no captions."""
    timeline = Timeline(conn)
    for segment in plan:
        timeline.add_inline(VideoAsset(asset_id=segment.video_id, start=segment.source_start,
                                       end=segment.source_start + (segment.reel_end - segment.reel_start)))
        if spec.title_cards:
            timeline.add_overlay(
                segment.reel_start,
                TextAsset(text=f"{segment.index}. {segment.label}",
                          duration=min(spec.label_seconds, segment.reel_end - segment.reel_start),
                          style=CARD_STYLE),
            )
    if spec.voiceover:
        audio_id = _voiceover_asset(conn, spec.voiceover)
        if audio_id:
            timeline.add_overlay(0, AudioAsset(asset_id=audio_id, disable_other_tracks=True,
                                               fade_out_duration=1))
    return timeline.generate_stream()


def _voiceover_asset(conn, text: str) -> str:
    """Generate a short TTS intro. A reel without one is fine, so never raise."""
    try:
        coll = conn.get_collection()
        audio = coll.generate_voice(text=text[:400])
        return getattr(audio, "id", "") or ""
    except Exception:
        return ""


def side_by_side(conn, left, right, seconds: float = 45.0) -> str:
    """Render a contradiction pair as one clip, both statements on screen.

    Two video tracks on the editor timeline, each scaled to half width. This is
    the exportable version of the split-screen the browser shows.
    """
    from videodb.editor import Clip, Position, Timeline as EditorTimeline, Track
    from videodb.editor import VideoAsset as EditorVideoAsset

    editor = EditorTimeline(conn)
    duration_left = min(seconds, left.end - left.start)
    duration_right = min(seconds, right.end - right.start)
    span = max(duration_left, duration_right)

    left_track = Track(z_index=0)
    editor.add_track(left_track)
    left_track.add_clip(0, Clip(EditorVideoAsset(left.video_id, start=left.start),
                                duration=span, scale=0.5, position=Position.left))
    right_track = Track(z_index=1)
    editor.add_track(right_track)
    # volume lives on the asset, not the clip; mute the right side so the two
    # statements do not talk over each other
    right_track.add_clip(0, Clip(EditorVideoAsset(right.video_id, start=right.start, volume=0),
                                 duration=span, scale=0.5, position=Position.right))
    return editor.generate_stream()


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
