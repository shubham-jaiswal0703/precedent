"""Teaching reels — stitch moments from across the archive into one stream."""
from typing import List, Optional

from videodb.asset import TextAsset, VideoAsset
from videodb.timeline import Timeline

from ..config import get_connection
from ..search.engine import PlayableMoment


def build_reel(
    moments: List[PlayableMoment],
    title_cards: bool = True,
    max_clip_seconds: float = 45.0,
    download_name: Optional[str] = None,
) -> str:
    """Compile moments into a single playable teaching reel.

    Returns the stream URL; optionally also downloads an MP4 via VideoDB.
    """
    if not moments:
        raise ValueError("No moments to compile")
    conn = get_connection()
    timeline = Timeline(conn)
    offset = 0.0
    for m in moments:
        end = min(m.end, m.start + max_clip_seconds)
        duration = end - m.start
        timeline.add_inline(VideoAsset(asset_id=m.video_id, start=m.start, end=end))
        if title_cards:
            label = m.attrs.get("label") or m.session_title or "Precedent"
            timeline.add_overlay(
                offset,
                TextAsset(text=label, duration=min(4.0, duration)),
            )
        offset += duration
    stream_url = timeline.generate_stream()
    if download_name:
        conn.download(stream_url, download_name)
    return stream_url
