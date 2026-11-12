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
                    run_history, indexes, progress, note_templates, prompts, wiki_settings (each
                    wiki's role and the Sessions tab's filter: see "Wiki roles" below)
    your own files  personal_capture_rules (.wiki/capture-rules.md): free-text rules for capture in
                    the personal wiki, the one place for them. A starter is copied in once if
                    missing; never updated, overwritten or reset; no status. personal_tags (the
                    person's own tags, a page in the personal wiki, made by the sessions tool when
                    the first one is added).
    file slots      three tiers (see MAIN_SLOTS, ADVANCED_SLOTS, INTERNAL below):
                    main: template.daily, template.weekly, copied into .wiki/note-templates/ where
                      missing; status "default" (unedited, follows newer defaults by itself),
                      "customised", "customised_newer_default"; reset_prompt() puts the default back.
                    advanced: the three agents' prompts, read from the app's own files ("built_in")
                      until customise_prompt() makes an editable copy in .wiki/prompts/;
                      reset_prompt() deletes the copy.
                    internal: request wording, samples, starters: never copied or listed, read
                      from the app's files by read_prompt().
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
    ("note_templates", "Note templates (the New note menu)", "folder", "note-templates", True),
    ("prompts", "Customised agent prompts (advanced)", "folder", "prompts", True),
    ("wiki_settings", "Wiki roles (personal, team, view only) and the Sessions filter", "file", "wiki-settings.json", True),
]
_APP_DATA = {row[0]: row for row in APP_DATA}

# File slots come in three tiers.
#   main      copied into .wiki on setup and shown in Settings: what a person actually edits.
#   advanced  shown in Settings, but read straight from the app's shipped file until the person
#             asks for an editable copy (customise_prompt); reset_prompt removes the copy again.
#   internal  never copied, never listed: always read from the shipped file (read_prompt works).
NOTE_TEMPLATES_DIR = "note-templates"   # the note templates' folder inside .wiki: change it here only
CAPTURE_RULES_FILE = "capture-rules.md"  # the personal capture rules, at the top of .wiki
LAYOUT_VERSION = 2                       # paths.json "layout": 2 once an older .wiki has been tidied

# Slots: (name, label, kind, group, parent entry, file inside it, shipped default in App Files).
MAIN_SLOTS = [
    ("template.daily", "Daily note", "template", "Note templates", "note_templates", "Daily.md", "app/templates/Notes/Daily.md"),
    ("template.weekly", "Weekly note", "template", "Note templates", "note_templates", "Weekly.md", "app/templates/Notes/Weekly.md"),
]
ADVANCED_SLOTS = [
    ("prompt.executive-assistant", "Executive assistant's prompt (Notes and Sessions tabs)", "prompt", "Agent prompts (advanced)", "prompts", "executive-assistant.md", "agents/executive-assistant/SKILL.md"),
    ("prompt.wiki-reviewer", "Wiki reviewer's prompt (Review tab)", "prompt", "Agent prompts (advanced)", "prompts", "wiki-reviewer.md", "agents/wiki-reviewer/SKILL.md"),
    ("prompt.team-wiki-manager", "Team wiki manager's prompt (Promotion tab)", "prompt", "Agent prompts (advanced)", "prompts", "team-wiki-manager.md", "agents/team-wiki-manager/SKILL.md"),
]
SLOTS = MAIN_SLOTS + ADVANCED_SLOTS
_SLOTS = {row[0]: row for row in SLOTS}
_ADVANCED = {row[0] for row in ADVANCED_SLOTS}

# Internal: name -> shipped file in App Files. The wording wrapped around each request, the samples
# and the one-time starters. read_prompt(name) reads them; nothing else about them can change.
INTERNAL = {
    "prompt.promotion-first-message": "agents/messages/promotion-first-message.md",
    "prompt.ingest-feedback": "agents/messages/ingest-feedback.md",
    "prompt.ingest-answers": "agents/messages/ingest-answers.md",
    "prompt.wikis-section": "agents/messages/wikis-section.md",
    "prompt.sessions-capture": "agents/messages/sessions-capture.md",
    "prompt.sessions-notes-capture": "agents/messages/sessions-notes-capture.md",
    "prompt.sessions-review": "agents/messages/sessions-review.md",
    "prompt.sessions-merges": "agents/messages/sessions-merges.md",
    "template.sample-note": "app/templates/Notes/Sample note.md",
    "template.sample-page": "app/templates/Pages/Sample page.md",
    "template.page-starter": "app/templates/starters/page-template.md",
    "template.rules-starter": "app/templates/starters/wiki-rules.md",
    "template.team-rules": "sessions/templates/team-wiki_rules.md",
}
# Internal slots no longer in use, with the shipped file an older copy is compared with when an
# older .wiki is tidied (upgrade_layout). template.personal-wiki: the app doesn't make WIKI.md any
# more (a wiki's role decides); only sb.py on its own reads the file, in place.
RETIRED_INTERNAL = {"template.personal-wiki": "sessions/templates/personal-WIKI.md"}

# Where the first layout (before the tiers) kept each now-internal or retired file, inside .wiki.
# On the first start of this version an unedited copy is removed; an edited one is left, unread,
# and listed once as a leftover (upgrade_layout).
OLD_LAYOUT = {
    **{name: "prompts/" + Path(file).name for name, file in INTERNAL.items() if name.startswith("prompt.")},
    "prompt.tasks": "prompts/TASKS.md",
    "prompt.note-taker": "prompts/note-taker.md",
    "prompt.ingest-first-message": "prompts/ingest-first-message.md",
    "template.sample-note": "templates/Notes/Sample note.md",
    "template.sample-page": "templates/Pages/Sample page.md",
    "template.page-starter": "starters/page-template.md",
    "template.rules-starter": "starters/wiki-rules.md",
    "template.personal-wiki": "starters/personal-WIKI.md",
    "template.team-rules": "starters/team-wiki_rules.md",
}
# Files that moved: name -> where the first layout kept them.
OLD_MOVES = {
    "template.daily": "templates/Notes/Daily.md",
    "template.weekly": "templates/Notes/Weekly.md",
    "personal_capture_rules": "prompts/personal-capture-rules.md",
}
LEFTOVERS_FILE = "leftovers.json"

# The person's own files: (name, label, kind, group, parent entry, file inside it, starter in App Files).
# Not defaults: the starter is copied in once, only where the file is missing, and never updated,
# overwritten or reset. No status. read_prompt() gives the text without <!-- comments -->.
USER_FILES = [
    ("personal_capture_rules", "My capture rules (personal wiki: what to pick out, what gets its own page)",
     "user_prompt", "Rules", "app_folder", CAPTURE_RULES_FILE, "agents/messages/personal-capture-rules.md"),
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
                  "indexes", "progress", "path_list", "personal_tags", "notes_folder", "sessions_config", "prompts",
                  "wiki_settings"}

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
        if name in INTERNAL:
            return APP_FILES / INTERNAL[name]
        if name in _ADVANCED:
            return APP_FILES / _SLOTS[name][6]   # built in: the shipped file, until customised
        if name in _SLOTS or name in _USER:
            row = _SLOTS.get(name) or _USER[name]
            parent = self.path(row[4])
            found = parent / row[5] if parent else None
            if name in OLD_MOVES and found is not None and not found.exists() and self.folder is not None \
                    and self.record.get("layout", 1) < LAYOUT_VERSION and (self.folder / OLD_MOVES[name]).is_file():
                return self.folder / OLD_MOVES[name]   # not tidied yet (the app hasn't started since): the old place
            return found
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
            return None   # none: the note templates come from note_templates, and no page templates
        folder = self.path("indexes" if part == "index" else "progress")
        if folder is None:
            return None
        return folder / (safe_name(alias) + (".md" if part == "index" else ""))

    def path(self, name: str) -> Path | None:
        if name in INTERNAL:
            return APP_FILES / INTERNAL[name]   # always the shipped file
        found = self.legacy(name) or self.override(name)
        if found is None and name in _ADVANCED:
            copy = self.copy_path(name)
            found = copy if copy is not None and copy.is_file() else None
        return found or self.default(name)

    def copy_path(self, name: str) -> Path | None:
        """Where an advanced slot's editable copy goes (.wiki/prompts/<file>), made or not."""
        parent = self.path("prompts")
        return parent / _SLOTS[name][5] if parent else None

    def has_copy(self, name: str) -> bool:
        """An advanced slot reads from the person's own file (a copy, an override, the old test folder)."""
        if self.legacy(name) or self.is_overridden(name):
            return True
        copy = self.copy_path(name)
        return copy is not None and copy.is_file()

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
        """The personal wiki's folder: the open wiki whose role is "personal" (see wiki_roles)."""
        roles = _roles_by_alias(self.folder, self.workspace)
        found = next((w for w in self.workspace if roles.get(w["alias"]) == "personal"), None)
        return Path(found["root"]) if found else None

    def role(self, alias: str) -> str:
        return _roles_by_alias(self.folder, self.workspace).get(alias, "view")


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
    """Every entry the person can see: {name, label, path, exists, kind, group, tier, status,
    default, state, can_reset, can_customise, can_change, can_clear, overridden}. Internal slots are
    not listed. Order: the rules (the main way to customise: the capture rules, then each wiki's rules
    file), the note templates, everything else, and the advanced agent prompts last.
    tier: "main" or "advanced". status: main slots "default" | "customised" |
    "customised_newer_default"; advanced slots "built_in" | "customised" | "customised_newer_default";
    None otherwise. state: one of STATES. can_clear: an optional entry (no default) that has a value.
    can_customise: an advanced slot still read from the app's own file.
    A wiki's rows (wiki.<alias>.*) also have role: "personal" | "team" | "view". Only the team wiki
    has a rules row; a view-only wiki has no progress row."""
    resolver = Resolver(workspace=workspace)
    user = {row[0]: row for row in USER_FILES}
    out = [_entry(resolver, "personal_capture_rules", user["personal_capture_rules"][1], "user_prompt", "Rules", True)]
    # A wiki's rows carry its role. Only the team wiki has a rules row: its rules file is the only
    # one any agent is sent (Promotion); a personal wiki's rules are the capture rules above, and a
    # view-only wiki's are never used. A view-only wiki has no progress row either (nothing is
    # captured there); its templates (the New note menu) and its index (read for context) stay.
    roles = {w["alias"]: resolver.role(w["alias"]) for w in resolver.workspace}
    for wiki in resolver.workspace:
        if roles[wiki["alias"]] != "team":
            continue
        label, kind = WIKI_PARTS["rules"]
        out.append({**_entry(resolver, f"wiki.{wiki['alias']}.rules", f"{wiki['alias']} wiki rules", kind, "Rules", True),
                    "role": roles[wiki["alias"]]})
    for name, label, kind, group, *_ in MAIN_SLOTS:
        out.append(_entry(resolver, name, label, kind, group, True))
    out += [_entry(resolver, "app_folder", "WikiApp's private folder", "folder", "App folder", False),
            _entry(resolver, "pointer_file", "Where the private folder is recorded", "file", "App folder", False),
            _entry(resolver, "path_list", "This list's changes (paths.json)", "file", "App folder", False)]
    for name, label, kind, _, can_change in APP_DATA:
        out.append(_entry(resolver, name, label, kind, "App data", can_change))
    for name, label, kind, group, *_ in USER_FILES:
        if name != "personal_capture_rules":
            out.append(_entry(resolver, name, label, kind, group, True))
    for wiki in resolver.workspace:
        role = roles[wiki["alias"]]
        for part, (label, kind) in WIKI_PARTS.items():
            if part == "rules" or (role == "view" and part == "progress"):
                continue
            out.append({**_entry(resolver, f"wiki.{wiki['alias']}.{part}", label, kind, f"Wiki: {wiki['alias']}", True),
                        "role": role})
    for name, label, kind in OUTSIDE:
        out.append(_entry(resolver, name, label, kind, "Outside the app", True))
    for name, label, kind, group, *_ in ADVANCED_SLOTS:
        out.append(_entry(resolver, name, label, kind, group, True))
    return out


def describe(name: str, workspace: list | None = None) -> dict:
    """One entry, as list_paths() gives it. (Internal slots have none.)"""
    if name in INTERNAL:
        raise ValueError(f"{name} is built into the app: it has no entry to show or change.")
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
    if name in _ADVANCED:
        can_reset = status in ("customised", "customised_newer_default") or (resolver.is_overridden(name) and not exists)
    else:
        can_reset = name in _SLOTS and (status != "default" or not exists)
    return {
        "name": name, "label": label, "path": str(found) if found else "", "exists": bool(exists), "kind": kind,
        "group": group, "tier": "advanced" if name in _ADVANCED else "main",
        "status": status, "default": str(default) if default else "",
        "state": _state(resolver, name, found, bool(exists)),
        "can_reset": can_reset,
        "can_customise": name in _ADVANCED and status == "built_in",
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
    if name in INTERNAL:
        raise ValueError(f"{name} is built into the app and can't be changed.")
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
                                         or name in _SLOTS or name in _USER or name in _OUTSIDE or name in INTERNAL
                                         or _WIKI_NAME.match(name)):
        raise ValueError(f"Unknown path: {name}")


# ---- Prompt and template slots ------------------------------------------------------------------

def slot_names() -> list[str]:
    """The listed slots (main and advanced). Internal ones are in INTERNAL."""
    return [row[0] for row in SLOTS]


def shipped_file(name: str) -> Path:
    """A slot's shipped default, an internal file, or a user file's starter."""
    if name in INTERNAL:
        return APP_FILES / INTERNAL[name]
    if name in _USER:
        return APP_FILES / _USER[name][6]
    if name not in _SLOTS:
        raise ValueError(f"Not a prompt or template: {name}")
    return APP_FILES / _SLOTS[name][6]


def shipped_text(name: str) -> str:
    """The default the app ships for a slot."""
    return _normalise(shipped_file(name).read_text(encoding="utf-8-sig"))


def slot_status(name: str, resolver: Resolver | None = None) -> str | None:
    """Main slots: "default", "customised" or "customised_newer_default". Advanced slots: "built_in"
    (read from the app's own file), "customised" or "customised_newer_default". None when the file
    is missing."""
    resolver = resolver or Resolver()
    if name in _ADVANCED and not resolver.has_copy(name):
        return "built_in"
    found = resolver.path(name)
    if found is None or not found.is_file():
        return None
    try:
        text = _normalise(found.read_text(encoding="utf-8-sig"))
        shipped = shipped_text(name)
    except (OSError, UnicodeDecodeError):
        return None
    if name in _ADVANCED:
        info = resolver.record["slots"].get(name) or {}
        base = None if resolver.legacy(name) else (info.get("override_base") if resolver.is_overridden(name) else info.get("base"))
        if text != shipped and base and base != _hash(shipped):
            return "customised_newer_default"
        return "customised"
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
    if name not in _SLOTS and name not in _USER and name not in INTERNAL:
        raise ValueError(f"Not a prompt or template: {name}")
    if name in INTERNAL:
        text = shipped_text(name)
        return fill(text, values) if values else text
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


def customise_prompt(name: str) -> dict:
    """An advanced slot (an agent's prompt): makes the editable copy in .wiki/prompts from the app's
    shipped file, if there isn't one yet. From then on the agent reads the copy. -> the entry."""
    if name not in _ADVANCED:
        raise ValueError(f"Only an agent's prompt can be customised: {name}")
    folder = require_app_folder()
    with _lock:
        record = load_record(folder)
        resolver = Resolver(folder, record)
        if not resolver.has_copy(name):
            copy = resolver.copy_path(name)
            ensure_parent(copy)
            text = shipped_text(name)
            with open(copy, "x", encoding="utf-8", newline="\n") as file:   # never over an existing file
                file.write(text)
            record["slots"][name] = {"base": _hash(text), "seeded": True}
            save_record(record, folder)
    return describe(name)


def reset_prompt(name: str) -> dict:
    """Main slot: replaces its file with the shipped default. Advanced slot (an agent's prompt):
    deletes the editable copy (or forgets the file it was pointed at, which is left alone) and goes
    back to the app's own file. -> the entry. (Not for the person's own files such as
    personal_capture_rules, nor for internal ones.)"""
    if name in _USER:
        raise ValueError("That file is yours: it has no default to reset to.")
    if name not in _SLOTS:
        raise ValueError(f"Not a prompt or template: {name}")
    folder = require_app_folder()
    if name in _ADVANCED:
        with _lock:
            record = load_record(folder)
            resolver = Resolver(folder, record)
            if resolver.is_overridden(name):
                record["overrides"].pop(name, None)   # the person's own file stays where it is
            else:
                copy = resolver.copy_path(name)
                if copy is not None and copy.is_file() and _inside(copy, folder):
                    copy.unlink()
                    if _norm_path(copy.parent) != _norm_path(folder):
                        try:
                            copy.parent.rmdir()   # the prompts folder, once nothing is customised (only when empty)
                        except OSError:
                            pass
            record["slots"].pop(name, None)
            save_record(record, folder)
        return describe(name)
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
    if name in INTERNAL:
        raise ValueError(f"{name} is built into the app and can't be changed.")
    if _kind_of(name) not in ("file", "prompt", "template", "user_prompt"):
        raise ValueError("That entry isn't a text file.")
    if name in _ADVANCED and not Resolver().has_copy(name):
        customise_prompt(name)   # never write into the app's own file: save into an editable copy
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
    """{name, path, exists, text (None when missing), default_text (slots), starter_text (user
    files), status}. Internal slots read too (their shipped text), for the page's starters."""
    resolver = Resolver()
    target = resolver.path(name)
    exists = bool(target) and target.is_file()
    out = {"name": name, "path": str(target) if target else "", "exists": exists,
           "text": _normalise(target.read_text(encoding="utf-8-sig")) if exists else None}
    if name in INTERNAL:
        out.update({"default_text": out["text"], "status": None, "tier": "internal"})
    elif name in _SLOTS:
        out["default_text"] = shipped_text(name)
        out["status"] = slot_status(name, resolver)
    elif name in _USER:
        out["starter_text"] = shipped_text(name)
        out["status"] = None
    return out


def sync_slots(folder: Path | None = None) -> dict:
    """Run on each start. First tidies a .wiki made by the first layout (upgrade_layout). Then
    copies each main slot's shipped default into the .wiki folder where its file has never been
    made, and brings unedited copies (main, or an advanced copy never edited) up to the app's current
    defaults. Advanced and internal slots are never copied here. Files outside the .wiki folder are
    never written, and a file the person deleted is not made again.
    -> {"created": [names], "updated": [names], "removed": [paths], "leftovers": [{path, kind, note}]}"""
    folder = folder if folder is not None else app_folder()
    report = {"created": [], "updated": [], "removed": [], "leftovers": []}
    if folder is None or not folder.is_dir():
        return report
    with _lock:
        record = load_record(folder)
        changed = False
        if record.get("layout", 1) < LAYOUT_VERSION:
            report.update(upgrade_layout(folder, record))
            changed = True
        resolver = Resolver(folder, record, use_env=False)
        for name in slot_names():
            target = resolver.path(name)
            if target is None or not _inside(target, folder):
                continue
            if name in _ADVANCED and not resolver.has_copy(name):
                continue   # built in: read from the app's own file, never copied here
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


def upgrade_layout(folder: Path, record: dict) -> dict:
    """Tidies a .wiki folder made by the first layout, once (record["layout"] becomes 2). Changes
    record in place; the caller saves it. Nothing the person edited is ever deleted:
      - a now-internal or retired file (OLD_LAYOUT) identical to a default the app recorded for it,
        or to today's shipped file, is removed; an edited one is left where it is, no longer read,
        and listed once as a leftover;
      - an agent prompt's copy in prompts/ (now advanced) is removed if unedited, kept as the
        person's customised copy if edited;
      - Daily and Weekly move to the note templates folder, the capture rules to capture-rules.md,
        unless the person had pointed them elsewhere (their override stays).
    -> {"removed": [paths], "leftovers": [{path, kind, note}]}"""
    removed, leftovers = [], []
    overrides, slots = record["overrides"], record["slots"]
    record["layout"] = LAYOUT_VERSION   # first, so the paths below are the new layout's

    def known(name, info):
        hashes = {info.get("base"), info.get("override_base")} - {None}
        for rel in (INTERNAL.get(name) or RETIRED_INTERNAL.get(name), _SLOTS[name][6] if name in _SLOTS else None,
                    "agents/TASKS.md" if name == "prompt.tasks" else None):
            if rel and (APP_FILES / rel).is_file():
                hashes.add(_hash(_normalise((APP_FILES / rel).read_text(encoding="utf-8-sig"))))
        return hashes

    def unedited(file, name, info):
        try:
            return _hash(_normalise(file.read_text(encoding="utf-8-sig"))) in known(name, info)
        except (OSError, UnicodeDecodeError):
            return False

    def leftover(file, what):
        leftovers.append({"path": str(file), "kind": "edited_old_copy",
                          "note": f"Your edited copy of {what}. WikiApp no longer reads it (this is now built into the "
                                  "app); it is left here for you to keep or delete."})

    for name, rel in OLD_LAYOUT.items():
        info = slots.pop(name, None) or {}
        pointed = overrides.pop(name, None)
        if pointed and _norm_path(Path(_expand(pointed))) != _norm_path(folder / rel):
            # pointed at a file of the person's own: never touched, just no longer read
            leftovers.append({"path": pointed, "kind": "old_override", "note": f"A file you had set for {name}, "
                              "which is now built into the app. WikiApp no longer reads it; the file is left as it was."})
        file = folder / rel
        if file.is_file():
            if unedited(file, name, info):
                file.unlink()
                removed.append(str(file))
            else:
                leftover(file, name)
    resolver = Resolver(folder, record, workspace=[], use_env=False)
    for name in _ADVANCED:
        copy = resolver.copy_path(name)
        if resolver.is_overridden(name) or copy is None or not copy.is_file():
            continue
        info = slots.get(name) or {}
        if unedited(copy, name, info):
            copy.unlink()
            removed.append(str(copy))
            slots.pop(name, None)
        else:
            slots.setdefault(name, {}).setdefault("base", info.get("base") or _hash(shipped_text(name)))
            slots[name]["seeded"] = True
    old_templates = overrides.pop("templates", None)
    overrides.pop("starters", None)
    for name, rel in OLD_MOVES.items():
        if resolver.is_overridden(name):
            continue   # the person pointed it somewhere: that stays
        old = (Path(_expand(old_templates)) / Path(rel).relative_to("templates")) if old_templates and rel.startswith("templates/") else folder / rel
        new = resolver.path(name)
        if not old.is_file() or new is None:
            continue
        if not _inside(old, folder):
            overrides[name] = str(old)   # their templates folder was elsewhere: keep using that file
            continue
        if not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            os.replace(old, new)
        elif name in _SLOTS and unedited(old, name, slots.get(name) or {}):
            old.unlink()
            removed.append(str(old))
        else:
            leftover(old, name)
    for rel in ("templates/Notes", "templates/Pages", "templates", "starters", "prompts"):
        try:
            (folder / rel).rmdir()   # only when empty
        except OSError:
            pass
    if leftovers:
        file = folder / LEFTOVERS_FILE
        try:
            listed = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            listed = []
        listed = listed if isinstance(listed, list) else []
        write_text_atomic(file, json.dumps(listed + leftovers, indent=1, ensure_ascii=False) + "\n")
    return {"removed": removed, "leftovers": leftovers}


# ---- Wiki roles ---------------------------------------------------------------------------------
# Each open wiki has a role, kept in the private folder (wiki_settings: wiki-settings.json), never
# in a file inside the wiki:
#   personal  where notes and sessions are captured, and Review and Suggest merges write (one at most)
#   team      the only wiki Promotion proposes changes to (one at most)
#   view      no agent writes to it or proposes pages for it (Promotion may still read it)
# Roles are keyed by the wiki's folder, so renaming its alias keeps its role. A wiki with no stored
# role (newly opened) is "view", whatever its alias. Upgrading an existing installation (no roles
# saved yet, opened by this version: the host's start-up, or choosing or adopting a private folder,
# all calling wiki_roles(persist=True, upgrade=True)): the personal wiki was the one picked in the
# Sessions tab (the sessionsWiki setting), else the one with the alias "personal", else the one wiki
# whose WIKI.md says type: personal; it becomes personal, and if exactly one other wiki is open it
# becomes the team wiki; with several others they all start as view and needs_team says a team
# wiki needs choosing. That result is saved at once, so a wiki opened afterwards is view only. A
# fresh private folder saves "no roles" the same way; nothing else ever works roles out.

ROLES = ("personal", "team", "view")
MIN_TURNS_OPTIONS = (0, 3, 5, 10, 20)
DEFAULT_MIN_TURNS = 3
_ROLE_WORDS = {"personal": "your personal wiki", "team": "your team wiki", "view": "view only"}


def root_key(root: str | os.PathLike) -> str:
    """A wiki folder as a key: absolute, resolved, case as the system compares it."""
    return _norm_path(Path(_expand(str(root))))


def load_wiki_settings(folder: Path | None = None) -> dict:
    """wiki-settings.json: {"version": 1, "roles": {root key: {role, root, alias}}, "sessions": {"min_turns"}}.
    "roles" is missing until the first result has been saved."""
    file = Resolver(folder).path("wiki_settings") if (folder or app_folder()) else None
    data = {}
    if file is not None:
        try:
            data = json.loads(file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
    return data if isinstance(data, dict) else {}


def _save_wiki_settings(data: dict) -> None:
    file = Resolver(require_app_folder()).path("wiki_settings")
    data["version"] = 1
    ensure_parent(file)
    write_text_atomic(file, json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def _marked_personal(root: str) -> bool:
    """A WIKI.md whose frontmatter says type: personal (how a personal wiki was marked before roles)."""
    try:
        text = (Path(root) / "WIKI.md").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False
    match = _FRONTMATTER.match(text)
    return bool(match and re.search(r"(?m)^type:\s*['\"]?personal['\"]?\s*$", match.group(0)))


def _first_roles(folder: Path | None, workspace: list[dict]) -> dict:
    """The roles before any were chosen, worked out from the older settings (see above)."""
    alias = read_settings(folder).get("sessionsWiki")
    personal = next((w for w in workspace if isinstance(alias, str) and w["alias"] == alias), None) \
        or next((w for w in workspace if w["alias"].lower() == "personal"), None)
    if personal is None:
        marked = [w for w in workspace if _marked_personal(w["root"])]
        personal = marked[0] if len(marked) == 1 else None
    others = [w for w in workspace if w is not personal]
    roles = {}
    if personal is not None:
        roles[root_key(personal["root"])] = {"role": "personal", "root": personal["root"], "alias": personal["alias"]}
    for w in others:
        roles[root_key(w["root"])] = {"role": "team" if len(others) == 1 else "view", "root": w["root"], "alias": w["alias"]}
    return roles


def _stored_roles(folder: Path | None, workspace: list[dict], persist: bool = False, upgrade: bool = False) -> dict:
    """{root key: {role, root, alias}}: the saved roles. With none saved yet: when upgrade (an
    existing installation being opened by this version: the host's start-up, choosing or adopting a
    private folder) the roles worked out from the older settings (_first_roles); otherwise none, so
    every wiki is view only. Saved when persist and there is a private folder."""
    data = load_wiki_settings(folder)
    roles = data.get("roles")
    if isinstance(roles, dict):
        return {k: v for k, v in roles.items() if isinstance(v, dict) and v.get("role") in ROLES}
    folder = folder if folder is not None else app_folder()
    if folder is not None and load_record(folder).get("roles_settled"):
        return {}   # settled with none (a fresh folder): every wiki is view only until one is chosen
    roles = _first_roles(folder, workspace) if upgrade else {}
    if persist and folder is not None and folder.is_dir():
        if not roles:
            # Nothing to keep: a note in paths.json says so, rather than a file of no roles, so a
            # fresh private folder still holds only what the person edits.
            with _lock:
                record = load_record(folder)
                record["roles_settled"] = True
                save_record(record, folder)
            return {}
        with _lock:
            fresh = load_wiki_settings(folder)
            if not isinstance(fresh.get("roles"), dict):
                fresh["roles"] = roles
                _save_wiki_settings(fresh)
            roles = fresh["roles"]
    return roles


def _roles_by_alias(folder: Path | None, workspace: list[dict], persist: bool = False, upgrade: bool = False) -> dict:
    stored = _stored_roles(folder, workspace, persist, upgrade)
    return {w["alias"]: (stored.get(root_key(w["root"])) or {}).get("role", "view") for w in workspace}


def _summary(roles: dict) -> dict:
    connected = list(roles.values())
    return {"roles": roles,
            "needs_personal": bool(connected) and "personal" not in connected,
            "needs_team": any(r != "personal" for r in connected) and "team" not in connected}


def wiki_roles(workspace: list | None = None, persist: bool = False, upgrade: bool = False) -> dict:
    """{"roles": {alias: "personal" | "team" | "view"}, "needs_team": bool, "needs_personal": bool}
    for the open wikis. A wiki not seen before is "view", whatever its alias. needs_personal: no
    open wiki is personal; needs_team: some open wiki isn't personal, and none is the team wiki.
    upgrade: this is an existing installation opened by this version (see _stored_roles); only
    then are roles worked out from the older settings, and only when none are saved yet."""
    folder = app_folder()
    workspace = read_workspace(folder) if workspace is None else workspace
    return _summary(_roles_by_alias(folder, workspace, persist, upgrade))


def set_wiki_role(alias: str, role: str) -> dict:
    """Gives an open wiki a role. Making a wiki personal or team makes the wiki that had that role
    view only. -> wiki_roles() plus "demoted": the alias of the wiki that lost the role, or None."""
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}. Choose personal, team or view.")
    folder = require_app_folder()
    workspace = read_workspace(folder)
    wiki = next((w for w in workspace if w["alias"] == alias), None)
    if wiki is None:
        raise ValueError(f"{alias} isn't one of the open wikis.")
    roles = _stored_roles(folder, workspace)   # the first result if none is saved yet
    with _lock:
        key = root_key(wiki["root"])
        demoted = None
        aliases = {root_key(w["root"]): w["alias"] for w in workspace}
        if role in ("personal", "team"):
            for other, entry in roles.items():
                if other != key and entry.get("role") == role:
                    entry["role"] = "view"
                    demoted = demoted or aliases.get(other) or entry.get("alias")
        roles[key] = {"role": role, "root": wiki["root"], "alias": alias}
        data = load_wiki_settings(folder)
        data["roles"] = roles
        _save_wiki_settings(data)
    return {**wiki_roles(workspace), "demoted": demoted}


def wiki_role_for_root(root: str | os.PathLike) -> str | None:
    """The role of the open wiki at root, or None when root isn't one of the open wikis (or there is
    no private folder: the sessions command line on its own)."""
    folder = app_folder()
    if folder is None:
        return None
    workspace = read_workspace(folder)
    key = root_key(root)
    wiki = next((w for w in workspace if root_key(w["root"]) == key), None)
    if wiki is None:
        return None
    return _roles_by_alias(folder, workspace).get(wiki["alias"], "view")


def wiki_with_role(role: str) -> dict | None:
    """The open wiki that has this role ("personal" or "team"): {"alias", "root"}, or None."""
    folder = app_folder()
    if folder is None:
        return None
    workspace = read_workspace(folder)
    roles = _roles_by_alias(folder, workspace)
    return next((w for w in workspace if roles.get(w["alias"]) == role), None)


def alias_of_root(root: str | os.PathLike) -> str:
    """The open wiki's alias for root, or the folder's name."""
    key = root_key(root)
    for w in read_workspace(app_folder()):
        if root_key(w["root"]) == key:
            return w["alias"]
    return Path(root).name or str(root)


def role_refusal(alias: str, role: str | None, wanted: str) -> str:
    """The plain-words reason a write to a wiki is refused. wanted: the role the write needs."""
    if wanted == "team":
        if role == "personal":
            return f"{alias} is your personal wiki; Promotion only proposes changes to the team wiki. Choose a team wiki in Settings."
        return f"{alias} is {_ROLE_WORDS.get(role or 'view', 'view only')}; choose a team wiki in Settings."
    if role == "team":
        return (f"{alias} is your team wiki; notes and sessions are only captured into your personal wiki. "
                "Choose your personal wiki in Settings.")
    if role == "view":
        return f"{alias} is view only; choose your personal wiki in Settings."
    return f"{alias} isn't your personal wiki; choose your personal wiki in Settings."


# ---- The Sessions tab's filter ---------------------------------------------------------------------
# "Hide sessions with fewer than N turns": only the person's own messages count. Kept in
# wiki-settings.json beside the roles.

def stored_min_turns() -> int | None:
    """The filter as the person set it, or None when it was never set (or there is no private folder)."""
    if app_folder() is None:
        return None
    value = (load_wiki_settings().get("sessions") or {}).get("min_turns")
    return value if isinstance(value, int) and not isinstance(value, bool) and value in MIN_TURNS_OPTIONS else None


def get_sessions_filter() -> dict:
    """{"min_turns": N, "options": [0, 3, 5, 10, 20]} (0: off)."""
    found = stored_min_turns()
    return {"min_turns": DEFAULT_MIN_TURNS if found is None else found, "options": list(MIN_TURNS_OPTIONS)}


def set_sessions_filter(min_turns) -> dict:
    if isinstance(min_turns, bool) or not isinstance(min_turns, int) or min_turns not in MIN_TURNS_OPTIONS:
        raise ValueError("Choose 0 (off), 3, 5, 10 or 20.")
    require_app_folder()
    with _lock:
        data = load_wiki_settings()
        sessions = data.get("sessions") if isinstance(data.get("sessions"), dict) else {}
        data["sessions"] = {**sessions, "min_turns": min_turns}
        _save_wiki_settings(data)
    return get_sessions_filter()


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
