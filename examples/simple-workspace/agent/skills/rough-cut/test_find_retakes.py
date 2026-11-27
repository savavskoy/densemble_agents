#!/usr/bin/env python3
"""Regression for retake recall on the IMG_1052 transcript.

Looks for the transcript and golden candidates next to this file, under
fixtures/, then under /state/jobs/<job> (container), then legacy host paths.
Set ROUGH_CUT_TEST_JOB (default 1120) and ROUGH_CUT_JOBS (default /state/jobs).
"""

import importlib.util
import json
import os
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TEST_JOB = os.environ.get("ROUGH_CUT_TEST_JOB", "1120").strip() or "1120"
STATE_JOBS = Path(os.environ.get("ROUGH_CUT_JOBS", "/state/jobs").strip() or "/state/jobs")
PERSONAL = Path("/Users/deepsket/densemble-home/workspaces/personal")
LEGACY_JOB = Path("/Users/deepsket/densemble-home/instance/state/jobs") / DEFAULT_TEST_JOB

CHAIN = set(range(131, 138))
KEPT_APART = (118, 124)


def load_module():
    path = HERE / "find_retakes.py"
    spec = importlib.util.spec_from_file_location("find_retakes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def first_existing(names, roots):
    for root in roots:
        for name in names:
            path = root / name
            if path.is_file():
                return path
    tried = [str(root / name) for root in roots for name in names]
    raise FileNotFoundError("missing fixture, tried:\n" + "\n".join(tried))


def fixture_roots():
    roots = [HERE, HERE / "fixtures", STATE_JOBS / DEFAULT_TEST_JOB]
    if PERSONAL.is_dir():
        roots.append(PERSONAL)
    if LEGACY_JOB.is_dir():
        roots.append(LEGACY_JOB)
    return tuple(roots)


class Img1052RecallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()
        transcript = first_existing(
            ("IMG_1052_transcript.json", "IMG_1052.transcript.json", "transcript.json"),
            fixture_roots(),
        )
        candidates = first_existing(
            ("IMG_1052_candidates.json", "IMG_1052.candidates.json", "candidates.json"),
            fixture_roots(),
        )
        cls.transcript_path = transcript
        cls.golden = json.loads(candidates.read_text(encoding="utf-8"))
        phrases = cls.mod.load_phrases(transcript)
        cls.signals = cls.mod.collect_signals(phrases)
        cls.clusters = cls.mod.cluster_signals(phrases, cls.signals)
        cls.sets = [set(cluster["segment_ids"]) for cluster in cls.clusters]

    def test_opener_chain_is_one_cluster(self):
        self.assertIn(CHAIN, self.sets)

    def test_three_word_near_duplicate(self):
        self.assertIn({59, 60}, self.sets)
        link = next(item for item in self.signals if {item["earlier_id"], item["later_id"]} == {59, 60})
        self.assertEqual(link["type"], "similar")
        self.assertGreaterEqual(link["score"], 0.85)

    def test_wide_opener_is_not_linked(self):
        earlier, later = KEPT_APART
        self.assertFalse(any(earlier in ids and later in ids for ids in self.sets))
        self.assertFalse(
            any(item["earlier_id"] == earlier and item["later_id"] == later for item in self.signals)
        )

    def test_previous_clusters_remain(self):
        for cluster in self.golden["clusters"]:
            ids = set(cluster["segment_ids"])
            self.assertTrue(any(ids <= found for found in self.sets), ids)
            if ids.isdisjoint(CHAIN):
                self.assertIn(ids, self.sets)

    def test_each_link_names_its_rule(self):
        known = {"similar", "prefix_restart", "opener_restart", "short_pause"}
        self.assertTrue(self.signals)
        for item in self.signals:
            self.assertIn(item["type"], known)
        chain = next(cluster for cluster in self.clusters if set(cluster["segment_ids"]) == CHAIN)
        self.assertTrue(any(item["type"] == "opener_restart" for item in chain["signals"]))
        self.assertTrue(
            any(
                item["type"] == "opener_restart" and item["earlier_id"] == 131 and item["later_id"] == 132
                for item in chain["signals"]
            )
        )


if __name__ == "__main__":
    unittest.main()
