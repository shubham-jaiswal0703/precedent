"""Live courtroom feed demo: index an RTSP stream in real time.

The same expression indexing that runs on the archive runs on a live feed.
Point any RTSP source at this (rtsp.me makes one from a phone camera in about
a minute) and watch scene descriptions arrive while the feed is running.

    .venv/bin/python scripts/live_demo.py connect rtsp://your-stream-url
    .venv/bin/python scripts/live_demo.py watch
    .venv/bin/python scripts/live_demo.py status

Honesty note for demo day: rehearse with the actual stream you will use. A VOD
test stream that ends mid-demo produces zero scenes and looks broken; a real
camera feed does not end.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from precedent.config import get_connection

STREAM_NAME = "precedent-live"
PROMPT = (
    "Describe what is visibly happening: who is in frame, their facial "
    "expressions, posture, and gestures, and any change of composure. "
    "Be concrete. If no people are visible, say so."
)


def _collection():
    return get_connection().get_collection()


def _stream():
    for stream in _collection().list_rtstreams():
        if stream.name == STREAM_NAME:
            return stream
    return None


def connect(url: str) -> None:
    coll = _collection()
    existing = _stream()
    if existing:
        print(f"already connected: {existing.id} ({existing.status})")
        return
    stream = coll.connect_rtstream(url=url, name=STREAM_NAME)
    print(f"connected: {stream.id} ({stream.status})")
    index = stream.index_scenes(
        extraction_type="time",
        extraction_config={"time": 10, "frame_count": 1},
        prompt=PROMPT,
        name="live-reactions",
    )
    index_id = getattr(index, "rtstream_index_id", None) or getattr(index, "id", "")
    print(f"live scene index: {index_id}")
    print("run `watch` in another terminal; descriptions arrive as the feed runs")


def status() -> None:
    stream = _stream()
    if not stream:
        print("no live stream connected")
        return
    print(f"{stream.id}  {stream.name}  {stream.status}")


def watch(poll_seconds: float = 12.0) -> None:
    stream = _stream()
    if not stream:
        print("no live stream connected; run `connect <rtsp-url>` first")
        return
    seen = set()
    print(f"watching {stream.name} ({stream.status}); ctrl-c to stop")
    while True:
        try:
            for index in stream.get_scene_index("") or []:
                pass  # older SDKs need an id; fall through to list-based path
        except Exception:
            pass
        try:
            indexes = getattr(stream, "list_scene_indexes", lambda: [])() or []
        except Exception:
            indexes = []
        for index in indexes:
            try:
                page = index.get_scenes(page_size=10) or {}
            except Exception:
                continue
            for scene in page.get("scenes", []):
                key = scene.get("start")
                if key in seen:
                    continue
                seen.add(key)
                print(f"[{scene.get('start')}] {str(scene.get('description'))[:180]}")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "connect" and len(sys.argv) > 2:
        connect(sys.argv[2])
    elif command == "watch":
        watch()
    else:
        status()
