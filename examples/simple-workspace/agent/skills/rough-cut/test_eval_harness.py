#!/usr/bin/env python3
"""The offline harness itself: gold validation, scoring in seconds, stored baseline.

A missing fixture or gold file fails these tests. It is never skipped.
"""

import json
import tempfile
import unittest
from pathlib import Path

from eval_recall import detect, load_gold, load_json, score, transcript_words

HERE = Path(__file__).resolve().parent
GOLD = HERE / "gold" / "IMG_1052" / "cuts.json"
FIXTURE = HERE / "fixtures" / "IMG_1052" / "transcript.json"
BASELINE_V5 = HERE / "gold" / "IMG_1052" / "baseline_v5.json"


def toy_words():
    """Ten one-second words, 0..10 s, no pauses."""
    return [{"start": float(i), "end": float(i + 1), "text": f"слово{i}"} for i in range(10)]


def toy_gold(cuts, keep):
    return {"cuts": cuts, "must_keep": keep}


class FilesExistTest(unittest.TestCase):
    def test_fixture_gold_and_baseline_exist(self):
        for path in (FIXTURE, GOLD, BASELINE_V5):
            self.assertTrue(path.is_file(), f"missing: {path}")

    def test_gold_matches_the_fixture(self):
        words = transcript_words(load_json(FIXTURE))
        gold = load_gold(GOLD, words)
        self.assertTrue(any(row.get("expected_miss") for row in gold["cuts"]))
        self.assertTrue(gold["must_keep"])


class GoldValidationTest(unittest.TestCase):
    def _write(self, payload):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "gold.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_quote_that_does_not_start_the_interval_is_an_error(self):
        words = toy_words()
        path = self._write(
            toy_gold([{"id": "x", "kind": "target", "start": 2.0, "end": 4.0, "quote": "слово9"}], [])
        )
        with self.assertRaises(SystemExit) as caught:
            load_gold(path, words)
        self.assertIn("quote", str(caught.exception))

    def test_cut_and_must_keep_may_not_share_words(self):
        words = toy_words()
        path = self._write(
            toy_gold(
                [{"id": "x", "kind": "target", "start": 2.0, "end": 5.0, "quote": "слово2"}],
                [{"id": "k", "start": 4.0, "end": 6.0, "quote": "слово4"}],
            )
        )
        with self.assertRaises(SystemExit):
            load_gold(path, words)

    def test_kind_must_be_known(self):
        words = toy_words()
        path = self._write(
            toy_gold([{"id": "x", "kind": "maybe", "start": 2.0, "end": 4.0, "quote": "слово2"}], [])
        )
        with self.assertRaises(SystemExit):
            load_gold(path, words)


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.words = toy_words()
        self.gold = toy_gold(
            [
                {"id": "t1", "kind": "target", "start": 1.0, "end": 3.0, "quote": "слово1"},
                {"id": "t2", "kind": "target", "start": 5.0, "end": 6.0, "quote": "слово5"},
                {"id": "m", "kind": "target", "expected_miss": True, "start": 7.0, "end": 8.0, "quote": "слово7"},
                {"id": "r", "kind": "regression", "start": 8.0, "end": 9.0, "quote": "слово8"},
            ],
            [{"id": "k", "start": 3.0, "end": 4.0, "quote": "слово3"}],
        )

    def test_recall_precision_collateral_and_unexplained_are_seconds(self):
        # cuts: all of t1, half of nothing in t2, one must_keep word, one word nobody listed
        cuts = [{"start": 1.0, "end": 4.0}, {"start": 9.0, "end": 10.0}]
        result = score(self.words, self.gold, cuts)
        summary = result["summary"]
        self.assertAlmostEqual(summary["recall_s"]["covered"], 2.0)
        self.assertAlmostEqual(summary["recall_s"]["gold"], 3.0)
        self.assertAlmostEqual(summary["collateral_s"], 1.0)
        self.assertAlmostEqual(summary["unexplained_s"], 1.0)
        self.assertAlmostEqual(summary["precision_s"]["hit"], 2.0)
        self.assertAlmostEqual(summary["precision_s"]["cut"], 4.0)
        self.assertEqual(summary["expected_miss"]["covered"], 0.0)
        self.assertEqual(summary["regression"]["covered"], 0.0)
        by_id = {case["id"]: case for case in result["cases"]}
        self.assertEqual(by_id["t1"]["status"], "HIT")
        self.assertEqual(by_id["t2"]["status"], "MISS")
        self.assertEqual(result["unexplained"][0]["quote"], "слово9")

    def test_expected_miss_is_counted_apart(self):
        result = score(self.words, self.gold, [{"start": 7.0, "end": 8.0}])
        summary = result["summary"]
        self.assertEqual(summary["recall_s"]["covered"], 0.0)
        self.assertAlmostEqual(summary["expected_miss"]["covered"], 1.0)
        self.assertAlmostEqual(summary["precision_s"]["share"], 1.0)

    def test_no_cuts_is_zero_not_a_division_error(self):
        result = score(self.words, self.gold, [])
        self.assertEqual(result["summary"]["precision_s"]["share"], 0.0)
        self.assertEqual(result["summary"]["recall_s"]["share"], 0.0)


class StoredBaselineTest(unittest.TestCase):
    def test_v5_never_cut_a_target_and_kept_every_accepted_cut(self):
        words = transcript_words(load_json(FIXTURE))
        gold = load_gold(GOLD, words)
        stored = load_json(BASELINE_V5)
        summary = score(words, gold, stored["cuts"])["summary"]
        self.assertEqual(summary["recall_s"]["covered"], 0.0)
        self.assertEqual(summary["expected_miss"]["covered"], 0.0)
        self.assertAlmostEqual(summary["regression"]["share"], 1.0, places=3)
        self.assertEqual(summary["collateral_s"], 0.0)
        self.assertEqual(summary["unexplained_s"], 0.0)

    def test_current_detector_holds_the_gate_on_the_fixture(self):
        """A gate, not a target: the detector may not lose a plain target or touch kept speech.

        A target that needs meaning or is an expected miss is not required, but the
        detector may not cut anything outside gold (`unexplained_s`).
        """
        words = transcript_words(load_json(FIXTURE))
        gold = load_gold(GOLD, words)
        result = score(words, gold, detect(load_json(FIXTURE)))
        summary = result["summary"]
        self.assertAlmostEqual(summary["regression"]["share"], 1.0, places=3)
        self.assertEqual(summary["collateral_s"], 0.0)
        self.assertEqual(summary["unexplained_s"], 0.0)
        plain = [
            case
            for case in result["cases"]
            if case["kind"] == "target" and not case["expected_miss"] and not case["requires_meaning"]
        ]
        self.assertTrue(plain)
        for case in plain:
            self.assertEqual(case["status"], "HIT", case["id"])
        for case in result["cases"]:
            if case["requires_meaning"]:
                self.assertEqual(case["covered_s"], 0.0, f"{case['id']} needs meaning; the detector must not guess")

    def test_the_detector_is_deterministic_on_the_fixture(self):
        transcript = load_json(FIXTURE)
        self.assertEqual(detect(transcript), detect(transcript))


if __name__ == "__main__":
    unittest.main()
