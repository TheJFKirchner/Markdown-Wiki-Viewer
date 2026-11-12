"""Find Claude Code session transcripts and reduce them to what was said and done.

A transcript is a JSONL file at <transcripts_dir>/<project>/<session-id>.jsonl.
Condensing keeps the user's messages, the assistant's text, and each tool call as
a one-liner. Tool output and thinking are dropped: they are the bulk of the file
and the place query results (and so PHI) would appear.

Subagents are part of the session that started them, never sessions of their own. How Claude
Code keeps them (checked against real transcripts; structure only):
  - the main assistant starts one with an Agent (formerly Task) tool call: input `description`,
    `prompt` (its instructions), `subagent_type`, and `run_in_background`;
  - a subagent that ran to the end in the foreground answers that call with a tool_result whose
    text is its report (the user line's `toolUseResult.status` is "completed");
  - one run in the background answers at once with `toolUseResult.status: "async_launched"`; its
    report arrives later as a user line that the person never typed: `origin.kind:
    "task-notification"`, text `<task-notification>` with `<tool-use-id>`, `<status>`,
    `<summary>` and `<result>` (the report). Background shell commands report the same way;
  - its own transcript is <project>/<session-id>/subagents/agent-<agentId>.jsonl (every line has
    `agentId`, mostly `isSidechain: true`), with agent-<agentId>.meta.json naming `toolUseId`,
    `description` and `agentType`. Older versions kept `agent-*.jsonl` beside the sessions, or
    sidechain lines inside the main file.
Everything a subagent wrote, and the instructions the assistant gave it, are the assistant's side:
the condensed transcript labels them so ("SUBAGENT ... reported:"), never as USER, and only the
person's own messages count as user turns. A subagent's final report is kept in preference to its
intermediate steps (a few one-line steps from its own transcript follow the report, and are the
first thing cut when the transcript is too long).
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
    if name == "SendMessage":
        return f"SendMessage to {_one_line(str(inp.get('to') or inp.get('recipient') or ''), 60)}".strip()
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
        and not event.get("agentId")
        and not event.get("isMeta")
        and not event.get("isCompactSummary")
        and isinstance(event.get("message"), dict)
    )


_NOTIFICATION = re.compile(r"^\s*<task-notification>", re.S)


def _origin_kind(event: dict) -> str:
    origin = event.get("origin")
    if isinstance(origin, dict):
        return str(origin.get("kind") or "")
    return origin if isinstance(origin, str) else ""


def _is_person(event: dict, text: str) -> bool:
    """A user line the person typed: not a tool result (no text), not a subagent's or background
    task's report (origin kind "task-notification", or the text is a <task-notification> block),
    and not a message from another session or agent (origin kind "peer")."""
    if not text:
        return False
    if _origin_kind(event) not in ("", "human"):
        return False
    return not _NOTIFICATION.match(text)


def _tag(name: str, text: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    return m.group(1).strip() if m else ""


def _raw_user_text(event: dict) -> str:
    """A user line's text blocks, untouched (for a <task-notification>)."""
    content = (event.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _local_date(timestamp: str | None, fallback: float) -> str:
    if timestamp:
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone().date().isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback).date().isoformat()


def read_meta(path: Path) -> dict:
    """Summarise one transcript for the session list. user_messages counts only the person's own
    messages (never a subagent's report or a sidechain); subagents counts the subagents the
    assistant started (Agent or Task calls), which are folded into this session."""
    custom_title = ai_title = ""
    first_prompt = ""
    cwd = ""
    entrypoint = ""
    first_ts = last_ts = None
    user_messages = 0
    subagents = 0
    for event in _events(path):
        # The session's name in Claude Code: one the person gave it (custom-title), else the one
        # Claude Code generated (ai-title). Each may be written again later; the last one counts.
        if event.get("type") == "custom-title" and event.get("customTitle"):
            custom_title = str(event["customTitle"])
            continue
        if event.get("type") == "ai-title" and event.get("aiTitle"):
            ai_title = str(event["aiTitle"])
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
            if _is_person(event, text):
                user_messages += 1
                first_prompt = first_prompt or text
        else:
            content = event["message"].get("content")
            if isinstance(content, list):
                subagents += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
                                 and b.get("name") in ("Agent", "Task"))
    mtime = path.stat().st_mtime
    title = custom_title or ai_title
    return {
        "session_id": path.stem,
        "path": str(path),
        "project": cwd or path.parent.name,
        "entrypoint": entrypoint,
        "named_title": title,   # Claude Code's name for the session, or "" (the readable name's words)
        "subagents": subagents,
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
    # <project>/<session>.jsonl only: a subagent's transcript (<session>/subagents/agent-*.jsonl,
    # or agent-*.jsonl beside the sessions in older versions) is part of its session, never listed.
    for path in root.glob("*/*.jsonl"):
        if path.stem.startswith("agent-"):
            continue
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
    if not root or not session_id or session_id.startswith("agent-") or any(c in session_id for c in "*?[]/\\"):
        raise FileNotFoundError(f"No transcript found for session {session_id} under {root}")
    matches = list(root.glob(f"*/{session_id}.jsonl")) or list(root.glob(f"*/{session_id}*.jsonl"))
    matches = [m for m in matches if not m.stem.startswith("agent-")]
    if not matches:
        raise FileNotFoundError(f"No transcript found for session {session_id} under {root}")
    if len({m.stem for m in matches}) > 1:
        raise FileNotFoundError(f"Session id {session_id} is ambiguous ({len(matches)} matches)")
    return max((_long(m) for m in matches), key=lambda m: m.stat().st_mtime)


SUBAGENT_ROLE = "ASSISTANT (subagent)"   # a subagent's report: the assistant's side, never the user's
REPORT_LIMIT = 6000                      # characters of one subagent report, before any other cut
MAX_STEPS = 8                            # one-line steps from a subagent's own transcript
_TAGS_IN_REPORT = re.compile(r"<(tools-used-before-summary|system-reminder|usage)>.*?</\1>", re.S)


def _clean_report(text: str) -> str:
    """A subagent's report as the model sees it: housekeeping tags out, long numbers (ids) masked."""
    text = _TAGS_IN_REPORT.sub("", text or "").strip()
    return _DIGITS.sub("#", text)


def _subagent_files(path: Path) -> dict[str, Path]:
    """The session's subagent transcripts, by the id of the Agent call that started each (from
    agent-<id>.meta.json) and by agent id ("agent:<id>")."""
    folder = _long(path.with_suffix("")) / "subagents"
    out: dict[str, Path] = {}
    if not folder.is_dir():
        return out
    for file in folder.glob("agent-*.jsonl"):
        out["agent:" + file.stem[len("agent-"):]] = file
        try:
            meta = json.loads(file.with_name(file.stem + ".meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and isinstance(meta.get("toolUseId"), str):
            out[meta["toolUseId"]] = file
    return out


def _subagent_own(file: Path | None) -> tuple[str, list[str]]:
    """(its last message, its steps as one-liners) from a subagent's own transcript."""
    if file is None:
        return "", []
    last, steps = "", []
    try:
        for event in _events(file):
            if event.get("type") != "assistant" or not isinstance(event.get("message"), dict):
                continue
            content = event["message"].get("content")
            if isinstance(content, str) and content.strip():
                last = content.strip()
            elif isinstance(content, list):
                text = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()
                last = text or last
                steps += [_tool_line(b.get("name", "tool"), b.get("input")) for b in content
                          if isinstance(b, dict) and b.get("type") == "tool_use"]
    except OSError:
        return "", []
    return last, steps


def _subagent_text(name: str, report: str, steps: list[str], note: str = "") -> str:
    text = f'SUBAGENT "{name}" reported{note} (the assistant\'s helper, not the user):\n'
    report = _clean_report(report) or "(no report)"
    if len(report) > REPORT_LIMIT:
        report = report[:REPORT_LIMIT] + f"\n[... {len(report) - REPORT_LIMIT} characters of the report cut ...]"
    text += report
    if steps:
        shown = "; ".join(steps[:MAX_STEPS]) + (f"; ... {len(steps) - MAX_STEPS} more" if len(steps) > MAX_STEPS else "")
        text += f"\n(its steps: {shown})"
    return text


def _segments(path: Path) -> list[tuple[str, str]]:
    """The conversation as (role, text): "USER" (only what the person typed), "ASSISTANT" (its
    text, one line per tool call, and its instructions to any subagent), SUBAGENT_ROLE (a
    subagent's report, where it reached the session)."""
    segments: list[tuple[str, str]] = []
    calls: dict[str, dict] = {}      # Agent/Task call id -> {"name", "agent_id", "done"}
    files = None

    def own_files():
        nonlocal files
        if files is None:
            files = _subagent_files(path)
        return files

    def add_assistant(text: str) -> None:
        if segments and segments[-1][0] == "ASSISTANT":
            segments[-1] = ("ASSISTANT", segments[-1][1] + "\n" + text)
        else:
            segments.append(("ASSISTANT", text))

    def add_report(call_id: str, report: str, note: str = "") -> None:
        call = calls[call_id]
        call["done"] = True
        file = own_files().get(call_id) or own_files().get("agent:" + call.get("agent_id", ""))
        last, steps = _subagent_own(file)
        segments.append((SUBAGENT_ROLE, _subagent_text(call["name"], report or last, steps, note)))

    for event in _events(path):
        if not _is_turn(event):
            continue
        if event["type"] == "user":
            content = event["message"].get("content")
            result = event.get("toolUseResult") if isinstance(event.get("toolUseResult"), dict) else {}
            if isinstance(content, list):
                for block in content:
                    if not (isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id") in calls):
                        continue
                    call = calls[block["tool_use_id"]]
                    call["agent_id"] = str(result.get("agentId") or "")
                    # Started in the background: this only says it started; the report comes later.
                    # (A message to a running subagent is answered the same way.)
                    if result.get("status") == "async_launched" or result.get("isAsync") or call.get("message"):
                        continue
                    add_report(block["tool_use_id"], _result_text(block.get("content")))
            raw = _raw_user_text(event)
            if _origin_kind(event) == "task-notification" or _NOTIFICATION.match(raw):
                call_id = _tag("tool-use-id", raw)
                if call_id in calls and not calls[call_id]["done"]:
                    status = _tag("status", raw)
                    add_report(call_id, _tag("result", raw), "" if status in ("", "completed") else f" ({status})")
                elif call_id not in calls:
                    # A background shell command (or a message to a running subagent) finished. Its
                    # output is tool output, so only its one-line summary is kept, masked.
                    add_assistant("  > background task finished: " + _mask(_tag("summary", raw) or "(no summary)", 160))
                continue
            text = _user_text(event)
            if _is_person(event, text):
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
                    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                    if block.get("name") in ("Agent", "Task"):
                        name = _one_line(inp.get("description") or inp.get("subagent_type") or "subagent", 80)
                        calls[str(block.get("id"))] = {"name": name, "agent_id": "", "done": False}
                        if inp.get("prompt"):
                            parts.append(f'    (the assistant\'s instructions to SUBAGENT "{name}": {_mask(inp["prompt"], 600)})')
                    elif block.get("name") == "SendMessage":
                        # The assistant continuing a subagent it started: the reply comes back as a
                        # <task-notification> for this call, and is that subagent's report.
                        name = _one_line(str(inp.get("to") or inp.get("recipient") or "subagent"), 60) + " (continued)"
                        calls[str(block.get("id"))] = {"name": name, "agent_id": "", "done": False, "message": True}
                        said = inp.get("message") or inp.get("content") or inp.get("summary")
                        if isinstance(said, str) and said.strip():
                            parts.append(f'    (the assistant\'s message to SUBAGENT "{name}": {_mask(said, 600)})')
        text = "\n".join(p for p in parts if p)
        if text:
            add_assistant(text)
    # A subagent whose report never reached the session (still running, stopped, or an older
    # transcript): its own last message, if its transcript is there.
    for call_id, call in calls.items():
        if not call["done"] and not call.get("message"):
            file = own_files().get(call_id) or own_files().get("agent:" + call["agent_id"])
            last, steps = _subagent_own(file)
            if last:
                segments.append((SUBAGENT_ROLE, _subagent_text(call["name"], last, steps,
                                                               " (its last message; no report reached the session)")))
    return segments


_SPEAKER_LIKE = re.compile(r"(?m)^#{1,2}(?=[ \t])")


def _render(segments: list[tuple[str, str]], cap: int | None) -> str:
    out = []
    for role, text in segments:
        if cap and len(text) > cap:
            text = text[:cap] + f"\n[... {len(text) - cap} characters cut ...]"
        # A heading inside a message (a report's "## Summary") would read like a new speaker: it
        # becomes a level-3 heading, so "## " lines are only ever the speakers.
        out.append(f"## {role}\n{_SPEAKER_LIKE.sub('###', text)}")
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
