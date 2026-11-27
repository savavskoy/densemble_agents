#!/usr/bin/env python3
"""Offline harness for retake detection: recall and precision in seconds.

Usage:
    python3 eval_recall.py --gold gold/<job>/cuts.json
    python3 eval_recall.py --gold gold/<job>/cuts.json --save-cuts baseline.json --label v5
    python3 eval_recall.py --gold gold/<job>/cuts.json --cuts baseline.json
    python3 eval_recall.py --gold gold/<job>/cuts.json --compare baseline.json

The detection step runs on a stored transcript (the gold file names it in
"fixture", or pass --transcript): sentence split, retake groups, word mask.
Nothing after that runs: no pause policy, no CapCut. The model is not called.

Gold file:
    {"job": "...", "fixture": "fixtures/<job>/transcript.json",
     "cuts":      [{"id", "kind": "target"|"regression", "start", "end", "quote",
                    "expected_miss": true (optional)}],
     "must_keep": [{"id", "start", "end", "quote"}]}

Times are source seconds. A word belongs to an interval when its midpoint lies
inside it. All seconds are word durations, so a pause between two cut phrases
is neither a hit nor a miss. The detector never reads "must_keep".

Metrics:
- recall_s: share of target gold seconds that the detector cut. Cases marked
  expected_miss are counted apart.
- regression: the same for cuts that were already accepted.
- precision_s: cut seconds that fall inside any gold cut.
- collateral_s: cut seconds inside must_keep.
- unexplained_s: cut seconds outside gold and must_keep. Listen to these.
"""

import argparse
import json
from pathlib import Path

from find_retakes import normalize
from segment_sentences import split_phrases
from take_spans import detect_cuts, phrases_from_segments, word_list

HIT_SHARE = 0.8
PARTIAL_SHARE = 0.2
RANGE_JOIN_S = 0.8
KINDS = ("target", "regression")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def transcript_words(transcript):
    """Every word of the transcript as {start, end, text}, in time order."""
    segments = transcript.get("segments") if isinstance(transcript, dict) else transcript
    if not isinstance(segments, list):
        raise SystemExit("transcript has no segments")
    words = []
    for segment in segments:
        for word in segment.get("words") or []:
            token = (word.get("word") or "").strip()
            if token:
                words.append({"start": float(word["start"]), "end": float(word["end"]), "text": token})
    words.sort(key=lambda item: (item["start"], item["end"]))
    return words


def midpoint(word):
    return (word["start"] + word["end"]) / 2


def words_in(words, start, end):
    return [index for index, word in enumerate(words) if start <= midpoint(word) <= end]


def seconds(words, indexes):
    return sum(words[index]["end"] - words[index]["start"] for index in indexes)


def _quote_words(quote):
    return normalize((quote or "").replace("…", " ")).split()


def load_gold(path, words):
    """Read and validate the gold file against the transcript words."""
    data = load_json(path)
    seen = set()
    members = {}
    for section in ("cuts", "must_keep"):
        rows = data.get(section)
        if not isinstance(rows, list):
            raise SystemExit(f"gold: {section} must be a list")
        for row in rows:
            name = row.get("id")
            if not name or name in seen:
                raise SystemExit(f"gold: missing or repeated id {name!r}")
            seen.add(name)
            start, end = float(row["start"]), float(row["end"])
            if end <= start:
                raise SystemExit(f"gold {name}: end must be after start")
            if section == "cuts" and row.get("kind") not in KINDS:
                raise SystemExit(f"gold {name}: kind must be one of {', '.join(KINDS)}")
            indexes = words_in(words, start, end)
            if not indexes:
                raise SystemExit(f"gold {name}: no transcript words in {start}-{end}")
            expected = _quote_words(row.get("quote"))
            actual = normalize(" ".join(words[index]["text"] for index in indexes)).split()
            if not expected or actual[: len(expected)] != expected:
                raise SystemExit(
                    f"gold {name}: quote does not start the interval {start}-{end}; "
                    f"transcript says {' '.join(actual[:8])!r}"
                )
            members[name] = (section, set(indexes))
    keep_words = set()
    gold_words = set()
    for section, indexes in members.values():
        (gold_words if section == "cuts" else keep_words).update(indexes)
    if gold_words & keep_words:
        raise SystemExit("gold: a cut and a must_keep share words")
    return data


def cut_intervals(phrases, mask):
    """Merge cut words that touch in the word stream into [start, end] intervals."""
    intervals = []
    current = None
    for phrase in phrases:
        dropped = mask.get(phrase["id"], set())
        for index, word in enumerate(word_list(phrase)):
            if index in dropped:
                if current is None:
                    current = [float(word["start"]), float(word["end"])]
                else:
                    current[1] = float(word["end"])
            elif current is not None:
                intervals.append(current)
                current = None
    if current is not None:
        intervals.append(current)
    return [{"start": round(start, 3), "end": round(end, 3)} for start, end in intervals]


def detect(transcript):
    """Detection step on a stored transcript. Splits sentences unless it is already split."""
    segments = transcript.get("segments") if isinstance(transcript, dict) else transcript
    if not (isinstance(transcript, dict) and transcript.get("sentence_ids")):
        segments = split_phrases(segments)
    phrases = phrases_from_segments(segments)
    _groups, mask = detect_cuts(phrases)
    return cut_intervals(phrases, mask)


def _share(part, whole):
    return part / whole if whole > 0 else 0.0


def _status(share):
    if share >= HIT_SHARE:
        return "HIT"
    return "PARTIAL" if share >= PARTIAL_SHARE else "MISS"


def score(words, gold, intervals):
    cut = set()
    for item in intervals:
        cut.update(words_in(words, float(item["start"]), float(item["end"])))
    cases = []
    gold_words = set()
    totals = {"target": [0.0, 0.0], "expected_miss": [0.0, 0.0], "regression": [0.0, 0.0], "meaning": [0.0, 0.0]}
    for row in gold["cuts"]:
        indexes = set(words_in(words, float(row["start"]), float(row["end"])))
        gold_words |= indexes
        whole = seconds(words, indexes)
        covered = seconds(words, indexes & cut)
        bucket = "regression" if row["kind"] == "regression" else (
            "expected_miss" if row.get("expected_miss") else "target"
        )
        totals[bucket][0] += covered
        totals[bucket][1] += whole
        if row.get("requires_meaning") and bucket == "target":
            totals["meaning"][0] += covered
            totals["meaning"][1] += whole
        cases.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "expected_miss": bool(row.get("expected_miss")),
                "requires_meaning": bool(row.get("requires_meaning")),
                "start": float(row["start"]),
                "end": float(row["end"]),
                "gold_s": round(whole, 3),
                "covered_s": round(covered, 3),
                "share": round(_share(covered, whole), 3),
                "status": _status(_share(covered, whole)),
            }
        )
    keep_words = set()
    for row in gold["must_keep"]:
        keep_words.update(words_in(words, float(row["start"]), float(row["end"])))
    cut_total = seconds(words, cut)
    hits = seconds(words, cut & gold_words)
    unexplained = sorted(cut - gold_words - keep_words)
    ranges = []
    for index in unexplained:
        word = words[index]
        if ranges and word["start"] - ranges[-1]["end"] < RANGE_JOIN_S:
            ranges[-1]["end"] = word["end"]
            ranges[-1]["indexes"].append(index)
        else:
            ranges.append({"start": word["start"], "end": word["end"], "indexes": [index]})
    listed = [
        {
            "start": round(item["start"], 2),
            "end": round(item["end"], 2),
            "seconds": round(seconds(words, item["indexes"]), 2),
            "quote": " ".join(words[index]["text"] for index in item["indexes"])[:120],
        }
        for item in ranges
    ]
    summary = {
        "recall_s": _pair(totals["target"]),
        "expected_miss": _pair(totals["expected_miss"]),
        "requires_meaning": _pair(totals["meaning"]),
        "regression": _pair(totals["regression"]),
        "precision_s": {"hit": round(hits, 3), "cut": round(cut_total, 3), "share": round(_share(hits, cut_total), 3)},
        "collateral_s": round(seconds(words, cut & keep_words), 3),
        "unexplained_s": round(seconds(words, unexplained), 3),
        "cut_s": round(cut_total, 3),
    }
    return {"cases": cases, "summary": summary, "unexplained": listed}


def _pair(pair):
    covered, whole = pair
    return {"covered": round(covered, 3), "gold": round(whole, 3), "share": round(_share(covered, whole), 3)}


def _pct(value):
    return f"{value * 100:.0f}%"


def _kind_label(case):
    return case["kind"] + ("*" if case["expected_miss"] else "")


def format_report(result, baseline=None):
    lines = []
    base = {item["id"]: item for item in (baseline or {}).get("cases", [])}
    header = f"{'case':<8}{'kind':<13}{'gold_s':>7}{'covered_s':>11}{'share':>7}  status"
    if baseline:
        header += f"   baseline_s"
    lines.append(header)
    for case in result["cases"]:
        status = case["status"] + (" (expected_miss)" if case["expected_miss"] else "")
        status += " (requires_meaning)" if case["requires_meaning"] else ""
        line = (
            f"{case['id']:<8}{_kind_label(case):<13}{case['gold_s']:>7.2f}"
            f"{case['covered_s']:>11.2f}{_pct(case['share']):>7}  {status}"
        )
        if baseline and case["id"] in base:
            line += f"   {base[case['id']]['covered_s']:.2f}"
        lines.append(line)
    lines.append("")
    summary = result["summary"]
    other = (baseline or {}).get("summary") or {}

    def row(label, text, key=None, fmt=None):
        suffix = ""
        if baseline and key:
            suffix = f"   (baseline {fmt(other[key])})"
        lines.append(f"{label:<16}{text}{suffix}")

    def pair_text(item):
        return f"{item['covered']:.1f} / {item['gold']:.1f} s  {_pct(item['share'])}"

    row("target recall_s", pair_text(summary["recall_s"]), "recall_s", pair_text)
    if summary["requires_meaning"]["gold"] or other.get("requires_meaning"):
        row("  needs meaning", pair_text(summary["requires_meaning"]), None)
    row("expected_miss", pair_text(summary["expected_miss"]), "expected_miss", pair_text)
    row("regression", pair_text(summary["regression"]), "regression", pair_text)

    def precision_text(item):
        return f"{_pct(item['share'])}  ({item['hit']:.1f} / {item['cut']:.1f} s of cuts)"

    row("precision_s", precision_text(summary["precision_s"]), "precision_s", precision_text)
    row("collateral_s", f"{summary['collateral_s']:.2f} s", "collateral_s", lambda value: f"{value:.2f} s")
    row("unexplained_s", f"{summary['unexplained_s']:.2f} s", "unexplained_s", lambda value: f"{value:.2f} s")
    for item in result["unexplained"]:
        lines.append(f"  unexplained {item['start']:.2f}-{item['end']:.2f} ({item['seconds']:.2f} s) «{item['quote']}»")
    return "\n".join(lines)


def resolve(base, raw):
    path = Path(raw)
    return path if path.is_absolute() else (base / path)


def parse_args():
    parser = argparse.ArgumentParser(description="Score retake detection against a gold list of cuts, in seconds.")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--transcript", type=Path, help="defaults to the fixture named in the gold file")
    parser.add_argument("--cuts", type=Path, help="score stored cut intervals instead of running the detector")
    parser.add_argument("--save-cuts", type=Path, help="write the cut intervals and metrics to this file")
    parser.add_argument("--label", default="", help="detector label stored with --save-cuts")
    parser.add_argument("--compare", type=Path, help="stored cuts to show next to the current result")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.gold.is_file():
        raise SystemExit(f"gold not found: {args.gold}")
    here = Path(__file__).resolve().parent
    gold_raw = load_json(args.gold)
    transcript_path = args.transcript or resolve(here, gold_raw.get("fixture") or "")
    if not transcript_path.is_file():
        raise SystemExit(f"fixture not found: {transcript_path}")
    transcript = load_json(transcript_path)
    words = transcript_words(transcript)
    gold = load_gold(args.gold, words)
    if args.cuts:
        stored = load_json(args.cuts)
        intervals = stored.get("cuts") if isinstance(stored, dict) else stored
    else:
        intervals = detect(transcript)
    result = score(words, gold, intervals)
    baseline = None
    if args.compare:
        stored = load_json(args.compare)
        baseline = score(words, gold, stored.get("cuts") if isinstance(stored, dict) else stored)
    if args.save_cuts:
        payload = {
            "detector": args.label or "current",
            "gold": gold.get("job"),
            "metrics": result["summary"],
            "cuts": intervals,
        }
        args.save_cuts.parent.mkdir(parents=True, exist_ok=True)
        args.save_cuts.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_report(result, baseline))


if __name__ == "__main__":
    main()
