"""A deterministic gate in front of the vision model's claims about a frame.

A vision model will describe a witness's expression from a frame where no face
is legible: a broadcast title card, a document close-up, a dip to black. Nothing
in its output separates "she looks composed" from "there was nothing here to
read", and for a legal tool that difference matters, because the second one is an
invented observation attached to a real docket number.

So the pixels are measured before a demeanour note is shown. This costs no model
calls, only fetching frame images the scene index already produced.

**What did not work, recorded so it is not retried.** Detail (variance of a
Laplacian) and luma, which are the obvious sharpness measures, are *anti*
correlated on this footage. Frames the model itself called unreadable scored 762
to 1383 detail while frames full of people scored 207 to 380, because a
Law and Crime title card is dense sharp text and a real courtroom plate is soft
and evenly lit. Absolute sharpness thresholds would have rejected exactly the
wrong half.

**What works: skin-tone coverage.** Measured across the two classes on the Heard
cross session, every frame the model called unreadable scored 0.000 and every
frame where it described people scored 0.47 to 0.55. The gate also rejects two
frames at 0.010 that the model's own text did not admit to, so it is slightly
stricter than the model's self-report, which is the direction we want.
"""
import io
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

# Separation on the calibration set was 0.000 against 0.47+, so this sits in a
# wide empty gap rather than on a cliff.
MIN_SKIN_FRACTION = 0.05
DARK_LUMA = 22.0
BRIGHT_LUMA = 236.0


@dataclass
class FrameStats:
    skin_fraction: float
    luma_mean: float
    detail: float
    ok: bool
    reason: str = ""

    @property
    def readable(self) -> bool:
        return self.ok


def _load_rgb(url: str, timeout: int = 20):
    from PIL import Image
    import numpy as np

    req = urllib.request.Request(url, headers={"User-Agent": "Precedent/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    # These decisions do not need full resolution, and a small array keeps a
    # whole-window pass cheap.
    image.thumbnail((240, 240))
    return np.asarray(image, dtype="float32")


def _skin_fraction(arr) -> float:
    """Share of pixels inside a broad skin-tone envelope.

    Deliberately wide: it is answering "are there people in this frame at all",
    not identifying anyone, and it must hold across skin tones and the warm wood
    and fabric of a courtroom.
    """
    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]
    brightest, darkest = arr.max(-1), arr.min(-1)
    spread = brightest - darkest
    mask = (
        (red > 70) & (green > 40) & (blue > 20)
        & (red > blue) & (red >= green)
        & (spread > 12) & (spread < 130)
    )
    return float(mask.mean())


def _detail(arr) -> float:
    """Laplacian variance. Reported for diagnosis, never used as the gate."""
    import numpy as np

    gray = arr.mean(-1)
    padded = np.pad(gray, 1, mode="edge")
    lap = (
        padded[:-2, 1:-1] + padded[1:-1, :-2] - 4 * padded[1:-1, 1:-1]
        + padded[1:-1, 2:] + padded[2:, 1:-1]
    )
    return float(lap.var())


def frame_stats(url: str) -> FrameStats:
    """Measure one frame. A fetch failure is reported, never assumed readable."""
    try:
        arr = _load_rgb(url)
    except Exception as exc:
        return FrameStats(0.0, 0.0, 0.0, False, f"frame unavailable ({type(exc).__name__})")

    skin = _skin_fraction(arr)
    luma = float(arr.mean())
    detail = _detail(arr)

    if luma <= DARK_LUMA:
        return FrameStats(skin, luma, detail, False, "frame is almost black")
    if luma >= BRIGHT_LUMA:
        return FrameStats(skin, luma, detail, False, "frame is blown out")
    if skin < MIN_SKIN_FRACTION:
        return FrameStats(skin, luma, detail, False,
                          "no people visible in frame, so demeanour cannot be read")
    return FrameStats(skin, luma, detail, True)


def readable_frames(urls: List[str]) -> tuple:
    """(readable stats, rejected stats) for a window's frames."""
    kept, rejected = [], []
    for url in urls:
        stats = frame_stats(url)
        (kept if stats.ok else rejected).append(stats)
    return kept, rejected


def motion_series(urls: List[str]) -> List[float]:
    """Mean absolute change between consecutive frames.

    A free local signal, used to find where something actually changes inside a
    window so the vision model is only asked about the parts that moved.
    """
    import numpy as np

    frames = []
    for url in urls:
        try:
            frames.append(_load_rgb(url).mean(-1))
        except Exception:
            frames.append(None)
    series: List[float] = []
    for earlier, later in zip(frames, frames[1:]):
        if earlier is None or later is None or earlier.shape != later.shape:
            series.append(0.0)
            continue
        series.append(float(np.abs(later - earlier).mean()))
    return series


def shift_gate(series: List[float], step_ratio: float = 1.8,
               spike_share: float = 0.7) -> Optional[dict]:
    """Is there a *sustained* change here rather than one busy frame?

    Borrowed from a sibling project's speed-ramp detector, where a raw max/min
    ratio kept surfacing single-frame spikes. A composure shift, like a change of
    playback speed, is a step between the two halves of a window, not a spike, so
    both conditions have to hold.
    """
    if len(series) < 4:
        return None
    total = sum(series) or 1e-6
    mid = len(series) // 2
    first, second = series[:mid], series[mid:]
    first_mean = (sum(first) / max(1, len(first))) or 1e-6
    second_mean = (sum(second) / max(1, len(second))) or 1e-6
    ratio = max(first_mean, second_mean) / min(first_mean, second_mean)
    share = max(series) / total
    if ratio >= step_ratio and share <= spike_share:
        return {
            "step_ratio": round(ratio, 2),
            "spike_share": round(share, 2),
            "direction": "settles" if first_mean > second_mean else "builds",
        }
    return None
