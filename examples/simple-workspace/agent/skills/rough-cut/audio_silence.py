"""ffmpeg silencedetect helpers for long-word repair."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from edl_policy import KEEP_SILENCE, SILENCE_MIN, SILENCE_NOISE_DB

_SILENCE_START = re.compile(r"silence_start:\s*([\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")


@dataclass(frozen=True)
class Span:
    start: float
    end: float


def detect_silences(audio: str, start: float, end: float) -> list[Span]:
    if end - start < SILENCE_MIN:
        return []
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-i",
        audio,
        "-af",
        f"silencedetect=n={SILENCE_NOISE_DB}dB:d={SILENCE_MIN}",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise SystemExit("ffmpeg not found") from error
    log = (proc.stderr or "") + (proc.stdout or "")
    events: list[tuple[str, float, float]] = []
    for line in log.splitlines():
        match = _SILENCE_START.search(line)
        if match:
            events.append(("start", float(match.group(1)), 0.0))
            continue
        match = _SILENCE_END.search(line)
        if match:
            events.append(("end", float(match.group(1)), float(match.group(2))))
    silences: list[Span] = []
    open_at: float | None = None
    for kind, at, _dur in events:
        at = start + at
        if kind == "start":
            open_at = at
        elif open_at is not None:
            silences.append(Span(max(start, open_at), min(end, at)))
            open_at = None
    inside = [Span(max(start, s.start), min(end, s.end)) for s in silences if s.end > s.start]
    return [s for s in inside if s.end - s.start >= SILENCE_MIN - 1e-6]


def speech_islands(window: Span, silences: list[Span]) -> list[Span]:
    if not silences:
        return [window]
    merged = []
    for s in sorted(silences, key=lambda item: item.start):
        if merged and s.start <= merged[-1].end:
            merged[-1] = Span(merged[-1].start, max(merged[-1].end, s.end))
        else:
            merged.append(s)
    islands = []
    cursor = window.start
    for silence in merged:
        if silence.start > cursor + 0.02:
            islands.append(Span(cursor, silence.start))
        cursor = max(cursor, silence.end)
    if window.end > cursor + 0.02:
        islands.append(Span(cursor, window.end))
    return islands


def shrink_silence(silence: Span) -> Span:
    """Keep KEEP_SILENCE s in the middle of a cut silence."""
    duration = silence.end - silence.start
    if duration <= KEEP_SILENCE:
        return silence
    mid = (silence.start + silence.end) / 2
    half = KEEP_SILENCE / 2
    return Span(mid - half, mid + half)