#!/usr/bin/env python3
"""Block retakes: the tail between two openings is part of the earlier take."""

import unittest

from take_spans import (
    build_retake_groups,
    is_restart_marker,
    plan_cuts,
    suspicious_items,
    word_mask,
    write_groups,
)


def phrase(pid, start, end, text):
    words = []
    tokens = text.split()
    if not tokens:
        tokens = [text]
    step = (end - start) / len(tokens)
    for index, token in enumerate(tokens):
        words.append({"word": token, "start": start + index * step, "end": start + (index + 1) * step})
    return {"id": pid, "start": start, "end": end, "text": text, "words": words}


def _ids(group):
    return {sentence_id for block in group["blocks"] for sentence_id in block["sentence_ids"]}


def _cut_ids(groups):
    """Sentence ids a list of groups would cut: every block but the kept (last) one."""
    return sorted({sid for group in groups for block in group["blocks"][:-1] for sid in block["sentence_ids"]})


class TakeSpanTest(unittest.TestCase):
    def test_marker_is_not_a_plain_negation(self):
        self.assertTrue(is_restart_marker("що точніше не так"))
        self.assertTrue(is_restart_marker("давай ще раз"))
        self.assertFalse(is_restart_marker("це точно не треба"))
        self.assertFalse(is_restart_marker("айтішка зараз не така"))

    def test_marker_cuts_only_when_the_restart_is_near(self):
        near = [
            phrase(1, 0.0, 3.0, "Я думаю що ні, це не так."),
            phrase(2, 3.1, 4.0, "що, точніше, не так."),
            phrase(3, 5.0, 8.0, "Я думаю що так, і це правда."),
        ]
        groups = build_retake_groups(near)
        self.assertEqual([group["signals"] for group in groups], [["marker"]])
        self.assertEqual(groups[0]["kept_id"], 3)
        self.assertEqual(_cut_ids(groups), [1])

    def test_marker_does_not_reach_a_far_late_line_with_the_same_opening(self):
        # The same lines, but the repeated opening comes 7 sentences and 46 s
        # after the first one. The marker is not next to it, so nothing is cut.
        far = [
            phrase(1, 0.0, 6.0, "Перший страх, який турбує дуже сильно новачків."),
            phrase(2, 6.2, 12.0, "Тобто новачок ще не почав вчити програмування зовсім."),
            phrase(3, 12.2, 14.0, "Я вважаю, що ні, я вважаю,"),
            phrase(4, 15.0, 16.0, "що, точніше, не так."),
            phrase(5, 17.0, 21.0, "Я скажу вам, що це взагалі не потрібно знати."),
            phrase(6, 21.2, 30.0, "Це буде плюсом, звісно, якщо ви вмієте рахувати."),
            phrase(7, 30.2, 40.0, "Але можна навіть без цього обійтися на початку."),
            phrase(8, 46.0, 50.0, "Перший страх, це знати складну математику."),
        ]
        self.assertEqual(build_retake_groups(far), [])

    def test_same_opening_keeps_only_the_last_take(self):
        phrases = [
            phrase(1, 0.0, 2.0, "в мене є різні власні проєкти для старту"),
            phrase(2, 3.0, 5.0, "в мене є різні комерційні проєкти учнів"),
            phrase(3, 6.0, 9.0, "В мене є різні проєкти на яких працюють мої учні"),
        ]
        groups = build_retake_groups(phrases)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["kept_id"], 3)
        cut = [sentence_id for block in groups[0]["blocks"][:-1] for sentence_id in block["sentence_ids"]]
        self.assertEqual(cut, [1, 2])
        mask = word_mask(phrases, groups[0]["blocks"][:-1], [])
        self.assertEqual(mask[1], set(range(len(phrases[0]["words"]))))
        self.assertEqual(mask[3], set())

    def test_fragment_restart_cuts_a_phrase_that_was_cut_off(self):
        stretched = phrase(1, 0.0, 4.0, "Зараз ми довго розбираємо цю тему і так")
        stretched["words"][-1]["start"] = 4.0 - 1.8
        later = phrase(2, 4.0, 8.0, "Зараз ми швидко розберемо цю тему повністю.")
        groups = build_retake_groups([stretched, later])
        self.assertEqual(_cut_ids(groups), [1])
        self.assertEqual(groups[0]["kept_id"], 2)
        self.assertIn("fragment_restart", groups[0]["signals"])
        ellipsis = phrase(3, 10.0, 12.0, "Потім треба отримувати...")
        follow = phrase(4, 12.2, 16.0, "Потім треба вміти значно більше за інших.")
        self.assertEqual(_cut_ids(build_retake_groups([ellipsis, follow])), [3])

    def test_fragment_restart_needs_a_real_cut_off(self):
        clause = phrase(1, 0.0, 4.0, "Зараз ми довго розбираємо цю тему,")
        later = phrase(2, 4.2, 8.0, "Зараз ми швидко розберемо цю тему повністю.")
        self.assertEqual(build_retake_groups([clause, later]), [])

    def test_near_duplicate_next_to_the_restart_is_cut(self):
        phrases = [
            phrase(1, 0.0, 3.0, "Отже ми рухаємося далі до наступної теми."),
            phrase(2, 3.2, 6.0, "А ми рухаємося далі до наступної теми."),
        ]
        groups = build_retake_groups(phrases)
        self.assertEqual(_cut_ids(groups), [1])
        self.assertEqual(groups[0]["signals"], ["similar"])

    def test_paraphrase_needs_a_long_pause_before_the_restart(self):
        earlier = "Це найважливіше правило для кожного нового учня на курсі."
        later = "Найважливіше правило для кожного учня, який щойно прийшов на курс."
        quick = [phrase(1, 0.0, 4.0, earlier), phrase(2, 4.2, 8.0, later)]
        self.assertEqual(build_retake_groups(quick), [])
        why = [item["reason"] for item in suspicious_items(quick, set()) if item["kind"] == "similar"]
        self.assertTrue(why and "перефраз" in why[0], why)
        slow = [phrase(1, 0.0, 4.0, earlier), phrase(2, 7.5, 11.0, later)]
        self.assertEqual(_cut_ids(build_retake_groups(slow)), [1])

    def test_similar_pair_far_apart_or_with_a_long_piece_is_not_cut(self):
        text = "Отже ми рухаємося далі до наступної теми."
        again = "А ми рухаємося далі до наступної теми."
        far = [
            phrase(1, 0.0, 3.0, text),
            phrase(2, 3.2, 6.0, "Між ними говорять про зовсім інші речі."),
            phrase(3, 6.2, 9.0, "І ще одна окрема думка стоїть тут посередині."),
            phrase(4, 9.2, 12.0, "Потім іде наступна окрема думка без повторів."),
            phrase(5, 12.2, 15.0, again),
        ]
        self.assertEqual(build_retake_groups(far), [])
        long_piece = [phrase(1, 0.0, 12.0, text), phrase(2, 12.2, 15.0, again)]
        self.assertEqual(build_retake_groups(long_piece), [])
        why = [item["reason"] for item in suspicious_items(long_piece, set()) if item["kind"] == "similar"]
        self.assertTrue(why, "a blocked pair must reach the report")

    def test_similar_never_joins_a_strong_group(self):
        phrases = [
            phrase(1, 0.0, 3.0, "Отже ми рухаємося далі до наступної теми."),
            phrase(2, 3.2, 6.0, "Отже ми рухаємося далі до наступної теми, швидко."),
            phrase(3, 6.2, 9.0, "А ми рухаємося далі до наступної теми."),
        ]
        groups = build_retake_groups(phrases)
        self.assertEqual([group["signals"] for group in groups], [["opener_restart"]])
        self.assertEqual(_cut_ids(groups), [1])

    def test_cut_take_drops_an_unfinished_tail(self):
        phrases = [
            phrase(1, 0.0, 3.0, "Сьогодні ми говоримо про паузи коротко."),
            phrase(2, 3.1, 4.5, "Це взагалі дуже..."),
            phrase(3, 6.0, 9.0, "Сьогодні ми говоримо про паузи докладно."),
        ]
        groups = build_retake_groups(phrases)
        self.assertEqual(_cut_ids(groups), [1, 2])

    def test_cut_take_drops_a_tail_that_is_said_again(self):
        phrases = [
            phrase(1, 0.0, 3.0, "Сьогодні ми говоримо про паузи коротко."),
            phrase(2, 3.1, 7.0, "Потім ми пройдемо усі приклади дуже уважно."),
            phrase(3, 8.0, 11.0, "Сьогодні ми говоримо про паузи докладно."),
            phrase(4, 11.1, 15.0, "Потім ми пройдемо усі приклади дуже повільно."),
        ]
        self.assertEqual(_cut_ids(build_retake_groups(phrases)), [1, 2])

    def test_cut_take_keeps_a_finished_unique_tail_and_a_tail_after_a_pause(self):
        pause = [
            phrase(1, 0.0, 3.0, "Сьогодні ми говоримо про паузи коротко."),
            phrase(2, 4.0, 5.0, "Це взагалі дуже..."),
            phrase(3, 6.0, 9.0, "Сьогодні ми говоримо про паузи докладно."),
        ]
        self.assertEqual(_cut_ids(build_retake_groups(pause)), [1])

    def test_marker_group_does_not_grow_a_tail(self):
        phrases = [
            phrase(1, 0.0, 3.0, "Я думаю що ні."),
            phrase(2, 3.1, 4.0, "Що, точніше, не так..."),
            phrase(3, 4.1, 6.0, "Це зовсім інша думка..."),
            phrase(4, 7.0, 10.0, "Я думаю що так."),
        ]
        groups = build_retake_groups(phrases)
        self.assertEqual([group["signals"] for group in groups], [["marker"]])
        self.assertNotIn(3, _cut_ids(groups))

    def test_finished_sentence_118_to_124_is_not_grouped(self):
        phrases = [
            phrase(118, 518.82, 526.30, "Але ти все одно маєш брати себе в руки, розбиратися, нехай на це піде більше часу,"),
            phrase(119, 527.04, 534.40, "але ось тут має бути напевно такий характер, що дають незрозумілу задачу, а ти робиш від себе все, щоб розібратися."),
            phrase(120, 534.52, 537.22, "І я тобі кажу так, якщо ти реально робиш від себе все,"),
            phrase(121, 537.90, 540.08, "то розібратися виходить."),
            phrase(122, 540.14, 545.54, "Або за рахунок якихось так overflow, або за рахунок просто якогось рандому,"),
            phrase(123, 545.54, 548.64, "або тобі хтось допоможе, або це буде штучний інтелект,"),
            phrase(124, 548.86, 551.58, "але ти все одно маєш вирішувати свої задачі"),
        ]
        groups = build_retake_groups(phrases)
        group = next(item for item in groups if {118, 124} <= _ids(item))
        cut = [sentence_id for block in group["blocks"][:-1] for sentence_id in block["sentence_ids"]]
        self.assertEqual(cut, [118])
        self.assertNotIn(119, cut)
        self.assertEqual(group["kept_id"], 124)

    def test_finished_period_next_to_same_opening_is_not_grouped(self):
        phrases = [
            phrase(1, 0.0, 4.0, "Але ти все одно маєш розібратися з цим спокійно."),
            phrase(2, 4.2, 8.0, "Але ти підеш далі і закриєш цю задачу повністю."),
        ]
        self.assertEqual(build_retake_groups(phrases), [])


if __name__ == "__main__":
    unittest.main()
