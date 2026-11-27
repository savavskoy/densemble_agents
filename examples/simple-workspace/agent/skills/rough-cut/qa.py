#!/usr/bin/env python3
"""QA checks for rough-cut EDL before writing CapCut."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from edl_policy import phrase_bounds, text_in_span

PAUSE_ERROR = 1.0
WORD_ERROR = 1.5
TRAILING_RE = re.compile(r"(,|\.\.\.|…)\s*$")
WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
LLM_WARN_RULES = frozenset({"duplicate_opener", "trailing_fragment", "trailing_off"})
# Content findings stay in the report. Only a broken result stops the build.
BLOCKING_RULES = frozenset({"missing_audio", "draft_info_write"})


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normalize_words(text):
    from find_retakes import normalize

    return [word for word in normalize(text).split() if word]


def phrase_map(transcript):
    phrases = transcript.get("segments") if isinstance(transcript, dict) else transcript
    return {int(p["id"]): p for p in phrases}


def fmt_time(seconds):
    return f"{float(seconds):.2f}s"


def phrase_ends_stretched(phrase) -> bool:
    text = (phrase.get("text") or "").strip()
    if text.endswith("...") or text.endswith("…"):
        return True
    if phrase.get("words"):
        last = phrase["words"][-1]
        return float(last["end"]) - float(last["start"]) > WORD_ERROR
    return False


def longest_word_duration(phrase) -> float:
    best = 0.0
    for word in phrase.get("words") or []:
        best = max(best, float(word["end"]) - float(word["start"]))
    return best


def audio_path(job_dir: Path, transcript) -> Path:
    raw = transcript.get("audio") if isinstance(transcript, dict) else ""
    path = Path(raw) if raw else job_dir / "audio.wav"
    if not path.is_file():
        path = job_dir / "audio.wav"
    return path


def blocking_errors(errors):
    return [item for item in errors if item.get("rule") in BLOCKING_RULES]


def audit(job_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    transcript_path = job_dir / "transcript.json"
    edl_path = job_dir / "edl.json"
    transcript = load_json(transcript_path)
    edl = load_json(edl_path)
    by_id = phrase_map(transcript)
    segments = edl.get("keep_segments") or []
    hidden = {int(item["phrase_id"]) for item in edl.get("hidden_speech") or []}
    handled = {(int(item["phrase_id"]), item.get("word")) for item in edl.get("handled_long_words") or []}
    processed_hidden = {
        int(item["phrase_id"])
        for item in edl.get("handled_long_words") or []
        if item.get("action") == "island_split"
    }
    errors: list[dict] = []
    warns: list[dict] = []
    seen_warns: set[tuple] = set()
    if not audio_path(job_dir, transcript).is_file():
        errors.append(
            {
                "level": "error",
                "rule": "missing_audio",
                "at": "",
                "text": str(job_dir / "audio.wav"),
            }
        )

    for item in edl.get("hidden_speech") or []:
        if int(item.get("phrase_id") or -1) in processed_hidden:
            continue
        errors.append(
            {
                "level": "error",
                "rule": "hidden_speech",
                "phrase_id": item["phrase_id"],
                "at": item.get("at"),
                "islands": item.get("islands"),
                "text": item.get("word"),
            }
        )

    for seg in segments:
        ids = [int(i) for i in (seg.get("phrase_ids") or [])]
        for aid, bid in zip(ids, ids[1:]):
            gap = phrase_bounds(by_id[bid])[0] - phrase_bounds(by_id[aid])[1]
            if gap > PAUSE_ERROR:
                errors.append(
                    {
                        "level": "error",
                        "rule": "pause_between_phrases",
                        "phrase_ids": [aid, bid],
                        "at": fmt_time(phrase_bounds(by_id[aid])[1]),
                        "gap_s": round(gap, 3),
                        "text": f"{by_id[aid].get('text', '').strip()} | {by_id[bid].get('text', '').strip()}",
                    }
                )
        for pid in ids:
            phrase = by_id[pid]
            for word in phrase.get("words") or []:
                start, end = float(word["start"]), float(word["end"])
                token = (word.get("word") or "").strip()
                duration = end - start
                if duration <= WORD_ERROR:
                    continue
                if pid in hidden:
                    continue
                if (pid, token) in handled:
                    continue
                key = ("long_word", pid, token)
                if key in seen_warns:
                    continue
                seen_warns.add(key)
                warns.append(
                    {
                        "level": "warn",
                        "rule": "long_word",
                        "phrase_ids": [pid],
                        "at": f"{fmt_time(start)}-{fmt_time(end)}",
                        "duration_s": round(duration, 3),
                        "text": token,
                    }
                )
        for aid, bid in zip(ids, ids[1:]):
            wa = normalize_words(text_in_span(by_id[aid], seg["content_start"], seg["content_end"]))
            wb = normalize_words(text_in_span(by_id[bid], seg["content_start"], seg["content_end"]))
            if len(wa) >= 2 and len(wb) >= 2 and wa[:2] == wb[:2]:
                key = ("duplicate_opener", aid, bid)
                if key not in seen_warns:
                    seen_warns.add(key)
                    warns.append(
                        {
                            "level": "warn",
                            "rule": "duplicate_opener",
                            "phrase_ids": [aid, bid],
                            "at": fmt_time(phrase_bounds(by_id[bid])[0]),
                            "text": f"{by_id[aid].get('text', '').strip()} | {by_id[bid].get('text', '').strip()}",
                        }
                    )
        if ids:
            last = by_id[ids[-1]]
            text = (last.get("text") or "").strip()
            last_token = text.split()[-1] if text.split() else ""
            broken = (
                TRAILING_RE.search(text)
                or last_token.endswith("...")
                or last_token.endswith("…")
                or (last_token.endswith("-") and len(last_token) > 1)
            )
            if broken:
                key = ("trailing_fragment", ids[-1])
                if key not in seen_warns:
                    seen_warns.add(key)
                    warns.append(
                        {
                            "level": "warn",
                            "rule": "trailing_fragment",
                            "phrase_ids": [ids[-1]],
                            "at": "{:.1f}–{:.1f}".format(*phrase_bounds(last)),
                            "text": text,
                        }
                    )

    for left, right in zip(segments, segments[1:]):
        left_ids = [int(i) for i in (left.get("phrase_ids") or [])]
        right_ids = [int(i) for i in (right.get("phrase_ids") or [])]
        if not left_ids or not right_ids:
            continue
        last_phrase = by_id[left_ids[-1]]
        first_phrase = by_id[right_ids[0]]
        if not phrase_ends_stretched(last_phrase):
            continue
        wa = normalize_words(last_phrase.get("text"))
        wb = normalize_words(first_phrase.get("text"))
        if len(wa) >= 2 and len(wb) >= 2 and wa[:2] == wb[:2]:
            key = ("trailing_off", left_ids[-1], right_ids[0])
            if key not in seen_warns:
                seen_warns.add(key)
                warns.append(
                    {
                        "level": "warn",
                        "rule": "trailing_off",
                        "phrase_ids": [left_ids[-1], right_ids[0]],
                        "at": fmt_time(phrase_bounds(first_phrase)[0]),
                        "text": f"{last_phrase.get('text', '').strip()} | {first_phrase.get('text', '').strip()}",
                        "last_word_duration_s": round(longest_word_duration(last_phrase), 3),
                    }
                )

    kept_rows = []
    for seg in segments:
        start = float(seg.get("content_start", seg["start"]))
        end = float(seg.get("content_end", seg["end"]))
        for phrase_id in seg.get("phrase_ids") or []:
            phrase = by_id[int(phrase_id)]
            text = text_in_span(phrase, start, end)
            if text:
                kept_rows.append((int(phrase_id), text, phrase))
    seen_pairs = set()
    for (earlier_id, earlier_text, earlier), (later_id, later_text, later) in zip(kept_rows, kept_rows[1:]):
        pair = (earlier_id, later_id, earlier_text, later_text)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        earlier_words = normalize_words(earlier_text)
        later_words = normalize_words(later_text)
        if len(earlier_words) >= 2 and len(later_words) >= 2 and earlier_words[:2] == later_words[:2]:
            errors.append(
                {
                    "level": "error",
                    "rule": "repeat_opener",
                    "phrase_ids": [earlier_id, later_id],
                    "at": fmt_time(phrase_bounds(later)[0]),
                    "text": f"{earlier_text} | {later_text}",
                }
            )

    hidden_list = list(edl.get("hidden_speech") or [])
    return errors, warns, hidden_list


def llm_review_payload(warns):
    return [item for item in warns if item.get("rule") in LLM_WARN_RULES]


def print_report(errors, warns):
    for item in errors + warns:
        level = item["level"]
        rule = item["rule"]
        keys = ", ".join(f"{k}={v}" for k, v in item.items() if k not in ("level", "rule"))
        print(f"{level}\t{rule}\t{keys}")
    print(
        f"summary\terrors={len(errors)}\twarns={len(warns)}\tblocking={len(blocking_errors(errors))}"
    )


def main():
    args = [item for item in sys.argv[1:] if item != "--strict"]
    strict = "--strict" in sys.argv[1:]
    if len(args) != 1:
        raise SystemExit(f"usage: {sys.argv[0]} <job_name_or_job_dir> [--strict]")
    arg = Path(args[0])
    if arg.is_dir():
        job_dir = arg
    else:
        root = Path(__import__("os").environ.get("ROUGH_CUT_JOBS", "/state/jobs").strip() or "/state/jobs")
        job_dir = root / arg.name
    errors, warns, hidden = audit(job_dir)
    print_report(errors, warns)
    if hidden:
        print("hidden_speech_json\t" + json.dumps(hidden, ensure_ascii=False))
    review = load_json(job_dir / "edl.json").get("manual_review") or []
    if review:
        print("проверить вручную")
        for item in review:
            print(f"{item.get('at')}\tphrase {item.get('phrase_id')}\t{item.get('word')}")
    llm = llm_review_payload(warns)
    if llm:
        print("llm_review_json\t" + json.dumps(llm, ensure_ascii=False))
    # Unresolved repeat_opener stays an error in the report and in needs_review.json.
    # It does not stop the build. --strict restores a stop on every error.
    if strict and errors:
        raise SystemExit(1)
    if blocking_errors(errors):
        raise SystemExit(1)


if __name__ == "__main__":
    main()