#!/usr/bin/env python3
"""Group duplicate takes into blocks and describe what a block cut removes.

A block runs from the start of take i to the start of take i+1 and includes
every sentence between those two restarts. The default edit drops every block
except the last one. Cuts follow word boundaries, so one sentence may be split.

Usage:
    python3 take_spans.py <job_name>

Writes /state/jobs/<job_name>/retake_groups.json. Override the jobs root with
ROUGH_CUT_JOBS.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from find_retakes import (
    OPENER_MAX_SECONDS,
    OPENER_WINDOW,
    collect_signals,
    job_dir,
    normalize,
    opening_words,
    ratio,
    signal,
    similar_match,
)
from review_policy import CUT_SIGNALS, UNIQUE_RETAKE_REASON, review_item

FRAGMENT_PREFIX = 2
FRAGMENT_WORD_SECONDS = 1.5
OPENER_CUT_WORDS = 4
# Strong signals cut on their own: opener_restart (same first 4 words), marker
# («точніше», «не так», «ще раз» between two same openings) and fragment_restart
# (an unfinished sentence, then the same 2 opening words).
# `similar` is weak. It cuts only when every guard below passes; otherwise the
# pair is listed in the report.
WEAK_TYPE = "similar"
# Guards for a weak cut. Each is the most conservative value that still gave the
# same result on the gold file (see eval_recall.py); a pair that fails a guard
# goes to the report instead of being cut.
WEAK_MAX_UNITS = 2  # the restart is at most this many sentences after the phrase
WEAK_MAX_GAP = 5.0  # ... and starts at most this many seconds after it
WEAK_MAX_CUT_SECONDS = 10.0  # a single weak cut is never longer than this
WEAK_NEAR_DUPLICATE = 0.85  # below this ratio the speaker must have stopped first
WEAK_RESTART_PAUSE = 3.0  # ... for at least this long
# A cut take also drops the tail that follows its first phrase, up to the next
# take. A following sentence joins the cut only while the pause before it stays
# under TAIL_GAP, it belongs to no group, and it is either unfinished or said
# again in the next TAIL_LOOKAHEAD sentences of the later take. A finished
# sentence that is not repeated stays in the timeline.
TAIL_GAP = 0.5
TAIL_LOOKAHEAD = 6
# Detected, written to the report, never turned into a cut. `similar` is
# reported when the guards stopped it.
REPORT_ONLY_TYPES = frozenset({"prefix_restart", "short_pause", "similar"})
ACTIONS = ("drop_all_but_last", "keep_all", "needs_review")
DEFAULT_ACTION = "drop_all_but_last"
MODEL_ACTIONS = frozenset({"keep_all", "needs_review"})
_ELLIPSIS_RE = re.compile(r"(?:\.\.\.|…)[\"'»”)\]]*$")


def load_sentences(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    segments = data.get("segments") if isinstance(data, dict) else data
    if not isinstance(segments, list):
        raise SystemExit(f"transcript has no segments: {path}")
    return phrases_from_segments(segments)


def phrases_from_segments(segments):
    """Sentence rows from transcript segments: normalized text, word times, sorted by time."""
    phrases = []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        norm = normalize(text)
        if not norm:
            continue
        words = []
        for word in segment.get("words") or []:
            token = (word.get("word") or "").strip()
            if not token:
                continue
            words.append(
                {
                    "word": token,
                    "start": float(word["start"]),
                    "end": float(word["end"]),
                }
            )
        phrases.append(
            {
                "id": int(segment["id"]),
                "start": float(segment.get("start") or 0),
                "end": float(segment.get("end") or 0),
                "text": text,
                "norm": norm,
                "words": words,
            }
        )
    phrases.sort(key=lambda phrase: (phrase["start"], phrase["id"]))
    return phrases


def word_list(phrase):
    words = phrase.get("words") or []
    if words:
        return words
    return [{"word": phrase["text"], "start": phrase["start"], "end": phrase["end"]}]


def sentence_start(phrase):
    return float(word_list(phrase)[0]["start"])


def sentence_end(phrase):
    return float(word_list(phrase)[-1]["end"])


def is_restart_marker(norm):
    words = (norm or "").split()
    if "точніше" in words:
        return True
    pairs = set(zip(words, words[1:]))
    return ("не", "так") in pairs or ("ще", "раз") in pairs


def marker_links(phrases):
    """Bridge two same openings when a restart marker sits between them.

    The pair must be as close as an `opener_restart` pair: inside OPENER_WINDOW
    sentences and OPENER_MAX_SECONDS. A marker relaxes the 4-word match to 3
    words; it does not relax how near the restart is. Without this a late line
    with the same opening, far from the marker, cuts an early phrase.
    """
    links = []
    for marker_index, marker in enumerate(phrases):
        if not is_restart_marker(marker["norm"]):
            continue
        for later_index in range(marker_index + 1, min(len(phrases), marker_index + 1 + OPENER_WINDOW)):
            later = phrases[later_index]
            opening = opening_words(later["norm"])
            if not opening:
                continue
            earlier = None
            low = max(0, later_index - OPENER_WINDOW)
            for earlier_index in range(marker_index - 1, low - 1, -1):
                previous = phrases[earlier_index]
                if later["start"] - previous["start"] > OPENER_MAX_SECONDS:
                    break
                if opening_words(previous["norm"]) == opening:
                    earlier = previous
                    break
            if earlier is None:
                continue
            links.append(signal("marker", earlier, later, ratio(earlier["norm"], later["norm"])))
            break
    return links


class _Union:
    def __init__(self):
        self.parent = {}

    def add(self, item):
        self.parent.setdefault(item, item)

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left, right):
        self.add(left)
        self.add(right)
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _span(link, by_id):
    return by_id[link["later_id"]]["start"] - by_id[link["earlier_id"]]["start"]


def _crosses(link, starts, by_id):
    earlier = by_id[link["earlier_id"]]["start"]
    later = by_id[link["later_id"]]["start"]
    for take_id in starts:
        moment = by_id[take_id]["start"]
        if earlier < moment < later:
            return True
    return False


def _touches(link, starts):
    return link["earlier_id"] in starts or link["later_id"] in starts


def _core(text):
    return (text or "").strip().rstrip("\"'»”)]")


def is_unfinished(phrase):
    """A cut-off phrase: an ellipsis, three words or fewer, or a stretched last word.

    A missing .?! is not enough. A sentence split on a pause often ends on a comma
    and is still a complete clause.
    """
    text = (phrase.get("text") or "").strip()
    norm = phrase.get("norm") or normalize(text)
    if _ELLIPSIS_RE.search(_core(text)):
        return True
    if len(norm.split()) <= 3:
        return True
    words = phrase.get("words") or []
    if words:
        last = words[-1]
        if float(last["end"]) - float(last["start"]) > FRAGMENT_WORD_SECONDS:
            return True
    return False


def shared_prefix_len(left, right):
    count = 0
    for earlier, later in zip((left or "").split(), (right or "").split()):
        if earlier != later:
            break
        count += 1
    return count


def qualifies_early_cut(earlier, later):
    """Cut the earlier phrase only when the later one shares its opening, or it is unfinished."""
    earlier_norm = earlier.get("norm") or normalize(earlier.get("text") or "")
    later_norm = later.get("norm") or normalize(later.get("text") or "")
    if shared_prefix_len(earlier_norm, later_norm) >= FRAGMENT_PREFIX:
        return True
    return is_unfinished(earlier)


def opener_cut_links(phrases):
    """Cut when the first 4 normalized words match. A pause is not required.

    The search stays inside the existing opener window.
    """
    links = []
    for index, earlier in enumerate(phrases):
        opening = opening_words(earlier.get("norm") or "", OPENER_CUT_WORDS)
        if not opening:
            continue
        last = min(len(phrases), index + 1 + OPENER_WINDOW)
        for later_index in range(index + 1, last):
            later = phrases[later_index]
            if later["start"] - earlier["start"] > OPENER_MAX_SECONDS:
                break
            if opening_words(later.get("norm") or "", OPENER_CUT_WORDS) != opening:
                continue
            links.append(signal("opener_restart", earlier, later, 1.0))
    return links


def fragment_restart_links(phrases):
    """Unfinished sentence whose next sentence restarts the same two normalized words.

    Only the immediately following sentence counts. A finished sentence that
    shares an opening with a later line (118 → 124) is not a group.
    """
    links = []
    for index in range(len(phrases) - 1):
        earlier = phrases[index]
        later = phrases[index + 1]
        earlier_norm = earlier.get("norm") or normalize(earlier.get("text") or "")
        later_norm = later.get("norm") or normalize(later.get("text") or "")
        if not is_unfinished(earlier):
            continue
        if shared_prefix_len(earlier_norm, later_norm) < FRAGMENT_PREFIX:
            continue
        links.append(signal("fragment_restart", earlier, later, ratio(earlier_norm, later_norm)))
    return links


def accepted_links(phrases):
    """opener_restart, markers, fragment restarts, then similar links that do not jump a take."""
    by_id = {phrase["id"]: phrase for phrase in phrases}
    found = collect_signals(phrases)
    strong = [item for item in found if item["type"] == "opener_restart"]
    strong.extend(marker_links(phrases))
    strong.extend(fragment_restart_links(phrases))
    starts = set()
    for item in strong:
        starts.add(item["earlier_id"])
        starts.add(item["later_id"])
    similars = [item for item in found if item["type"] == "similar"]
    similars.sort(key=lambda item: (-_span(item, by_id), item["earlier_id"], item["later_id"]))
    kept = list(strong)

    def accept(item):
        starts.add(item["earlier_id"])
        starts.add(item["later_id"])
        kept.append(item)

    # Extend an opening chain before accepting a paraphrase that merely sits inside it.
    remaining = list(similars)
    while True:
        touching = [item for item in remaining if _touches(item, starts) and not _crosses(item, starts, by_id)]
        if not touching:
            break
        accept(touching[0])
        remaining.remove(touching[0])
    for item in remaining:
        if _crosses(item, starts, by_id):
            continue
        accept(item)
    return kept


def _groups_from_links(phrases, links):
    if not links:
        return []
    union = _Union()
    for item in links:
        union.union(item["earlier_id"], item["later_id"])
    buckets = {}
    for item in links:
        buckets.setdefault(union.find(item["earlier_id"]), []).append(item)
    groups = []
    for grouped in buckets.values():
        ids = {value for item in grouped for value in (item["earlier_id"], item["later_id"])}
        if len(ids) < 2:
            continue
        groups.append({"ids": ids, "links": grouped})
    return groups


def _clip_end(phrases, start_index, end_index, foreign_kept):
    for index in range(start_index + 1, end_index):
        if phrases[index]["id"] in foreign_kept:
            return index
    return end_index


def _block_record(sentences, take_id, end_time, kept_phrases):
    start_time = sentence_start(sentences[0])
    text = " ".join(phrase["text"] for phrase in sentences).strip()
    return {
        "take_id": take_id,
        "start": round(start_time, 3),
        "end": round(end_time, 3),
        "text": text,
        "sentence_ids": [phrase["id"] for phrase in sentences],
        "unique_content": unique_sentences(sentences, take_id, kept_phrases),
    }


def similar_to_kept(phrase, kept_phrases):
    opening = opening_words(phrase["norm"])
    for kept in kept_phrases:
        if similar_match(phrase["norm"], kept["norm"], ratio(phrase["norm"], kept["norm"])):
            return True
        if opening and opening == opening_words(kept["norm"]):
            return True
    return False


def unique_sentences(sentences, anchor_id, kept_phrases):
    found = []
    for phrase in sentences:
        if phrase["id"] == anchor_id:
            continue
        if similar_to_kept(phrase, kept_phrases):
            continue
        found.append(
            {
                "id": phrase["id"],
                "start": round(sentence_start(phrase), 3),
                "end": round(sentence_end(phrase), 3),
                "text": phrase["text"],
            }
        )
    return found


def _said_again(sentence, phrases, start_index):
    """True when a later sentence repeats this one: similar text or the same 3-word opening."""
    opening = opening_words(sentence["norm"])
    for later in phrases[start_index : start_index + TAIL_LOOKAHEAD]:
        if similar_match(sentence["norm"], later["norm"], ratio(sentence["norm"], later["norm"])):
            return True
        if opening and opening == opening_words(later["norm"]):
            return True
    return False


def _tail_after(phrases, index_of, sentences, next_take_id, linked):
    """Sentences that continue a cut take without a real pause, up to the next take."""
    index = index_of[sentences[-1]["id"]]
    stop = index_of[next_take_id]
    grown = list(sentences)
    while index + 1 < stop:
        following = phrases[index + 1]
        if following["id"] in linked:
            break
        if sentence_start(following) - sentence_end(phrases[index]) >= TAIL_GAP:
            break
        if not is_unfinished(following) and not _said_again(following, phrases, stop):
            break
        grown.append(following)
        index += 1
    return grown


def _extend_tails(phrases, index_of, drafts):
    """Let every cut take drop its own tail. A marker group is not extended.

    A marker only says that some earlier words were a false start, not where
    that take ends, so its cut stays exactly the phrase that matched.
    """
    linked = {take_id for draft in drafts for take_id in draft["ordered"]}
    for draft in drafts:
        if any(item["type"] == "marker" for item in draft["links"]):
            continue
        blocks = draft["blocks"]
        for position in range(len(blocks) - 1):
            take_id, sentences, _end = blocks[position]
            grown = _tail_after(phrases, index_of, sentences, blocks[position + 1][0], linked)
            blocks[position] = (take_id, grown, sentence_end(grown[-1]))


def weak_link_reason(earlier, later, index_of, strong_ids):
    """Why a `similar` link may not cut `earlier`. None means every guard passed."""
    if earlier["id"] in strong_ids or later["id"] in strong_ids:
        return "уже в группе с сильным сигналом"
    if index_of[later["id"]] - index_of[earlier["id"]] > WEAK_MAX_UNITS:
        return "повтор не рядом"
    gap = sentence_start(later) - sentence_end(earlier)
    if gap > WEAK_MAX_GAP:
        return "повтор не рядом"
    if sentence_end(earlier) - sentence_start(earlier) > WEAK_MAX_CUT_SECONDS:
        return "кусок длиннее предела"
    if ratio(earlier["norm"], later["norm"]) < WEAK_NEAR_DUPLICATE and gap < WEAK_RESTART_PAUSE:
        return "перефраз без паузы"
    return None


def weak_links(phrases, strong, found=None):
    """`similar` links that passed every guard. They never join a strong group."""
    by_id = {phrase["id"]: phrase for phrase in phrases}
    index_of = {phrase["id"]: index for index, phrase in enumerate(phrases)}
    strong_ids = {take_id for item in strong for take_id in (item["earlier_id"], item["later_id"])}
    if found is None:
        found = collect_signals(phrases)
    return [
        item
        for item in found
        if item["type"] == WEAK_TYPE
        and weak_link_reason(by_id[item["earlier_id"]], by_id[item["later_id"]], index_of, strong_ids) is None
    ]


def _materialize(phrases, links, mode):
    """Turn links into groups. Span mode cuts everything up to the next take.

    Phrase mode cuts only the duplicate sentences, so a unique line between
    two takes stays in the timeline.
    """
    raw_groups = _groups_from_links(phrases, links)
    index_of = {phrase["id"]: index for index, phrase in enumerate(phrases)}
    prepared = []
    for group in raw_groups:
        ordered = sorted(group["ids"], key=lambda take_id: (index_of[take_id], take_id))
        prepared.append({"ordered": ordered, "links": group["links"]})
    kept_ids = {group["ordered"][-1] for group in prepared}
    drafts = []
    for group in prepared:
        ordered = group["ordered"]
        foreign = kept_ids - {ordered[-1]}
        blocks = []
        for position, take_id in enumerate(ordered):
            start_index = index_of[take_id]
            last = position + 1 == len(ordered)
            if mode == "phrase" or last:
                sentences = [phrases[start_index]]
                end_time = sentence_end(phrases[start_index])
            else:
                end_index = _clip_end(phrases, start_index, index_of[ordered[position + 1]], foreign)
                if end_index <= start_index:
                    continue
                sentences = phrases[start_index:end_index]
                end_time = sentence_start(phrases[end_index])
            blocks.append((take_id, sentences, end_time))
        if len(blocks) < 2:
            continue
        drafts.append({"ordered": ordered, "links": group["links"], "blocks": blocks})
    if mode == "phrase":
        _extend_tails(phrases, index_of, drafts)
    cut_ids = {
        phrase["id"]
        for draft in drafts
        for _take, sentences, _end in draft["blocks"][:-1]
        for phrase in sentences
    }
    kept_phrases = [phrase for phrase in phrases if phrase["id"] not in cut_ids]
    built = []
    for draft in drafts:
        records = [
            _block_record(sentences, take_id, end_time, kept_phrases)
            for take_id, sentences, end_time in draft["blocks"]
        ]
        built.append(
            {
                "kept_id": draft["ordered"][-1],
                "signals": sorted({item["type"] for item in draft["links"]}),
                "cut_mode": mode,
                "blocks": records,
                "_order": index_of[draft["ordered"][0]],
            }
        )
    return built


def build_retake_groups(phrases):
    """Groups that are actually cut.

    Strong signals cut: a 4-word opener_restart, a restart marker («точніше»,
    «не так», «ще раз») and a fragment_restart. A `similar` pair cuts only when
    weak_link_reason finds no guard. Each cut drops the duplicate phrase and
    the tail of that take (see _extend_tails). `short_pause` and
    `prefix_restart` stay in the report.
    """
    for phrase in phrases:
        phrase.setdefault("norm", normalize(phrase.get("text") or ""))
    strong = opener_cut_links(phrases) + marker_links(phrases) + fragment_restart_links(phrases)
    links = strong + weak_links(phrases, strong)
    built = _materialize(phrases, links, "phrase")
    built.sort(key=lambda group: (group["_order"], group["kept_id"]))
    for number, group in enumerate(built):
        group["id"] = number
        del group["_order"]
    return built


def detect_cuts(phrases):
    """Detection only: retake groups and the word mask they cut, before any pause policy."""
    groups = build_retake_groups(phrases)
    actions = {int(group["id"]): DEFAULT_ACTION for group in groups}
    return groups, word_mask(phrases, cut_blocks(groups, actions), [])


def write_groups(path, job_name, groups):
    payload = {
        "job": job_name,
        "default_action": DEFAULT_ACTION,
        "groups": groups,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_groups(folder):
    path = Path(folder) / "retake_groups.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("groups") if isinstance(payload, dict) else payload
    if not isinstance(groups, list):
        raise SystemExit(f"retake_groups.json has no groups: {path}")
    return groups


def _restore_covers(ops, blocks):
    """True when a human restore in take_overrides.json covers every cut block."""
    restores = [op for op in ops if op["op"] == "restore"]
    if not restores or not blocks:
        return False
    for block in blocks:
        start, end = float(block["start"]), float(block["end"])
        covered = any(
            float(op["start"]) <= start + 1e-3 and float(op["end"]) >= end - 1e-3 for op in restores
        )
        if not covered:
            return False
    return True


def load_actions(folder, groups):
    """Default every group to drop_all_but_last.

    keep_all and needs_review written by the model are ignored. keep_all is
    applied only when take_overrides.json restores every cut block of that group.
    Ignored decisions are returned as needs_review items.
    """
    path = Path(folder) / "group_decisions.json"
    actions = {int(group["id"]): DEFAULT_ACTION for group in groups}
    reasons = {}
    ignored = []
    ops = load_ops(folder)
    by_id = {int(group["id"]): group for group in groups}
    if not path.is_file():
        for group in groups:
            if _restore_covers(ops, (group.get("blocks") or [])[:-1]):
                actions[int(group["id"])] = "keep_all"
        return actions, reasons, ignored
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("groups") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise SystemExit("group_decisions.json must contain groups")
    known = set(actions)
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit("group decision must be an object")
        group_id = int(entry["id"])
        action = entry.get("action")
        if group_id not in known:
            raise SystemExit(f"unknown retake group id: {group_id}")
        if action not in ACTIONS:
            raise SystemExit(f"group {group_id} action must be one of {', '.join(ACTIONS)}")
        reason = (entry.get("reason") or "").strip()
        if not reason:
            raise SystemExit(f"group {group_id} needs a reason")
        group = by_id[group_id]
        blocks = (group.get("blocks") or [])[:-1]
        if action == DEFAULT_ACTION:
            actions[group_id] = action
            reasons[group_id] = reason
            continue
        if action in MODEL_ACTIONS and _restore_covers(ops, blocks):
            actions[group_id] = "keep_all"
            reasons[group_id] = reason
            continue
        actions[group_id] = DEFAULT_ACTION
        quote = ""
        at = ""
        if group.get("blocks"):
            quote = group["blocks"][0].get("text") or ""
            at = f"{group['blocks'][0]['start']:.1f}–{group['blocks'][-1]['end']:.1f}"
        print(
            f"warning: group {group_id} action {action} ignored; no restore in take_overrides.json",
            file=sys.stderr,
        )
        ignored.append(
            review_item(
                "ignored_decision",
                at,
                quote,
                f"{action} из group_decisions.json проигнорировано: нет restore в take_overrides.json",
                group_id=group_id,
                action=action,
            )
        )
    for group in groups:
        group_id = int(group["id"])
        if actions[group_id] == "keep_all":
            continue
        if _restore_covers(ops, (group.get("blocks") or [])[:-1]):
            actions[group_id] = "keep_all"
    return actions, reasons, ignored


def load_ops(folder):
    path = Path(folder) / "take_overrides.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    ops = payload.get("ops") if isinstance(payload, dict) else payload
    if not isinstance(ops, list):
        raise SystemExit("take_overrides.json must contain ops")
    cleaned = []
    for op in ops:
        kind = op.get("op")
        if kind not in ("drop", "restore"):
            raise SystemExit("take override op must be drop or restore")
        start, end = float(op["start"]), float(op["end"])
        if end <= start:
            raise SystemExit("take override end must be after start")
        cleaned.append({"op": kind, "start": start, "end": end})
    return cleaned


def save_ops(folder, ops):
    path = Path(folder) / "take_overrides.json"
    path.write_text(json.dumps({"ops": ops}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def cut_blocks(groups, actions):
    """Non-last blocks of groups whose action is drop_all_but_last."""
    chosen = []
    for group in groups:
        if actions.get(int(group["id"]), DEFAULT_ACTION) != DEFAULT_ACTION:
            continue
        blocks = group.get("blocks") or []
        chosen.extend(blocks[:-1])
    return chosen


def _word_hits(word, start, end, *, closed_end=False):
    ws, we = float(word["start"]), float(word["end"])
    if we == ws:
        if closed_end:
            return start <= ws <= end
        return start <= ws < end
    return ws < end and we > start


def snap_range(phrases, start, end):
    """Expand a manual range so it covers whole words and does not end mid-word."""
    start, end = float(start), float(end)
    if end <= start:
        raise SystemExit("end must be after start")
    touching = []
    for phrase in phrases:
        for word in word_list(phrase):
            if _word_hits(word, start, end):
                touching.append(word)
    if not touching:
        return round(start, 3), round(end, 3)
    snapped_start = min(float(word["start"]) for word in touching)
    snapped_end = max(float(word["end"]) for word in touching)
    return round(snapped_start, 3), round(snapped_end, 3)


def word_mask(phrases, blocks, ops):
    """Word indexes to remove. Group blocks drop whole sentences; ops then edit the mask."""
    by_id = {phrase["id"]: phrase for phrase in phrases}
    mask = {phrase["id"]: set() for phrase in phrases}
    for block in blocks:
        for sentence_id in block.get("sentence_ids") or []:
            phrase = by_id.get(int(sentence_id))
            if phrase is None:
                continue
            mask[phrase["id"]].update(range(len(word_list(phrase))))
    for op in ops:
        start, end = float(op["start"]), float(op["end"])
        for phrase in phrases:
            words = word_list(phrase)
            for index, word in enumerate(words):
                closed = op["op"] == "restore"
                if not _word_hits(word, start, end, closed_end=closed):
                    continue
                if op["op"] == "drop":
                    mask[phrase["id"]].add(index)
                else:
                    mask[phrase["id"]].discard(index)
    return mask


def apply_mask(phrases, mask):
    """Keep unmasked words. A chunk after a cut does not join the previous phrase."""
    output = []
    pending_cut = False
    for phrase in phrases:
        words = phrase.get("words") or []
        synthetic = not words
        units = word_list(phrase)
        dropped = mask.get(phrase["id"], set())
        if synthetic and 0 in dropped:
            pending_cut = True
            continue
        if not synthetic and len(dropped) >= len(units):
            pending_cut = True
            continue
        if synthetic:
            chunk = dict(phrase)
            chunk["hard_cut"] = pending_cut
            output.append(chunk)
            pending_cut = False
            continue
        current = []
        hard = pending_cut
        for index, word in enumerate(words):
            if index in dropped:
                if current:
                    output.append(_chunk(phrase, current, hard))
                    current = []
                    hard = False
                hard = True
                pending_cut = True
            else:
                current.append(word)
        if current:
            output.append(_chunk(phrase, current, hard))
            pending_cut = False
    return output


def _chunk(phrase, words, hard_cut):
    text = " ".join(word["word"] for word in words).strip()
    return {
        "id": phrase["id"],
        "start": float(words[0]["start"]),
        "end": float(words[-1]["end"]),
        "text": text,
        "norm": normalize(text),
        "words": words,
        "hard_cut": bool(hard_cut),
    }


def kept_phrases_after(phrases, mask):
    kept = []
    for phrase in phrases:
        words = word_list(phrase)
        dropped = mask.get(phrase["id"], set())
        if len(dropped) >= len(words):
            continue
        if phrase.get("words"):
            remaining = [word for index, word in enumerate(phrase["words"]) if index not in dropped]
            text = " ".join(word["word"] for word in remaining).strip()
        else:
            text = phrase["text"]
        kept.append({"id": phrase["id"], "text": text, "norm": normalize(text)})
    return kept


def review_for_plan(phrases, groups, actions, reasons, mask):
    """needs_review rows: LLM holds, plus unique sentences that the cut actually removed."""
    items = []
    by_id = {phrase["id"]: phrase for phrase in phrases}
    kept = kept_phrases_after(phrases, mask)
    seen = set()
    for group in groups:
        action = actions.get(int(group["id"]), DEFAULT_ACTION)
        if action == "needs_review":
            blocks = group.get("blocks") or []
            quote = blocks[0]["text"] if blocks else ""
            at = ""
            if blocks:
                at = f"{blocks[0]['start']:.1f}–{blocks[-1]['end']:.1f}"
            items.append(
                review_item(
                    "retake_group",
                    at,
                    quote,
                    reasons.get(int(group["id"])) or "Группа дублей без автоматического вырезания",
                    group_id=int(group["id"]),
                )
            )
        if action != DEFAULT_ACTION:
            continue
        for block in (group.get("blocks") or [])[:-1]:
            anchor = int(block["take_id"])
            for sentence_id in block.get("sentence_ids") or []:
                sentence_id = int(sentence_id)
                if sentence_id == anchor or sentence_id in seen:
                    continue
                phrase = by_id.get(sentence_id)
                if phrase is None:
                    continue
                words = word_list(phrase)
                dropped = mask.get(sentence_id, set())
                if not dropped:
                    continue
                if phrase.get("words"):
                    removed = [word for index, word in enumerate(phrase["words"]) if index in dropped]
                    text = " ".join(word["word"] for word in removed).strip()
                else:
                    text = phrase["text"]
                fragment = {"id": sentence_id, "text": text, "norm": normalize(text)}
                if not text or similar_to_kept(fragment, kept):
                    continue
                seen.add(sentence_id)
                start = sentence_start(phrase)
                end = sentence_end(phrase)
                items.append(
                    review_item(
                        "unique_retake",
                        f"{start:.1f}–{end:.1f}",
                        text,
                        UNIQUE_RETAKE_REASON,
                        phrase_id=sentence_id,
                        group_id=int(group["id"]),
                    )
                )
    return items


def cut_take_items(groups, actions):
    """One row per automatically cut block, for the owner-facing report."""
    items = []
    for group in groups:
        if actions.get(int(group["id"]), DEFAULT_ACTION) != DEFAULT_ACTION:
            continue
        signals = [name for name in CUT_SIGNALS if name in (group.get("signals") or [])]
        if not signals:
            signals = list(group.get("signals") or ["retake"])
        for block in (group.get("blocks") or [])[:-1]:
            start, end = float(block["start"]), float(block["end"])
            items.append(
                review_item(
                    "cut_take",
                    f"{start:.1f}–{end:.1f}",
                    block.get("text") or "",
                    signals[0],
                    signal=signals[0],
                    signals=signals,
                    start=round(start, 3),
                    end=round(end, 3),
                )
            )
    items.sort(key=lambda item: (item.get("start") or 0, item.get("at") or ""))
    return items


def _quote_pair(earlier, later):
    left = (earlier.get("text") or "").strip()
    right = (later.get("text") or "").strip()
    if right:
        return f"{left} | {right}"
    return left


def _strong_ids(groups):
    """Sentence ids that sit in a group with at least one strong signal."""
    found = set()
    for group in groups or []:
        if set(group.get("signals") or []) - {WEAK_TYPE}:
            for block in group.get("blocks") or []:
                found.add(int(block["take_id"]))
    return found


def suspicious_items(phrases, cut_ids, groups=None):
    """Signals that stay in the timeline. They are not cuts.

    A `similar` pair lands here when a guard stopped it; the reason says which.
    Trailing fragments are not listed here: qa.py reports them from the final timeline.
    """
    by_id = {phrase["id"]: phrase for phrase in phrases}
    index_of = {phrase["id"]: index for index, phrase in enumerate(phrases)}
    strong_ids = _strong_ids(groups)
    items = []
    seen = set()

    def add(kind, earlier, later, reason):
        if earlier["id"] in cut_ids:
            return
        key = (kind, earlier["id"], later["id"])
        if key in seen:
            return
        seen.add(key)
        items.append(
            review_item(
                kind,
                f"{sentence_start(earlier):.1f}–{sentence_end(earlier):.1f}",
                _quote_pair(earlier, later),
                reason,
                start=round(sentence_start(earlier), 3),
            )
        )

    for item in collect_signals(phrases):
        if item["type"] not in REPORT_ONLY_TYPES:
            continue
        earlier = by_id.get(item["earlier_id"])
        later = by_id.get(item["later_id"])
        if earlier is None or later is None:
            continue
        if item["type"] == WEAK_TYPE:
            why = weak_link_reason(earlier, later, index_of, strong_ids)
            reason = "Похожие фразы, дубль не вырезан" + (f": {why}" if why else "")
        else:
            reason = "Повтор начала, дубль не вырезан"
        add(item["type"], earlier, later, reason)
    items.sort(key=lambda item: (item.get("start") or 0, item.get("at") or ""))
    return items


def plan_cuts(folder, phrases):
    """Cut what retake_groups.json lists, then apply the owner's drop and restore ops.

    group_decisions.json is not read. Besides the cut rows, the report gets the
    pairs a guard stopped.
    """
    groups = load_groups(folder)
    actions = {int(group["id"]): DEFAULT_ACTION for group in groups}
    blocks = cut_blocks(groups, actions)
    mask = word_mask(phrases, blocks, load_ops(folder))
    extras = cut_take_items(groups, actions)
    cut_ids = {sentence_id for block in blocks for sentence_id in (block.get("sentence_ids") or [])}
    extras.extend(suspicious_items(phrases, cut_ids, groups))
    return mask, extras


def render_preview(folder, seconds):
    """Kept sentences in edit order, up to `seconds` of timeline."""
    folder = Path(folder)
    transcript = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))
    edl = json.loads((folder / "edl.json").read_text(encoding="utf-8"))
    by_id = {int(phrase["id"]): phrase for phrase in transcript["segments"]}
    from edl_policy import text_in_span

    lines = []
    cursor = 0.0
    for index, segment in enumerate(edl.get("keep_segments") or []):
        if cursor >= seconds:
            break
        if index and lines:
            lines.append("[✂]")
        start = float(segment.get("content_start", segment["start"]))
        end = float(segment.get("content_end", segment["end"]))
        for phrase_id in segment.get("phrase_ids") or []:
            phrase = by_id.get(int(phrase_id))
            if phrase is None:
                continue
            text = text_in_span(phrase, start, end)
            if text:
                lines.append(text)
        cursor += float(segment["end"]) - float(segment["start"])
    return "\n".join(lines)


def append_op(folder, kind, start, end):
    phrases = load_sentences(folder / "transcript.json")
    start, end = snap_range(phrases, start, end)
    ops = load_ops(folder)
    ops.append({"op": kind, "start": start, "end": end})
    save_ops(folder, ops)
    return start, end


def rebuild_and_report(job_name, seconds=60):
    script_dir = Path(__file__).resolve().parent
    built = __import__("subprocess").run(
        [sys.executable, str(script_dir / "build_edl.py"), job_name],
        check=False,
    )
    if built.returncode:
        raise SystemExit(built.returncode)
    qa = __import__("subprocess").run([sys.executable, str(script_dir / "qa.py"), job_name], check=False)
    print(render_preview(job_dir(job_name), seconds))
    if qa.returncode:
        raise SystemExit(qa.returncode)


def parse_args():
    parser = argparse.ArgumentParser(description="Build retake blocks from duplicate openings.")
    parser.add_argument("job_name")
    return parser.parse_args()


def main():
    args = parse_args()
    folder = job_dir(args.job_name)
    transcript = folder / "transcript.json"
    if not transcript.is_file():
        raise SystemExit(f"transcript not found: {transcript}")
    groups = build_retake_groups(load_sentences(transcript))
    path = folder / "retake_groups.json"
    write_groups(path, args.job_name, groups)
    print(path)


if __name__ == "__main__":
    main()
