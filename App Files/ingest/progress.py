"""Telling the app what's happening, and keeping a log of it in the run folder.

The app reads one JSON object per line from this program's output: progress, cards and the result.
Every line also goes to the run's log.jsonl, with a few extra entries the app doesn't need.
"""

import json
from pathlib import Path

log_file = None


def open_log(run_folder: Path) -> None:
    global log_file
    log_file = open(run_folder / "log.jsonl", "a", encoding="utf-8")


def close_log() -> None:
    if log_file:
        log_file.close()


def tell_app(event: dict) -> None:
    """One progress line for the app, also kept in the log."""
    print(json.dumps(event, ensure_ascii=False), flush=True)
    log(event)


def log(entry: dict) -> None:
    if log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log_file.flush()
