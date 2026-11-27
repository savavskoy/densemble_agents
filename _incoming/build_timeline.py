#!/usr/bin/env python3
"""Build a clean A-roll timeline from an EDL.

Usage:
    python3 /workspaces/build_timeline.py <capcut_project_dir> [edl.json]

The project must contain draft_info.json.bak: one untouched source clip.
/tmp/edl.json is the default EDL. It is a list, or an object with
keep_segments, of {"start": float, "end": float, "label": "..."}.

Each keep range is padded by 0.18s before the start and 0.25s after the
end, clamped to the media. Ranges closer than 0.35s are joined. The
source is cut on those intervals and packed with no gaps. Scale stays
1.0. No titles, no overlay graphics. The backup file is not modified.
"""

import json
import sys
import uuid
from pathlib import Path

MARGIN_BEFORE = 0.18
MARGIN_AFTER = 0.25
MERGE_GAP = 0.35
US = 1_000_000
DEFAULT_EDL = Path("/tmp/edl.json")


def new_id():
    return str(uuid.uuid4()).upper()


def load_edl(path):
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = data.get("keep_segments") or []
    segments = []
    for item in data:
        start = float(item["start"])
        end = float(item["end"])
        if end <= start:
            continue
        segments.append(
            {
                "start": start,
                "end": end,
                "label": (item.get("label") or "").strip(),
            }
        )
    if not segments:
        raise SystemExit(f"EDL is empty: {path}")
    return segments


def prepare(segments, media_end):
    padded = []
    for item in sorted(segments, key=lambda entry: (entry["start"], entry["end"])):
        start = max(0.0, item["start"] - MARGIN_BEFORE)
        end = min(media_end, item["end"] + MARGIN_AFTER)
        if end - start < 0.05:
            continue
        padded.append({"start": start, "end": end, "label": item["label"]})
    merged = []
    for item in padded:
        if merged and item["start"] - merged[-1]["end"] < MERGE_GAP:
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            if item["label"] and item["label"] not in merged[-1]["label"]:
                previous = merged[-1]["label"]
                merged[-1]["label"] = f"{previous} + {item['label']}".strip(" +")
            continue
        merged.append(item)
    return merged


def load_base(project):
    backup = project / "draft_info.json.bak"
    if not backup.is_file():
        raise SystemExit(f"clean backup is missing: {backup}")
    draft = json.loads(backup.read_text())
    video_tracks = [track for track in draft.get("tracks") or [] if track.get("type") == "video"]
    if not video_tracks:
        raise SystemExit(f"no video track in {backup}")
    main = next((track for track in video_tracks if track.get("flag", 0) == 0), video_tracks[0])
    if not main.get("segments"):
        raise SystemExit(f"no source segment in {backup}")
    template = json.loads(json.dumps(main["segments"][0]))
    material_id = template.get("material_id")
    videos = [item for item in draft["materials"].get("videos") or [] if item.get("id") == material_id]
    if not videos:
        videos = draft["materials"]["videos"][:1]
        material_id = videos[0]["id"]
        template["material_id"] = material_id
    media = int(videos[0]["duration"])
    template["id"] = new_id()
    template["source_timerange"] = {"start": 0, "duration": media}
    template["target_timerange"] = {"start": 0, "duration": media}
    template["render_timerange"] = {"start": 0, "duration": 0}
    template["clip"]["scale"] = {"x": 1.0, "y": 1.0}
    template["clip"]["transform"] = {"x": 0.0, "y": 0.0}
    template["uniform_scale"] = {"on": True, "value": 1.0}
    template["volume"] = 1.0
    template["render_index"] = 0
    template["track_render_index"] = 0
    template["common_keyframes"] = []
    template["keyframe_refs"] = []
    main["id"] = main.get("id") or new_id()
    main["segments"] = [template]
    main["flag"] = 0
    main["type"] = "video"
    draft["tracks"] = [main]
    draft["materials"]["videos"] = videos[:1]
    draft["materials"]["texts"] = []
    draft["duration"] = media
    return draft, media


def assemble(draft, ranges):
    template = draft["tracks"][0]["segments"][0]
    extra_refs = list(template.get("extra_material_refs") or [])
    material_id = template["material_id"]
    media = draft["materials"]["videos"][0]["duration"]
    segments = []
    cursor = 0
    for item in ranges:
        start_us = max(0, int(round(item["start"] * US)))
        end_us = min(media, int(round(item["end"] * US)))
        duration = end_us - start_us
        if duration < 50_000:
            continue
        segment = json.loads(json.dumps(template))
        segment["id"] = new_id()
        segment["material_id"] = material_id
        segment["extra_material_refs"] = extra_refs
        segment["source_timerange"] = {"start": start_us, "duration": duration}
        segment["target_timerange"] = {"start": cursor, "duration": duration}
        segment["render_timerange"] = {"start": 0, "duration": 0}
        segment["clip"]["scale"] = {"x": 1.0, "y": 1.0}
        segment["clip"]["transform"] = {"x": 0.0, "y": 0.0}
        segment["uniform_scale"] = {"on": True, "value": 1.0}
        segment["volume"] = 1.0
        segment["render_index"] = 0
        segment["track_render_index"] = 0
        segment["common_keyframes"] = []
        segment["keyframe_refs"] = []
        segments.append(segment)
        cursor += duration
    if not segments:
        raise SystemExit("all EDL ranges collapsed to empty cuts")
    draft["tracks"][0]["segments"] = segments
    draft["duration"] = cursor
    return cursor


def save(project, draft, duration):
    payload = json.dumps(draft, ensure_ascii=False, separators=(",", ":"))
    (project / "draft_info.json").write_text(payload)
    for copy in project.glob("Timelines/*/draft_info.json"):
        copy.write_text(payload)
    meta_path = project / "draft_meta_info.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text())
        meta["tm_duration"] = duration
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")))


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit(f"usage: {sys.argv[0]} <capcut_project_dir> [edl.json]")
    project = Path(sys.argv[1])
    edl_path = Path(sys.argv[2]) if len(sys.argv) == 3 else DEFAULT_EDL
    requested = load_edl(edl_path)
    draft, media = load_base(project)
    media_end = media / US
    ranges = prepare(requested, media_end)
    duration = assemble(draft, ranges)
    save(project, draft, duration)
    print(
        json.dumps(
            {
                "project": str(project),
                "edl": str(edl_path),
                "source_s": round(media_end, 3),
                "keeps_in": len(requested),
                "clips": len(draft["tracks"][0]["segments"]),
                "duration_us": duration,
                "duration_s": round(duration / US, 3),
                "margins": [-MARGIN_BEFORE, MARGIN_AFTER],
                "merge_gap": MERGE_GAP,
                "ranges": [
                    {
                        "start": round(item["start"], 3),
                        "end": round(item["end"], 3),
                        "label": item["label"],
                    }
                    for item in ranges
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
