#!/usr/bin/env python3
"""Build edl.json from a transcript and drop decisions.

Usage:
    python3 build_edl.py <job_name>

Consecutive kept phrases join one interval when the gap between them is under
PHRASE_JOIN_GAP. Each clip then keeps a slice of the original pause
(pause_to_keep in edl_policy): 0.30 s after a sentence, 0.15 s inside one,
0.25 s on a retake boundary, and a pause longer than 1 s is compressed to
0.35 s. Cut edges snap to silence within 0.1 s without trimming the word.
content_start / content_end are the source in/out that CapCut reads.
Override the jobs root with ROUGH_CUT_JOBS.
"""

import json
import os
import sys
from pathlib import Path

from edl_policy import (
    PAUSE_LONG,
    PHRASE_JOIN_GAP,
    SNAP_WINDOW,
    SILENCE_MIN,
    final_bounds,
    phrase_bounds,
    snap_edge,
    text_ends_sentence,
)
from long_word_repair import repair_pieces
from review_policy import apply_drop_policy, from_unresolved, write_needs_review

DEFAULT_JOBS_ROOT = Path("/state/jobs")


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


def content_segments(phrases, dropped):
    """Group kept phrases; split when the gap to the next kept phrase reaches PHRASE_JOIN_GAP."""
    pieces = []
    current = None
    for phrase in phrases:
        phrase_id = phrase["id"]
        if phrase_id in dropped:
            continue
        start, end = phrase_bounds(phrase)
        text = (phrase.get("text") or "").strip()
        if current is None:
            current = {
                "content_start": start,
                "content_end": end,
                "phrase_ids": [phrase_id],
                "label": text,
            }
            continue
        gap = start - current["content_end"]
        if phrase.get("hard_cut") or gap >= PHRASE_JOIN_GAP:
            pieces.append(current)
            current = {
                "content_start": start,
                "content_end": end,
                "phrase_ids": [phrase_id],
                "label": text,
            }
            continue
        current["content_end"] = end
        current["phrase_ids"].append(phrase_id)
        if text:
            current["label"] = f"{current['label']} {text}".strip()
    if current is not None:
        pieces.append(current)
    return pieces


def build_edl(folder):
    transcript = load_json(folder / "transcript.json")
    decisions = load_json(folder / "decisions.json")
    if not isinstance(decisions, dict) or set(decisions) != {"drop_ids"}:
        raise SystemExit("decisions.json must be an object with only drop_ids")
    phrases = transcript.get("segments") if isinstance(transcript, dict) else transcript
    if not isinstance(phrases, list) or not phrases:
        raise SystemExit(f"transcript has no segments: {folder / 'transcript.json'}")
    candidates = load_json(folder / "candidates.json") if (folder / "candidates.json").is_file() else {}
    dropped, auto_retakes, _kept_back = apply_drop_policy(decisions, candidates, phrases)
    from take_spans import apply_mask, load_sentences, plan_cuts

    sentences = load_sentences(folder / "transcript.json")
    mask, extra_review = plan_cuts(folder, sentences)
    phrases = apply_mask(sentences, mask)
    media_end = float(transcript.get("duration") or sentences[-1]["end"])
    pieces = content_segments(phrases, dropped)
    if not pieces:
        raise SystemExit("no keep segments left after applying drop_ids")
    audio_path = Path(transcript.get("audio") or folder / "audio.wav")
    if not audio_path.is_file():
        audio_path = folder / "audio.wav"
    if not audio_path.is_file():
        raise SystemExit(f"audio not found: {folder / 'audio.wav'}")
    pieces, hidden_speech, handled_long_words, silence_splits, manual_review = repair_pieces(
        pieces, phrases, dropped, audio_path
    )
    pieces = coalesce_after_repair(pieces)
    by_id = {phrase["id"]: phrase for phrase in phrases}
    speech = [(piece["content_start"], piece["content_end"]) for piece in pieces]
    sentence_end = [text_ends_sentence(piece.get("label") or "") for piece in pieces]
    hard_in = [bool(by_id[piece["phrase_ids"][0]].get("hard_cut")) for piece in pieces]
    bridge_after = [bool(piece.get("bridge_after", True)) for piece in pieces]
    compressed_pauses = _compressed_pauses(speech, media_end, bridge_after)
    ceilings = next_word_starts(
        speech, [word for phrase in sentences for word in phrase.get("words") or [] if "start" in word and "end" in word]
    )
    bounds = snap_bounds(
        final_bounds(speech, sentence_end, hard_in, media_end, bridge_after, ceilings),
        audio_path,
        media_end,
        ceilings,
    )
    keep_segments = []
    for piece, (clip_start, clip_end) in zip(pieces, bounds):
        if clip_end <= clip_start:
            continue
        keep_segments.append(
            {
                "start": round(clip_start, 3),
                "end": round(clip_end, 3),
                "content_start": round(clip_start, 3),
                "content_end": round(clip_end, 3),
                "label": piece["label"],
                "phrase_ids": piece["phrase_ids"],
            }
        )
    if not keep_segments:
        raise SystemExit("no keep segments left after applying pauses")
    return {
        "keep_segments": keep_segments,
        "hidden_speech": hidden_speech,
        "handled_long_words": handled_long_words,
        "silence_splits": silence_splits,
        "manual_review": manual_review,
        "auto_retakes": auto_retakes,
        "extra_review": extra_review,
        "compressed_pauses": compressed_pauses,
    }


def publish(folder, payload, silence_splits):
    from qa import audit

    out_path = folder / "edl.json"
    extra_review = list(payload.pop("extra_review", None) or [])
    compressed_pauses = int(payload.pop("compressed_pauses", 0) or 0)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors, warns, _hidden = audit(folder)
    write_needs_review(
        folder,
        payload.get("manual_review") or [],
        warns,
        payload.get("auto_retakes") or [],
        silence_splits,
        extra_review + from_unresolved(errors),
        compressed_pauses,
    )
    return out_path


def _compressed_pauses(speech, media_end, bridge_after):
    """How many original gaps the pause policy compresses. Does not move a cut."""
    count = 0
    for index, (_start, end) in enumerate(speech):
        if index < len(bridge_after) and not bridge_after[index]:
            continue
        if index + 1 < len(speech):
            gap = speech[index + 1][0] - end
        else:
            gap = media_end - end
        if gap > PAUSE_LONG:
            count += 1
    return count


def next_word_starts(speech, words):
    """For each speech range, where the next transcript word starts (cut or kept).

    Whisper words can touch or overlap, so the next word is the first one that
    ends after the range does. The result is never earlier than the range end.
    With no word after the range there is no ceiling (infinity).
    """
    ordered = sorted(words, key=lambda word: (float(word["start"]), float(word["end"])))
    starts = []
    for _begin, end in speech:
        end = float(end)
        following = next((float(word["start"]) for word in ordered if float(word["end"]) > end + 0.001), None)
        starts.append(float("inf") if following is None else max(end, following))
    return starts


def snap_bounds(bounds, audio_path, media_end, ceilings=None):
    """Pull each cut onto a nearby silence edge. Missing audio leaves the bounds."""
    if not audio_path or not Path(audio_path).is_file():
        return bounds
    from audio_silence import detect_silences

    scan = SNAP_WINDOW + SILENCE_MIN
    snapped = []
    for index, (start, end) in enumerate(bounds):
        prev_end = snapped[-1][1] if snapped else 0.0
        next_speech = bounds[index + 1][0] if index + 1 < len(bounds) else media_end
        start_silences = detect_silences(str(audio_path), max(0.0, start - scan), start + scan)
        end_silences = detect_silences(str(audio_path), max(0.0, end - scan), min(media_end, end + scan))
        start = snap_edge(start, start_silences, "start")
        end = snap_edge(end, end_silences, "end")
        start = min(max(start, prev_end), next_speech)
        end = min(max(end, start), next_speech)
        if ceilings is not None:
            end = min(end, max(float(ceilings[index]), float(bounds[index][1])))
        snapped.append((start, end))
    return snapped


def coalesce_after_repair(pieces):
    from long_word_repair import coalesce_pieces

    return coalesce_pieces(pieces)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <job_name>")
    folder = job_dir(sys.argv[1])
    if not (folder / "decisions.json").is_file():
        raise SystemExit(f"decisions not found: {folder / 'decisions.json'}")
    payload = build_edl(folder)
    out_path = publish(folder, payload, payload.get("silence_splits") or [])
    print(out_path)
    print(folder / "needs_review.json")


if __name__ == "__main__":
    main()