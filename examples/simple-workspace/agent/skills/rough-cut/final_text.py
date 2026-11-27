#!/usr/bin/env python3
"""Write the kept sentences in edit order for a text review.

Usage:
    python3 final_text.py <job_name>

Each sentence has its id and start time. [✂] marks a clip boundary.
The file is also split into 3.5 minute windows with a 30 second overlap.
"""

import json
import os
import sys
from pathlib import Path

from edl_policy import text_in_span

DEFAULT_JOBS_ROOT = Path("/state/jobs")
WINDOW = 210.0
OVERLAP = 30.0


def jobs_root():
    raw = os.environ.get("ROUGH_CUT_JOBS", "").strip()
    return Path(raw) if raw else DEFAULT_JOBS_ROOT


def main():
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <job_name>")
    folder = jobs_root() / sys.argv[1]
    transcript = json.loads((folder / "transcript.json").read_text(encoding="utf-8"))
    edl = json.loads((folder / "edl.json").read_text(encoding="utf-8"))
    by_id = {int(phrase["id"]): phrase for phrase in transcript["segments"]}
    lines = ["# Final text", ""]
    flat = []
    for index, segment in enumerate(edl.get("keep_segments") or []):
        if index:
            lines.append("[✂]")
            flat.append(None)
        span_start = float(segment.get("content_start", segment["start"]))
        span_end = float(segment.get("content_end", segment["end"]))
        for phrase_id in segment.get("phrase_ids") or []:
            phrase = by_id[int(phrase_id)]
            text = text_in_span(phrase, span_start, span_end)
            if not text:
                continue
            line = f"[{phrase['id']}] {float(phrase['start']):.1f}s {text}"
            lines.append(line)
            flat.append((float(phrase["start"]), line))
    lines.append("")
    lines.append("# Windows")
    if flat:
        start = flat[0][0] if flat[0] else 0.0
        end_time = max(item[0] for item in flat if item)
        cursor = start
        while cursor <= end_time:
            stop = cursor + WINDOW
            lines.append("")
            lines.append(f"## {cursor:.0f}s–{stop:.0f}s")
            for item in flat:
                if item and cursor - OVERLAP <= item[0] < stop:
                    lines.append(item[1])
            cursor += WINDOW - OVERLAP
    path = folder / "final_text.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()