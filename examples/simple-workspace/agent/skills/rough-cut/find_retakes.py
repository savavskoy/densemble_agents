#!/usr/bin/env python3
"""Find candidate retake clusters in a transcript. No model calls.

Comparisons use normalized text (lowercase, punctuation removed, spaces
collapsed) and SequenceMatcher(autojunk=False). Four signals:

- similar: difflib ratio of two phrases is high, inside a window of 10
  phrases. Both phrases need at least 4 words, or at least 3 when the ratio
  is at least 0.85.
- prefix_restart: a later, longer phrase matches the earlier one on a prefix
  of the same length (same 10-phrase window)
- opener_restart: the first 3 normalized words match, the later phrase is
  within 6 segments and 40 seconds, and it follows a pause of at least 0.8s
  or the full-phrase ratio is at least 0.85
- short_pause: a short or truncated phrase, then a pause over 1.5s, then a
  longer phrase on a related topic

Each signal records its rule in "type". Clusters are transitive (union-find).
Clusters larger than MAX_CLUSTER_SIZE are logged and split by time proximity.
A one-phrase piece is merged back so the last take is not dropped.

Usage:
    python3 find_retakes.py <job_name> [--transcript PATH]

Reads /state/jobs/<job_name>/transcript.json and writes candidates.json
beside it. Override the jobs root with ROUGH_CUT_JOBS.
"""

import argparse
import json
import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

log = logging.getLogger("find_retakes")

DEFAULT_JOBS_ROOT = Path("/state/jobs")
WINDOW = 10
SIMILAR_MIN_RATIO = 0.60
SIMILAR_MIN_WORDS = 4
SIMILAR_RELAXED_RATIO = 0.85
SIMILAR_RELAXED_WORDS = 3
PREFIX_MIN_RATIO = 0.75
PREFIX_MIN_WORDS = 3
OPENER_WORDS = 3
OPENER_WINDOW = 6
OPENER_MAX_SECONDS = 40.0
OPENER_MIN_PAUSE = 0.8
OPENER_MIN_RATIO = 0.85
PAUSE_SECONDS = 1.5
TOPIC_MIN_SCORE = 0.45
SHORT_MAX_WORDS = 12
SHORT_LENGTH_RATIO = 0.75
MAX_CLUSTER_SIZE = 12
PUNCTUATION = re.compile(r"[^\w\s']+", re.UNICODE)
SPACES = re.compile(r"\s+")
STOPWORDS = frozenset(
    """
    a an the and or to of in on for with at from by as is it that this we you
    i he she they be was were are not just so
    і й та але або що це як на не у в з із до від про за ми ви я ти він вона
    вони його її їх вже ще то ж би
    и но а что это как на не к по из от за для мы вы я ты он она они его ее их
    уже то же бы
    """.split()
)


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


# Spoken variants that should match across takes.
VARIANTS = {"у": "в", "в": "в", "ув": "в", "і": "і", "й": "і", "з": "з", "із": "з", "зі": "з"}


def normalize(text):
    lowered = (text or "").lower()
    stripped = PUNCTUATION.sub(" ", lowered)
    tokens = [VARIANTS.get(word, word) for word in SPACES.sub(" ", stripped).split()]
    return " ".join(tokens)


def word_count(text):
    return len(text.split()) if text else 0


def content_words(text):
    return {word for word in text.split() if word not in STOPWORDS and len(word) > 1}


def ratio(left, right):
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def prefix_ratio(earlier, later):
    """Score the earlier phrase against the same-length prefix of the later one."""
    if not earlier or len(later) <= len(earlier):
        return 0.0
    return ratio(earlier, later[: len(earlier)])


def opening_words(text, count=OPENER_WORDS):
    words = text.split()
    if len(words) < count:
        return None
    return words[:count]


def pause_before(phrases, index):
    if index <= 0:
        return 0.0
    return phrases[index]["start"] - phrases[index - 1]["end"]


def similar_match(earlier, later, full):
    left = word_count(earlier)
    right = word_count(later)
    if left >= SIMILAR_MIN_WORDS and right >= SIMILAR_MIN_WORDS and full >= SIMILAR_MIN_RATIO:
        return True
    return (
        left >= SIMILAR_RELAXED_WORDS
        and right >= SIMILAR_RELAXED_WORDS
        and full >= SIMILAR_RELAXED_RATIO
    )


def topic_score(earlier, later):
    left = content_words(earlier)
    right = content_words(later)
    score = max(ratio(earlier, later), prefix_ratio(earlier, later), jaccard(left, right))
    if len(left) >= 2 and left <= right:
        score = max(score, 0.8)
    return score


def is_shorter(earlier, later):
    earlier_words = word_count(earlier)
    later_words = word_count(later)
    if earlier_words < 2 or later_words <= earlier_words:
        return False
    return earlier_words <= SHORT_MAX_WORDS or (earlier_words / later_words) <= SHORT_LENGTH_RATIO


def load_phrases(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(segments, list):
        raise SystemExit(f"transcript has no segments: {path}")
    phrases = []
    for segment in segments:
        text = normalize(segment.get("text"))
        if not text:
            continue
        phrases.append(
            {
                "id": segment["id"],
                "start": float(segment.get("start") or 0),
                "end": float(segment.get("end") or 0),
                "text": (segment.get("text") or "").strip(),
                "norm": text,
            }
        )
    return phrases


def collect_signals(phrases):
    signals = []
    for index, earlier in enumerate(phrases):
        last = min(len(phrases), index + 1 + WINDOW)
        for later_index in range(index + 1, last):
            later = phrases[later_index]
            full = ratio(earlier["norm"], later["norm"])
            if similar_match(earlier["norm"], later["norm"], full):
                signals.append(signal("similar", earlier, later, full))
            if later_index - index <= OPENER_WINDOW and later["start"] - earlier["start"] <= OPENER_MAX_SECONDS:
                same_open = opening_words(earlier["norm"])
                if same_open and same_open == opening_words(later["norm"]):
                    pause = pause_before(phrases, later_index)
                    if pause >= OPENER_MIN_PAUSE or full >= OPENER_MIN_RATIO:
                        signals.append(signal("opener_restart", earlier, later, full, pause))
            lead = prefix_ratio(earlier["norm"], later["norm"])
            if (
                word_count(earlier["norm"]) >= PREFIX_MIN_WORDS
                and word_count(later["norm"]) > word_count(earlier["norm"])
                and lead >= PREFIX_MIN_RATIO
            ):
                signals.append(signal("prefix_restart", earlier, later, lead))
            if later_index == index + 1:
                pause = later["start"] - earlier["end"]
                topic = topic_score(earlier["norm"], later["norm"])
                if pause > PAUSE_SECONDS and is_shorter(earlier["norm"], later["norm"]) and topic >= TOPIC_MIN_SCORE:
                    signals.append(signal("short_pause", earlier, later, topic, pause))
    return signals


def signal(kind, earlier, later, score, pause=None):
    item = {
        "type": kind,
        "earlier_id": earlier["id"],
        "later_id": later["id"],
        "score": round(score, 3),
    }
    if pause is not None:
        item["pause_s"] = round(pause, 3)
    return item


def cluster_signals(phrases, signals):
    parent = {phrase["id"]: phrase["id"] for phrase in phrases}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for item in signals:
        union(item["earlier_id"], item["later_id"])
    grouped = {}
    for item in signals:
        grouped.setdefault(find(item["earlier_id"]), []).append(item)
    by_id = {phrase["id"]: phrase for phrase in phrases}
    clusters = []
    for group in grouped.values():
        ids = sorted({value for item in group for value in (item["earlier_id"], item["later_id"])})
        group.sort(key=lambda item: (item["earlier_id"], item["later_id"], item["type"]))
        clusters.append(
            {
                "segment_ids": ids,
                "members": [
                    {
                        "id": by_id[segment_id]["id"],
                        "start": by_id[segment_id]["start"],
                        "end": by_id[segment_id]["end"],
                        "text": by_id[segment_id]["text"],
                    }
                    for segment_id in ids
                ],
                "signals": group,
            }
        )
    clusters.sort(key=lambda item: item["segment_ids"][0])
    return number_clusters(cap_clusters(clusters))


def split_by_proximity(members, cap):
    ordered = sorted(members, key=lambda item: (item["start"], item["id"]))
    if len(ordered) <= cap:
        return [ordered]
    middle = len(ordered) / 2
    split_at = 1
    best = None
    for index in range(1, len(ordered)):
        gap = ordered[index]["start"] - ordered[index - 1]["end"]
        rank = (gap, -abs(index - middle))
        if best is None or rank > best:
            best = rank
            split_at = index
    pieces = split_by_proximity(ordered[:split_at], cap) + split_by_proximity(ordered[split_at:], cap)
    return merge_orphan_pieces(pieces)


def merge_orphan_pieces(pieces):
    """Keep a one-phrase side of a proximity split with its neighbor.

    The widest gap is often the pause before the last take. Dropping that
    singleton would remove the last duplicate from the cluster.
    """
    if not pieces:
        return pieces
    merged = [list(pieces[0])]
    for piece in pieces[1:]:
        if len(piece) < 2 or len(merged[-1]) < 2:
            merged[-1].extend(piece)
        else:
            merged.append(list(piece))
    if len(merged) > 1 and len(merged[0]) < 2:
        merged[1] = merged[0] + merged[1]
        merged = merged[1:]
    return merged


def cap_clusters(clusters):
    capped = []
    for cluster in clusters:
        members = cluster["members"]
        if len(members) <= MAX_CLUSTER_SIZE:
            capped.append(cluster)
            continue
        log.warning(
            "cluster of %d phrases exceeds MAX_CLUSTER_SIZE=%d; splitting by proximity (ids %s)",
            len(members),
            MAX_CLUSTER_SIZE,
            cluster["segment_ids"],
        )
        for piece in split_by_proximity(members, MAX_CLUSTER_SIZE):
            if len(piece) < 2:
                continue
            ids = sorted(member["id"] for member in piece)
            present = set(ids)
            signals = [
                item
                for item in cluster["signals"]
                if item["earlier_id"] in present and item["later_id"] in present
            ]
            capped.append(
                {
                    "segment_ids": ids,
                    "members": sorted(piece, key=lambda item: (item["start"], item["id"])),
                    "signals": signals,
                }
            )
    return capped


def number_clusters(clusters):
    clusters.sort(key=lambda item: item["segment_ids"][0])
    for index, item in enumerate(clusters):
        item["id"] = index
    return clusters


def write_candidates(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Find retake candidates in a rough-cut transcript.")
    parser.add_argument("job_name")
    parser.add_argument("--transcript", type=Path, help="defaults to the job's transcript.json")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = parse_args()
    folder = job_dir(args.job_name)
    transcript = args.transcript.expanduser() if args.transcript else folder / "transcript.json"
    if not transcript.is_file():
        raise SystemExit(f"transcript not found: {transcript}")
    phrases = load_phrases(transcript)
    clusters = cluster_signals(phrases, collect_signals(phrases))
    out_path = folder / "candidates.json"
    write_candidates(
        out_path,
        {
            "job": args.job_name,
            "transcript": str(transcript),
            "phrase_count": len(phrases),
            "clusters": clusters,
        },
    )
    print(out_path)


if __name__ == "__main__":
    main()
