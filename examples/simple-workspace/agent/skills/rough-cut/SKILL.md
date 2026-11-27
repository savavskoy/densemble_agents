---
name: rough-cut
description: Rough A-roll in CapCut from a talking-head video. Use when the owner asks to mount, rough-cut, or trim a video into a CapCut project, remove retakes, or build decisions.json for the edit.
---

# Rough cut

Black-and-white A-roll: transcribe, find retake clusters, drop bad takes, build an
EDL, write the CapCut timeline. Run every command from this skill folder
(`agent/skills/rough-cut/` in the active workspace).

**Trigger.** Owner says something like: «Смонтируй `<video path>` в проект
`<CapCut project name>`» (or the same in another language). Read this file and
follow the steps below.

**Inputs.**

- Video path: absolute path to the source file (host paths under `SOURCE_DIR_*`
  are visible inside the container at the same absolute path).
- CapCut project name: folder name under `/workspaces/capcut_projects/`.
- **Job name:** stem of the video file (no directory, no extension), e.g.
  `IMG_1052` from `…/IMG_1052.MOV`. Job files live in `/state/jobs/<job_name>/`.

Run Python with the rough-cut venv in the container when present:
`/state/venvs/rough-cut/bin/python`. `find_retakes.py`, `build_edl.py`,
`eval_recall.py`, and tests need only the standard library. `transcribe.py`
needs faster-whisper in that venv.

After **each** step, run the step’s check. On failure, stop and tell the owner
what failed; do not continue.

## Step 0 — Environment

From this skill directory:

```bash
test "$(grep -c opener_restart find_retakes.py)" -gt 0
python3 -m unittest test_find_retakes
```

Both must succeed. Tests read the IMG_1052 fixture from `fixtures/` or from
`/state/jobs/1120/` (`transcript.json` and `candidates.json` on the state mount).
If `opener_restart` is missing, fixtures are absent, or tests fail, stop and say
so.

## Step 1 — Transcript

Before transcribing in Docker, confirm the video path exists **inside the
container** (same absolute path as on the host). If `test -f "<video_path>"`
fails, stop and tell the owner to set `SOURCE_DIR_*` in `docker/.env` (parent
folder of the video), then recreate the container.

```bash
python3 transcribe.py <video_path> <job_name> [--language auto]
```

Creates `/state/jobs/<job_name>/transcript.json` (and `audio.wav`).

**Check:** If `transcript.json` already exists for this job, do not re-run
transcribe. Otherwise confirm the file exists and `segments` is a non-empty list.

## Step 1b — Sentences

```bash
python3 segment_sentences.py <job_name>
```

Splits each transcript segment at a word that ends with `.` `?` `!` or `…`, and
at a pause of 0.7 s or more. A sentence mark that is followed by the next word
within 0.25 s also splits (`HOLD_TIGHT_PUNCTUATION` in `edl_policy.py` is off:
a restart often starts right after a mark, and one coarse unit hides it).
Word times stay on the sentence. `find_retakes.py` and `decisions.json` use
these sentence ids. The untouched whisper transcript is `transcript.whisper.json`.

## Step 2 — Candidates

```bash
python3 find_retakes.py <job_name>
```

Writes `/state/jobs/<job_name>/candidates.json`.

**Check:** File exists; each cluster has `members` with `id` and `text`.

## Step 3 — Take blocks

```bash
python3 take_spans.py <job_name>
```

Writes `/state/jobs/<job_name>/retake_groups.json`. Only the duplicate phrases
are cut. Strong signals cut by themselves:

- `opener_restart`: the first 4 normalized words match, inside the opener
  window. A pause is not required.
- `marker`: a restart marker («точніше», «не так», «ще раз») between two lines
  with the same opening. The pair must be as near as an `opener_restart` pair
  (6 sentences, 40 s). A marker relaxes the match to 3 words, not the distance;
  a late line with the same opening, far from the marker, cuts nothing.
- `fragment_restart`: a cut-off phrase (an ellipsis, three words or fewer, or a
  last word stretched over 1.5 s) followed by a phrase with the same first 2
  words. A missing `.?!` alone is not a cut-off.

A weak signal, `similar` (a close paraphrase of an earlier phrase), cuts only
when every guard holds. It never joins a strong group; the restart is within 2
sentences and 5 s; the cut piece is at most 10 s; a paraphrase (similarity
under 0.85) needs a pause of 3 s or more before the restart. A pair a guard
stopped stays in the timeline and goes to the report with the reason.

A cut take also drops the sentences that follow it without a real pause
(under 0.5 s), up to the next take, but only an unfinished sentence or one said
again in the next 6 sentences of the later take. A finished sentence that is
not repeated stays. Marker groups are not extended.

`prefix_restart`, `short_pause` and trailing phrases are not cut. They are
listed in the report. Do not write `group_decisions.json`. The file is not read.

`decisions.json` is not where retakes are chosen. It must still exist; use
`{"drop_ids": []}`. Validate it against [`decisions.schema.json`](decisions.schema.json).

`drop_take.py` and `restore_take.py` are for the owner, not for the model.
Run one only when the owner names a range. Each command rebuilds the edit,
runs `qa.py`, and prints the kept text of the first 60 seconds:

```bash
python3 drop_take.py <job_name> <start_s> <end_s>
python3 restore_take.py <job_name> <start_s> <end_s>
```

**Check:** `retake_groups.json` exists and each group has `blocks` and `kept_id`.

## Step 4 — EDL

Do not write timecodes by hand.

```bash
python3 build_edl.py <job_name>
```

Builds `/state/jobs/<job_name>/edl.json`: kept phrases, gap joins under 0.24 s,
then a real pause from the original (see `edl_policy.py`). ffmpeg
`silencedetect` runs on long words (>1.5 s) only. One silence inside a word is
cut, leaving 0.3 s. Two or more speech islands delete that word entirely and
the word is listed in the report. A word shorter than 1.5 s is not opened.

**Check:** each segment has `start`, `end`, and `phrase_ids`.

Optional finer cut points (audio snap, does not write CapCut):

```bash
python3 snap_cuts.py <job_name>
```

Writes `/state/jobs/<job_name>/cuts.json` for review. Step 5 still uses
`edl.json` from step 4.

**Check:** `edl.json` exists; `keep_segments` is non-empty.

## Step 4b — QA

```bash
python3 qa.py <job_name>
```

Exits 0 unless the result is broken (no audio, or `draft_info` cannot be
written). Other `error` lines, including an unresolved `repeat_opener`, stay
in the report and in `needs_review.json` and do not stop the build.
`qa.py --strict` stops on any error. A long word that was removed or split
is not an error. Do not drop `needs_review.json` items yourself. Do not decide
which duplicate to keep: the cut is already fixed.

## Confidence

Strong signals (`opener_restart`, `marker`, `fragment_restart`) and a guarded
`similar` are cut, and only the duplicate phrases and their unfinished or
repeated tail. A finished sentence between two duplicates stays. Other signals
and every pair a guard stopped stay in the timeline and in `needs_review.json`. The model does not choose. The owner puts
a range back with `restore_take` or removes one with `drop_take`.

## Step 5 — CapCut timeline

CapCut project directory:

`/workspaces/capcut_projects/<capcut_project_name>`

The project must already contain the full source on one video track.

Ensure `draft_info.json.bak` exists in that folder: if it is missing, copy once
from `draft_info.json`. Never overwrite an existing `.bak`.

Run [`build_timeline.py`](build_timeline.py) from this skill folder (same script
as the trusted workspace copy):

```bash
python3 build_timeline.py /workspaces/capcut_projects/<capcut_project_name> /state/jobs/<job_name>/edl.json
```

It reads `content_start` / `content_end`, packs clips into `draft_info.json`, and updates
`draft_meta_info.json` when present. The `.bak` file is not modified.

**Check:** printed JSON shows sensible `duration_s` and `clips`; CapCut project
opens with the new cuts.

## Step 6 — Report

After `build_timeline.py`, send one message in this shape:

```text
Итог 676.0 с из 862.0 с исходника.
Вырезано дублей: 4, пауз сжато: 6.
edl_policy.py sha1: <hex>

Вырезано:
1. 12.0–14.2 — «сьогодні ми говоримо про паузи»

Проверь вручную:
1. 18.0–20.0 — «Зараз просто…» — Фраза обрывается
```

Use the durations from the timeline report (`duration_s` and `source_s`).
The duplicate count is `cut_takes`, the pause count is `auto_pauses`.
`Вырезано` lists every cut duplicate in time order: timecode and quote.
`Проверь вручную` is `needs_review.json` items sorted by risk (highest first),
then by timecode, at most 15; the rest is one line «… ещё N в needs_review.json».
Hidden speech and blocked `similar` pairs come first, trailing fragments last.
Rows with the same kind, time and quote are listed once. `sha1` is `edl_policy.py`.

## Стиль монтажа (по эталону)

Числа сняты с готового talking-head монтажа, не с конкретного файла.

- Между соседними оставленными клипами остаётся тишина: медиана **0.07 с**, 90-й процентиль **0.24 с**.
- До первого слова клипа берётся **0.05 с** (медиана). После последнего слова медиана **0.00 с**, 90-й процентиль **0.09 с**.
- Пауз длиннее 1 с в готовом монтаже: **0**.
- Самый короткий клип: **0.33 с**.

Правила (их применяет `build_edl.py`, таймкоды руками не пиши):

- Пауза никогда не заходит в следующее слово транскрипта, даже если оно вырезано: следующий оставленный клип может быть в десятках секунд, а вырезанное слово стоит вплотную.
- Пауза между клипами берётся из оригинала и ограничивается: 0.30 с после `.?!…`, 0.15 с внутри предложения, 0.25 с на стыке дубля. Пауза длиннее 1 с сжимается до 0.35 с.
- Короткий промежуток меньше 0.24 с остаётся внутри клипа как есть.
- Слово короче 1.5 с не режется изнутри. Граница реза сдвигается на тишину не дальше 0.1 с и только наружу от слова.
- Дубль вырезается по сильному сигналу (первые 4 слова, маркер рестарта, оборванная фраза и рестарт с теми же 2 словами) или по `similar` с охранными условиями. Остальное остаётся в ролике и попадает в «Проверь вручную».

## Measuring recall (optional)

```bash
python3 eval_recall.py --gold gold/<job>/cuts.json
```

Runs only the detection step (sentence split, retake groups, word mask) on the
stored transcript named in the gold file (`fixtures/<job>/transcript.json`).
Prints one table: case, covered seconds, HIT / PARTIAL / MISS, then
`target recall_s`, `regression`, `precision_s`, `collateral_s`, `unexplained_s`.
All numbers are word seconds. The gold file lists `cuts` (`target` or
`regression`, `expected_miss` optional) and `must_keep`, each with source
times and a `quote`. A target may carry `requires_meaning` (which of two takes
stays is a matter of sense, not wording); it still counts as a target, and the
table shows it apart. The detector never reads `must_keep`. `--save-cuts FILE`
stores the result, `--compare FILE` prints it next to the current run,
`--cuts FILE` scores a stored result. The v5 baseline is
`gold/IMG_1052/baseline_v5.json`.