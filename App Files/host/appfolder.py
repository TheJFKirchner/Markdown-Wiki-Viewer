"""WikiApp's private .wiki folder: choosing it on the first start, what setup puts in it, bringing
over what older versions left, moving it later, and the agentlib library the AI features need.

    first_run_state(candidate)   has a place been chosen, what setup would make or find there, the
                                 one-time list of leftovers from older versions, agentlib's state
    choose_location(path)        the first start: makes the folder, copies older data in, sets it up
    relocate(path, mode)         later: "move" the folder's contents there, or "adopt" what's there
    startup()                    each start: brings the prompt and template copies up to date
    agentlib_status()            whether the AI features can run, and if not, why
    connection_status()          how the person signs in to the engine (agentlib; free, sends nothing)
    test_connection()            agentlib's connection check: one tiny real request
    open_path(name)              opens an entry in the system's default app or file manager

The suggested place is the app's own project folder (the one holding WikiApp.cmd); .gitignore
keeps a .wiki folder there out of git.

Nothing is created until a place is chosen. Bringing over older data only copies: nothing is
deleted, and nothing already in the chosen folder is overwritten. The paths themselves come from
pathlist.py.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pathlist
from pathlist import PathMissing, Resolver

APP_FILES = pathlist.APP_FILES
LEFTOVERS_FILE = pathlist.LEFTOVERS_FILE
AGENT_IDS = list(pathlist.AGENT_SLOTS.values())
OLD_SKILL_IDS = AGENT_IDS + pathlist.RETIRED_AGENTS   # every agent an older version made a skill of

# What older versions kept in their data folder -> the entry it belongs to now. The retired
# Notes tab's cards (ingest/pending.json) and the note taker's prompt are not copied forward.
OLD_DATA = [
    ("settings.json", "settings"),
    ("window.txt", "window_placement"),
    ("ingest/pending-promotion.json", "pending_promotion"),
]


def old_locations() -> dict:
    """Where older versions kept things. Tests replace this."""
    home = Path.home()
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
    out = {"data": home / ".wikiapp", "skills": claude / "skills", "retired": None, "retired_runs": None}
    if os.name == "nt":   # the retired Windows-only version of the app
        out["retired"] = Path(os.environ.get("LOCALAPPDATA", "")) / "WikiApp" if os.environ.get("LOCALAPPDATA") else None
        out["retired_runs"] = Path(os.environ.get("TEMP", "")) / "WikiApp" / "ingest-runs" if os.environ.get("TEMP") else None
    return out


def _old_data_folder(old: dict) -> tuple[Path | None, Path | None]:
    """(data folder, its runs folder): ~/.wikiapp, or else what the retired version left."""
    data = old.get("data")
    if data and (Path(data) / "settings.json").is_file():
        return Path(data), Path(data) / "ingest-runs"
    retired = old.get("retired")
    if retired and (Path(retired) / "settings.json").is_file():
        return Path(retired), Path(old["retired_runs"]) if old.get("retired_runs") else None
    if data and Path(data).is_dir():
        return Path(data), Path(data) / "ingest-runs"
    return None, None


# ---- What setup would do ----------------------------------------------------------------------

def preview(folder: Path) -> dict:
    """What choosing `folder` would really create, copy from an older version, or find already
    there: the folder, settings, the capture rules, the note templates (and their folder), and
    anything an older version left to copy. Agent prompts and internal files are read from the app
    itself, so they aren't listed (unless an older version's edited prompt will be copied). Writes
    nothing. -> {"folder", "folder_exists", "items": [{name, label, path, action, source}], ...}
    action: "create" (made now, or a shipped default), "copy" (from an older version), "found"."""
    folder = Path(folder)
    resolver = Resolver(folder, pathlist.load_record(folder) if folder.is_dir() else None, workspace=[], use_env=False)
    old = old_locations()
    data, runs = _old_data_folder(old)
    items = []

    def add(name, label, target, action, source=None):
        items.append({"name": name, "label": label, "path": str(target) if target else "", "action": action,
                      "source": str(source) if source else ""})

    add("app_folder", "WikiApp's private folder", folder, "found" if folder.is_dir() else "create")
    for relative, name in OLD_DATA:
        target = resolver.path(name)
        source = data / relative if data else None
        if target is not None and target.exists():
            add(name, _label(name), target, "found")
        elif source is not None and source.is_file():
            add(name, _label(name), target, "copy", source)
        elif name == "settings":
            add(name, _label(name), target, "create")
    runs_target = resolver.path("run_history")
    if runs is not None and runs.is_dir() and any(runs.iterdir()):
        add("run_history", _label("run_history"), runs_target, "found" if runs_target and runs_target.is_dir() else "copy", runs)
    rules = resolver.path("personal_capture_rules")
    old_rules = folder / pathlist.OLD_MOVES["personal_capture_rules"]
    add("personal_capture_rules", _label("personal_capture_rules"), rules,
        "found" if rules.exists() or old_rules.is_file() else "create", pathlist.shipped_file("personal_capture_rules"))
    templates = resolver.path("note_templates")
    add("note_templates", _label("note_templates"), templates, "found" if templates.is_dir() else "create")
    for name, *_ in pathlist.MAIN_SLOTS:
        target = resolver.path(name)
        old_copy = folder / pathlist.OLD_MOVES[name]
        add(name, _label(name), target, "found" if target.exists() or old_copy.is_file() else "create",
            pathlist.shipped_file(name))
    for name in pathlist.AGENT_SLOTS:
        skill = _old_skill(old, name)
        copy = resolver.copy_path(name)
        if skill is not None and copy is not None and not copy.exists():
            add(name, _label(name), copy, "copy", skill)
    old_index, inside = _old_wiki_index(folder)
    return {"folder": str(folder), "folder_exists": folder.is_dir(), "items": items,
            # The place is an older version's <wiki>/.wiki index folder, or inside a wiki: the page warns.
            "old_wiki_index": old_index, "inside_wiki": inside}


def _old_wiki_index(folder: Path) -> tuple[bool, str]:
    """(is `folder` an older version's index folder <wiki>/.wiki, the wiki folder it is in or "")."""
    folder = Path(folder)
    old_index = (folder / "index.md").is_file() and not (folder / pathlist.PATHS_FILE).exists()
    roots = [Path(r) for r in wiki_roots()]
    for parent in [folder.parent, *folder.parent.parents]:
        if any(pathlist._norm_path(parent) == pathlist._norm_path(r) for r in roots):
            return old_index, str(parent)
        if (parent / "WIKI.md").is_file() or (parent / "wiki_rules.md").is_file():
            return old_index, str(parent)
    return old_index, ""


def wiki_roots() -> list[str]:
    """The wiki folders the app knows of: the open workspace's, and an older version's (before
    the first start's copy has run)."""
    roots = [w["root"] for w in pathlist.read_workspace()]
    data, _ = _old_data_folder(old_locations())
    if data is not None:
        try:
            settings = json.loads((data / "settings.json").read_text(encoding="utf-8-sig"))
            items = json.loads(settings.get("workspace") or "[]")
            roots += [w["root"] for w in items if isinstance(w, dict) and isinstance(w.get("root"), str)]
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    seen, out = set(), []
    for root in roots:
        key = pathlist._norm_path(Path(root))
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def check_candidate(candidate: str | None) -> tuple[Path | None, str]:
    """(the .wiki folder a typed or picked place means, "" or why it can't be used)."""
    if candidate is None or not str(candidate).strip():
        return None, "Give a folder."
    raw = pathlib_expand(str(candidate))
    if not Path(raw).is_absolute():
        return None, f"Give a full path, such as {pathlist.suggested_folder().parent}."
    target = pathlist.folder_for(raw)
    if not target.parent.is_dir():
        return target, f"The folder {target.parent} doesn't exist."
    if target.exists() and not target.is_dir():
        return target, f"{target} is a file, not a folder."
    return target, ""


def pathlib_expand(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value.strip()))


def _label(name: str) -> str:
    for row in pathlist.APP_DATA:
        if row[0] == name:
            return row[1]
    for row in pathlist.SLOTS + pathlist.USER_FILES:
        if row[0] == name:
            return row[1]
    return {"app_folder": "WikiApp's private folder"}.get(name, name)


def _old_skill(old: dict, name: str) -> Path | None:
    """An older version's copy of an agent's prompt in Claude Code's skills folder, if the person
    edited it (an unedited one is the same as the app's own file, so there is nothing to bring over)."""
    if name not in pathlist.AGENT_SLOTS or not old.get("skills"):
        return None
    skill = Path(old["skills"]) / pathlist.AGENT_SLOTS[name] / "SKILL.md"
    try:
        edited = skill.is_file() and pathlist._normalise(skill.read_text(encoding="utf-8-sig")) != pathlist.shipped_text(name)
    except (OSError, UnicodeDecodeError):
        edited = False
    return skill if edited else None


# ---- Bringing over what older versions left (copies only) -----------------------------------------

def migrate(folder: Path) -> dict:
    """Copies the old data folder's settings, cards waiting for review and past runs, and the
    agents' prompts from Claude Code's skills folder, into `folder`. Only where `folder` has no
    such file yet; nothing is deleted or overwritten. -> {"copied": [paths]}"""
    folder = Path(folder)
    record = pathlist.load_record(folder)
    resolver = Resolver(folder, record, workspace=[], use_env=False)
    old = old_locations()
    data, runs = _old_data_folder(old)
    copied = []
    if data is not None:
        for relative, name in OLD_DATA:
            source, target = data / relative, resolver.path(name)
            if source.is_file() and target is not None and _copy_new(source, target, folder):
                copied.append(str(target))
    runs_target = resolver.path("run_history")
    if runs is not None and runs.is_dir() and runs_target is not None:
        for source in sorted(runs.rglob("*")):
            if source.is_file() and _copy_new(source, runs_target / source.relative_to(runs), folder):
                copied.append(str(runs_target / source.relative_to(runs)))
    # The agents' prompts: an edited one comes along as the person's customised copy (advanced);
    # an unedited one stays behind (the app reads its own file). (The retired note taker's prompt,
    # and the old "Your notes" that belonged to it, stay behind too.)
    record_changed = False
    for name in pathlist.AGENT_SLOTS:
        target = resolver.copy_path(name)
        if resolver.is_overridden(name) or target is None or target.exists() or not pathlist._inside(target, folder):
            continue
        skill = _old_skill(old, name)
        if skill is None:
            continue
        text = pathlist._normalise(skill.read_text(encoding="utf-8-sig"))
        target.parent.mkdir(parents=True, exist_ok=True)
        pathlist.write_text_atomic(target, text)
        record["slots"].setdefault(name, {}).update({"base": pathlist._hash(pathlist.shipped_text(name)), "seeded": True})
        record_changed = True
        copied.append(str(target))
    if record_changed:
        pathlist.save_record(record, folder)
    return {"copied": copied}


def _copy_new(source: Path, target: Path, folder: Path) -> bool:
    """Copies one file only if the target doesn't exist. Folders are only made inside `folder`."""
    if target.exists():
        return False
    if not target.parent.is_dir():
        if not pathlist._inside(target.parent, folder):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, target)
    except OSError:
        return False
    return True


# ---- Leftovers: what older versions put in places WikiApp no longer uses ---------------------------

def find_leftovers(folder: Path | None = None) -> list[dict]:
    """[{path, kind, note}] for the old data folder, the old copies of the agents' prompts in
    Claude Code's skills folder, each wiki's old .wiki/index.md, and template samples the app
    once copied into a wiki. Nothing here is used any more; the person decides what to delete."""
    old = old_locations()
    out = []
    data = old.get("data")
    if data and Path(data).is_dir():
        out.append({"path": str(data), "kind": "old_app_folder",
                    "note": "WikiApp's old private folder. What it held was copied into the new one."})
    if old.get("skills"):
        for agent_id in OLD_SKILL_IDS:
            skill = Path(old["skills"]) / agent_id / "SKILL.md"
            if skill.is_file():
                out.append({"path": str(skill.parent), "kind": "old_skill",
                            "note": "An old copy of an agent's prompt, made a Claude Code skill by an older WikiApp. "
                                    "WikiApp no longer reads it; Claude Code lists it as a skill until it's deleted."})
    for wiki in pathlist.read_workspace(folder):
        root = Path(wiki["root"])
        index = root / ".wiki" / "index.md"
        if index.is_file():
            out.append({"path": str(index), "kind": "old_index",
                        "note": f"The {wiki['alias']} wiki's old index, written by an older WikiApp. Indexes are now kept in the private folder."})
        for slot, relative in (("template.sample-note", "Templates/Notes/Sample note.md"),
                               ("template.sample-page", "Templates/Pages/Sample page.md")):
            sample = root / relative
            try:
                same = sample.is_file() and pathlist._normalise(sample.read_text(encoding="utf-8-sig")) == pathlist.shipped_text(slot)
            except (OSError, UnicodeDecodeError):
                same = False
            if same:
                out.append({"path": str(sample), "kind": "seeded_template",
                            "note": f"A sample template an older WikiApp copied into the {wiki['alias']} wiki, unchanged since."})
    return out


def read_leftovers() -> list[dict]:
    folder = pathlist.app_folder()
    if folder is None:
        return []
    try:
        items = json.loads((folder / LEFTOVERS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return items if isinstance(items, list) else []


def dismiss_leftovers() -> None:
    """The person has seen the list: it isn't shown again."""
    folder = pathlist.require_app_folder()
    pathlist.write_text_atomic(folder / LEFTOVERS_FILE, "[]\n")


# ---- Choosing, moving, adopting ---------------------------------------------------------------------

def first_run_state(candidate: str | None = None) -> dict:
    """candidate: a place being considered (None: the chosen folder, or the suggested one; "" is
    checked like any typed text, and is not valid). valid/error say whether it can be used."""
    folder = pathlist.app_folder()
    if candidate is not None:
        target, error = check_candidate(candidate)
    else:
        target = folder if folder is not None else pathlist.suggested_folder()
        error = "" if target.parent.is_dir() else f"The folder {target.parent} doesn't exist."
    return {
        "chosen": folder is not None,
        "location": str(folder) if folder else None,
        "location_exists": bool(folder and folder.is_dir()),
        "from_env": pathlist.from_env(),
        "pointer_file": str(pathlist.pointer_file()),
        "suggested": str(pathlist.suggested_folder()),
        "valid": not error,
        "error": error,
        "preview": preview(target) if target is not None else None,
        "wiki_roots": wiki_roots(),
        "leftovers": read_leftovers(),
        "agentlib": agentlib_status(),
    }


def choose_location(chosen: str) -> dict:
    """The first start: the person picked a place. Makes the .wiki folder there (or uses the one
    already there), copies in what older versions left, copies in the shipped prompts and templates
    where missing, and records the place in the pointer file. Nothing already there is overwritten."""
    if pathlist.from_env():
        raise ValueError("WIKIAPP_DATA_DIR is set, so it decides where the private folder is.")
    current = pathlist.app_folder()
    if current is not None and current.is_dir():
        raise ValueError("A place is already chosen. Use Move or Adopt to change it.")
    folder, error = check_candidate(chosen)
    if error:
        raise (PathMissing if folder is not None and not folder.parent.is_dir() else ValueError)(error)
    folder.mkdir(exist_ok=True)
    had_list = (folder / LEFTOVERS_FILE).exists()   # an adopted folder's own list is kept as it is
    copied = migrate(folder)["copied"]
    created = pathlist.sync_slots(folder)           # may list an older layout's edited copies
    if not had_list:
        listed = created.get("leftovers") or []
        pathlist.write_text_atomic(folder / LEFTOVERS_FILE,
                                   json.dumps(find_leftovers(folder) + listed, indent=1, ensure_ascii=False) + "\n")
    _write_pointer(folder)
    _settle_roles()
    return {**first_run_state(), "copied": copied, "created": created["created"]}


def _settle_roles() -> None:
    """Saves the wiki roles once a private folder is chosen or adopted: an older installation's
    settings (migrated or already there) give its roles; a fresh folder saves none, so every wiki
    opened from then on starts as view only (pathlist.wiki_roles)."""
    try:
        pathlist.wiki_roles(persist=True, upgrade=True)
    except (OSError, PathMissing):
        pass


def relocate(new_path: str, mode: str) -> dict:
    """Changes where the private folder is. mode "move": its contents go to the new place, which
    must be empty (or not there yet), and the old folder is removed. mode "adopt": the folder
    already at the new place is used as it is (missing prompts and templates are filled in), and
    the old one is left alone. The two are never merged."""
    if mode not in ("move", "adopt"):
        raise ValueError('mode must be "move" or "adopt".')
    if pathlist.from_env():
        raise ValueError("WIKIAPP_DATA_DIR is set, so it decides where the private folder is.")
    current = pathlist.app_folder()
    target = pathlist.folder_for(new_path)
    if current is not None and pathlist._norm_path(target) == pathlist._norm_path(current):
        raise ValueError("That's where the folder is already.")
    left_behind = []
    if mode == "adopt":
        if not target.is_dir():
            raise PathMissing(f"There's no {pathlist.FOLDER_NAME} folder at {target.parent} to adopt.")
        pathlist.sync_slots(target)
        _write_pointer(target)
        _settle_roles()
    else:
        current = pathlist.require_app_folder()
        if pathlist._inside(target, current):
            raise ValueError("The new place can't be inside the folder itself.")
        if not target.parent.is_dir():
            raise PathMissing(f"The folder {target.parent} doesn't exist.")
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError(f"{target} already has files in it. Choose Adopt to use them, or pick an empty place.")
        shutil.copytree(current, target, dirs_exist_ok=True)
        record = pathlist.load_record(target)
        moved = False
        for name, value in list(record["overrides"].items()):
            if name != "notes_folder" and value and pathlist._inside(Path(value), current):
                record["overrides"][name] = str(target / Path(value).resolve().relative_to(current.resolve()))
                moved = True
        if moved:
            pathlist.save_record(record, target)
        _write_pointer(target)

        def note(_function, path, _error):
            left_behind.append(str(path))   # locked or in use: left for the person to delete
        if sys.version_info >= (3, 12):
            shutil.rmtree(current, onexc=note)
        else:
            shutil.rmtree(current, onerror=note)
    return {**first_run_state(), "left_behind": left_behind}


def startup() -> dict:
    """Each start. With a folder chosen and there, the prompt and template copies are brought up
    to date (sync_slots). A folder named by WIKIAPP_DATA_DIR is made if missing (the developer asked
    for it); a chosen folder that has gone is reported, never made again."""
    folder = pathlist.app_folder()
    if folder is None:
        return {"chosen": False}
    if not folder.is_dir() and pathlist.from_env():
        folder.mkdir(parents=True, exist_ok=True)
    if not folder.is_dir():
        return {"chosen": True, "missing": True}
    return {"chosen": True, "missing": False, **pathlist.sync_slots(folder)}


def _write_pointer(folder: Path) -> None:
    pointer = pathlist.pointer_file()
    if not pointer.parent.is_dir():
        raise PathMissing(f"The folder {pointer.parent} doesn't exist.")
    pathlist.write_text_atomic(pointer, str(folder) + "\n")


# ---- agentlib ---------------------------------------------------------------------------------------

def _setup_module():
    if str(APP_FILES) not in sys.path:
        sys.path.append(str(APP_FILES))
    import setup
    return setup


def agentlib_status() -> dict:
    """{"path", "found": [paths], "installed", "message"}: message says why the AI features are off."""
    found = pathlist.find_agentlib()
    overridden = bool(pathlist.load_record()["overrides"].get("agentlib")) if pathlist.app_folder() else False
    folder = pathlist.path("agentlib")
    installed = pathlist.agentlib_installed()
    message = ""
    if not installed:
        if overridden and (folder is None or not pathlist.is_agentlib_folder(folder)):
            message = f"AI features are off: the agentlib folder set in Paths isn't there any more ({folder})."
        elif folder is None and not found:
            message = ("AI features are off: the agentlib library wasn't found in the folders next to this app's folder "
                       "(or one level inside them). Set its folder in Paths.")
        elif folder is None:
            message = ("AI features are off: more than one agentlib library was found ("
                       + "; ".join(str(p) for p in found) + "). Choose one in Paths.")
        else:
            try:
                note = _setup_module().agentlib_note()
            except Exception:
                note = ""
            message = note or f"AI features are off: agentlib is at {folder} but isn't installed yet. Restart WikiApp to install it."
    return {"path": str(folder) if folder else "", "found": [str(p) for p in found], "installed": installed, "message": message}


def install_agentlib() -> dict:
    """Installs the agentlib folder from the path list into the app's Python (editable, so the
    library is never copied). Takes a while the first time: it brings in the Claude Agent SDK.
    -> {"ok", "message"}"""
    folder = pathlist.path("agentlib")
    if folder is None or not pathlist.is_agentlib_folder(folder):
        return {"ok": False, "message": agentlib_status()["message"] or "No agentlib folder is set."}
    setup = _setup_module()
    ok, message = setup.install_agentlib(setup.venv_python(), folder)
    if ok:
        setup.mark_current()
    return {"ok": ok, "message": message}


# ---- Is the engine set up, and does it answer? (agentlib's connection check) -----------------------

STATUS_FIELDS = ("ok", "method", "summary", "setup_file", "setup_doc", "problems", "notes")


def connection_status(engine: str | None = None) -> dict:
    """How this person signs in to the engine, from agentlib's own setup (setup/local.toml). Free:
    sends nothing. Never holds secret values.
    -> {engine, ok, method, summary, setup_file, setup_doc, problems, notes}"""
    engine = engine or pathlist.get_engine_settings()["engine"]
    if not pathlist.agentlib_installed():
        message = agentlib_status()["message"] or "agentlib isn't installed."
        return {"engine": engine, "ok": False, "method": "", "summary": message, "setup_file": None,
                "setup_doc": None, "problems": [message], "notes": []}
    try:
        import agentlib
        status = agentlib.connection_status(engine)
    except Exception as error:   # a broken setup file, an unknown engine...
        return {"engine": engine, "ok": False, "method": "", "summary": str(error), "setup_file": None,
                "setup_doc": None, "problems": [str(error)], "notes": []}
    return {"engine": engine, **{key: getattr(status, key) for key in STATUS_FIELDS}}


def test_connection(engine: str | None = None) -> dict:
    """agentlib's connection check: ONE tiny real request on the engine's cheapest model (a fraction
    of a cent on Claude). Never raises. -> {engine, ok, model, cost_usd, error, fix, report}"""
    engine = engine or pathlist.get_engine_settings()["engine"]
    if not pathlist.agentlib_installed():
        message = agentlib_status()["message"] or "agentlib isn't installed."
        return {"engine": engine, "ok": False, "model": None, "cost_usd": 0.0, "error": message,
                "fix": "Install agentlib (see Settings), then try again.", "report": message}
    try:
        import agentlib
        result = agentlib.check_connection_sync(engine)
    except Exception as error:
        return {"engine": engine, "ok": False, "model": None, "cost_usd": 0.0, "error": str(error), "fix": None,
                "report": str(error)}
    return {"engine": engine, "ok": result.ok, "model": result.model, "cost_usd": result.cost_usd,
            "error": result.error, "fix": result.fix, "report": result.report()}


# ---- Opening an entry in the system's own app ------------------------------------------------------

def open_path(name: str) -> dict:
    """Opens a path-list entry: a file in its default app, a folder in the file manager.
    -> {"ok": True} or {"ok": False, "error"}"""
    try:
        entry = pathlist.describe(name)
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    if not entry["path"] or entry["kind"] == "relative_folder":
        return {"ok": False, "error": "That entry has no single place to open."}
    target = Path(entry["path"])
    if not target.exists():
        return {"ok": False, "error": f"{target} doesn't exist" + (" yet." if entry["state"] == "not_created" else ".")}
    try:
        system_open(target)
    except OSError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True}


def system_open(target: Path) -> None:
    """The system's default app for a file, the file manager for a folder. Tests replace this."""
    if os.name == "nt":
        os.startfile(str(target))
    else:
        import subprocess
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])
