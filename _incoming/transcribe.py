#!/workspaces/.venv/bin/python3
"""Transcribe a video with a local offline Whisper model.

No API keys and no network calls. Audio is extracted with ffmpeg, then
recognized by faster-whisper from /workspaces/.venv.

The default model is medium (int8 on CPU). Override the cache folder name
or an absolute model directory with WHISPER_MODEL.
"""

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

AUDIO_PATH = "/tmp/audio.wav"
OUT_PATH = "/tmp/transcript.json"
VENV_PYTHON = Path("/workspaces/.venv/bin/python")
CACHE_ROOT = Path("/workspaces/.cache/whisper")
DEFAULT_MODEL = "medium"


def model_dir():
    raw = os.environ.get("WHISPER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    path = Path(raw)
    if path.is_absolute():
        return path
    return CACHE_ROOT / raw


def ensure_local_engine():
    if Path(sys.executable).resolve() != VENV_PYTHON.resolve() and VENV_PYTHON.exists():
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])
    folder = model_dir()
    try:
        import faster_whisper  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            "Local Whisper is not installed. "
            "Expected faster-whisper in /workspaces/.venv "
            f"and model files in {folder}."
        ) from error
    if not (folder / "model.bin").is_file():
        raise RuntimeError(
            "Local Whisper is not installed. "
            f"Model files were not found in {folder}."
        )
    return folder


def extract_audio(video_path):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            video_path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            AUDIO_PATH,
        ],
        check=True,
    )


def audio_duration(path):
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def transcribe(audio_path, folder):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(folder),
        device="cpu",
        compute_type="int8",
        local_files_only=True,
    )
    segments, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        vad_filter=False,
        beam_size=5,
    )
    phrase_list = []
    word_list = []
    texts = []
    for index, segment in enumerate(segments):
        text = (segment.text or "").strip()
        phrase_list.append(
            {
                "id": index,
                "start": segment.start,
                "end": segment.end,
                "text": text,
            }
        )
        if text:
            texts.append(text)
        for word in segment.words or []:
            word_list.append(
                {
                    "word": word.word,
                    "start": word.start,
                    "end": word.end,
                }
            )
    return {
        "text": " ".join(texts).strip(),
        "language": info.language,
        "duration": info.duration or audio_duration(audio_path),
        "task": "transcribe",
        "model": folder.name,
        "segments": phrase_list,
        "words": word_list,
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <video>")
    folder = ensure_local_engine()
    extract_audio(sys.argv[1])
    result = transcribe(AUDIO_PATH, folder)
    with open(OUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(OUT_PATH)


if __name__ == "__main__":
    main()
