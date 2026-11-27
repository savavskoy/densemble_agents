"""Split EDL pieces using ffmpeg silencedetect on long words."""

from __future__ import annotations

from pathlib import Path

from audio_silence import KEEP_SILENCE, SILENCE_MIN, Span, detect_silences, speech_islands
from edl_policy import LONG_WORD, MIN_ISLAND, PHRASE_JOIN_GAP, phrase_bounds


def long_words_in_kept(phrases, dropped):
    for phrase in phrases:
        pid = int(phrase["id"])
        if pid in dropped:
            continue
        for word in phrase.get("words") or []:
            start, end = float(word["start"]), float(word["end"])
            if end - start > LONG_WORD:
                yield pid, start, end, (word.get("word") or "").strip()


def piece_hits(piece, start, end, phrase_id):
    if phrase_id not in piece["phrase_ids"]:
        return False
    return piece["content_start"] <= end and piece["content_end"] >= start


def split_remove_silence(piece, silence: Span):
    """Remove silence from piece; leave KEEP_SILENCE on the leading edge of the gap."""
    cs, ce = piece["content_start"], piece["content_end"]
    cut_start = silence.start
    cut_end = silence.end
    if cut_end <= cs or cut_start >= ce:
        return [piece]
    keep_end = min(cut_start + KEEP_SILENCE, cut_end) if cut_end - cut_start > KEEP_SILENCE else cut_end
    parts = []
    if cut_start > cs + 0.05:
        parts.append(
            {
                "content_start": cs,
                "content_end": keep_end,
                "phrase_ids": list(piece["phrase_ids"]),
                "label": piece["label"],
            }
        )
    if cut_end < ce - 0.05:
        parts.append(
            {
                "content_start": cut_end,
                "content_end": ce,
                "phrase_ids": list(piece["phrase_ids"]),
                "label": piece["label"],
            }
        )
    return parts or [piece]


def coalesce_pieces(pieces):
    pieces = sorted(pieces, key=lambda p: p["content_start"])
    out = []
    for piece in pieces:
        if not out:
            out.append(piece)
            continue
        prev = out[-1]
        gap = piece["content_start"] - prev["content_end"]
        locked = prev.get("island_id") and piece.get("island_id") and prev["island_id"] != piece["island_id"]
        if not locked and prev["phrase_ids"] == piece["phrase_ids"] and gap < PHRASE_JOIN_GAP:
            prev["content_end"] = piece["content_end"]
        else:
            out.append(piece)
    return out


def drop_word(piece, word_start, word_end):
    """Remove a whole word. No empty remnant, no silence left in its place."""
    cs, ce = piece["content_start"], piece["content_end"]
    word_start = max(cs, float(word_start))
    word_end = min(ce, float(word_end))
    parts = []
    if word_start > cs + 0.05:
        parts.append(
            {
                "content_start": cs,
                "content_end": word_start,
                "phrase_ids": list(piece["phrase_ids"]),
                "label": piece["label"],
                "bridge_after": False,
            }
        )
    if word_end < ce - 0.05:
        parts.append(
            {
                "content_start": word_end,
                "content_end": ce,
                "phrase_ids": list(piece["phrase_ids"]),
                "label": piece["label"],
            }
        )
    return parts


def split_piece_on_islands(piece, word_start, word_end, islands, token):
    """Keep each speech island, drop islands under 0.15s, leave 0.3s of each gap."""
    kept = [island for island in islands if island.end - island.start >= MIN_ISLAND]
    cs, ce = piece["content_start"], piece["content_end"]
    if not kept:
        return split_remove_silence(piece, Span(word_start, word_end))

    ranges = []
    prefix = (cs, min(word_start, ce)) if word_start > cs + 0.02 else None
    for index, island in enumerate(kept):
        start = max(cs, island.start)
        end = min(ce, island.end)
        if index + 1 < len(kept):
            end = min(ce, end + KEEP_SILENCE, kept[index + 1].start)
        else:
            end = min(ce, end + KEEP_SILENCE, word_end)
        if index == 0 and prefix and prefix[1] >= start - 0.05:
            start = prefix[0]
            prefix = None
        ranges.append((start, end))
    if prefix:
        ranges.insert(0, prefix)
    if word_end < ce - 0.02:
        if ranges and word_end <= ranges[-1][1] + 0.05:
            ranges[-1] = (ranges[-1][0], ce)
        else:
            ranges.append((max(word_end, cs), ce))

    parts = []
    for index, (start, end) in enumerate(ranges):
        if end - start < 0.05:
            continue
        parts.append(
            {
                "content_start": start,
                "content_end": end,
                "phrase_ids": list(piece["phrase_ids"]),
                "label": piece["label"],
                "island_id": f"{token}-{index}",
            }
        )
    return parts or [piece]


def repair_pieces(pieces, phrases, dropped, audio_path: Path):
    hidden_speech: list[dict] = []
    handled: list[dict] = []
    splits: list[dict] = []
    manual_review: list[dict] = []
    if not audio_path.is_file():
        return pieces, hidden_speech, handled, splits, manual_review

    out = list(pieces)
    for phrase_id, w_start, w_end, word_text in long_words_in_kept(phrases, dropped):
        silences = detect_silences(str(audio_path), w_start, w_end)
        if not silences:
            continue
        islands = speech_islands(Span(w_start, w_end), silences)
        if len(islands) >= 2:
            new_out = []
            removed = False
            for piece in out:
                if not piece_hits(piece, w_start, w_end, phrase_id):
                    new_out.append(piece)
                    continue
                parts = drop_word(piece, w_start, w_end)
                new_out.extend(parts)
                removed = True
            if removed:
                out = new_out
                manual_review.append(
                    {
                        "phrase_id": phrase_id,
                        "word": word_text,
                        "at": f"{w_start:.1f}–{w_end:.1f}",
                        "dropped_word": True,
                        "islands": len(islands),
                    }
                )
                handled.append({"phrase_id": phrase_id, "word": word_text, "action": "drop_word"})
            continue
        if len(islands) != 1:
            continue
        touched = False
        new_out = []
        for piece in out:
            if not piece_hits(piece, w_start, w_end, phrase_id):
                new_out.append(piece)
                continue
            main_silence = max(silences, key=lambda s: s.end - s.start)
            if main_silence.end - main_silence.start < SILENCE_MIN:
                new_out.append(piece)
                continue
            parts = split_remove_silence(piece, main_silence)
            if len(parts) > 1:
                splits.append(
                    {
                        "phrase_id": phrase_id,
                        "word": word_text,
                        "silence": [round(main_silence.start, 3), round(main_silence.end, 3)],
                    }
                )
                handled.append({"phrase_id": phrase_id, "word": word_text, "action": "silence_split"})
                touched = True
            new_out.extend(parts)
        if touched:
            out = coalesce_pieces(new_out)
    return out, hidden_speech, handled, splits, manual_review