#!/usr/bin/env python3
"""Turn drop decisions into keep ranges snapped to quiet audio.

Usage:
    python3 snap_cuts.py <job_name>

Reads /state/jobs/<job_name>/decisions.json and transcript.json. Checks the
decisions, then builds keep ranges from the words of the phrases that stay.
Each cut sits on the quietest 10 ms frame in a ±0.25s window on the outside
of the word. The search uses wave.readframes. If the audio cannot be read,
the edge falls back to 0.18s before the first word and 0.25s after the last.
Writes cuts.json beside the transcript. Override the jobs root with
ROUGH_CUT_JOBS.
"""

import json
import os
import struct
import wave
from pathlib import Path

DEFAULT_JOBS_ROOT = Path("/state/jobs")
SNAP_WINDOW = 0.25
FRAME_SECONDS = 0.01
FALLBACK_BEFORE = 0.18
FALLBACK_AFTER = 0.25
MERGE_GAP = 0.35
REASON_MAX = 240


def jobs_root():
    raw = os.environ.get("ROUGH_CUT_JOBS", "").strip()
    return Path(raw) if raw else DEFAULT_JOBS_ROOT


def job_dir(name):
    if not name or name in (".", "..") or name != Path(name).name or "/" in name or "\\" in name:
        raise SystemExit("job name must be a single folder name")
    folder = jobs_root() / name
    if not folder.is_dir():
        raise SystemExit(f"job directory not found: {folder}")
    return folder


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"invalid JSON in {path}: {error}") from error


def validate_decisions(decisions, phrases):
    if not isinstance(decisions, dict) or set(decisions) != {"drop_ids"}:
        raise SystemExit("decisions.json must be an object with only drop_ids")
    items = decisions["drop_ids"]
    if not isinstance(items, list):
        raise SystemExit("drop_ids must be a list")
    known = {phrase["id"] for phrase in phrases}
    seen = set()
    drops = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "reason", "kept_instead"}:
            raise SystemExit("each drop must have only id, reason, and kept_instead")
        phrase_id = item["id"]
        kept = item["kept_instead"]
        reason = item["reason"]
        if not isinstance(phrase_id, int) or phrase_id < 0:
            raise SystemExit(f"drop id is not a phrase id: {phrase_id!r}")
        if not isinstance(kept, int) or kept < 0:
            raise SystemExit(f"kept_instead is not a phrase id: {kept!r}")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > REASON_MAX:
            raise SystemExit(f"reason for {phrase_id} must be 1..{REASON_MAX} characters")
        if phrase_id == kept:
            raise SystemExit(f"phrase {phrase_id} cannot be kept instead of itself")
        if phrase_id not in known or kept not in known:
            raise SystemExit(f"phrase {phrase_id} or {kept} is not in the transcript")
        if phrase_id in seen:
            raise SystemExit(f"phrase {phrase_id} is listed twice")
        seen.add(phrase_id)
        drops.append({"id": phrase_id, "reason": reason.strip(), "kept_instead": kept})
    for item in drops:
        if item["kept_instead"] in seen:
            raise SystemExit(
                f"kept phrase {item['kept_instead']} is also marked to drop"
            )
    return drops


def phrase_words(phrase):
    words = []
    for word in phrase.get("words") or []:
        text = (word.get("word") or "").strip()
        if not text:
            continue
        words.append((float(word["start"]), float(word["end"])))
    if words:
        return words
    return [(float(phrase["start"]), float(phrase["end"]))]


class WaveEnergy:
    """10 ms RMS over a window, read with wave.readframes."""

    def __init__(self, path):
        self.path = Path(path)
        self.usable = False
        self.duration = 0.0
        self.rate = 0
        self.frames = 0
        if not self.path.is_file():
            return
        try:
            with wave.open(str(self.path), "rb") as handle:
                self.channels = handle.getnchannels()
                self.width = handle.getsampwidth()
                self.rate = handle.getframerate()
                self.frames = handle.getnframes()
        except (wave.Error, EOFError, OSError):
            return
        if self.channels != 1 or self.width != 2 or self.rate <= 0 or self.frames <= 0:
            return
        self.usable = True
        self.duration = self.frames / float(self.rate)

    def quietest(self, start, end):
        if not self.usable:
            return None
        start = max(0.0, start)
        end = min(self.duration, end)
        if end - start < FRAME_SECONDS:
            return None
        first = int(start * self.rate)
        last = min(self.frames, int(end * self.rate))
        if last - first < 2:
            return None
        try:
            with wave.open(str(self.path), "rb") as handle:
                handle.setpos(first)
                raw = handle.readframes(last - first)
        except (wave.Error, EOFError, OSError):
            return None
        count = len(raw) // 2
        if count < 2:
            return None
        samples = struct.unpack("<" + "h" * count, raw[: count * 2])
        step = max(1, int(FRAME_SECONDS * self.rate))
        best_time = None
        best_energy = None
        for offset in range(0, count - step + 1, step):
            chunk = samples[offset : offset + step]
            energy = sum(sample * sample for sample in chunk) / float(len(chunk))
            center = start + (offset + step / 2.0) / self.rate
            if best_energy is None or energy < best_energy:
                best_energy = energy
                best_time = center
        return best_time


def fallback_edge(nominal, side, media_end):
    if side == "start":
        return max(0.0, nominal - FALLBACK_BEFORE)
    return min(media_end, nominal + FALLBACK_AFTER)


def snap_edge(energy, nominal, side, media_end):
    """Quietest frame in ±0.25s that stays outside the kept word."""
    if side == "start":
        window_start = nominal - SNAP_WINDOW
        window_end = nominal
    else:
        window_start = nominal
        window_end = nominal + SNAP_WINDOW
    quiet = energy.quietest(window_start, window_end)
    if quiet is None:
        return fallback_edge(nominal, side, media_end), "fallback"
    if side == "start" and quiet > nominal:
        return fallback_edge(nominal, side, media_end), "fallback"
    if side == "end" and quiet < nominal:
        return fallback_edge(nominal, side, media_end), "fallback"
    return max(0.0, min(media_end, quiet)), "energy"


def keep_pieces(phrases, dropped):
    pieces = []
    current = None
    for phrase in phrases:
        if phrase["id"] in dropped:
            if current is not None:
                pieces.append(current)
                current = None
            continue
        start, end = phrase_words(phrase)[0][0], phrase_words(phrase)[-1][1]
        if current is None:
            current = {"start": start, "end": end, "phrase_ids": [phrase["id"]]}
            continue
        current["end"] = end
        current["phrase_ids"].append(phrase["id"])
    if current is not None:
        pieces.append(current)
    return pieces


def snap_pieces(pieces, energy, media_end):
    snapped = []
    for piece in pieces:
        start, start_mode = snap_edge(energy, piece["start"], "start", media_end)
        end, end_mode = snap_edge(energy, piece["end"], "end", media_end)
        if end - start < 0.05:
            start = fallback_edge(piece["start"], "start", media_end)
            end = fallback_edge(piece["end"], "end", media_end)
            start_mode = "fallback"
            end_mode = "fallback"
        if end - start < 0.05:
            continue
        snapped.append(
            {
                "start": start,
                "end": end,
                "phrase_ids": list(piece["phrase_ids"]),
                "start_mode": start_mode,
                "end_mode": end_mode,
            }
        )
    return snapped


def merge_ranges(ranges):
    merged = []
    for item in ranges:
        if merged and item["start"] - merged[-1]["end"] < MERGE_GAP:
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            merged[-1]["phrase_ids"].extend(item["phrase_ids"])
            merged[-1]["end_mode"] = item["end_mode"]
            continue
        merged.append(
            {
                "start": item["start"],
                "end": item["end"],
                "phrase_ids": list(item["phrase_ids"]),
                "start_mode": item["start_mode"],
                "end_mode": item["end_mode"],
            }
        )
    return merged


def build_cuts(folder):
    transcript = load_json(folder / "transcript.json")
    decisions = load_json(folder / "decisions.json")
    phrases = transcript.get("segments") if isinstance(transcript, dict) else transcript
    if not isinstance(phrases, list) or not phrases:
        raise SystemExit(f"transcript has no segments: {folder / 'transcript.json'}")
    drops = validate_decisions(decisions, phrases)
    dropped_ids = {item["id"] for item in drops}
    by_id = {phrase["id"]: (phrase.get("text") or "").strip() for phrase in phrases}
    for item in drops:
        item["text"] = by_id.get(item["id"], "")
    audio = transcript.get("audio") if isinstance(transcript, dict) else None
    energy = WaveEnergy(audio) if audio else WaveEnergy("")
    media_end = energy.duration or float(transcript.get("duration") or 0)
    if media_end <= 0:
        media_end = max(phrase_words(phrase)[-1][1] for phrase in phrases)
    pieces = keep_pieces(phrases, dropped_ids)
    ranges = merge_ranges(snap_pieces(pieces, energy, media_end))
    return {
        "audio": audio or "",
        "media_s": round(media_end, 3),
        "energy": energy.usable,
        "dropped": drops,
        "keeps": [
            {
                "start": round(item["start"], 3),
                "end": round(item["end"], 3),
                "phrase_ids": item["phrase_ids"],
                "start_mode": item["start_mode"],
                "end_mode": item["end_mode"],
            }
            for item in ranges
        ],
    }


def main():
    import sys

    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <job_name>")
    folder = job_dir(sys.argv[1])
    payload = build_cuts(folder)
    out_path = folder / "cuts.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out_path)


if __name__ == "__main__":
    main()
