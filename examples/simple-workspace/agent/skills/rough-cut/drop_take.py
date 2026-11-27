#!/usr/bin/env python3
"""Cut a time range on word boundaries, then rebuild the edit.

Usage:
    python3 drop_take.py <job_name> <start_s> <end_s>

The range expands to whole words. After the cut, qa.py runs and the kept text
of the first 60 seconds is printed.
"""

import sys

from find_retakes import job_dir
from take_spans import append_op, rebuild_and_report


def main():
    if len(sys.argv) != 4:
        raise SystemExit(f"usage: {sys.argv[0]} <job_name> <start_s> <end_s>")
    job_name = sys.argv[1]
    folder = job_dir(job_name)
    start, end = append_op(folder, "drop", sys.argv[2], sys.argv[3])
    print(f"drop {start:.3f}–{end:.3f}", flush=True)
    rebuild_and_report(job_name, 60)


if __name__ == "__main__":
    main()
