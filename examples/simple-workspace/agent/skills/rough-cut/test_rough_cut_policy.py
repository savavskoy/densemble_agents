"""Pause policy, sentence pauses, timeline bounds, and a stable EDL."""

import json
import os
import tempfile
import unittest
import wave
from pathlib import Path

from audio_silence import Span
from build_edl import build_edl, publish
from build_timeline import load_edl, prepare
from edl_policy import final_bounds, pause_to_keep, snap_edge
from build_edl import next_word_starts
from long_word_repair import drop_word, long_words_in_kept, repair_pieces
from review_policy import dedupe, format_report, write_needs_review
from segment_sentences import split_phrases


def word(text, start, end):
    return {"word": text, "start": start, "end": end}


class PausePolicyTest(unittest.TestCase):
    def test_pause_caps(self):
        self.assertEqual(pause_to_keep(0, sentence_end=True), 0.0)
        self.assertEqual(pause_to_keep(0.1, sentence_end=True), 0.1)
        self.assertEqual(pause_to_keep(0.4, sentence_end=True), 0.3)
        self.assertEqual(pause_to_keep(0.4, sentence_end=False), 0.15)
        self.assertEqual(pause_to_keep(0.4, sentence_end=False, hard_cut=True), 0.25)
        self.assertEqual(pause_to_keep(2.0, sentence_end=True), 0.35)

    def test_original_pause_is_attached_and_a_long_gap_is_compressed(self):
        speech = [(0.0, 1.0), (1.5, 2.0), (6.0, 7.0)]
        bounds = final_bounds(speech, [True, False, True], [False, False, False], 8.0)
        self.assertEqual(bounds[0], (0.0, 1.3))
        self.assertEqual(bounds[1], (1.5, 2.35))
        self.assertEqual(bounds[2], (6.0, 7.3))

    def test_snap_moves_outward_only_within_a_tenth(self):
        self.assertEqual(snap_edge(1.0, [Span(1.04, 1.2)], "end"), 1.04)
        self.assertEqual(snap_edge(1.0, [Span(0.9, 0.96)], "end"), 1.0)
        self.assertEqual(snap_edge(1.0, [Span(0.92, 0.98)], "start"), 0.98)
        self.assertEqual(snap_edge(1.0, [Span(1.3, 1.5)], "end"), 1.0)

    def test_pause_does_not_run_into_a_cut_word(self):
        speech = [(0.0, 1.0), (40.0, 41.0)]
        plain = final_bounds(speech, [True, True], [False, True], 50.0)
        self.assertAlmostEqual(plain[0][1], 1.35)
        capped = final_bounds(speech, [True, True], [False, True], 50.0, ceilings=[1.0, float("inf")])
        self.assertAlmostEqual(capped[0][1], 1.0)
        roomy = final_bounds(speech, [True, True], [False, True], 50.0, ceilings=[1.2, float("inf")])
        self.assertAlmostEqual(roomy[0][1], 1.2)

    def test_next_word_start_counts_cut_words_and_has_no_limit_at_the_end(self):
        words = [word("а", 0.0, 1.0), word("б", 1.0, 1.4), word("в", 1.3, 2.0), word("г", 5.0, 5.5)]
        starts = next_word_starts([(0.0, 1.0), (1.0, 1.4), (5.0, 5.5)], words)
        self.assertEqual(starts[0], 1.0)
        self.assertEqual(starts[1], 1.4)  # overlapping next word: never earlier than the range end
        self.assertEqual(starts[2], float("inf"))

    def test_word_shorter_than_1_5s_is_not_opened(self):
        short = {"id": 1, "words": [word("пауза", 0.0, 1.4)]}
        self.assertEqual(list(long_words_in_kept([short], set())), [])
        long = {"id": 1, "words": [word("пауза", 0.0, 1.6)]}
        self.assertEqual(len(list(long_words_in_kept([long], set()))), 1)


class SentenceSplitTest(unittest.TestCase):
    def test_pause_of_0_7s_starts_a_sentence(self):
        phrases = [
            {
                "start": 0.0,
                "end": 3.0,
                "text": "перша частина друга частина",
                "words": [
                    word("перша", 0.0, 0.4),
                    word("частина", 0.5, 1.0),
                    word("друга", 1.7, 2.1),
                    word("частина", 2.2, 3.0),
                ],
            }
        ]
        rows = split_phrases(phrases)
        self.assertEqual([row["text"] for row in rows], ["перша частина", "друга частина"])
        self.assertGreaterEqual(rows[1]["pause_before"], 0.7)

    def test_tight_punctuation_splits_by_default_and_holds_when_the_flag_is_on(self):
        phrases = [
            {
                "start": 0.0,
                "end": 1.2,
                "text": "Кінець. Початок",
                "words": [word("Кінець.", 0.0, 0.5), word("Початок", 0.6, 1.2)],
            }
        ]
        split = split_phrases(phrases)
        self.assertEqual([row["text"] for row in split], ["Кінець.", "Початок"])
        held = split_phrases(phrases, hold_tight=True)
        self.assertEqual(len(held), 1)


class TimelineBoundsTest(unittest.TestCase):
    def test_missing_content_bounds_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edl.json"
            path.write_text(json.dumps({"keep_segments": [{"start": 0, "end": 1}]}), encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                load_edl(path)
        self.assertIn("content_start", str(caught.exception))

    def test_prepare_does_not_pad_or_merge(self):
        segments = load_edl_rows()
        prepared = prepare(segments, 10.0)
        self.assertEqual([(item["start"], item["end"]) for item in prepared], [(0.0, 1.0), (1.1, 2.0)])


def load_edl_rows():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "edl.json"
        path.write_text(
            json.dumps(
                {
                    "keep_segments": [
                        {"content_start": 0.0, "content_end": 1.0, "label": "a"},
                        {"content_start": 1.1, "content_end": 2.0, "label": "b"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return load_edl(path)


class ReportAndDeterminismTest(unittest.TestCase):
    def test_report_lists_every_cut_in_time_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            cuts = [
                {
                    "kind": "cut_take",
                    "at": f"{index}.0–{index}.5",
                    "quote": f"дубль {index}",
                    "reason": "prefix_restart",
                    "risk": 0,
                    "signal": "prefix_restart",
                    "signals": ["prefix_restart"],
                    "start": float(index),
                    "end": float(index) + 0.5,
                }
                for index in range(12)
            ]
            cuts.reverse()
            write_needs_review(folder, [], [], [], [], cuts)
            payload = json.loads((folder / "needs_review.json").read_text())
            payload["cut_takes"].reverse()
            (folder / "needs_review.json").write_text(json.dumps(payload))
            text = format_report(folder, 20, 10)
        self.assertIn("Вырезано дублей: 12", text)
        self.assertIn("Проверь вручную:", text)
        self.assertIn("edl_policy.py sha1:", text)
        self.assertEqual(text.count("дубль"), 12)
        order = [text.index(f"дубль {index}»") for index in range(12)]
        self.assertEqual(order, sorted(order))

    def test_report_is_deduped_and_ordered_by_risk_then_time(self):
        def item(kind, at, quote, risk):
            return {"kind": kind, "at": at, "quote": quote, "reason": kind, "risk": risk, "start": float(at.split("–")[0])}

        rows = [
            item("trailing_fragment", "1.0–2.0", "хвіст", 10),
            item("similar", "30.0–31.0", "пізній повтор", 60),
            item("similar", "9.0–10.0", "ранній повтор", 60),
            item("hidden_speech", "50.0–51.0", "прихована мова", 80),
            item("short_pause", "9.0–10.0", "ранній повтор", 55),
            item("similar", "9.0–10.0", "ранній повтор", 60),
        ]
        self.assertEqual(len(dedupe(rows)), 5)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_needs_review(folder, [], [], [], [], rows)
            text = format_report(folder, 20, 10)
        order = [text.index(word) for word in ("прихована мова", "ранній повтор", "пізній повтор", "хвіст")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(text.count("ранній повтор"), 2)

    def test_report_shows_fifteen_rows_and_counts_the_rest(self):
        rows = [
            {"kind": "similar", "at": f"{index}.0–{index}.5", "quote": f"рядок {index}", "reason": "similar", "risk": 60, "start": float(index)}
            for index in range(20)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write_needs_review(folder, [], [], [], [], rows)
            text = format_report(folder, 20, 10)
        self.assertIn("рядок 14", text)
        self.assertNotIn("рядок 15", text)
        self.assertIn("ещё 5 в needs_review.json", text)

    def test_two_builds_write_the_same_edl(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "job"
            folder.mkdir()
            wav = folder / "audio.wav"
            with wave.open(str(wav), "w") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\x00\x00" * 16000)
            transcript = {
                "duration": 1.0,
                "audio": str(wav),
                "segments": [
                    {
                        "id": 0,
                        "start": 0.1,
                        "end": 0.6,
                        "text": "Одна фраза.",
                        "words": [word("Одна", 0.1, 0.3), word("фраза.", 0.35, 0.6)],
                        "pause_before": 0.0,
                    }
                ],
            }
            (folder / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
            (folder / "decisions.json").write_text(json.dumps({"drop_ids": []}), encoding="utf-8")
            previous = os.environ.get("ROUGH_CUT_JOBS")
            os.environ["ROUGH_CUT_JOBS"] = str(Path(tmp))
            try:
                first = json.loads(publish(folder, build_edl(folder), []).read_text(encoding="utf-8"))
                second = json.loads(publish(folder, build_edl(folder), []).read_text(encoding="utf-8"))
            finally:
                if previous is None:
                    os.environ.pop("ROUGH_CUT_JOBS", None)
                else:
                    os.environ["ROUGH_CUT_JOBS"] = previous
        self.assertEqual(first, second)
        segment = first["keep_segments"][0]
        self.assertIn("content_start", segment)
        self.assertIn("content_end", segment)
        self.assertGreater(segment["content_end"], 0.6)
        self.assertLessEqual(segment["content_end"] - 0.6, 0.35)

    def test_a_cut_phrase_that_follows_without_a_pause_is_not_played(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "job"
            folder.mkdir()
            wav = folder / "audio.wav"
            with wave.open(str(wav), "w") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\x00\x00" * 16000 * 8)

            def segment(index, start, words):
                rows, cursor = [], start
                for text in words:
                    rows.append(word(text, cursor, cursor + 0.3))
                    cursor += 0.3
                return {"id": index, "start": start, "end": cursor, "text": " ".join(words), "words": rows, "pause_before": 0.0}

            first = segment(0, 0.1, ["Вступ", "тут."])
            cut = segment(1, first["end"], ["Сьогодні", "ми", "говоримо", "про", "паузи", "коротко."])
            kept = segment(2, 4.0, ["Сьогодні", "ми", "говоримо", "про", "паузи", "докладно."])
            transcript = {"duration": 8.0, "audio": str(wav), "segments": [first, cut, kept]}
            (folder / "transcript.json").write_text(json.dumps(transcript), encoding="utf-8")
            (folder / "decisions.json").write_text(json.dumps({"drop_ids": []}), encoding="utf-8")
            from take_spans import build_retake_groups, load_sentences, write_groups

            groups = build_retake_groups(load_sentences(folder / "transcript.json"))
            self.assertEqual(len(groups), 1)
            write_groups(folder / "retake_groups.json", "job", groups)
            previous = os.environ.get("ROUGH_CUT_JOBS")
            os.environ["ROUGH_CUT_JOBS"] = str(Path(tmp))
            try:
                edl = build_edl(folder)
            finally:
                if previous is None:
                    os.environ.pop("ROUGH_CUT_JOBS", None)
                else:
                    os.environ["ROUGH_CUT_JOBS"] = previous
        self.assertEqual(edl["keep_segments"][0]["phrase_ids"], [0])
        self.assertLessEqual(edl["keep_segments"][0]["end"], cut["words"][0]["start"] + 1e-6)

    def test_two_speech_islands_drop_the_whole_word(self):
        from audio_silence import Span
        import long_word_repair as repair

        piece = {
            "content_start": 0.0,
            "content_end": 4.0,
            "phrase_ids": [1],
            "label": "перед Копайлот після",
        }
        phrases = [{"id": 1, "words": [word("Копайлот", 1.0, 3.2)]}]
        original = repair.detect_silences
        repair.detect_silences = lambda _audio, _start, _end: [Span(1.6, 2.4)]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                audio = Path(tmp) / "audio.wav"
                audio.write_bytes(b"\x00")
                pieces, _hidden, handled, _splits, review = repair_pieces([piece], phrases, set(), audio)
        finally:
            repair.detect_silences = original
        self.assertEqual([(item["content_start"], item["content_end"]) for item in pieces], [(0.0, 1.0), (3.2, 4.0)])
        self.assertFalse(any(item["content_start"] < 3.2 and item["content_end"] > 1.0 for item in pieces))
        self.assertEqual(handled[0]["action"], "drop_word")
        self.assertTrue(review[0]["dropped_word"])
        self.assertEqual(drop_word(piece, 0.0, 4.0), [])


if __name__ == "__main__":
    unittest.main()
