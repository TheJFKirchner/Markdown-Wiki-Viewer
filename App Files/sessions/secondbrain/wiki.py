"""All file writes to the personal wiki. Models produce text; this module places it.

Layout of a personal wiki (in WikiApp, the open wiki whose role is "personal"):
    WIKI.md               marks the folder as a personal wiki (type: personal) for the command line
                          on its own; in WikiApp the role decides, and Set up doesn't make it
    wiki_rules.md         optional rules for the agents that work in this wiki
    index.md              one line per topic, grouped by folder, regenerated from the topic pages
    promotion-queue.md    data findings waiting to be promoted to the team wiki
    <topic>.md            a topic's page: current state, your notes, and a dated log. Its
                          frontmatter `tags` connect it to related topics
    <tag>/                a tag that became a folder: its topics, and a hub page <tag>.md
    Sessions/             one short record per captured session or note (frontmatter `origin`:
                          session or note)

The tool's own progress for the wiki (ledger.json: which sessions and notes have been captured or
skipped; spend.json; conflicts.json; the write lock; the model's work folder) is kept in WikiApp's
progress folder for the wiki (see state_dir), not in the wiki itself.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
PLAIN = re.compile(r"[A-Za-z0-9_./\\ -]+")
NO_STATE = "_Not yet summarised. See the log below._"


def stamp() -> str:
    """Now, as UTC text that sorts in time order. A page's `changed` is compared with its
    `promoted` (written by WikiApp the same way) to tell whether it changed since."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
INDEX_MARK = "Generated from page frontmatter; do not edit by hand."


class WikiError(Exception):
    pass


# ---------- frontmatter ----------

def _parse_value(v: str):
    if v == "":
        return ""
    if v.startswith("[") and v.endswith("]"):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
    if v.startswith('"'):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v.strip('"')
    if len(v) > 1 and v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def parse(text: str) -> tuple[dict, str]:
    """Split a page into (frontmatter, body). Only flat `key: value` lines are read."""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line[0] in " \t-#" or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = _parse_value(value.strip())
    return meta, text[m.end():]


def _dump_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False)
    s = str(v)
    if s and PLAIN.fullmatch(s) and s == s.strip() and s not in ("true", "false") and not re.fullmatch(r"-?\d+", s):
        return s
    return json.dumps(s, ensure_ascii=False)


def render(meta: dict, body: str) -> str:
    lines = [f"{k}: {_dump_value(v)}" for k, v in meta.items()]
    return "---\n" + "\n".join(lines) + "\n---\n" + body.lstrip("\n")


def read_page(path: Path) -> tuple[dict, str]:
    return parse(path.read_text(encoding="utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    os.replace(tmp, path)


# ---------- sections ----------
# The parts of a page this tool writes are found by their headings: everything under the heading,
# up to the next heading of the same or a higher level. Pages carry no marker comments. A page
# whose heading was renamed or removed is left alone, with an error that says which heading.

HEADINGS = {"state": "Current state", "related": "Related", "notes": "Notes", "log": "Log", "members": "Topics", "queue": "Findings"}
# Pages written by earlier versions marked these parts with comments; they are dropped on the way in.
_OLD_MARKS = re.compile(r"^<!-- (?:sb:\w+:(?:start|end)|Yours\. Automation never edits this section\.) -->[ \t]*\n?", re.M)


def _clean(text: str) -> str:
    return _OLD_MARKS.sub("", text.replace("<!-- sb:queue:start -->", "## Findings"))


def _span(text: str, name: str) -> tuple[int, int]:
    heading = HEADINGS[name]
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n", text + "\n", re.M)
    if not m:
        raise WikiError(f"A page has no '## {heading}' heading, so it was left alone. Put the heading back and try again.")
    nxt = re.search(r"^#{1,2} ", text[m.end():], re.M)
    return m.end(), (m.end() + nxt.start() if nxt else len(text))


def get_zone(text: str, name: str) -> str:
    text = _clean(text)
    a, b = _span(text, name)
    return text[a:b].strip("\n")


def set_zone(text: str, name: str, content: str) -> str:
    text = _clean(text)
    a, b = _span(text, name)
    tail = text[b:]
    content = content.strip("\n")
    return text[:a] + (content + "\n" if content else "") + ("\n" + tail if tail else "")


def ensure_related(text: str) -> str:
    """A topic page with a '## Related' heading: pages made before it existed get one, right after
    the Current state section. Nothing else on the page moves."""
    text = _clean(text)
    if re.search(r"^## Related[ \t]*$", text, re.M):
        return text
    _, b = _span(text, "state")
    head = text[:b].rstrip("\n") + "\n\n"
    tail = text[b:].lstrip("\n")
    return head + "## Related\n" + ("\n" + tail if tail else "")


# ---------- basics ----------

def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug[:limit].strip("-") or "untitled"


def app_role(root: Path) -> str | None:
    """The wiki's role in WikiApp ("personal", "team" or "view"), or None when WikiApp has no say:
    no private folder (the command line on its own), or a folder that isn't one of the open wikis."""
    try:
        from .config import pathlist
        return pathlist.wiki_role_for_root(root)
    except Exception:  # the path list can't be read: as on the command line on its own
        return None


def _personal_by_role(root: Path) -> bool:
    """True when WikiApp says root is the personal wiki; False when WikiApp has no say (then a
    WIKI.md saying type: personal decides). Raises WikiError when WikiApp says it isn't: a team or
    view-only wiki, or a folder outside the open wikis while another is the personal wiki."""
    role = app_role(root)
    if role == "personal":
        return True
    try:
        from .config import pathlist
        if role is not None:
            raise WikiError(pathlist.role_refusal(pathlist.alias_of_root(root), role, "personal"))
        other = pathlist.wiki_with_role("personal")
    except WikiError:
        raise
    except Exception:
        return False
    if other:
        raise WikiError(f"{root} isn't your personal wiki ({other['alias']} is). Notes and sessions are only "
                        "captured into your personal wiki; choose it in Settings.")
    return False


def is_personal(root: Path) -> bool:
    """Whether writes to root are allowed (see require_personal), without raising."""
    try:
        if _personal_by_role(root):
            return True
    except WikiError:
        return False
    try:
        return (root / "WIKI.md").exists() and read_page(root / "WIKI.md")[0].get("type") == "personal"
    except OSError:
        return False


def require_personal(root: Path) -> dict:
    """Refuse to write anywhere but the personal wiki. In WikiApp that is the open wiki whose role is
    "personal" (Settings): a team or view-only wiki is refused, and its WIKI.md is not needed or
    read. Without WikiApp (the command line on its own) it is a folder whose WIKI.md says type: personal."""
    if _personal_by_role(root):
        meta = {}
        if (root / "WIKI.md").exists():
            try:
                meta = read_page(root / "WIKI.md")[0]
            except (OSError, UnicodeDecodeError):
                meta = {}
        upgrade_layout(root)
        meta["_rules"] = ""
        return meta
    cfg_file = root / "WIKI.md"
    if not cfg_file.exists():
        raise WikiError(f"{root} has no WIKI.md. Run 'sb.py init' to set it up as a personal wiki.")
    meta, body = read_page(cfg_file)
    if meta.get("type") != "personal":
        raise WikiError(
            f"{root} is marked type '{meta.get('type')}', not 'personal'. Sessions are only ever written to a personal wiki."
        )
    upgrade_layout(root)
    # The personal wiki's rules are the person's capture rules file (the path list's
    # personal_capture_rules, sent by prompts.personal_rules_section), not a file in the wiki.
    meta["_rules"] = ""
    return meta


OLD_STATE = ".sb"
COPIED_MARK = "copied-from-sb.txt"


def state_dir(root: Path) -> Path:
    """Where the tool keeps this wiki's progress: ledger.json, spend.json, conflicts.json, the lock
    and the model's work folder. That is WikiApp's progress folder for the wiki
    (pathlist.progress_dir) once the app has a private folder, and <wiki>/.sb when it has none
    (the command line on its own). The first time the progress folder is used, everything in
    <wiki>/.sb is copied across; nothing is ever deleted."""
    old = root / OLD_STATE
    try:
        from .config import pathlist
        target = pathlist.progress_dir(root)
        pathlist.ensure_parent(target / COPIED_MARK)  # made inside the private folder only
    except Exception:  # no private folder chosen (or the path list can't be read)
        old.mkdir(parents=True, exist_ok=True)
        return old
    _copy_old_state(old, target)
    return target


def _copy_old_state(old: Path, target: Path) -> None:
    if (target / COPIED_MARK).exists() or not old.is_dir():
        return
    for item in old.iterdir():
        dest = target / item.name
        if item.name == "lock" or dest.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    from datetime import datetime
    (target / COPIED_MARK).write_text(
        f"Copied from the wiki's {OLD_STATE} folder on {datetime.now().date().isoformat()}. "
        "That folder was left as it was and can be deleted by hand.\n", encoding="utf-8")


class Lock:
    """Short exclusive lock around file writes, so two ingests cannot interleave."""

    def __init__(self, root: Path, timeout: float = 90, stale: float = 600):
        self.path = state_dir(root) / "lock"
        self.timeout, self.stale = timeout, stale

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.time() > deadline:
                    raise WikiError("Another ingest is holding the wiki lock. Try again shortly.")
                time.sleep(0.4)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# ---------- ledger ----------

def load_ledger(root: Path) -> dict:
    """Which sessions and notes have been captured or skipped. Keys: a session's id, or
    `note:<capture_id>` for a note."""
    path = state_dir(root) / "ledger.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_ledger(root: Path, ledger: dict) -> None:
    write_text(state_dir(root) / "ledger.json", json.dumps(ledger, indent=1, ensure_ascii=False))


# ---------- spend ----------

def add_spend(root: Path, kind: str, spend: dict) -> None:
    """Add one command's model spend to the wiki's running totals (spend.json in its progress
    folder), by kind: capture, review or merge. Call it while holding the Lock."""
    if not spend.get("calls"):
        return
    totals = load_spend(root)
    row = totals.setdefault(kind, {"cost": 0.0, "tokens_in": 0, "tokens_out": 0, "calls": 0, "runs": 0})
    for key in ("cost", "tokens_in", "tokens_out", "calls"):
        row[key] = round(row.get(key, 0) + spend.get(key, 0), 6)
    row["runs"] = row.get("runs", 0) + 1
    write_text(state_dir(root) / "spend.json", json.dumps(totals, indent=1))


def load_spend(root: Path) -> dict:
    path = state_dir(root) / "spend.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# ---------- pages ----------
# A topic is a page about one piece of work (a project, an analysis, a question). It sits at the
# top of the wiki as <slug>.md, or inside a folder once it has been grouped. A tag is a label in a
# topic's frontmatter that connects related topics; when enough topics share one, the tag can
# become a folder with a hub page. Pages are found by name wherever they sit, so moving one never
# breaks a [[link]] to it.

SESSIONS_DIR = "Sessions"
_NOT_PAGES = {"templates"}  # folders (lower case) that hold no pages of the wiki itself


def wiki_files(root: Path) -> list[Path]:
    """Every Markdown file in the wiki, hidden folders and Templates left out."""
    out = []
    for path in sorted(root.rglob("*.md")):
        parts = path.relative_to(root).parts
        if any(p.startswith(".") for p in parts) or parts[0].lower() in _NOT_PAGES:
            continue
        out.append(path)
    return out


def _in_sessions(root: Path, path: Path) -> bool:
    return path.relative_to(root).parts[0].lower() == SESSIONS_DIR.lower()


def topic_pages(root: Path) -> list[tuple[Path, dict]]:
    out = []
    for path in wiki_files(root):
        if _in_sessions(root, path):
            continue
        meta, _ = read_page(path)
        if meta.get("type") == "topic":
            out.append((path, meta))
    return out


def find_topic(root: Path, slug: str) -> Path | None:
    return next((p for p, _ in topic_pages(root) if p.stem == slug), None)


def _name_taken(root: Path, name: str) -> Path | None:
    """Any page in the wiki with this name. Names must be unique: links go by name."""
    return next((p for p in wiki_files(root) if p.stem.lower() == name.lower()), None)


def clean_tags(tags, limit: int = 4) -> list[str]:
    out = []
    for t in tags if isinstance(tags, list) else []:
        slug = slugify(t, 40)
        if slug != "untitled" and slug not in out:
            out.append(slug)
    return out[:limit]


def all_tags(root: Path) -> dict[str, int]:
    """Every tag in use on a topic, with how many topics carry it."""
    counts: dict[str, int] = {}
    for _, meta in topic_pages(root):
        for tag in clean_tags(meta.get("tags"), 20):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


NO_RELATED = "_None yet. A review fills this in._"


def _new_topic(title: str) -> str:
    return f"# {title}\n\n## Current state\n{NO_STATE}\n\n## Related\n{NO_RELATED}\n\n## Notes\n\n## Log\n"


_LOG_LINK = re.compile(r"\(\[\[([^\]]+)\]\]\)(?: — also touches .*)?\s*$")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]*))?\]\]")


def links_in(text: str) -> list[str]:
    """The page names [[linked]] in a text."""
    return [m.group(1).strip() for m in _WIKILINK.finditer(text or "")]


def unlink_missing(text: str, topics: set[str]) -> tuple[str, list[str]]:
    """The text with every [[link]] that isn't to an existing topic turned back into plain words
    (its label, or the name). -> (text, the names unlinked)"""
    names = {t.lower() for t in topics}
    removed = []

    def one(m):
        if m.group(1).strip().lower() in names:
            return m.group(0)
        removed.append(m.group(1).strip())
        return (m.group(3) or m.group(1)).strip()
    return _WIKILINK.sub(one, text or ""), removed


def _log_lines(body: str) -> list[str]:
    return [ln for ln in get_zone(body, "log").splitlines() if ln.startswith("- ")]


def upsert_topic(root: Path, topic: dict, date: str, note_stem: str) -> dict:
    """Make sure the topic's page exists and count this session on it. The log itself is rebuilt
    from the session notes afterwards (rebuild_log), once the session's note is written."""
    slug = topic["slug"]
    path = find_topic(root, slug)
    created = path is None
    if created:
        clash = _name_taken(root, slug)
        if clash:
            raise WikiError(f"Can't make the topic '{slug}': {clash} already has that name. Rename that page, or the topic.")
        path = root / f"{slug}.md"
        meta = {   # no "kind": tags say what kind of thing a topic is
            "title": topic["title"],
            "type": "topic",
            "tags": clean_tags(topic.get("tags")),
            "folder": "",
            "summary": topic["summary"],
            "created": date,
            "updated": date,
            "state_as_of": "",
            "entries_since_review": 0,
            "needs_review": False,
            "review_reason": "",
        }
        body = _new_topic(topic["title"])
    else:
        meta, body = read_page(path)
        meta["tags"] = clean_tags(list(meta.get("tags") or []) + list(topic.get("tags") or []), 6)
    if f"[[{note_stem}]]" not in get_zone(body, "log"):  # a re-ingest of a session already counted adds nothing
        meta["entries_since_review"] = int(meta.get("entries_since_review") or 0) + 1
    if topic.get("supersedes") and not created:  # a new topic has nothing to supersede
        meta["needs_review"], meta["review_reason"] = True, "reversed"
    meta["updated"] = max(str(meta.get("updated") or ""), date)
    meta["changed"] = stamp()
    write_text(path, render(meta, _clean(body)))
    return {"slug": slug, "created": created, "path": path.relative_to(root).as_posix(), "tags": meta["tags"]}


def drop_note_from_topics(root: Path, note_stem: str, keep: set[str]) -> list[str]:
    """On re-ingest: the topics this session was filed under before and isn't now. They are marked
    for review; their logs lose the line when they are rebuilt. -> their names."""
    link = f"[[{note_stem}]]"
    dropped = []
    for path, _ in topic_pages(root):
        if path.stem in keep:
            continue
        meta, body = read_page(path)
        if link not in get_zone(body, "log"):
            continue
        meta["needs_review"] = True
        meta["review_reason"] = meta.get("review_reason") or "removed"
        meta["changed"] = stamp()
        write_text(path, render(meta, body))
        dropped.append(path.stem)
    return dropped


ORIGINS = ("note", "session")
# A log line: "- 2026-11-03 [note] — what it added ([[record]]) — also touches [[a]], [[b]]". The
# word in brackets says where it came from: a note the person wrote, or a session (a Claude Code
# session or a meeting summary). "also touches" names the other topics the same record was filed
# under (left out when there are none).
LOG_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2})(?: \[(note|session)\])? — (.*?) \(\[\[([^\]]+)\]\]\)(?: — also touches (.*?))?\s*$")


def origin_of(meta: dict) -> str:
    """"note" for a record captured from one of the person's notes, else "session"."""
    return "note" if meta.get("origin") == "note" else "session"


def log_source(line: str) -> str | None:
    """Where a log line came from ("note" or "session"), or None for a line without the mark."""
    m = LOG_LINE.match(line)
    return m.group(2) if m else None


def note_entries(meta: dict) -> dict[str, str]:
    """A session note's line for each of its topics, from its frontmatter `entries`."""
    out = {}
    for item in meta.get("entries") or []:
        slug, _, text = str(item).partition(": ")
        if text:
            out[slug] = text
    return out


def rebuild_log(root: Path, slug: str, legacy: list[str] | None = None) -> int:
    """Write a topic's Log again from the records filed under it, newest first: one dated line per
    session or note, marked with where it came from, linking to its record. Nothing is edited in
    place, so the log can't drift from the records. legacy: log lines to fall back on for records
    written before records carried their own line. -> how many entries the log lists."""
    path = find_topic(root, slug)
    if not path:
        return 0
    meta, body = read_page(path)
    known = {}
    for line in [*(legacy or []), *_log_lines(body)]:
        m = _LOG_LINK.search(line)
        if m:
            known.setdefault(m.group(1), line)
    lines = []
    existing = {p.stem for p, _ in topic_pages(root)}
    for note, nmeta, _ in session_notes(root):
        if slug not in (nmeta.get("topics") or []):
            continue
        entry = note_entries(nmeta).get(slug)
        if not entry and note.stem in known:
            old = LOG_LINE.match(known[note.stem])
            entry = old.group(3) if old else ""
        date = str(nmeta.get("date") or "")
        if entry and date and entry.startswith(date):   # the text already opens with the date: don't say it twice
            entry = re.sub(r"\A\s*[:—–-]?\s*", "", entry[len(date):]) or entry
        others = [t for t in dict.fromkeys(nmeta.get("topics") or []) if t != slug and t in existing]
        also = (" — also touches " + ", ".join(f"[[{t}]]" for t in others)) if others else ""
        lines.append(f"- {date} [{origin_of(nmeta)}] — {entry or nmeta.get('title') or note.stem} ([[{note.stem}]]){also}")
    lines.sort(key=lambda ln: ln[2:12], reverse=True)
    new = set_zone(body, "log", "\n".join(lines) or "_No sessions yet._")
    if new != body:
        write_text(path, render(meta, new))
    return len(lines)


# ---------- folders ----------
# A tag that enough topics share can become a folder: <tag>/ with a hub page <tag>/<tag>.md that
# lists the topics moved into it. A topic lives in one folder at most, and keeps all its tags.

def folder_hubs(root: Path) -> dict[str, tuple[Path, dict]]:
    out = {}
    for path in wiki_files(root):
        if path.parent != root and path.stem == path.parent.name:
            meta, _ = read_page(path)
            if meta.get("type") == "folder":
                out[path.stem] = (path, meta)
    return out


def suggest_folders(root: Path, minimum: int = 3) -> list[dict]:
    """Which tags could become folders, worked out from the topics' tags (no model involved):
    a tag at least `minimum` loose topics share, or loose topics carrying a tag that already has
    a folder. Each topic is offered to one folder only: an existing one first, then the largest."""
    hubs = folder_hubs(root)
    loose = [(p, m) for p, m in topic_pages(root) if p.parent == root]
    by_tag: dict[str, list[str]] = {}
    for path, meta in loose:
        for tag in clean_tags(meta.get("tags"), 20):
            by_tag.setdefault(tag, []).append(path.stem)
    order = sorted(by_tag, key=lambda t: (t not in hubs, -len(by_tag[t]), t))
    out, taken = [], set()
    for tag in order:
        topics = [s for s in by_tag[tag] if s not in taken]
        new = tag not in hubs
        if not topics or (new and len(topics) < minimum):
            continue
        if new and _blocked_folder(root, tag):
            continue
        taken.update(topics)
        title = str(hubs[tag][1].get("title") or tag) if not new else tag.replace("-", " ").capitalize()
        out.append({"tag": tag, "new": new, "title": title, "topics": topics})
    return out


def _blocked_folder(root: Path, tag: str) -> str:
    """Why this tag can't become a folder, or '' if it can."""
    if (root / tag).exists():
        return f"A folder called '{tag}' already exists and wasn't made by this tool."
    clash = _name_taken(root, tag)
    return f"{clash} already has the name '{tag}', which the folder's page would need." if clash else ""


def _new_hub(title: str, tag: str) -> str:
    return f"# {title}\n\nTopics tagged `{tag}`.\n\n## Topics\n\n## Notes\n"


def apply_folder(root: Path, tag: str, title: str, slugs: list[str], today: str) -> dict:
    """Turn a tag into a folder (if it isn't one yet) and move these topics into it."""
    tag = slugify(tag, 40)
    topics = {p.stem: (p, m) for p, m in topic_pages(root)}
    missing = [s for s in slugs if s not in topics]
    if missing:
        raise WikiError(f"No topic page for: {', '.join(missing)}")
    hubs = folder_hubs(root)
    created = tag not in hubs
    hub = root / tag / f"{tag}.md"
    if created:
        why = _blocked_folder(root, tag)
        if why:
            raise WikiError(why)
        title = title or tag.replace("-", " ").capitalize()
        meta = {"title": title, "type": "folder", "tags": [tag], "summary": f"Topics tagged {tag}.", "created": today, "updated": today}
        write_text(hub, render(meta, _new_hub(title, tag)))
    moved = []
    for s in slugs:
        path, meta = topics[s]
        target = hub.parent / path.name
        if path != target:
            if target.exists():
                raise WikiError(f"{target} already exists.")
            _, body = read_page(path)
            meta["folder"] = tag
            meta["tags"] = clean_tags([tag] + list(meta.get("tags") or []), 6)
            meta["changed"] = stamp()
            write_text(target, render(meta, body))
            path.unlink()
            moved.append(s)
    if moved:  # the hub lists different topics now
        hub_meta, hub_body = read_page(hub)
        hub_meta.update(updated=today, changed=stamp())
        write_text(hub, render(hub_meta, hub_body))
    write_index(root)
    return {"tag": tag, "created": created, "moved": moved, "hub": hub.relative_to(root).as_posix()}


def _refresh_hubs(root: Path, topics: list[tuple[Path, dict]]) -> None:
    """Each hub lists the topics in its folder, from their own frontmatter."""
    for hub, _ in folder_hubs(root).values():
        members = sorted(((p, m) for p, m in topics if p.parent == hub.parent), key=lambda pm: pm[0].stem)
        lines = [f"- [[{p.stem}]] — {' '.join(str(m.get('summary') or m.get('title') or p.stem).split())}" for p, m in members]
        text = hub.read_text(encoding="utf-8")
        new = set_zone(text, "members", "\n".join(lines) or "_No topics yet._")
        if new != text:
            meta, body = parse(new)
            meta["changed"] = stamp()
            write_text(hub, render(meta, body))


# ---------- merges ----------

def _replace_links(root: Path, old: str, new: str) -> None:
    """Every [[old]] in the wiki becomes [[new]], so nothing is left pointing at a page that's gone."""
    pattern = re.compile(r"\[\[" + re.escape(old) + r"(?=[\]|#])")
    for path in wiki_files(root):
        with open(path, encoding="utf-8", newline="") as f:  # line endings kept as they are
            text = f.read()
        changed = pattern.sub("[[" + new, text)
        if changed != text:
            temp = path.with_name(path.name + ".tmp")
            with open(temp, "w", encoding="utf-8", newline="") as f:
                f.write(changed)
            os.replace(temp, path)


def _own_notes(body: str) -> str:
    """What the person wrote under the page's Notes heading."""
    try:
        return get_zone(body, "notes").strip()
    except WikiError:
        return ""


def merge_topics(root: Path, keep: str, merge: list[str]) -> dict:
    """Fold topics into one: their sessions, tags, tasks and your notes move to `keep`, every link
    to them is repointed, and their pages are removed. `keep` is then due for a review."""
    topics = {p.stem: p for p, _ in topic_pages(root)}
    merge = [m for m in dict.fromkeys(merge) if m != keep]
    missing = [s for s in [keep, *merge] if s not in topics]
    if missing:
        raise WikiError(f"No topic page for: {', '.join(missing)}")
    if not merge:
        raise WikiError("Nothing to merge.")
    keep_meta, keep_body = read_page(topics[keep])
    before = len(_log_lines(keep_body))
    tags = list(keep_meta.get("tags") or [])
    carried, legacy = [], []
    for old in merge:
        meta, body = read_page(topics[old])
        legacy += _log_lines(body)
        tags += list(meta.get("tags") or [])
        notes = _own_notes(body)
        if notes:
            carried.append(f"From {meta.get('title') or old}:\n\n{notes}")
    if carried:  # your own notes on the merged pages are kept, at the end of this page's Notes
        keep_body = set_zone(keep_body, "notes", "\n\n".join([_own_notes(keep_body), *carried]).strip())
    keep_meta["tags"] = clean_tags(tags, 6)
    keep_meta["needs_review"], keep_meta["review_reason"] = True, "merged"
    keep_meta["changed"] = stamp()
    write_text(topics[keep], render(keep_meta, _clean(keep_body)))
    for old in merge:
        topics[old].unlink()
        _replace_links(root, old, keep)
    for path, meta, body in session_notes(root):  # session notes name their topics in frontmatter too
        listed = list(meta.get("topics") or [])
        if not any(t in merge for t in listed) and listed.count(keep) <= 1:
            continue
        meta["topics"] = list(dict.fromkeys(keep if t in merge else t for t in listed))
        entries = {}
        for slug, text in note_entries(meta).items():
            entries.setdefault(keep if slug in merge else slug, text)
        if entries:
            meta["entries"] = [f"{slug}: {text}" for slug, text in entries.items()]
        body = re.sub(r"^Topics: \[\[.*$", "Topics: " + " · ".join(f"[[{t}]]" for t in meta["topics"]), body, count=1, flags=re.M)
        write_text(path, render(meta, body))
    after = rebuild_log(root, keep, legacy)
    keep_meta, keep_body = read_page(topics[keep])
    keep_meta["entries_since_review"] = int(keep_meta.get("entries_since_review") or 0) + max(0, after - before)
    write_text(topics[keep], render(keep_meta, keep_body))
    write_index(root)
    return {"kind": "topic", "keep": keep, "merged": merge, "path": topics[keep].relative_to(root).as_posix()}


def merge_tags(root: Path, keep: str, merge: list[str]) -> dict:
    """Replace tags with one: on every topic and session note, and a folder is renamed to match.
    A reference tag (the read-only reference tag list) can be kept but never merged away. The
    person's own tags file loses the merged tags' lines; the reference list is never written."""
    from . import tags as taglists
    keep = slugify(keep, 40)
    merge = [m for m in dict.fromkeys(slugify(m, 40) for m in merge) if m != keep]
    if not merge:
        raise WikiError("Nothing to merge.")
    tagset = taglists.TagSet(root)
    fixed = [m for m in merge if tagset.is_reference(m)]
    if fixed:
        raise WikiError(f"{', '.join(fixed)} {'is' if len(fixed) == 1 else 'are'} in the reference tag list, which can't be changed here.")
    hubs = folder_hubs(root)
    with_folder = [m for m in merge if m in hubs]
    if with_folder and (keep in hubs or len(with_folder) > 1):
        raise WikiError(f"{', '.join(with_folder)} and {keep} can't be merged automatically: more than one of them is a folder.")
    if with_folder and _blocked_folder(root, keep):
        raise WikiError(_blocked_folder(root, keep))
    pages = 0
    for path in wiki_files(root):
        meta, body = read_page(path)
        listed = meta.get("tags")
        if meta.get("type") not in ("topic", "folder", "session"):  # only pages this tool wrote
            continue
        if not isinstance(listed, list) or not any(t in merge for t in listed):
            continue
        meta["tags"] = list(dict.fromkeys(keep if t in merge else t for t in listed))
        if meta.get("folder") in merge:
            meta["folder"] = keep
        if meta.get("type") in ("topic", "folder"):
            meta["changed"] = stamp()
        write_text(path, render(meta, body))
        pages += 1
    if with_folder:
        old = with_folder[0]
        (root / old / f"{old}.md").rename(root / old / f"{keep}.md")
        (root / old).rename(root / keep)
        _replace_links(root, old, keep)
        hub = root / keep / f"{keep}.md"  # the folder's page says the new tag
        meta, body = read_page(hub)
        title = keep.replace("-", " ").capitalize()
        body = body.replace(f"# {meta.get('title')}\n", f"# {title}\n", 1).replace(f"Topics tagged `{old}`.", f"Topics tagged `{keep}`.", 1)
        meta.update(title=title, tags=[keep], summary=f"Topics tagged {keep}.", changed=stamp())
        write_text(hub, render(meta, body))
    write_index(root)
    listed = taglists.merge_personal(root, keep, merge)
    return {"kind": "tag", "keep": keep, "merged": merge, "pages": pages, "personal_tags_changed": listed}


# ---------- index ----------

def _own_index(root: Path) -> Path:
    """index.md, once it's certain that writing it won't replace a page someone wrote."""
    path = root / "index.md"
    if path.exists() and INDEX_MARK not in path.read_text(encoding="utf-8", errors="replace"):
        raise WikiError(f"{path} already exists and wasn't made by this tool. Rename it, then try again.")
    return path


def write_index(root: Path) -> None:
    """One line per topic, grouped by folder, most recently updated first."""
    _own_index(root)
    topics = topic_pages(root)
    for path, _ in topics:  # pages from an earlier version lose their marker comments
        text = path.read_text(encoding="utf-8")
        if _clean(text) != text:
            write_text(path, _clean(text))
    _refresh_hubs(root, topics)
    hubs = folder_hubs(root)

    def line(path, meta):
        summary = " ".join(str(meta.get("summary") or meta.get("title") or path.stem).split())
        tags = " ".join(f"#{t}" for t in clean_tags(meta.get("tags"), 20))
        return f"- [[{path.stem}]] — {summary}{' · ' + tags if tags else ''} · updated {meta.get('updated') or ''}"

    def newest_first(rows):
        return sorted(rows, key=lambda pm: (str(pm[1].get("updated") or ""), pm[0].stem), reverse=True)

    lines = ["# Index", "", f"One line per topic, grouped by folder, most recently updated first. {INDEX_MARK}", ""]
    for tag in sorted(hubs):
        members = [(p, m) for p, m in topics if p.parent == hubs[tag][0].parent]
        lines += [f"## Folder: [[{tag}]]", *[line(p, m) for p, m in newest_first(members)], ""]
    loose = [(p, m) for p, m in topics if not any(p.parent == h[0].parent for h in hubs.values())]
    if loose or not hubs:
        lines += ["## Not in a folder" if hubs else "## Topics", *[line(p, m) for p, m in newest_first(loose)], ""]
    write_text(root / "index.md", "\n".join(lines))


def index_text(root: Path) -> str:
    """The index as an agent is shown it: the folder headings and the topic lines."""
    path = root / "index.md"
    if not path.exists():
        return ""
    return "\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith(("- [[", "## ")))


def tags_text(root: Path) -> str:
    """The tags in use, most used first, as an agent is shown them."""
    counts = all_tags(root)
    return "\n".join(f"- {t} ({n} topic{'s' if n != 1 else ''})" for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


# ---------- to-dos ----------
# The AI never touches tasks. A checkbox line ("- [ ] ...", "* [x] ...", "1. [/] ...") stays only
# where the person wrote it: no capture or review writes one onto a topic page or into a record.
# Task lines already in records from earlier versions are left as they are.

TASK_LINE = re.compile(r"^(\s*)(?:[-*+]\s+|\d+[.)]\s+)?\[[ xX/-]\](?:\s|$)")


def is_task_text(text: str) -> bool:
    """True for a checkbox line, or an item that would render as one once written as "- item"."""
    return bool(TASK_LINE.match(str(text or "").strip()))


def strip_task_lines(text: str) -> str:
    """The text without its checkbox lines."""
    return "\n".join(ln for ln in str(text or "").split("\n") if not TASK_LINE.match(ln)).strip()


def _old_tasks_section(path: Path) -> str:
    """The Tasks section of a record written by an earlier version, word for word (its lines may
    have been ticked by hand since), so a re-capture never loses it. "" when there is none."""
    if not path.exists():
        return ""
    _, body = read_page(path)
    m = re.search(r"^## Tasks[ \t]*\n(.*?)(?=^#{1,2} |\Z)", body, re.S | re.M)
    return f"## Tasks\n{m.group(1).strip()}\n\n" if m and m.group(1).strip() else ""


# ---------- session notes ----------

def _section(title: str, lines: list[str]) -> str:
    return f"## {title}\n" + "\n".join(lines) + "\n\n" if lines else ""


def write_session_note(root: Path, rel_path: str, info: dict, data: dict, tags: list[str], ingested_at: str) -> None:
    """tags: the tags of the note's topics, so the note shows under the same tags. No to-do is
    ever written: a checkbox line in any part of the model's reply is left out."""
    slugs = [t["slug"] for t in data["topics"]]
    keep_tasks = _old_tasks_section(root / rel_path)
    origin = "note" if info.get("source") == "note" else "session"
    meta = {
        "title": data["title"],
        "type": "session",
        "origin": origin,   # where it came from: one of the person's notes, or a session
        "date": info["date"],
        "session_id": info["session_id"],
        "source": info["source"],
        "project": info.get("project", ""),
        "topics": slugs,
        "tags": tags,
        # This record's line in each topic's log; the logs are rebuilt from these.
        "entries": [f"{t['slug']}: {t['entry']}" for t in data["topics"]],
        "ingested": ingested_at,
    }
    if info.get("capture_id"):
        meta["capture_id"] = info["capture_id"]
    body = f"# {data['title']}\n\n"
    if origin == "note":
        body += f"From your note: [[{info.get('note_name') or info.get('project')}]]\n\n"
    if slugs:
        body += "Topics: " + " · ".join(f"[[{s}]]" for s in slugs) + "\n\n"
    body += f"## Summary\n{strip_task_lines(data['summary'])}\n\n"
    body += _section("Decisions", [
        f"- **{d['decision']}**" + (f" — {d['why']}" if d["why"] else "") for d in data["decisions"] if not is_task_text(d["decision"])
    ])
    body += _section("Findings", [f"- {x}" for x in data["findings"] if not is_task_text(x)])
    body += _section("Data findings", [f"- **{d['subject']}** — {d['finding']}" for d in data["data_findings"]])
    body += _section("Open questions", [f"- {x}" for x in data["open_questions"] if not is_task_text(x)])
    body += keep_tasks
    write_text(root / rel_path, render(meta, body))


def session_notes(root: Path) -> list[tuple[Path, dict, str]]:
    folder = root / SESSIONS_DIR
    out = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        meta, body = read_page(path)
        if meta.get("type") == "session":
            out.append((path, meta, body))
    return out


def session_notes_for(root: Path, slug: str) -> list[tuple[dict, str]]:
    """Session notes about this topic, oldest first."""
    return [(meta, body) for _, meta, body in records_for(root, slug)]


def records_for(root: Path, slug: str) -> list[tuple[Path, dict, str]]:
    """The records (captured sessions and notes) about this topic, oldest first."""
    out = [(p, meta, body) for p, meta, body in session_notes(root) if slug in (meta.get("topics") or [])]
    out.sort(key=lambda pmb: str(pmb[1].get("date") or ""))
    return out


# ---------- promotion queue ----------

def _queue_page() -> str:
    return (
        "# Promotion queue\n\n"
        "Findings about tables and subject areas, captured from sessions and waiting to be promoted to the team wiki. "
        "A line is ticked once it has been promoted (WikiApp's Promotion tab does this).\n\n"
        "## Findings\n"
    )


def update_queue(root: Path, date: str, note_stem: str, findings: list[dict]) -> int:
    path = root / "promotion-queue.md"
    text = path.read_text(encoding="utf-8") if path.exists() else _queue_page()
    link = f"[[{note_stem}]]"
    lines = [ln for ln in get_zone(text, "queue").splitlines() if ln.strip()]
    # Keep lines already promoted; replace this session's pending ones.
    lines = [ln for ln in lines if not (link in ln and ln.startswith("- [ ]"))]
    done = "\n".join(ln for ln in lines if link in ln)
    added = 0
    for f in findings:
        item = f"**{f['subject']}** — {f['finding']}"
        if item in done:
            continue
        lines.append(f"- [ ] {date} · {item} ({link})")
        added += 1
    write_text(path, set_zone(text, "queue", "\n".join(lines)))
    return added


# ---------- setup and team index ----------

def init_personal(root: Path, template: str) -> list[str]:
    """Set up: the personal wiki's pages, where missing. -> exactly what was created, in the wiki,
    in this order: "WIKI.md" (on the command line on its own only), "Sessions/" (the records'
    folder), "promotion-queue.md", "index.md". In WikiApp the wiki's role makes it personal, so no WIKI.md is made
    (an existing one is left alone); a team or view-only wiki is refused before anything is written."""
    created = []
    by_role = _personal_by_role(root)
    cfg_file = root / "WIKI.md"
    if not by_role:
        if cfg_file.exists():
            require_personal(root)   # the command line on its own: WIKI.md must say type: personal
        else:
            write_text(cfg_file, template)
            created.append("WIKI.md")
    if not (root / SESSIONS_DIR).is_dir():
        (root / SESSIONS_DIR).mkdir(parents=True, exist_ok=True)
        created.append(SESSIONS_DIR + "/")
    state_dir(root)
    had_index = (root / "index.md").exists()
    if not (root / "promotion-queue.md").exists():
        write_text(root / "promotion-queue.md", _queue_page())
        created.append("promotion-queue.md")
    write_index(root)
    if not had_index:
        created.append("index.md")
    return created


def write_team_index(root: Path) -> int:
    """Regenerate the team wiki's index.md from page frontmatter, grouped by type."""
    _own_index(root)
    groups: dict[str, list[str]] = {}
    count = 0
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or rel.parts[0] in ("sources", "Templates"):
            continue
        if rel.as_posix() in ("index.md", "WIKI.md", "wiki_rules.md"):
            continue
        meta, _ = read_page(path)
        kind = str(meta.get("type") or "untyped")
        summary = " ".join(str(meta.get("summary") or meta.get("description") or meta.get("title") or "").split())
        line = f"- [[{path.stem}]]" + (f" — {summary}" if summary else "") + f" · `{rel.as_posix()}`"
        groups.setdefault(kind, []).append(line)
        count += 1
    lines = ["# Index", "", f"One line per page, grouped by type, from `sb.py reindex --wiki team`. {INDEX_MARK}", ""]
    for kind in sorted(groups):
        lines += [f"## {kind}", *groups[kind], ""]
    write_text(root / "index.md", "\n".join(lines))
    return count


# ---------- upgrade from the first layout ----------

def upgrade_layout(root: Path) -> list[str]:
    """The first version kept a page per tag in tags/ (grouped into areas) and session notes in
    session-notes/<year>/. Those pages become topics at the top of the wiki and notes in Sessions/;
    an area becomes a tag on its topics. Only pages this tool wrote are moved (by their `type`),
    nothing is overwritten, and once there is nothing left to move it does nothing. -> what was moved."""
    old_tags, old_notes = root / "tags", root / "session-notes"

    def ours(folder: Path, types: tuple) -> list[tuple[Path, dict, str]]:
        found = []
        for path in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
            meta, body = read_page(path)
            if meta.get("type") in types:
                found.append((path, meta, body))
        return found

    if not ours(old_tags, ("tag", "area")) and not ours(old_notes, ("session",)):
        return []
    moved = []
    with Lock(root):
        for path, meta, body in ours(old_tags, ("tag", "area")):
            if meta.get("type") == "area":
                # An area was only a list of its tags. Its own notes, if any, are kept as a page.
                notes = _own_notes(body)
                target = root / f"{path.stem}-notes.md"
                if notes and not target.exists():
                    write_text(target, f"# {meta.get('title') or path.stem}: notes\n\n{notes}\n")
                    moved.append(target.name)
                if not notes or target.exists():
                    path.unlink()
                continue
            target = root / path.name
            if target.exists():
                continue
            meta["type"] = "topic"
            meta["tags"] = clean_tags([meta.get("area")] if meta.get("area") else [])
            meta["folder"] = ""
            meta.pop("area", None)
            meta.setdefault("review_reason", "")
            meta["changed"] = stamp()
            write_text(target, render(meta, body))
            path.unlink()
            moved.append(target.name)
        renamed = {}
        for path, meta, body in ours(old_notes, ("session",)):
            target = root / SESSIONS_DIR / path.name
            if target.exists():
                continue
            meta["topics"] = list(meta.get("tags") or [])
            meta["tags"] = []
            body = body.replace("\nTags: [[", "\nTopics: [[", 1)
            write_text(target, render(meta, body))
            old_rel = path.relative_to(root).as_posix()
            renamed[old_rel] = target.relative_to(root).as_posix()
            path.unlink()
            moved.append(renamed[old_rel])
        if renamed and (state_dir(root) / "ledger.json").exists():
            ledger = load_ledger(root)
            for entry in ledger.values():
                if entry.get("note") in renamed:
                    entry["note"] = renamed[entry["note"]]
            save_ledger(root, ledger)
        for folder in (old_tags, old_notes):  # removed only once empty
            for sub in sorted((d for d in folder.rglob("*") if d.is_dir()), reverse=True) if folder.is_dir() else []:
                if not any(sub.iterdir()):
                    sub.rmdir()
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        if moved:
            write_index(root)
    return moved
