#!/usr/bin/env python3
"""Transcribe a video with a local faster-whisper model.

No API keys and no network calls. ffmpeg writes mono 16 kHz audio into the
job directory, then faster-whisper reads that file with local files only.

Usage:
    python3 transcribe.py <video> <job_name> [--language auto]

Writes /state/jobs/<job_name>/transcript.json (and audio.wav beside it).
Segments are split where a pause between words is longer than
WORD_PAUSE_SPLIT seconds, then id and pause_before are recomputed.
Override the jobs root with ROUGH_CUT_JOBS. Override the model with
WHISPER_MODEL (default medium) and the download root with WHISPER_MODEL_DIR
(default /state/models/whisper). An absolute WHISPER_MODEL path is loaded
as a local model directory.
"""

import argparse
import json
import os
import subprocess
import wave
from pathlib import Path

DEFAULT_JOBS_ROOT = Path("/state/jobs")
DEFAULT_MODEL = "medium"
DEFAULT_MODEL_DIR = Path("/state/models/whisper")
WORD_PAUSE_SPLIT = 0.4


def jobs_root():
    raw = os.environ.get("ROUGH_CUT_JOBS", "").strip()
    return Path(raw) if raw else DEFAULT_JOBS_ROOT


def job_dir(name):
    if not name or name in (".", "..") or name != Path(name).name or "/" in name or "\\" in name:
        raise SystemExit("job name must be a single folder name")
    folder = jobs_root() / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def model_spec():
    name = os.environ.get("WHISPER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    raw_dir = os.environ.get("WHISPER_MODEL_DIR", "").strip()
    folder = Path(raw_dir) if raw_dir else DEFAULT_MODEL_DIR
    path = Path(name)
    if path.is_absolute():
        return str(path), folder, path.name
    return name, folder, name


def load_model():
    model_name, model_dir, label = model_spec()
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise SystemExit(
            "faster-whisper is not installed. "
            "Create the venv from docker/.env.example and run this script with it."
        ) from error
    try:
        model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",
            download_root=str(model_dir),
            local_files_only=True,
        )
    except Exception as error:
        raise SystemExit(
            f"Could not load Whisper model {model_name!r} from {model_dir} "
            f"(local files only). Download it once into that directory. {error}"
        ) from error
    return model, label, model_dir


def extract_audio(video, wav_path):
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip() or "ffmpeg failed"
        raise SystemExit(message)
    with wave.open(str(wav_path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getframerate() != 16000:
            raise SystemExit(f"expected mono 16kHz audio, got {wav_path}")
        return handle.getnframes() / float(handle.getframerate())


def rounded(value):
    return round(float(value), 3)


def transcribe(model, wav_path, language):
    kwargs = {
        "word_timestamps": True,
        "vad_filter": True,
        "condition_on_previous_text": False,
    }
    if language != "auto":
        kwargs["language"] = language
    segments, info = model.transcribe(str(wav_path), **kwargs)
    raw = []
    for segment in segments:
        words = []
        for word in segment.words or []:
            text = (word.word or "").strip()
            if not text:
                continue
            words.append(
                {
                    "word": text,
                    "start": float(word.start),
                    "end": float(word.end),
                }
            )
        raw.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": (segment.text or "").strip(),
                "words": words,
            }
        )
    return split_on_word_pauses(raw), info


def split_on_word_pauses(phrases, pause_limit=WORD_PAUSE_SPLIT):
    """Split wherever two consecutive words are more than pause_limit seconds apart."""
    pieces = []
    for phrase in phrases:
        words = phrase.get("words") or []
        if len(words) < 2:
            pieces.append(phrase)
            continue
        groups = [[words[0]]]
        for word in words[1:]:
            gap = float(word["start"]) - float(groups[-1][-1]["end"])
            if gap > pause_limit:
                groups.append([word])
            else:
                groups[-1].append(word)
        if len(groups) == 1:
            pieces.append(phrase)
            continue
        for group in groups:
            pieces.append(
                {
                    "start": float(group[0]["start"]),
                    "end": float(group[-1]["end"]),
                    "text": " ".join(word["word"].strip() for word in group if word["word"].strip()),
                    "words": group,
                }
            )
    return assign_phrase_ids(pieces)


def assign_phrase_ids(phrases):
    assigned = []
    previous_end = None
    for index, phrase in enumerate(phrases):
        start = float(phrase["start"])
        end = float(phrase["end"])
        pause = 0.0 if previous_end is None else max(0.0, start - previous_end)
        words = []
        for word in phrase.get("words") or []:
            words.append(
                {
                    "word": word["word"],
                    "start": rounded(word["start"]),
                    "end": rounded(word["end"]),
                }
            )
        assigned.append(
            {
                "id": index,
                "start": rounded(start),
                "end": rounded(end),
                "text": (phrase.get("text") or "").strip(),
                "words": words,
                "pause_before": rounded(pause),
            }
        )
        previous_end = end
    return assigned


def write_transcript(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Transcribe a video into a rough-cut job.")
    parser.add_argument("video", type=Path)
    parser.add_argument("job_name")
    parser.add_argument(
        "--language",
        default="auto",
        help="Whisper language code, or auto (default) to detect it",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    video = args.video.expanduser()
    if not video.is_file():
        raise SystemExit(f"video not found: {video}")
    language = args.language.strip().lower() or "auto"
    folder = job_dir(args.job_name)
    model, label, model_dir = load_model()
    wav_path = folder / "audio.wav"
    duration = extract_audio(video, wav_path)
    phrases, info = transcribe(model, wav_path, language)
    payload = {
        "source": str(video),
        "audio": str(wav_path),
        "language": info.language or language,
        "duration": rounded(info.duration or duration),
        "model": label,
        "model_dir": str(model_dir),
        "segments": phrases,
    }
    out_path = folder / "transcript.json"
    write_transcript(out_path, payload)
    print(out_path)


if __name__ == "__main__":
    main()
