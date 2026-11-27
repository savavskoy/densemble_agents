"""Confidence classes and needs_review.json for every rough-cut job."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

CONFIDENT_RATIO = 0.85
OPENER_PAUSE = 0.8

# The report lists the highest risk first. A duplicate that may still be in the
# timeline ranks above a phrase that merely trails off.
RISK = {
    "hidden_speech": 80,
    "retake_group": 70,
    "repeat_opener": 65,
    "similar": 60,
    "unique_retake": 60,
    "fragment_restart": 58,
    "ignored_decision": 55,
    "short_pause": 55,
    "duplicate_opener": 50,
    "prefix_restart": 45,
    "trailing_off": 40,
    "trailing_fragment": 10,
    "long_word": 5,
}
REPORT_LIMIT = 15

# Automatic cuts are counted and listed separately from the "check this" items.
CUT_SIGNALS = ("opener_restart", "marker", "fragment_restart", "similar")

UNIQUE_RETAKE_REASON = "текст из вырезанного дубля не повторяется, вернуть?"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def signals_of(candidates):
    if not isinstance(candidates, dict):
        return []
    found = []
    for cluster in candidates.get("clusters") or []:
        found.extend(cluster.get("signals") or [])
    return found


def is_confident(signal):
    score = float(signal.get("score") or 0)
    if score >= CONFIDENT_RATIO:
        return True
    if signal.get("type") == "opener_restart" and float(signal.get("pause_s") or 0) >= OPENER_PAUSE:
        return True
    return False


def confident_earlier_ids(candidates):
    """Last take wins on a confident link. The earlier phrase is cut."""
    dropped = set()
    for signal in signals_of(candidates):
        if is_confident(signal):
            dropped.add(int(signal["earlier_id"]))
    return dropped


def opening_pair(text):
    from find_retakes import normalize

    words = normalize(text).split()
    return tuple(words[:2]) if len(words) >= 2 else None


def uncertain_opener_ids(phrases, candidates):
    """Shared 2-word openings that are not a confident link. Keep both takes."""
    by_id = {int(phrase["id"]): phrase for phrase in phrases}
    confident_pairs = set()
    for signal in signals_of(candidates):
        if is_confident(signal):
            confident_pairs.add((int(signal["earlier_id"]), int(signal["later_id"])))
    kept = set()
    seen = set()
    for signal in signals_of(candidates):
        pair = (int(signal["earlier_id"]), int(signal["later_id"]))
        if pair in seen or pair in confident_pairs:
            continue
        seen.add(pair)
        earlier = by_id.get(pair[0])
        later = by_id.get(pair[1])
        if not earlier or not later:
            continue
        left = opening_pair(earlier.get("text"))
        right = opening_pair(later.get("text"))
        if left and left == right:
            kept.add(pair[0])
    return kept


def hidden_speech_drop(reason):
    text = (reason or "").lower()
    return "hidden speech" in text or "hidden_speech" in text


def apply_drop_policy(decisions, candidates, phrases):
    """Honor explicit drop_ids. Retake cuts come only from take spans."""
    del candidates, phrases
    dropped = set()
    kept_back = set()
    for item in decisions.get("drop_ids") or []:
        if not isinstance(item, dict):
            continue
        phrase_id = int(item["id"])
        if hidden_speech_drop(item.get("reason") or ""):
            kept_back.add(phrase_id)
            continue
        dropped.add(phrase_id)
    return dropped, [], sorted(kept_back)


def review_item(kind, at, quote, reason, **extra):
    islands = int(extra.get("islands") or 0)
    risk = RISK.get(kind, 0) + islands
    item = {
        "kind": kind,
        "at": at,
        "quote": (quote or "").strip()[:180],
        "reason": reason,
        "risk": risk,
    }
    item.update(extra)
    return item


def _leading_time(text):
    match = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return float(match.group()) if match else 0.0


def policy_sha1():
    path = Path(__file__).resolve().parent / "edl_policy.py"
    return hashlib.sha1(path.read_bytes()).hexdigest()


def from_islands(entries):
    items = []
    pauses = 0
    for entry in entries:
        if entry.get("dropped_word"):
            items.append(
                review_item(
                    "hidden_speech",
                    entry.get("at") or "",
                    entry.get("word") or "",
                    "длинное слово с несколькими островками вырезано целиком",
                    phrase_id=entry.get("phrase_id"),
                    word=entry.get("word"),
                    islands=int(entry.get("islands") or 0),
                    start=_leading_time(entry.get("at")),
                )
            )
            continue
        kept = entry.get("kept_islands") or []
        pauses += max(0, len(kept) - 1)
        items.append(
            review_item(
                "hidden_speech",
                entry.get("at") or "",
                entry.get("word") or "",
                f"{len(kept)} островка речи внутри длинного слова, тишина между ними вырезана",
                phrase_id=entry.get("phrase_id"),
                word=entry.get("word"),
                islands=len(kept),
                start=_leading_time(entry.get("at")),
            )
        )
    return items, pauses


def from_unresolved(errors):
    """repeat_opener pairs that no retake group removed. Risk sits above unique_retake."""
    items = []
    for error in errors or []:
        if error.get("rule") != "repeat_opener":
            continue
        items.append(
            review_item(
                "repeat_opener",
                error.get("at") or "",
                error.get("text") or "",
                "Повтор начала двух фраз подряд не снят",
                phrase_ids=error.get("phrase_ids"),
            )
        )
    return items


def from_warns(warns):
    items = []
    for warn in warns:
        rule = warn.get("rule")
        if rule not in {"duplicate_opener", "trailing_fragment", "trailing_off", "long_word"}:
            continue
        if rule == "duplicate_opener":
            reason = "Общее начало двух фраз, уверенность ниже порога"
        elif rule == "trailing_off":
            reason = "Растянутый хвост перед похожим началом"
        elif rule == "long_word":
            reason = "Длинное слово без тишины внутри, резать нечего"
        else:
            reason = "Фраза обрывается на запятую, многоточие или обрывок"
        items.append(
            review_item(
                rule,
                warn.get("at") or "",
                warn.get("text") or "",
                reason,
                phrase_ids=warn.get("phrase_ids"),
            )
        )
    return items


def _by_risk(item):
    return (-int(item.get("risk") or 0), _leading_time(item.get("at")), item.get("quote") or "")


def dedupe(items):
    """One row per (kind, place, quote). The highest risk wins."""
    best = {}
    order = []
    for item in items:
        key = (item.get("kind"), item.get("at"), item.get("quote"))
        if key not in best:
            order.append(key)
            best[key] = item
        elif int(item.get("risk") or 0) > int(best[key].get("risk") or 0):
            best[key] = item
    return [best[key] for key in order]


def _cut_summary(extra_items):
    cuts = [item for item in extra_items if item.get("kind") == "cut_take"]
    counts = {name: 0 for name in CUT_SIGNALS}
    for item in cuts:
        for name in item.get("signals") or []:
            if name in counts:
                counts[name] += 1
    cuts.sort(key=lambda item: (item.get("start") or 0, item.get("at") or ""))
    return counts, cuts


def write_needs_review(
    folder, island_entries, warns, auto_retakes, silence_splits, extra_items=None, compressed_pauses=0
):
    island_items, island_pauses = from_islands(island_entries)
    extra = list(extra_items or [])
    cut_counts, cut_takes = _cut_summary(extra)
    items = island_items + from_warns(warns) + [item for item in extra if item.get("kind") != "cut_take"]
    items = dedupe(items)
    items.sort(key=_by_risk)
    payload = {
        "auto_retakes": len(cut_takes),
        "auto_pauses": len(silence_splits) + island_pauses + int(compressed_pauses or 0),
        "cut_counts": cut_counts,
        "cut_takes": cut_takes,
        "policy_sha1": policy_sha1(),
        "items": items,
    }
    path = Path(folder) / "needs_review.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, payload


def format_report(folder, source_s, duration_s):
    payload = load_json(Path(folder) / "needs_review.json")
    lines = [
        f"Итог {duration_s:.1f} с из {source_s:.1f} с исходника.",
        f"Вырезано дублей: {payload.get('auto_retakes', 0)}, пауз сжато: {payload.get('auto_pauses', 0)}.",
        f"edl_policy.py sha1: {payload.get('policy_sha1') or policy_sha1()}.",
        "",
    ]
    cuts = sorted(
        payload.get("cut_takes") or [],
        key=lambda item: (_leading_time(item.get("at")), str(item.get("quote") or "")),
    )
    lines.append("Вырезано:")
    if not cuts:
        lines.append("пусто.")
    for index, item in enumerate(cuts, start=1):
        lines.append(f"{index}. {item.get('at')} — «{item.get('quote')}»")
    lines.append("")
    ranked = sorted(payload.get("items") or [], key=_by_risk)
    lines.append("Проверь вручную:")
    if not ranked:
        lines.append("пусто.")
    for index, item in enumerate(ranked[:REPORT_LIMIT], start=1):
        lines.append(f"{index}. {item.get('at')} — «{item.get('quote')}» — {item.get('reason')}")
    if len(ranked) > REPORT_LIMIT:
        lines.append(f"… ещё {len(ranked) - REPORT_LIMIT} в needs_review.json")
    return "\n".join(lines)
