"""Every file and folder WikiApp uses, in one list. Every path in the app comes from here.

WikiApp keeps everything private to one person in one folder named `.wiki`, at a place the
person chooses on the first start (the app's own project folder, the one holding WikiApp.cmd,
is suggested; .gitignore keeps it out of git). The only thing kept in a fixed place is a
one-line pointer file that records where that folder is:

    ~/.wikiapp-location            (WIKIAPP_POINTER_FILE overrides where it is, for tests)

WIKIAPP_DATA_DIR, when set, is the `.wiki` folder itself and the pointer is not read.

Each entry in the list has a name ("settings", "prompt.wiki-reviewer", "wiki.team.rules"...), a
path, a kind, a group and a state ("ok", "missing", "not_created", "unset": see STATES). Most
entries can be pointed somewhere else (an override, kept in the folder's paths.json); by default
they derive from the `.wiki` folder. Entries:

    app folder      app_folder, pointer_file, path_list
    app data        settings, window_placement, instance, engine_settings, pending_promotion,
                    run_history, indexes, progress, prompts, templates, starters
    your own files  personal_capture_rules (USER_FILES below): free-text rules for capture in the
                    personal wiki. A starter is copied in once if missing; never updated,
                    overwritten or reset; no status. personal_tags (the person's own tags, a page
                    in the personal wiki, made by the sessions tool when the first one is added).
    prompt slots    prompt.<...> and template.<...> (SLOTS below): a text file the app ships a
                    default for. The default is copied into the folder only where the file is
                    missing. Each slot has a status: "default" (an unedited copy, which follows
                    the app's newer defaults by itself), "customised", or
                    "customised_newer_default" (edited, and the app now ships a different
                    default). reset_prompt() puts the shipped default back.
    each wiki       wiki.<alias>.rules, wiki.<alias>.templates, wiki.<alias>.index,
                    wiki.<alias>.progress
    outside         notes_folder, transcripts, agentlib, sessions_config, tag_list_reference (unset
                    by default; any tags file, read only: the app never writes it)

Nothing here creates a folder the person didn't ask for: with no pointer file, nothing is
written at all, and a configured path that is gone is reported (exists = False), never made
again. Files are only ever created inside the `.wiki` folder, or where the person saves one.

Standard library only, Python 3.10+: setup.py, the ingest run and sessions/sb.py import it too.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import threading
from pathlib import Path

APP_FILES = Path(__file__).resolve().parent.parent   # the app's own files (code and shipped defaults)
FOLDER_NAME = ".wiki"
POINTER_NAME = ".wikiapp-location"
PATHS_FILE = "paths.json"                             # in the .wiki folder: overrides and slot records
STATUSES = ("default", "customised", "customised_newer_default")
_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.S)
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w-]*)\s*\}\}")
_lock = threading.Lock()


class PathMissing(Exception):
    """A path the app needs isn't there (or no folder has been chosen yet)."""


# ---- The .wiki folder and its pointer -----------------------------------------------------------

def pointer_file() -> Path:
    return Path(os.environ.get("WIKIAPP_POINTER_FILE") or Path.home() / POINTER_NAME)


def from_env() -> bool:
    """True when WIKIAPP_DATA_DIR decides the folder (developer and test runs)."""
    return bool(os.environ.get("WIKIAPP_DATA_DIR"))


def app_folder() -> Path | None:
    """The .wiki folder, or None when none has been chosen yet. It may no longer exist."""
    env = os.environ.get("WIKIAPP_DATA_DIR")
    if env:
        return Path(env)
    try:
        lines = pointer_file().read_text(encoding="utf-8-sig").strip().splitlines()
    except OSError:
        return None
    return Path(_expand(lines[0])) if lines and lines[0].strip() else None


def is_chosen() -> bool:
    return app_folder() is not None


def suggested_folder() -> Path:
    """The app's own project folder (the one holding WikiApp.cmd): .wiki there is git-ignored."""
    return APP_FILES.parent / FOLDER_NAME


def folder_for(chosen: str | os.PathLike) -> Path:
    """The .wiki folder for a place the person picked: the folder itself if it is named .wiki,
    otherwise a .wiki folder inside it (a folder picker can't easily make or pick a dot folder)."""
    path = Path(_expand(str(chosen)))
    if not path.is_absolute():
        raise ValueError(f"Not a full path: {chosen}")
    return path if path.name.lower() == FOLDER_NAME else path / FOLDER_NAME


def require_app_folder() -> Path:
    """The .wiki folder, or a clear error when there is none to write to."""
    folder = app_folder()
    if folder is None:
        raise PathMissing("Choose where WikiApp keeps its private folder first.")
    if not folder.is_dir():
        raise PathMissing(f"WikiApp's private folder is missing: {folder}. Restore it, or choose another place.")
    return folder


def ensure_parent(path: str | os.PathLike) -> None:
    """Makes sure a file's folder exists before it is written. Folders are only ever made inside
    the .wiki folder; anywhere else a missing folder is an error, never made again."""
    parent = Path(path).parent
    if parent.is_dir():
        return
    folder = app_folder()
    if folder is not None and folder.is_dir() and _inside(parent, folder):
        parent.mkdir(parents=True, exist_ok=True)
        return
    if folder is None:
        raise PathMissing("Choose where WikiApp keeps its private folder first.")
    raise PathMissing(f"The folder {parent} doesn't exist any more. Restore it, or point this entry somewhere else.")


# ---- The entries --------------------------------------------------------------------------------
# App data: (name, label, kind, path inside the .wiki folder, can be pointed elsewhere).

APP_DATA = [
    ("settings", "Settings (open folders, colours, last view...)", "file", "settings.json", True),
    ("window_placement", "Window size and position", "file", "window.txt", True),
    ("instance", "Running copy (while the app is open)", "file", "instance.json", False),
    ("engine_settings", "Engine settings", "file", "engine.json", True),
    ("pending_promotion", "Promotion tab: cards waiting for review", "file", "ingest/pending-promotion.json", True),
    ("run_history", "Past ingest runs", "folder", "ingest-runs", True),
    ("indexes", "Wiki indexes (one per wiki, rebuilt on each run)", "folder", "indexes", True),
    ("progress", "Progress (session capture ledger and spend, per wiki)", "folder", "progress", True),
    ("prompts", "Prompts folder", "folder", "prompts", True),
    ("templates", "Private templates (for wikis without a Templates folder)", "folder", "templates", True),
    ("starters", "Starters for new files", "folder", "starters", True),
]
_APP_DATA = {row[0]: row for row in APP_DATA}

# Prompt slots: (name, label, kind, group, parent entry, file inside it, shipped default in App Files).
SLOTS = [
    ("prompt.executive-assistant", "Executive assistant (Sessions tab)", "prompt", "Prompts", "prompts", "executive-assistant.md", "agents/executive-assistant/SKILL.md"),
    ("prompt.wiki-reviewer", "Wiki reviewer (Review tab)", "prompt", "Prompts", "prompts", "wiki-reviewer.md", "agents/wiki-reviewer/SKILL.md"),
    ("prompt.team-wiki-manager", "Team wiki manager (Promotion tab)", "prompt", "Prompts", "prompts", "team-wiki-manager.md", "agents/team-wiki-manager/SKILL.md"),
    ("prompt.promotion-first-message", "Promotion run: first message", "prompt", "Prompts", "prompts", "promotion-first-message.md", "agents/messages/promotion-first-message.md"),
    ("prompt.ingest-feedback", "Promotion: feedback message", "prompt", "Prompts", "prompts", "ingest-feedback.md", "agents/messages/ingest-feedback.md"),
    ("prompt.ingest-answers", "Promotion: answers message", "prompt", "Prompts", "prompts", "ingest-answers.md", "agents/messages/ingest-answers.md"),
    ("prompt.wikis-section", "Promotion: the Wikis section","prompt", "Prompts", "prompts", "wikis-section.md", "agents/messages/wikis-section.md"),
    ("prompt.sessions-capture", "Sessions: capture request", "prompt", "Prompts", "prompts", "sessions-capture.md", "agents/messages/sessions-capture.md"),
    ("prompt.sessions-notes-capture", "Notes: capture request (a note into the personal wiki)", "prompt", "Prompts", "prompts", "sessions-notes-capture.md", "agents/messages/sessions-notes-capture.md"),
    ("prompt.sessions-review", "Review: topic review request", "prompt", "Prompts", "prompts", "sessions-review.md", "agents/messages/sessions-review.md"),
    ("prompt.sessions-merges", "Review: merge suggestions request", "prompt", "Prompts", "prompts", "sessions-merges.md", "agents/messages/sessions-merges.md"),
    ("template.daily", "Daily note", "template", "Templates", "templates", "Notes/Daily.md", "app/templates/Notes/Daily.md"),
    ("template.weekly", "Weekly note", "template", "Templates", "templates", "Notes/Weekly.md", "app/templates/Notes/Weekly.md"),
    ("template.sample-note", "Sample note template", "template", "Templates", "templates", "Notes/Sample note.md", "app/templates/Notes/Sample note.md"),
    ("template.sample-page", "Sample page template", "template", "Templates", "templates", "Pages/Sample page.md", "app/templates/Pages/Sample page.md"),
    ("template.page-starter", "Starter for a new page template", "template", "Templates", "starters", "page-template.md", "app/templates/starters/page-template.md"),
    ("template.rules-starter", "Starter for a wiki's rules", "template", "Templates", "starters", "wiki-rules.md", "app/templates/starters/wiki-rules.md"),
    ("template.personal-wiki", "Personal wiki marker (WIKI.md)", "template", "Templates", "starters", "personal-WIKI.md", "sessions/templates/personal-WIKI.md"),
    ("template.team-rules", "Starter for a team wiki's rules", "template", "Templates", "starters", "team-wiki_rules.md", "sessions/templates/team-wiki_rules.md"),
]
_SLOTS = {row[0]: row for row in SLOTS}

# The person's own files: (name, label, kind, group, parent entry, file inside it, starter in App Files).
# Not defaults: the starter is copied in once, only where the file is missing, and never updated,
# overwritten or reset. No status. read_prompt() gives the text without <!-- comments -->.
USER_FILES = [
    ("personal_capture_rules", "My capture rules (personal wiki: what to pick out, what gets its own page)",
     "user_prompt", "Prompts", "prompts", "personal-capture-rules.md", "agents/messages/personal-capture-rules.md"),
    # Your own tags, a normal page in the personal wiki (parent "personal_wiki": the folder picked
    # in the Sessions tab). Never made up front: sync_slots never writes it (it is outside the
    # .wiki folder), and sessions/secondbrain/tags.py makes it the first time a new tag is added.
    ("personal_tags", "My tags (personal wiki: tags of my own, beyond the reference list, with what each means)",
     "user_prompt", "Prompts", "personal_wiki", "personal-tags.md", "agents/messages/sessions-personal-tags.md"),
]
_USER = {row[0]: row for row in USER_FILES}
_COMMENT = re.compile(r"<!--.*?-->", re.S)

AGENT_SLOTS = {"prompt.executive-assistant": "executive-assistant",
               "prompt.wiki-reviewer": "wiki-reviewer", "prompt.team-wiki-manager": "team-wiki-manager"}
# The notes flow's old note taker (retired: notes are captured by the sessions pipeline now).
# Its old files are neither copied forward nor listed; an old skill copy shows up as a leftover.
RETIRED_AGENTS = ["note-taker"]

# Outside the .wiki folder: (name, label, kind).
OUTSIDE = [
    ("notes_folder", "Notes folder (inside each wiki)", "relative_folder"),
    ("transcripts", "Claude Code transcripts", "folder"),
    ("agentlib", "agentlib library (the AI features need it)", "library"),
    ("sessions_config", "Sessions command line: config.json", "file"),
    # Unset by default. Any existing tags file (typically a team wiki's tag list), in whatever
    # format the team uses. Read only: the app never writes it (write_file refuses its kind).
    ("tag_list_reference", "Reference tag list (read only; for example your team's tag list)", "reference_file"),
]
_OUTSIDE = {row[0]: row for row in OUTSIDE}

# Optional entries with no default: "clear" empties them (instead of "back to default").
OPTIONAL = {"tag_list_reference"}

# Entries the app (or the sessions tool) makes the first time it needs them; until then their
# state is "not_created", not "missing". Each wiki's index and progress folder are too.
CREATED_ON_USE = {"settings", "window_placement", "instance", "engine_settings", "pending_promotion", "run_history",
                  "indexes", "progress", "path_list", "personal_tags", "notes_folder", "sessions_config"}

# A row's state in the Paths window:
#   ok           it is there
#   missing      a path that should exist and doesn't (a configured path that has gone)
#   not_created  the app makes it the first time it's needed
#   unset        an optional entry with no value (or nothing chosen yet to derive it from)
STATES = ("ok", "missing", "not_created", "unset")

WIKI_PARTS = {
    "rules": ("Rules file", "file"),
    "templates": ("Templates folder", "folder"),
    "index": ("Index (rebuilt on each ingest run)", "file"),
    "progress": ("Progress folder", "folder"),
}
_WIKI_NAME = re.compile(r"\Awiki\.(.+)\.(rules|templates|index|progress)\Z")


# ---- The folder's own record (paths.json) -------------------------------------------------------

def _record_file(folder: Path | None) -> Path | None:
    return folder / PATHS_FILE if folder else None


def load_record(folder: Path | None = None) -> dict:
    """{"overrides": {name: path}, "slots": {name: {"base", "override_base", "seeded"}}}"""
    folder = folder if folder is not None else app_folder()
    record = {}
    file = _record_file(folder)
    if file is not None:
        try:
            record = json.loads(file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            record = {}
    if not isinstance(record, dict):
        record = {}
    record.setdefault("version", 1)
    record["overrides"] = record.get("overrides") if isinstance(record.get("overrides"), dict) else {}
    record["slots"] = record.get("slots") if isinstance(record.get("slots"), dict) else {}
    return record


def save_record(record: dict, folder: Path | None = None) -> None:
    folder = folder if folder is not None else require_app_folder()
    if not folder.is_dir():
        raise PathMissing(f"WikiApp's private folder is missing: {folder}")
    write_text_atomic(folder / PATHS_FILE, json.dumps(record, indent=1, ensure_ascii=False) + "\n")


# ---- Working out a path -------------------------------------------------------------------------

class Resolver:
    """Paths for one .wiki folder (the chosen one, or one being previewed) and one workspace."""

    def __init__(self, folder: Path | None = None, record: dict | None = None, workspace: list | None = None,
                 use_env: bool = True):
        self.folder = folder if folder is not None else app_folder()
        self.record = record if record is not None else load_record(self.folder)
        self._workspace = workspace
        self.use_env = use_env

    @property
    def workspace(self) -> list[dict]:
        if self._workspace is None:
            self._workspace = read_workspace(self.folder)
        return self._workspace

    def override(self, name: str) -> Path | None:
        value = self.record["overrides"].get(name)
        if not value:
            return None
        return Path(value) if name == "notes_folder" else Path(_expand(value))

    def legacy(self, name: str) -> Path | None:
        """WIKIAPP_SKILLS_DIR: the old test override for the agents' prompt files, kept so older
        tests still run. Its <agent>/SKILL.md files win; a missing one reads the shipped default."""
        skills = os.environ.get("WIKIAPP_SKILLS_DIR") if self.use_env else None
        if skills and name in AGENT_SLOTS:
            return Path(skills) / AGENT_SLOTS[name] / "SKILL.md"
        return None

    def default(self, name: str) -> Path | None:
        if name == "app_folder":
            return self.folder
        if name == "pointer_file":
            return pointer_file()
        if name == "path_list":
            return _record_file(self.folder)
        if name in _APP_DATA:
            return self.folder / _APP_DATA[name][3] if self.folder else None
        if name == "personal_wiki":
            return self.personal_root()
        if name == "tag_list_reference":
            return None   # unset until the person points it at a file
        if name in _SLOTS or name in _USER:
            row = _SLOTS.get(name) or _USER[name]
            parent = self.path(row[4])
            return parent / row[5] if parent else None
        if name == "transcripts":
            return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
        if name == "agentlib":
            found = find_agentlib()
            return found[0] if len(found) == 1 else None
        if name == "sessions_config":
            env = os.environ.get("SECOND_BRAIN_CONFIG")
            return Path(_expand(env)) if env else APP_FILES / "sessions" / "config.json"
        if name == "notes_folder":
            return Path(self.notes_folder_default())
        match = _WIKI_NAME.match(name)
        if match:
            alias, part = match.groups()
            root = self.wiki_root(alias)
            return self.wiki_default(alias, root, part)
        raise ValueError(f"Unknown path: {name}")

    def wiki_default(self, alias: str, root: Path | None, part: str) -> Path | None:
        if part == "rules":
            return root / "wiki_rules.md" if root else None
        if part == "templates":
            if root is not None and (root / "Templates").is_dir():
                return root / "Templates"   # a wiki with its own Templates folder keeps using it
            return self.path("templates")
        folder = self.path("indexes" if part == "index" else "progress")
        if folder is None:
            return None
        return folder / (safe_name(alias) + (".md" if part == "index" else ""))

    def path(self, name: str) -> Path | None:
        return self.legacy(name) or self.override(name) or self.default(name)

    def wiki_root(self, alias: str) -> Path | None:
        for wiki in self.workspace:
            if wiki.get("alias") == alias:
                return Path(wiki["root"])
        return None

    def notes_folder_default(self) -> str:
        """The page's own setting (notesDir in settings.json) until the list overrides it."""
        settings = read_settings(self.folder)
        return clean_relative(settings.get("notesDir") or "") or "Notes"

    def is_overridden(self, name: str) -> bool:
        return bool(self.record["overrides"].get(name))

    def personal_root(self) -> Path | None:
        """The personal wiki's folder: the workspace folder picked in the Sessions tab (the
        sessionsWiki setting), else the one with the alias "personal"."""
        alias = read_settings(self.folder).get("sessionsWiki")
        found = next((w for w in self.workspace if isinstance(alias, str) and w["alias"] == alias), None) \
            or next((w for w in self.workspace if w["alias"].lower() == "personal"), None)
        return Path(found["root"]) if found else None


def path(name: str) -> Path | None:
    """The path of one entry right now, or None when it can't be known (no folder chosen yet,
    agentlib not found...). For a wiki's entries use wiki_paths() instead."""
    return Resolver().path(name)


def wiki_paths(alias: str, root: str | os.PathLike | None = None) -> dict[str, Path | None]:
    """One wiki's rules file, templates folder, index file and progress folder.
    root: the wiki's folder (needed when the wiki isn't in the saved workspace, e.g. sb.py)."""
    resolver = Resolver()
    root = Path(root) if root else resolver.wiki_root(alias)
    out = {}
    for part in WIKI_PARTS:
        name = f"wiki.{alias}.{part}"
        out[part] = resolver.legacy(name) or resolver.override(name) or resolver.wiki_default(alias, root, part)
    return out


def alias_for_root(root: str | os.PathLike) -> str:
    """The alias a wiki folder has in the saved workspace, or its folder name when it isn't there."""
    want = _norm_path(Path(root))
    for wiki in read_workspace(app_folder()):
        if _norm_path(Path(wiki["root"])) == want:
            return wiki["alias"]
    return Path(root).name or "wiki"


def personal_tags_path(root: str | os.PathLike) -> Path:
    """The personal tags file for the personal wiki at root: the personal_tags entry if it was
    pointed somewhere else, otherwise personal-tags.md at the top of that wiki. It may not exist yet."""
    return Resolver().override("personal_tags") or Path(root) / _USER["personal_tags"][5]


def reference_tags_path() -> Path | None:
    """The reference tag list (tag_list_reference), or None when it isn't set. Read only."""
    return Resolver().override("tag_list_reference")


def progress_dir(root: str | os.PathLike, alias: str | None = None) -> Path:
    """Where the sessions tool keeps one personal wiki's progress (what used to be <wiki>/.sb:
    ledger.json, spend.json, the lock, the model's work folder). Raises PathMissing when there is
    no .wiki folder to keep it in."""
    require_app_folder()
    found = wiki_paths(alias or alias_for_root(root), root)["progress"]
    if found is None:
        raise PathMissing("No progress folder is set.")
    return found


# ---- The list, for the app's Paths window -------------------------------------------------------

def list_paths(workspace: list | None = None) -> list[dict]:
    """Every entry: {name, label, path, exists, kind, group, status, default, state, can_reset,
    can_change, can_clear, overridden}. status is only set for prompt and template slots; state
    is one of STATES; can_clear is true for an optional entry (no default) that has a value."""
    resolver = Resolver(workspace=workspace)
    out = [_entry(resolver, "app_folder", "WikiApp's private folder", "folder", "App folder", False),
           _entry(resolver, "pointer_file", "Where the private folder is recorded", "file", "App folder", False),
           _entry(resolver, "path_list", "This list's changes (paths.json)", "file", "App folder", False)]
    for name, label, kind, _, can_change in APP_DATA:
        out.append(_entry(resolver, name, label, kind, "App data", can_change))
    for name, label, kind, group, *_ in SLOTS + USER_FILES:
        out.append(_entry(resolver, name, label, kind, group, True))
    for wiki in resolver.workspace:
        for part, (label, kind) in WIKI_PARTS.items():
            out.append(_entry(resolver, f"wiki.{wiki['alias']}.{part}", label, kind, f"Wiki: {wiki['alias']}", True))
    for name, label, kind in OUTSIDE:
        out.append(_entry(resolver, name, label, kind, "Outside the app", True))
    return out


def describe(name: str, workspace: list | None = None) -> dict:
    """One entry, as list_paths() gives it."""
    for entry in list_paths(workspace):
        if entry["name"] == name:
            return entry
    resolver = Resolver(workspace=workspace)
    _check_name(name)
    match = _WIKI_NAME.match(name)
    label, kind = WIKI_PARTS[match.group(2)] if match else (name, "file")
    return _entry(resolver, name, label, kind, f"Wiki: {match.group(1)}" if match else "", True)


def _entry(resolver: Resolver, name: str, label: str, kind: str, group: str, can_change: bool) -> dict:
    found = resolver.path(name)
    default = resolver.default(name)
    status = None
    if name in _SLOTS:
        status = slot_status(name, resolver)
    if kind == "relative_folder":
        exists = any((Path(w["root"]) / str(found)).is_dir() for w in resolver.workspace)
    elif kind == "library":
        exists = bool(found) and is_agentlib_folder(found)
    elif found is None:
        exists = False
    else:
        exists = found.is_dir() if kind == "folder" else found.is_file()
    return {
        "name": name, "label": label, "path": str(found) if found else "", "exists": bool(exists), "kind": kind,
        "group": group, "status": status, "default": str(default) if default else "",
        "state": _state(resolver, name, found, bool(exists)),
        "can_reset": name in _SLOTS and (status != "default" or not exists),
        "can_change": can_change and not (name in AGENT_SLOTS and resolver.legacy(name)),
        "can_clear": name in OPTIONAL and resolver.is_overridden(name),
        "overridden": resolver.is_overridden(name),
    }


def _state(resolver: Resolver, name: str, found: Path | None, exists: bool) -> str:
    """"ok" | "missing" | "not_created" | "unset" (see STATES)."""
    if exists:
        return "ok"
    if found is None or not str(found):
        return "unset"
    match = _WIKI_NAME.match(name)
    made_on_use = name in CREATED_ON_USE or name == "pointer_file" or bool(match and match.group(2) in ("index", "progress", "rules"))
    if made_on_use:
        folder = resolver.folder
        if (folder is not None and folder.is_dir() and _inside(found, folder)) or Path(found).parent.is_dir():
            return "not_created"
    return "missing"


# ---- Changing an entry --------------------------------------------------------------------------

def set_path(name: str, new_path: str | None) -> dict:
    """Points one entry somewhere else; an empty path puts it back to its default. -> the entry.
    A prompt or template slot must point at a file that exists; a folder at a folder that exists;
    a file the app writes (settings, a wiki's rules or index...) at a place whose folder exists.
    Changing the .wiki folder itself is relocate() in appfolder.py, not this."""
    _check_name(name)
    if name in ("app_folder", "pointer_file", "path_list", "instance"):
        raise ValueError("That one can't be changed here." + (" Use Move or Adopt to change the folder." if name == "app_folder" else ""))
    folder = require_app_folder()
    with _lock:
        record = load_record(folder)
        resolver = Resolver(folder, record)
        slot = record["slots"].setdefault(name, {}) if name in _SLOTS else None
        value = (new_path or "").strip()
        if not value:
            record["overrides"].pop(name, None)
            if slot is not None:
                slot.pop("override_base", None)
        elif name == "notes_folder":
            cleaned = clean_relative(value)
            if not cleaned:
                raise ValueError("Give the notes folder as a folder name inside the wiki, such as Notes.")
            record["overrides"][name] = cleaned
        else:
            target = Path(_expand(value))
            if not target.is_absolute():
                raise ValueError(f"Give a full path: {value}")
            _validate(name, resolver, target)
            record["overrides"][name] = str(target)
            if slot is not None:
                slot["override_base"] = _hash(shipped_text(name))
        save_record(record, folder)
    return describe(name)


def _validate(name: str, resolver: Resolver, target: Path) -> None:
    kind = _kind_of(name)
    if name == "agentlib":
        if not is_agentlib_folder(target):
            raise ValueError(f"{target} isn't the agentlib library's folder (it should hold pyproject.toml and an agentlib package).")
    elif name in _SLOTS or name in _USER:
        if not target.is_file():
            raise ValueError(f"There's no file at {target}. A prompt or template can point at an existing file only.")
    elif kind == "reference_file":
        if not target.is_file():
            raise ValueError(f"There's no file at {target}. Point it at an existing tags file.")
    elif kind == "folder":
        if not target.is_dir():
            raise ValueError(f"There's no folder at {target}.")
    elif not target.parent.is_dir():
        raise ValueError(f"The folder {target.parent} doesn't exist.")
    elif target.is_dir():
        raise ValueError(f"{target} is a folder; this needs a file.")


def _kind_of(name: str) -> str:
    if name in _APP_DATA:
        return _APP_DATA[name][2]
    if name in _SLOTS:
        return _SLOTS[name][2]
    if name in _USER:
        return _USER[name][2]
    if name in _OUTSIDE:
        return _OUTSIDE[name][2]
    match = _WIKI_NAME.match(name)
    if match:
        return WIKI_PARTS[match.group(2)][1]
    return "file"


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not (name in ("app_folder", "pointer_file", "path_list") or name in _APP_DATA
                                         or name in _SLOTS or name in _USER or name in _OUTSIDE
                                         or _WIKI_NAME.match(name)):
        raise ValueError(f"Unknown path: {name}")


# ---- Prompt and template slots ------------------------------------------------------------------

def slot_names() -> list[str]:
    return [row[0] for row in SLOTS]


def shipped_file(name: str) -> Path:
    """A slot's shipped default, or a user file's starter."""
    if name in _USER:
        return APP_FILES / _USER[name][6]
    if name not in _SLOTS:
        raise ValueError(f"Not a prompt or template: {name}")
    return APP_FILES / _SLOTS[name][6]


def shipped_text(name: str) -> str:
    """The default the app ships for a slot."""
    return _normalise(shipped_file(name).read_text(encoding="utf-8-sig"))


def slot_status(name: str, resolver: Resolver | None = None) -> str | None:
    """"default", "customised" or "customised_newer_default"; None when the file is missing."""
    resolver = resolver or Resolver()
    found = resolver.path(name)
    if found is None or not found.is_file():
        return None
    try:
        text = _normalise(found.read_text(encoding="utf-8-sig"))
        shipped = shipped_text(name)
    except (OSError, UnicodeDecodeError):
        return None
    if text == shipped:
        return "default"
    info = resolver.record["slots"].get(name) or {}
    base = info.get("override_base") if resolver.is_overridden(name) else info.get("base")
    if resolver.legacy(name):
        base = None
    if base and _hash(text) == base:
        return "default"   # an unedited copy of an older default: sync_slots() brings it up to date
    if base and base != _hash(shipped):
        return "customised_newer_default"
    return "customised"


def read_prompt(name: str, **values) -> str:
    """The current text of a prompt or template slot, with any {{name}} placeholders given in
    values filled in (others are left as they are). A slot whose file is at its usual place but
    missing (or with no folder chosen yet) reads the shipped default; a slot pointed at a file
    that is gone fails with a clear message.
    A user file (personal_capture_rules) reads without its <!-- comments --> and trimmed, so the
    untouched starter reads as "" (nothing to add); a missing one at its usual place also reads "".
    """
    if name not in _SLOTS and name not in _USER:
        raise ValueError(f"Not a prompt or template: {name}")
    resolver = Resolver()
    found = resolver.path(name)
    if found is not None and found.is_file():
        text = _normalise(found.read_text(encoding="utf-8-sig"))
    elif name in _USER and (found is None or not resolver.is_overridden(name)):
        text = ""
    elif found is None or resolver.legacy(name) or not resolver.is_overridden(name):
        text = shipped_text(name)
    else:
        row = _SLOTS.get(name) or _USER[name]
        raise PathMissing(f"{row[1]}: the file {found} is gone. Point it at another file in Paths"
                          + ("." if name in _USER else ", or reset it."))
    if name in _USER:
        text = _COMMENT.sub("", text).strip()
    return fill(text, values) if values else text


def prompt_body(name: str, **values) -> str:
    """read_prompt() without a skill file's frontmatter (the lines between the first two ---)."""
    return _FRONTMATTER.sub("", read_prompt(name, **values), count=1).strip()


def fill(text: str, values: dict) -> str:
    """Fills {{name}} placeholders in one pass (text put in is never filled again)."""
    def one(match):
        key = match.group(1)
        return str(values[key]) if key in values else match.group(0)
    return _PLACEHOLDER.sub(one, text)


def reset_prompt(name: str) -> dict:
    """Replaces a slot's file with the shipped default. -> the entry. (Not for the person's own
    files such as personal_capture_rules: those are never reset.)"""
    if name in _USER:
        raise ValueError("That file is yours: it has no default to reset to.")
    if name not in _SLOTS:
        raise ValueError(f"Not a prompt or template: {name}")
    folder = require_app_folder()
    with _lock:
        record = load_record(folder)
        resolver = Resolver(folder, record)
        target = resolver.path(name)
        if target is None:
            raise PathMissing("No file is set for it.")
        text = shipped_text(name)
        ensure_parent(target)
        write_text_atomic(target, text)
        info = record["slots"].setdefault(name, {})
        info["override_base" if resolver.is_overridden(name) else "base"] = _hash(text)
        info["seeded"] = True
        save_record(record, folder)
    return describe(name)


def write_file(name: str, text: str, expect: str | None = None) -> dict:
    """Saves the text of a file entry (a prompt or template slot, a wiki's rules file...).
    expect: the text the caller last read; if the file changed since, nothing is written."""
    if _kind_of(name) not in ("file", "prompt", "template", "user_prompt"):
        raise ValueError("That entry isn't a text file.")
    resolver = Resolver()
    target = resolver.path(name)
    if target is None:
        raise PathMissing("No file is set for it.")
    if expect is not None:
        current = _normalise(target.read_text(encoding="utf-8-sig")) if target.is_file() else None
        if current is not None and current != _normalise(expect):
            raise ValueError("The file changed on disk since it was opened. Reopen it to see the change.")
    ensure_parent(target)
    write_text_atomic(target, _normalise(text))
    return describe(name)


def read_file(name: str) -> dict:
    """{name, path, exists, text (None when missing), default_text (slots only)}"""
    resolver = Resolver()
    target = resolver.path(name)
    exists = bool(target) and target.is_file()
    out = {"name": name, "path": str(target) if target else "", "exists": exists,
           "text": _normalise(target.read_text(encoding="utf-8-sig")) if exists else None}
    if name in _SLOTS:
        out["default_text"] = shipped_text(name)
        out["status"] = slot_status(name, resolver)
    elif name in _USER:
        out["starter_text"] = shipped_text(name)
        out["status"] = None
    return out


def sync_slots(folder: Path | None = None) -> dict:
    """Run on each start: copies a slot's shipped default into the .wiki folder where its file has
    never been made, and brings unedited copies up to the app's current defaults. Files outside the
    .wiki folder are never written, and a file the person deleted is not made again.
    -> {"created": [names], "updated": [names]}"""
    folder = folder if folder is not None else app_folder()
    report = {"created": [], "updated": []}
    if folder is None or not folder.is_dir():
        return report
    with _lock:
        record = load_record(folder)
        resolver = Resolver(folder, record, use_env=False)
        changed = False
        for name in slot_names():
            target = resolver.path(name)
            if target is None or not _inside(target, folder):
                continue
            info = record["slots"].setdefault(name, {})
            key = "override_base" if resolver.is_overridden(name) else "base"
            shipped = shipped_text(name)
            if not target.exists():
                if info.get("seeded"):
                    continue   # deleted on purpose: reported as missing, not made again
                target.parent.mkdir(parents=True, exist_ok=True)
                write_text_atomic(target, shipped)
                info.update({key: _hash(shipped), "seeded": True})
                report["created"].append(name)
                changed = True
                continue
            try:
                text = _normalise(target.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError):
                continue
            if not info.get("seeded") or not info.get(key):
                # Found already there (an adopted folder, a migrated prompt): an exact copy of the
                # default counts as unedited; anything else as the person's own.
                info.update({key: _hash(shipped), "seeded": True})
                changed = True
            elif _hash(text) == info[key] and info[key] != _hash(shipped):
                write_text_atomic(target, shipped)   # unedited: follows the newer default
                info[key] = _hash(shipped)
                report["updated"].append(name)
                changed = True
            elif text == shipped and info[key] != _hash(shipped):
                info[key] = _hash(shipped)
                changed = True
        for name in _USER:
            # The person's own file: the starter goes in once, where there is no file; after that
            # it is never written, updated or made again.
            target = resolver.path(name)
            if target is None or not _inside(target, folder):
                continue
            info = record["slots"].setdefault(name, {})
            if target.exists():
                if not info.get("seeded"):
                    info["seeded"] = True
                    changed = True
                continue
            if info.get("seeded"):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "x", encoding="utf-8", newline="\n") as file:   # "x": never over an existing file
                file.write(shipped_text(name))
            info["seeded"] = True
            report["created"].append(name)
            changed = True
        if changed:
            save_record(record, folder)
    return report


# ---- Engine settings ----------------------------------------------------------------------------
# engine.json: {"engine": "claude", "engines": {"claude": {...}}}. Each engine keeps its own
# fields under its id, so a future engine adds its block without touching the others.

ENGINES = {
    "claude": {
        "label": "Claude (Claude Code and the Claude Agent SDK)",
        "defaults": {
            # Each agent's model: the one source of truth. The tabs' model menus show this as their
            # choice and save a change back here (agent_model / set_agent_model below, or
            # getEngineSettings / setEngineSettings from the page). executive-assistant: Sessions
            # and notes Capture; wiki-reviewer: Review; team-wiki-manager: Promotion.
            "models": {"executive-assistant": "claude-haiku-5-5", "wiki-reviewer": "claude-sonnet-5-5",
                       "team-wiki-manager": "claude-sonnet-5-5"},
        },
    },
}
MODEL_AGENTS = ("executive-assistant", "wiki-reviewer", "team-wiki-manager")


def agent_model(agent_id: str, engine: str | None = None) -> str:
    """The model an agent uses on the chosen engine (or `engine`): the saved choice, or the default."""
    settings = get_engine_settings()
    models = settings["engines"].get(engine or settings["engine"], {}).get("models") or {}
    return str(models.get(agent_id) or "")


def set_agent_model(agent_id: str, model: str, engine: str | None = None) -> dict:
    """Saves an agent's model (what a tab's model menu does when the person picks another).
    model "" puts it back to the engine's default. -> get_engine_settings()"""
    if agent_id not in MODEL_AGENTS:
        raise ValueError(f"Unknown agent: {agent_id}")
    if not isinstance(model, str) or (model and not all(c.isalnum() or c in "-_.[]" for c in model)):
        raise ValueError("Bad model id.")
    engine = engine or get_engine_settings()["engine"]
    value = model or ENGINES.get(engine, {}).get("defaults", {}).get("models", {}).get(agent_id, "")
    return set_engine_settings({"engines": {engine: {"models": {agent_id: value}}}})


def get_engine_settings() -> dict:
    """{"engine": id, "engines": {id: {fields}}, "available": [{"id", "label"}]}"""
    stored = {}
    found = path("engine_settings")
    if found is not None:
        try:
            stored = json.loads(found.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            stored = {}
    stored = stored if isinstance(stored, dict) else {}
    saved_engines = stored.get("engines") if isinstance(stored.get("engines"), dict) else {}
    engines = {}
    for engine_id, spec in ENGINES.items():
        mine = saved_engines.get(engine_id) if isinstance(saved_engines.get(engine_id), dict) else {}
        engines[engine_id] = _merge(spec["defaults"], mine)
        models = engines[engine_id].get("models")
        if isinstance(models, dict):
            models = engines[engine_id]["models"] = dict(models)   # never the shared defaults
            for retired in RETIRED_AGENTS:   # e.g. the note taker's model, saved by an earlier version
                models.pop(retired, None)
    for engine_id, fields in saved_engines.items():   # an engine this version doesn't know: kept as is
        if engine_id not in engines and isinstance(fields, dict):
            engines[engine_id] = fields
    engine = stored.get("engine") if stored.get("engine") in ENGINES else "claude"
    return {"engine": engine, "engines": engines,
            "available": [{"id": k, "label": v["label"]} for k, v in ENGINES.items()]}


def set_engine_settings(settings: dict) -> dict:
    """Saves {"engine": id, "engines": {id: {fields}}} (either part may be left out). -> get_engine_settings()"""
    if not isinstance(settings, dict):
        raise ValueError("Engine settings must be an object.")
    target = path("engine_settings")
    if target is None:
        raise PathMissing("Choose where WikiApp keeps its private folder first.")
    current = get_engine_settings()
    engine = settings.get("engine", current["engine"])
    if engine not in ENGINES:
        raise ValueError(f"Unknown engine: {engine}")
    engines = current["engines"]
    for engine_id, fields in (settings.get("engines") or {}).items():
        if not isinstance(fields, dict):
            raise ValueError(f"Settings for {engine_id} must be an object.")
        engines[engine_id] = _merge(engines.get(engine_id) or {}, fields)
    ensure_parent(target)
    write_text_atomic(target, json.dumps({"engine": engine, "engines": engines}, indent=1, ensure_ascii=False) + "\n")
    return get_engine_settings()


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        out[key] = _merge(out[key], value) if isinstance(out.get(key), dict) and isinstance(value, dict) else value
    return out


# ---- agentlib -----------------------------------------------------------------------------------
# agentlib is a separate library, never copied into the app. It is looked for next to the app's
# project folder: in each sibling folder, and one level inside each.

def is_agentlib_folder(folder: str | os.PathLike) -> bool:
    folder = Path(folder)
    return (folder.is_dir() and (folder / "agentlib" / "__init__.py").is_file()
            and ((folder / "pyproject.toml").is_file() or (folder / "setup.py").is_file()))


def find_agentlib(project: Path | None = None) -> list[Path]:
    """Every agentlib library folder beside the project folder (default: the one holding App Files)."""
    project = (project or APP_FILES.parent).resolve()
    found = []
    try:
        siblings = sorted(p for p in project.parent.iterdir() if p.is_dir())
    except OSError:
        return found
    for sibling in siblings:
        if sibling.name.startswith(".") or sibling.resolve() == project:
            continue
        if sibling.name.lower() == "agentlib" and is_agentlib_folder(sibling):
            found.append(sibling)
        try:
            children = sorted(p for p in sibling.iterdir() if p.is_dir() and p.name.lower() == "agentlib")
        except OSError:
            continue
        found += [child for child in children if is_agentlib_folder(child)]
    return found


def agentlib_installed() -> bool:
    """True when agentlib can be imported by this Python (without importing it)."""
    try:
        return importlib.util.find_spec("agentlib") is not None
    except (ImportError, ValueError):
        return False


# ---- Settings and workspace ---------------------------------------------------------------------

def read_settings(folder: Path | None = None) -> dict:
    """The page's saved settings (settings.json), or {}."""
    resolver_folder = folder if folder is not None else app_folder()
    if resolver_folder is None:
        return {}
    record = load_record(resolver_folder)
    value = record["overrides"].get("settings")
    file = Path(_expand(value)) if value else resolver_folder / "settings.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_workspace(folder: Path | None = None) -> list[dict]:
    """The open wikis, from the saved settings: [{"alias", "root"}]."""
    raw = read_settings(folder).get("workspace")
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("alias"), str) and isinstance(item.get("root"), str):
            out.append({"alias": item["alias"], "root": item["root"]})
    return out


# ---- Helpers ------------------------------------------------------------------------------------

def write_text_atomic(file: str | os.PathLike, text: str) -> None:
    """Written to a temporary file first, so a crash mid-write never leaves half a file."""
    file = Path(file)
    temp = file.with_name(f"{file.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    with _replace_lock:   # Windows refuses two replaces of one file at the same moment
        os.replace(temp, file)


_replace_lock = threading.Lock()


def safe_name(alias: str) -> str:
    """A wiki alias as a file name."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", alias).strip(" .") or "wiki"


def clean_relative(text: str) -> str:
    """A folder typed by the person -> "Notes" or "Work/Notes" (like cleanNotesDir in notes.js)."""
    parts = [re.sub(r'[<>:"|?*\x00-\x1f]', "", p).strip() for p in str(text or "").replace("\\", "/").split("/")]
    return "/".join(p for p in parts if p and p not in (".", ".."))


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").lstrip("﻿")


def _hash(text: str) -> str:
    return hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()


def _expand(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value.strip()))


def _norm_path(path: Path) -> str:
    try:
        path = path.resolve()
    except OSError:
        pass
    return os.path.normcase(str(path))


def _inside(path: Path, folder: Path) -> bool:
    child, parent = _norm_path(Path(path)), _norm_path(Path(folder))
    return child == parent or child.startswith(parent.rstrip("\\/") + os.sep)
