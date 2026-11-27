#!/usr/bin/env python3
"""Split transcript segments into sentences. Word times stay on each sentence.

Usage:
    python3 segment_sentences.py <job_name>

A sentence ends on . ? ! …, or when the gap before the next word is at least
SENTENCE_PAUSE (0.7 s). Punctuation does not split when the next word starts
sooner than PUNCT_HOLD_PAUSE and HOLD_TIGHT_PUNCTUATION is on (off by default).
The original segment list is kept once in transcript.whisper.json.
"""

import json
import os
import sys
from pathlib import Path

from edl_policy import HOLD_TIGHT_PUNCTUATION, PUNCT_HOLD_PAUSE, SENTENCE_ENDINGS, SENTENCE_PAUSE

DEFAULT_JOBS_ROOT = Path("/state/jobs")
ENDINGS = SENTENCE_ENDINGS


def jobs_root():
    raw = os.environ.get("ROUGH_CUT_JOBS", "").strip()
    return Path(raw) if raw else DEFAULT_JOBS_ROOT


def ends_sentence(word):
    text = (word.get("word") or "").strip()
    return text.endswith(ENDINGS)


def split_word_stream(words, *, hold_tight=None, sentence_pause=None, punct_hold=None):
    """Split one word stream on punctuation or a long pause."""
    if hold_tight is None:
        hold_tight = HOLD_TIGHT_PUNCTUATION
    if sentence_pause is None:
        sentence_pause = SENTENCE_PAUSE
    if punct_hold is None:
        punct_hold = PUNCT_HOLD_PAUSE
    sentences = []
    bucket = []
    for index, word in enumerate(words):
        if bucket:
            gap = float(word["start"]) - float(bucket[-1]["end"])
            if gap >= sentence_pause:
                sentences.append(bucket)
                bucket = []
        bucket.append(word)
        if not ends_sentence(word):
            continue
        nxt = words[index + 1] if index + 1 < len(words) else None
        if nxt is not None and hold_tight:
            gap_after = float(nxt["start"]) - float(word["end"])
            if gap_after < punct_hold:
                continue
        sentences.append(bucket)
        bucket = []
    if bucket:
        sentences.append(bucket)
    return sentences


def split_phrases(phrases, **limits):
    """Split the whole word stream. A lone short word is joined to the next segment."""
    phrases = [dict(phrase) for phrase in phrases]
    index = 0
    while index < len(phrases) - 1:
        words = list(phrases[index].get("words") or [])
        token = (words[0].get("word") if len(words) == 1 else "") or ""
        if len(words) == 1 and not ends_sentence(words[0]) and len(token.strip(" ,")) <= 2:
            nxt = phrases[index + 1]
            nxt["words"] = words + list(nxt.get("words") or [])
            if nxt["words"]:
                nxt["start"] = float(nxt["words"][0]["start"])
            phrases.pop(index)
            continue
        index += 1
    sentences = []
    stream = []

    def flush_stream():
        if not stream:
            return
        sentences.extend(split_word_stream(stream, **limits))
        stream.clear()

    for phrase in phrases:
        words = list(phrase.get("words") or [])
        if not words:
            flush_stream()
            text = (phrase.get("text") or "").strip()
            if text:
                sentences.append(
                    {
                        "start": float(phrase["start"]),
                        "end": float(phrase["end"]),
                        "text": text,
                        "words": [],
                    }
                )
            continue
        stream.extend(words)
    flush_stream()
    rows = []
    for index, words in enumerate(sentences):
        if isinstance(words, dict):
            words["id"] = index
            words["pause_before"] = 0.0
            rows.append(words)
            continue
        text = " ".join((word.get("word") or "").strip() for word in words).strip()
        rows.append(
            {
                "id": index,
                "start": float(words[0]["start"]),
                "end": float(words[-1]["end"]),
                "text": text,
                "words": words,
                "pause_before": 0.0,
            }
        )
    for index, row in enumerate(rows):
        if index == 0:
            continue
        row["pause_before"] = round(row["start"] - rows[index - 1]["end"], 3)
    return rows


def main():
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <job_name>")
    folder = jobs_root() / sys.argv[1]
    path = folder / "transcript.json"
    transcript = json.loads(path.read_text(encoding="utf-8"))
    if transcript.get("sentence_ids"):
        print(path)
        return
    backup = folder / "transcript.whisper.json"
    if not backup.is_file():
        backup.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    phrases = transcript.get("segments") if isinstance(transcript, dict) else transcript
    transcript["segments"] = split_phrases(phrases)
    transcript["sentence_ids"] = True
    path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()