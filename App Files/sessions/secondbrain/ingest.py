"""Turn one session, one meeting summary file, or one of the person's notes into a record filed under its topics."""
from __future__ import annotations

import hashlib
import html
import os
import re
import secrets
import zipfile
from datetime import datetime
from pathlib import Path

from . import llm, prompts, review, transcripts, wiki
from . import tags as taglists

MAX_TOPICS = 3


def _s(x) -> str:
    return " ".join(x.split()) if isinstance(x, str) else ""


def _strings(x) -> list[str]:
    return [s for s in (_s(i) for i in x) if s and not wiki.is_task_text(s)] if isinstance(x, list) else []


def normalise(data: dict) -> dict:
    """Coerce the model's reply into the exact shape the writer expects."""
    out = {
        "worth_recording": bool(data.get("worth_recording", True)),
        "skip_reason": _s(data.get("skip_reason")),
        "title": _s(data.get("title")) or "Untitled session",
        "summary": wiki.strip_task_lines(data["summary"]) if isinstance(data.get("summary"), str) else "",
        "findings": _strings(data.get("findings")),
        "open_questions": _strings(data.get("open_questions")),
        "decisions": [],
        "data_findings": [],
        "topics": [],
    }
    # The AI never touches to-dos: an item that is a checkbox line is dropped wherever it turns up
    # (wiki.is_task_text), so no task reaches a record or a topic page.
    for d in data.get("decisions") or []:
        text = _s(d.get("decision")) if isinstance(d, dict) else _s(d)
        if text and not wiki.is_task_text(text):
            out["decisions"].append({"decision": text, "why": _s(d.get("why")) if isinstance(d, dict) else ""})
    for f in data.get("data_findings") or []:
        if isinstance(f, dict) and _s(f.get("subject")) and _s(f.get("finding")) and not wiki.is_task_text(_s(f["finding"])):
            out["data_findings"].append({"subject": _s(f["subject"]), "finding": _s(f["finding"])})
    seen = set()
    for t in data.get("topics") or []:
        if not isinstance(t, dict):
            continue
        slug = wiki.slugify(t.get("slug") or t.get("title") or "")
        if slug == "untitled" or slug in seen:
            continue
        seen.add(slug)
        title = _s(t.get("title")) or slug.replace("-", " ").capitalize()
        out["topics"].append({
            "slug": slug,
            "title": title,
            "summary": (_strings([t.get("summary")]) or [title])[0],
            "entry": (_strings([t.get("entry")]) or [out["title"]])[0],
            "supersedes": bool(t.get("supersedes")),
            "tags": wiki.clean_tags(t.get("tags"), 3),
        })
    out["topics"] = out["topics"][:MAX_TOPICS]
    out["new_tags"] = [{"tag": n.get("tag"), "description": n.get("description")}
                       for n in data.get("new_tags") or [] if isinstance(n, dict)]
    if out["worth_recording"] and not out["summary"]:
        out["worth_recording"], out["skip_reason"] = False, "The model returned no summary."
    return out


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


SOURCE_KINDS = {
    "session": "a Claude Code working session (tool output removed)",
    "file": "a meeting summary or notes file, such as a Microsoft Teams recap",
}


def _capture_prompt(cfg, root: Path, wiki_cfg: dict, info: dict, kind: str, source_text: str,
                    tagset: "taglists.TagSet") -> str:
    today = datetime.now().date().isoformat()
    if kind == "note":
        request = prompts.request_text("note", today=today, note_name=info.get("note_name") or info.get("project") or "", date=info["date"])
    else:
        request = prompts.request_text("capture", today=today, source_kind=SOURCE_KINDS[kind], date=info["date"],
                                       project=info.get("project") or "(unknown)")
    return prompts.build("executive-assistant", [
        ("This request", request),
        *prompts.personal_rules_section(),   # the personal wiki's only rules: the capture rules file
        ("Existing topics", wiki.index_text(root) or "(no topics yet)"),
        *tagset.prompt_sections(),
        ("Existing tags", wiki.tags_text(root) or "(no tags yet)"),
        ("Reply format", prompts.NOTE_CAPTURE_REPLY if kind == "note" else prompts.CAPTURE_REPLY),
        ("The source", source_text),
    ])


def _record(cfg, info: dict, source_text: str, kind: str, dry_run: bool, ledger_extra: dict | None = None) -> dict:
    """Capture one source: a session ("session"), a meeting summary file ("file") or one of the
    person's notes ("note"). The ledger entry is keyed by info["session_id"]."""
    root = cfg.personal
    wiki_cfg = wiki.require_personal(root)
    tagset = taglists.TagSet(root)
    prompt = _capture_prompt(cfg, root, wiki_cfg, info, kind, source_text, tagset)
    llm.take_spend()  # start counting from here
    try:
        reply = llm.call_json(cfg, prompt, cfg.extract_model, thinking=cfg.capture_thinking,
                              schema=prompts.CAPTURE_SCHEMA, name="executive-assistant")
    except llm.LLMError:
        review._charge(root, "capture")
        raise
    data = normalise(reply)
    # New tags need a description of at most 8 words; one without is left out, here and on its topics.
    new_tags, rejected, tag_warnings = tagset.check_new(data["new_tags"])
    for t in data["topics"]:
        t["tags"] = tagset.settle(t["tags"], rejected)
    spend = llm.take_spend()
    result = {"session_id": info["session_id"], "title": data["title"], "warnings": [*tagset.warnings, *tag_warnings],
              "spend": spend, "topics": [], "conflicts": [], "new_tags": []}
    if dry_run:
        return {**result, "status": "dry-run", "extraction": data}

    if not data["worth_recording"]:
        with wiki.Lock(root):
            ledger = wiki.load_ledger(root)
            ledger[info["session_id"]] = _keep_name(ledger, info["session_id"], {
                "status": "skipped", "at": _now(), "reason": data["skip_reason"] or "Nothing durable to record.",
                "transcript_mtime": info.get("mtime"), "by": "model", "cost": spend["cost"], "title": data["title"],
                **(ledger_extra or {}),
            })
            wiki.save_ledger(root, ledger)
            wiki.add_spend(root, "capture", spend)
        return {**result, "status": "skipped", "reason": ledger[info["session_id"]]["reason"]}

    with wiki.Lock(root):
        ledger = wiki.load_ledger(root)
        prior = ledger.get(info["session_id"], {}).get("note")
        if prior and (root / prior).exists():
            rel = prior
        else:
            rel = _new_record_path(root, info["date"], data["title"], info.get("capture_id") or info["session_id"])
        stem = Path(rel).stem
        topics = [wiki.upsert_topic(root, t, info["date"], stem) for t in data["topics"]]
        dropped = wiki.drop_note_from_topics(root, stem, keep={t["slug"] for t in topics})
        tags = list(dict.fromkeys(tag for t in topics for tag in t["tags"]))  # the note carries its topics' tags
        wiki.write_session_note(root, rel, info, data, tags, _now())
        for slug in [*(t["slug"] for t in topics), *dropped]:  # each log, again from the session notes
            wiki.rebuild_log(root, slug)
        queued = wiki.update_queue(root, info["date"], stem, data["data_findings"])
        used = {tag for t in topics for tag in t["tags"]}
        added = taglists.add_personal(root, [n for n in new_tags if n["tag"] in used])  # only tags actually used
        wiki.write_index(root)
        ledger[info["session_id"]] = _keep_name(ledger, info["session_id"], {
            "status": "ingested", "at": _now(), "note": rel, "transcript_mtime": info.get("mtime"), "cost": spend["cost"],
            "title": data["title"], **(ledger_extra or {}),
        })
        wiki.save_ledger(root, ledger)
        wiki.add_spend(root, "capture", spend)

    after = taglists.TagSet(root)
    for t in topics:  # the Review tab picks these up; capture never rewrites a summary itself
        t["review_due"] = review.is_due(cfg, t["slug"])
        t["personal_tags"] = after.personal_only(t["tags"])   # tags a team wiki wouldn't know
    return {**result, "status": "ingested", "note": rel, "topics": topics, "tags": tags, "queued_findings": queued,
            "new_tags": added}


def _new_record_path(root: Path, date: str, title: str, ref: str) -> str:
    """A new record's path: Sessions/<date>-<title words>.md. A short piece of the session's (or
    note's) id is added only when another record already has that name."""
    base = f"{wiki.SESSIONS_DIR}/{date}-{wiki.slugify(title, 40)}"
    if not (root / f"{base}.md").exists():
        return f"{base}.md"
    short = re.sub(r"[^A-Za-z0-9]", "", ref).lower()
    for n in (8, len(short)):
        if short and not (root / f"{base}-{short[:n]}.md").exists():
            return f"{base}-{short[:n]}.md"
    n = 2
    while (root / f"{base}-{n}.md").exists():
        n += 1
    return f"{base}-{n}.md"


# ---------- readable session names ----------
# Each session gets a short readable name, "<date>-<a few words>" (2026-11-12-churn-dashboard-fix),
# shown instead of its id. The words come from Claude Code's name for the session (one the person
# gave it, else the one Claude Code generated), else the person's first message: no request to a
# model. A short piece of the id is added only when two names would clash. A name is kept in the
# session's ledger entry once given, so it never changes; the id stays the hidden reference.

NAME_WORDS = 5


def _keep_name(ledger: dict, key: str, entry: dict) -> dict:
    """A new ledger entry for key that keeps the name the session was given."""
    name = (ledger.get(key) or {}).get("name") if isinstance(ledger.get(key), dict) else None
    return {**entry, "name": name} if name else entry


def _name_base(meta: dict) -> str:
    words = wiki.slugify(meta.get("named_title") or meta.get("first_prompt") or meta.get("title") or "", 48).split("-")
    words = [w for w in words if w][:NAME_WORDS]
    phrase = "-".join(words)
    if phrase == "untitled" or not phrase:
        phrase = "session"
    return f"{meta['date']}-{phrase}"


def new_name(meta: dict, taken: set) -> str:
    base = _name_base(meta)
    if base not in taken:
        return base
    short = re.sub(r"[^a-z0-9]", "", str(meta["session_id"]).lower())
    for n in (4, 8, len(short)):
        if short and f"{base}-{short[:n]}" not in taken:
            return f"{base}-{short[:n]}"
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def assign_names(cfg, metas: list[dict], save: bool = True) -> dict[str, str]:
    """{session id: name} for these sessions: the name each was given before, or a new one. New
    names are saved in the ledger when save (only in a folder writes are allowed in: see
    wiki.require_personal); otherwise they are worked out for this answer only."""
    root = cfg.personal
    ledger = wiki.load_ledger(root)

    def given(sid):
        entry = ledger.get(sid)
        return entry.get("name") if isinstance(entry, dict) else None

    missing = [m for m in metas if not given(m["session_id"])]
    if missing and save and wiki.is_personal(root):
        with wiki.Lock(root):
            ledger = wiki.load_ledger(root)
            taken = {e.get("name") for e in ledger.values() if isinstance(e, dict) and e.get("name")}
            for meta in sorted(missing, key=lambda m: (m["date"], m["mtime"])):
                if not given(meta["session_id"]):
                    name = new_name(meta, taken)
                    taken.add(name)
                    ledger.setdefault(meta["session_id"], {})["name"] = name
            wiki.save_ledger(root, ledger)
        missing = []
    out = {m["session_id"]: given(m["session_id"]) for m in metas if given(m["session_id"])}
    taken = set(out.values()) | {e.get("name") for e in ledger.values() if isinstance(e, dict) and e.get("name")}
    for meta in missing:   # not saved: worked out for this answer only
        out[meta["session_id"]] = new_name(meta, taken)
        taken.add(out[meta["session_id"]])
    return out


def resolve_session(cfg, ref: str):
    """A transcript by session id (or an unambiguous prefix), or by the readable name it was given."""
    try:
        return transcripts.find_session(cfg, ref)
    except FileNotFoundError:
        ledger = wiki.load_ledger(cfg.personal)
        sid = next((k for k, e in ledger.items() if isinstance(e, dict) and e.get("name") == ref), None)
        if not sid:
            raise
        return transcripts.find_session(cfg, sid)


def ingest_session(cfg, session_id: str, dry_run: bool = False, force: bool = False, only_new: bool = False) -> dict:
    """only_new: a session already captured, whose transcript hasn't changed since, is not sent
    again (the app always asks this way; the command line re-captures unless --only-new).
    session_id may also be the session's readable name. A session chosen here is captured however
    few turns it has: the minimum-turns filter only hides sessions from the list (and so from
    "ingest all"). force is kept for older callers; it changes nothing now."""
    path = resolve_session(cfg, session_id)
    info = transcripts.read_meta(path)
    info["source"] = "claude-code"
    if not dry_run:
        wiki.require_personal(cfg.personal)   # a team or view-only wiki is refused before anything is sent
    info["name"] = assign_names(cfg, [info], save=not dry_run).get(info["session_id"])
    if only_new:
        entry = wiki.load_ledger(cfg.personal).get(info["session_id"]) or {}
        if entry.get("status") == "ingested" and info["mtime"] <= (entry.get("transcript_mtime") or 0) + 2:
            return {"session_id": info["session_id"], "name": info["name"], "title": entry.get("title") or info["title"],
                    "status": "unchanged", "note": entry.get("note"),
                    "reason": "Already captured, and the session hasn't changed since.",
                    "topics": [], "warnings": [], "conflicts": []}
    if info["user_messages"] == 0:
        return {"session_id": info["session_id"], "name": info["name"], "title": info["title"], "status": "skipped",
                "reason": "The session has no message from you.", "warnings": []}
    text = transcripts.condense(path, cfg.max_transcript_chars)
    return {"name": info["name"], **_record(cfg, info, text, "session", dry_run)}


def _read_source_file(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()
    return path.read_text(encoding="utf-8", errors="replace").strip()


def ingest_file(cfg, file_path: str, date: str | None = None, dry_run: bool = False) -> dict:
    """Ingest a meeting summary or notes file (.md, .txt, .vtt, .docx)."""
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No such file: {path}")
    text = _read_source_file(path)
    if not text:
        raise ValueError(f"{path} is empty")
    info = {
        "session_id": "file-" + hashlib.sha1(str(path).lower().encode("utf-8")).hexdigest()[:12],
        "source": "file",
        "project": path.name,
        "date": date or datetime.fromtimestamp(path.stat().st_mtime).date().isoformat(),
        "mtime": path.stat().st_mtime,
    }
    text = text[: cfg.max_transcript_chars]
    return _record(cfg, info, text, "file", dry_run)


# ---------- the person's notes ----------
# A note (a Markdown file in a notes folder) is captured into the personal wiki exactly as a session
# is: a record in Sessions/ (origin: note), a line in each of its topics' logs marked [note]. The
# note itself gets two frontmatter properties: `capture_id` (permanent, written before the first
# capture, so a renamed or moved note is still the same note) and `ingested: <date>` (captured).
# The ledger keeps, under `note:<capture_id>`, a hash of the note's text when it was captured: an
# unchanged note is never sent again, and an edited one is captured again in place of its earlier
# record (same record, same log lines replaced, never added twice).

NOTE_ID = re.compile(r"\An-[0-9a-f]{12}\Z")
NOT_NOTES = {"topic", "session", "folder", "personal"}   # pages this tool writes, never captured as notes


def _read_raw(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:  # line endings and BOM kept as they are
        return f.read()


def _meta_body(raw: str) -> tuple[dict, str]:
    return wiki.parse(raw.lstrip("﻿").replace("\r\n", "\n"))


def _text_hash(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()[:20]


def _with_properties(raw: str, values: dict) -> str:
    """The note's text with these frontmatter properties set: an existing line for the property is
    replaced, a missing one added at the end of the frontmatter (made if there is none). Every
    other line is left exactly as it was, line endings included."""
    bom = "﻿" if raw.startswith("﻿") else ""
    text = raw[len(bom):]
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    fresh = [f"{k}: {v}{nl}" for k, v in values.items()]
    if lines and lines[0].strip() == "---":
        close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if close is not None:
            front = lines[1:close]
            for (key, _), line in zip(values.items(), fresh):
                at = next((i for i, ln in enumerate(front) if re.match(rf"{re.escape(key)}\s*:", ln)), None)
                if at is None:
                    front.append(line)
                else:
                    front[at] = line
            return bom + lines[0] + "".join(front) + "".join(lines[close:])
    return bom + f"---{nl}" + "".join(fresh) + f"---{nl}" + text


def _mark_note(path: Path, expected: str, values: dict) -> str | None:
    """Sets frontmatter properties in the note, only if it still reads as expected (the person may
    be typing in it). Written to a hidden temp file, then swapped in. -> the new text, or None."""
    if _read_raw(path) != expected:
        return None
    new = _with_properties(expected, values)
    if new == expected:
        return new
    temp = path.with_name(f".{path.name}.sb.tmp")
    with open(temp, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    os.replace(temp, path)
    return new


def _same_file(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(str(b))


def _note_date(meta: dict, path: Path) -> str:
    for key in ("date", "started", "created"):
        value = str(meta.get(key) or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return value
    return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()


def _read_note(cfg, file_path: str) -> tuple[Path, str, dict, str]:
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No such note: {path}")
    if path.suffix.lower() not in (".md", ".markdown"):
        raise ValueError(f"{path.name} isn't a Markdown note.")
    root = cfg.personal.resolve()
    if path.is_relative_to(root / wiki.SESSIONS_DIR):
        raise ValueError(f"{path.name} is a record this tool wrote, not a note.")
    raw = _read_raw(path)
    meta, body = _meta_body(raw)
    if meta.get("type") in NOT_NOTES:
        raise ValueError(f"{path.name} is a page this tool writes (type: {meta.get('type')}), not a note.")
    return path, raw, meta, body


def _known_id(cfg, meta: dict, path: Path, ledger: dict) -> str:
    """The note's capture_id, or "" when it has none yet, or is a copy of another captured note
    (both files carrying the same id): a copy is a new note and gets its own id."""
    cid = str(meta.get("capture_id") or "")
    if not NOTE_ID.match(cid):
        return ""
    entry = ledger.get("note:" + cid)
    other = Path(entry["path"]) if entry and entry.get("path") else None
    if other and not _same_file(str(other), path) and other.is_file():
        try:
            if _meta_body(_read_raw(other))[0].get("capture_id") == cid:
                return ""
        except (OSError, UnicodeDecodeError):
            pass
    return cid


def note_status(cfg, file_path: str) -> dict:
    """Whether a note is captured: "new" (never captured), "changed" (edited since it was
    captured) or "captured" (captured as it is now). No request to Claude."""
    try:
        path, raw, meta, body = _read_note(cfg, file_path)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return {"path": str(file_path), "status": "error", "error": str(e)}
    ledger = wiki.load_ledger(cfg.personal)
    cid = _known_id(cfg, meta, path, ledger)
    entry = ledger.get("note:" + cid) if cid else None
    status = "new" if not entry else "captured" if entry.get("hash") == _text_hash(body) else "changed"
    # A note the older Notes flow handled (`ingested:` but never given a capture_id) counts as done.
    # Choosing it deliberately still captures it (captureNotes treats it as new).
    legacy = not entry and not str(meta.get("capture_id") or "") and bool(meta.get("ingested"))
    if legacy:
        status = "captured"
    return {"path": str(path), "status": status, "legacy": legacy, "capture_id": cid,
            "captured_at": (entry or {}).get("at", "") or (str(meta.get("ingested")) if legacy else ""),
            "record": (entry or {}).get("note", ""), "ingested": str(meta.get("ingested") or "")}


def _relink_record(record: Path, note: Path) -> bool:
    """A captured note was renamed or moved: its record's link and `project` name the note's
    current file. A text edit of those two places only; nothing is sent anywhere. -> whether it changed."""
    try:
        with open(record, encoding="utf-8", newline="") as f:
            text = f.read()
    except OSError:
        return False
    new = re.sub(r"(?m)^(From your note: \[\[)[^\]\r\n]*(\]\])", lambda m: m.group(1) + note.stem + m.group(2), text, count=1)
    m = wiki.FM_RE.match(new)
    if m:   # only inside the frontmatter
        front = re.sub(r"(?m)^project:.*$", lambda _: "project: " + wiki._dump_value(note.name), m.group(0), count=1)
        new = front + new[m.end():]
    if new == text:
        return False
    wiki.write_text(record, new)
    return True


def ingest_note(cfg, file_path: str, dry_run: bool = False, force: bool = False) -> dict:
    """Capture one of the person's notes into the personal wiki. A note captured before and not
    changed since is not sent again (status "unchanged"), unless force."""
    root = cfg.personal
    wiki.require_personal(root)
    path, raw, meta, body = _read_note(cfg, file_path)
    if not body.strip():
        raise ValueError(f"{path.name} is empty.")
    digest = _text_hash(body)
    ledger = wiki.load_ledger(root)
    cid = _known_id(cfg, meta, path, ledger)
    entry = ledger.get("note:" + cid) if cid else None
    base = {"path": str(path), "note_name": path.stem, "warnings": [], "conflicts": [], "topics": []}
    today = datetime.now().date().isoformat()

    if entry and entry.get("hash") == digest and not force:
        # Captured as it is now (perhaps renamed or moved since): nothing is sent again.
        if not dry_run:
            if not _same_file(str(entry.get("path") or ""), path):
                with wiki.Lock(root):
                    ledger = wiki.load_ledger(root)
                    ledger["note:" + cid]["path"] = str(path)
                    wiki.save_ledger(root, ledger)
            if not meta.get("ingested"):
                _mark_note(path, raw, {"capture_id": cid, "ingested": today})
            if entry.get("note"):
                with wiki.Lock(root):
                    _relink_record(root / str(entry["note"]), path)
        return {**base, "capture_id": cid, "session_id": "note:" + cid, "status": "unchanged",
                "title": entry.get("title") or path.stem, "note": entry.get("note"),
                "reason": "Already captured, and the note hasn't changed since."}

    if not cid and not dry_run:
        # The permanent id goes into the note before anything is sent, so the note stays the same
        # note whatever happens next (a failed capture, a rename).
        cid = "n-" + secrets.token_hex(6)
        raw = _mark_note(path, raw, {"capture_id": cid})
        if raw is None:
            raise wiki.WikiError(f"{path.name} changed while it was being read. Try again.")
    info = {
        "session_id": "note:" + (cid or "new"),
        "source": "note",
        "capture_id": cid,
        "note_name": path.stem,
        "project": path.name,
        "date": _note_date(meta, path),
        "mtime": path.stat().st_mtime,
    }
    result = _record(cfg, info, body.strip()[: cfg.max_transcript_chars], "note", dry_run,
                     ledger_extra={"kind": "note", "path": str(path), "hash": digest, "capture_id": cid})
    result = {**base, **result, "path": str(path), "capture_id": cid}
    if dry_run:
        return result
    if _mark_note(path, raw, {"capture_id": cid, "ingested": today}) is None:
        result["warnings"].append(f"{path.name} changed during the capture, so it wasn't marked as captured. "
                                  "Capture it again to take the change in.")
    return result


def skip_session(cfg, session_id: str, reason: str) -> dict:
    path = resolve_session(cfg, session_id)
    root = cfg.personal
    wiki.require_personal(root)
    meta = transcripts.read_meta(path)
    name = assign_names(cfg, [meta]).get(path.stem)
    with wiki.Lock(root):
        ledger = wiki.load_ledger(root)
        ledger[path.stem] = _keep_name(ledger, path.stem, {
            "status": "skipped", "at": _now(), "reason": reason or "Skipped by user.",
            "transcript_mtime": path.stat().st_mtime, "by": "user",
        })
        wiki.save_ledger(root, ledger)
    return {"session_id": path.stem, "name": name, "status": "skipped", "reason": ledger[path.stem]["reason"]}


def list_sessions(cfg, days: int | None = None, include_done: bool = False, min_turns: int | None = None) -> dict:
    """Sessions in the lookback window with their ingest status (new, updated, ingested or skipped):
    {"sessions": [rows], "hidden_count": N, "min_turns": N}. A session with fewer of the person's own
    messages than min_turns (default: cfg.hide_below(), the Sessions filter) is left out and only
    counted in hidden_count; 0 hides none."""
    min_turns = cfg.hide_below() if min_turns is None else max(0, int(min_turns))
    ledger = wiki.load_ledger(cfg.personal)
    shown, hidden = [], 0
    for meta in transcripts.recent_sessions(cfg, days):
        entry = ledger.get(meta["session_id"])
        entry = entry if isinstance(entry, dict) and entry.get("status") else None   # a name alone: still new
        if not entry:
            status = "new"
        elif entry["status"] == "ingested" and meta["mtime"] > (entry.get("transcript_mtime") or 0) + 2:
            status = "updated"
        else:
            status = entry["status"]
        if status in ("ingested", "skipped") and not include_done:
            continue
        if meta["user_messages"] < min_turns:
            hidden += 1
            continue
        shown.append((meta, entry, status))
    names = assign_names(cfg, [m for m, _, _ in shown]) if shown else {}
    rows = []
    for meta, entry, status in shown:
        row = {k: meta[k] for k in ("session_id", "title", "date", "last_active", "project", "entrypoint", "user_messages",
                                    "subagents", "first_prompt")}
        row["name"] = names.get(meta["session_id"])
        row["status"] = status
        if entry:
            row["note"] = entry.get("note")
            row["reason"] = entry.get("reason")
        rows.append(row)
    return {"sessions": rows, "hidden_count": hidden, "min_turns": min_turns}
