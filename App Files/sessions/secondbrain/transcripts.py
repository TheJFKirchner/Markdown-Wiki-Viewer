"""Find Claude Code session transcripts and reduce them to what was said and done.

A transcript is a JSONL file at <transcripts_dir>/<project>/<session-id>.jsonl.
Condensing keeps the user's messages, the assistant's text, and each tool call as
a one-liner. Tool output and thinking are dropped: they are the bulk of the file
and the place query results (and so PHI) would appear.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

SENTINEL = "[second-brain:internal]"

_STRIP = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<local-command-(stdout|stderr|caveat)>.*?</local-command-\1>", re.S),
    re.compile(r"<command-message>.*?</command-message>", re.S),
]
_CMD = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def _long(path: Path) -> Path:
    """Windows refuses paths over ~260 characters unless they carry the extended-length prefix."""
    s = str(path)
    if sys.platform == "win32" and len(s) >= 240 and not s.startswith("\\\\?\\"):
        return Path("\\\\?\\" + os.path.abspath(s))
    return path


def _clean_user_text(text: str) -> str:
    m = _CMD.search(text)
    if m:
        a = _ARGS.search(text)
        return (m.group(1).strip() + " " + (a.group(1).strip() if a else "")).strip()
    for pattern in _STRIP:
        text = pattern.sub("", text)
    return text.strip()


def _user_text(event: dict) -> str:
    content = (event.get("message") or {}).get("content")
    if isinstance(content, str):
        return _clean_user_text(content)
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return _clean_user_text("\n".join(parts))
    return ""


def _one_line(value, limit: int) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


_DIGITS = re.compile(r"\d{6,}")
_QUOTED = re.compile(r"'[^'\n]*'|\"[^\"\n]*\"")
_SQL = re.compile(r"\b(select|insert|update|delete|where|values)\b", re.I)


def _mask(command: str, limit: int = 160) -> str:
    """A command as the model sees it: what was run, without the values in it. Long numbers
    (ids) are masked everywhere, and quoted values inside anything that looks like a query."""
    command = " ".join(str(command).split())
    if _SQL.search(command):
        command = _QUOTED.sub("'?'", command)
    command = _DIGITS.sub("#", command)
    return command if len(command) <= limit else command[: limit - 1] + "…"


def _tool_line(name: str, inp: dict) -> str:
    inp = inp if isinstance(inp, dict) else {}
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return f"{name} {inp.get('file_path') or inp.get('notebook_path') or ''}".strip()
    if name in ("Bash", "PowerShell"):
        return f"{name}: {_mask(inp.get('command', ''))}"
    if name in ("Grep", "Glob"):
        return f"{name} {_mask(inp.get('pattern', ''), 120)} {inp.get('path', '')}".strip()
    if name in ("Agent", "Task"):
        return f"{name}: {_one_line(inp.get('description', ''), 120)}"
    if name == "Skill":
        return f"Skill {inp.get('skill', '')}"
    if name == "WebSearch":
        return f"WebSearch {_mask(inp.get('query', ''))}"
    if name == "WebFetch":
        return f"WebFetch {inp.get('url', '')}"
    return f"{name} {_mask(json.dumps(inp, ensure_ascii=False), 120)}"


def _events(path: Path):
    """Yield the user and assistant events of the main conversation, in order."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            yield event


def _is_turn(event: dict) -> bool:
    return (
        event.get("type") in ("user", "assistant")
        and not event.get("isSidechain")
        and not event.get("isMeta")
        and not event.get("isCompactSummary")
        and isinstance(event.get("message"), dict)
    )


def _local_date(timestamp: str | None, fallback: float) -> str:
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone().date().isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback).date().isoformat()


def read_meta(path: Path) -> dict:
    """Summarise one transcript for the session list."""
    title = ""
    first_prompt = ""
    cwd = ""
    entrypoint = ""
    first_ts = last_ts = None
    user_messages = 0
    for event in _events(path):
        if event.get("type") == "custom-title" and event.get("customTitle"):
            title = event["customTitle"]
            continue
        if not _is_turn(event):
            continue
        ts = event.get("timestamp")
        first_ts = first_ts or ts
        last_ts = ts or last_ts
        cwd = cwd or event.get("cwd", "")
        entrypoint = entrypoint or event.get("entrypoint", "")
        if event["type"] == "user":
            text = _user_text(event)
            if text:
                user_messages += 1
                first_prompt = first_prompt or text
    mtime = path.stat().st_mtime
    return {
        "session_id": path.stem,
        "path": str(path),
        "project": cwd or path.parent.name,
        "entrypoint": entrypoint,
        "title": title or _one_line(first_prompt, 80),
        "first_prompt": _one_line(first_prompt, 200),
        "date": _local_date(first_ts, mtime),
        "last_active": _local_date(last_ts, mtime),
        "user_messages": user_messages,
        "mtime": mtime,
        "internal": first_prompt.startswith(SENTINEL),
    }


def recent_sessions(cfg, days: int | None = None) -> list[dict]:
    """Every real session touched in the lookback window, newest first."""
    days = cfg.lookback_days if days is None else days
    cutoff = time.time() - days * 86400
    root = cfg.transcripts
    if not root or not root.exists():
        return []
    out = []
    for path in root.glob("*/*.jsonl"):
        if any(pat and pat in path.parent.name for pat in cfg.exclude_project_patterns):
            continue
        path = _long(path)
        try:
            if path.stat().st_mtime < cutoff:
                continue
            meta = read_meta(path)
        except OSError:
            continue
        # Never listed: this tool's own calls, empty sessions, and sessions a script started
        # through the Agent SDK (WikiApp's own Notes and Promotion runs among them).
        if meta["internal"] or meta["user_messages"] == 0 or meta["entrypoint"].lower().startswith("sdk"):
            continue
        out.append(meta)
    out.sort(key=lambda m: m["mtime"], reverse=True)
    return out


def find_session(cfg, session_id: str) -> Path:
    """Locate a transcript by full session id, or by an unambiguous prefix."""
    root = cfg.transcripts
    matches = list(root.glob(f"*/{session_id}.jsonl")) or list(root.glob(f"*/{session_id}*.jsonl"))
    if not matches:
        raise FileNotFoundError(f"No transcript found for session {session_id} under {root}")
    if len({m.stem for m in matches}) > 1:
        raise FileNotFoundError(f"Session id {session_id} is ambiguous ({len(matches)} matches)")
    return max((_long(m) for m in matches), key=lambda m: m.stat().st_mtime)


def _segments(path: Path) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for event in _events(path):
        if not _is_turn(event):
            continue
        if event["type"] == "user":
            text = _user_text(event)
            if text:
                segments.append(("USER", text))
            continue
        content = event["message"].get("content")
        parts = []
        if isinstance(content, str):
            parts.append(content.strip())
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    parts.append(block["text"].strip())
                elif block.get("type") == "tool_use":
                    parts.append("  > " + _tool_line(block.get("name", "tool"), block.get("input")))
        text = "\n".join(p for p in parts if p)
        if not text:
            continue
        if segments and segments[-1][0] == "ASSISTANT":
            segments[-1] = ("ASSISTANT", segments[-1][1] + "\n" + text)
        else:
            segments.append(("ASSISTANT", text))
    return segments


def _render(segments: list[tuple[str, str]], cap: int | None) -> str:
    out = []
    for role, text in segments:
        if cap and len(text) > cap:
            text = text[:cap] + f"\n[... {len(text) - cap} characters cut ...]"
        out.append(f"## {role}\n{text}")
    return "\n\n".join(out)


def condense(path: Path, max_chars: int) -> str:
    """Render the transcript within max_chars, cutting long messages before dropping any."""
    segments = _segments(path)
    for cap in (None, 6000, 3000, 1500, 800):
        text = _render(segments, cap)
        if len(text) <= max_chars:
            return text
    # Still too long: keep the opening and the end, where the ask and the outcome are.
    head, tail = [], []
    head_budget, tail_budget = int(max_chars * 0.35), int(max_chars * 0.6)
    used = 0
    i = 0
    while i < len(segments) and used + min(len(segments[i][1]), 800) < head_budget:
        head.append(segments[i])
        used += min(len(segments[i][1]), 800) + 12
        i += 1
    used = 0
    j = len(segments) - 1
    while j >= i and used + min(len(segments[j][1]), 800) < tail_budget:
        tail.insert(0, segments[j])
        used += min(len(segments[j][1]), 800) + 12
        j -= 1
    omitted = j - i + 1
    middle = f"\n\n[... {omitted} messages omitted from the middle of this session ...]\n\n" if omitted > 0 else "\n\n"
    return _render(head, 800) + middle + _render(tail, 800)
