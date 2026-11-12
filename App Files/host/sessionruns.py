"""Session and note capture, and review: the Ingest view's Notes, Sessions and Review tabs.

Each request runs sessions/sb.py (see sessions/INTEGRATION.md) in this app's Python with no
window, and returns the JSON it prints. sb.py does all the work: it lists the Claude Code
sessions that haven't been captured, and captures one into the chosen personal wiki as a
session note filed under topics. It refuses to write to a folder that isn't the personal wiki
(the wiki whose role is "personal" in Settings; see pathlist.wiki_roles), so a wrong choice here
can't touch a team or view-only wiki.

Several captures may run at once (each page call has its own thread); sb.py locks its writes.
"""

import json
import os
import re
import subprocess
import threading
from pathlib import Path

from ingestruns import console_python

APP_DIR = Path(__file__).resolve().parent.parent
SB_SCRIPT = APP_DIR / "sessions" / "sb.py"


class SessionRuns:
    def __init__(self):
        self._processes = set()
        self._lock = threading.Lock()

    def run(self, command, root, extra=(), timeout=120):
        """Runs `sb.py <command> --json --personal <root> ...` and returns its result."""
        if not root or not Path(root).is_dir():
            raise ValueError("That folder isn't there any more.")
        cmd = [str(console_python()), "-X", "utf8", str(SB_SCRIPT), command, "--json", "--personal", str(root), *extra]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(cmd, cwd=str(SB_SCRIPT.parent), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **options)
        with self._lock:
            self._processes.add(process)
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(process)
            raise RuntimeError("It took too long and was stopped.")
        finally:
            with self._lock:
                self._processes.discard(process)
        try:
            result = json.loads(out)
        except ValueError:
            raise RuntimeError((err.strip().splitlines() or out.strip().splitlines() or ["sb.py failed."])[-1])
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"])
        return result

    def status(self, root):
        return self.run("status", root, timeout=30)

    def setup(self, root):
        """Set up: the personal wiki's pages. -> status plus "created": exactly what was made in the
        wiki ("Sessions/", "promotion-queue.md", "index.md"; never WIKI.md in the app)."""
        created = self.run("init", root, timeout=30).get("created") or []
        return {**self.status(root), "created": created}

    def list(self, root, days=None, include_done=False):
        extra = (["--days", str(int(days))] if days else []) + (["--all"] if include_done else [])
        return self.run("list", root, extra, timeout=180)

    def ingest(self, root, session_id, force=False, model=None):
        """One request to the executive assistant (Haiku 5.5 unless another model is picked), usually 20 to 40 seconds.
        A session already captured and unchanged since is not sent again (status "unchanged")."""
        extra = [_session_id(session_id), "--only-new"] + (["--force"] if force else []) + _model(model)
        return self.run("ingest", root, extra, timeout=900)

    # ---- The Notes tab: the person's notes, captured into the personal wiki like sessions ----

    def capture_notes(self, root, paths, model=None, post_event=None):
        """Captures notes one after another (each is shown the topics made so far), one request to
        the executive assistant each. A note captured before and unchanged since is not sent again.
        Events: "notesCapture" {root, path, index, total, status: "running" | "done" | "error",
        result?} for each note, then "notesCaptureDone" {root, results}.
        -> {"results": [{path, status, title, topics, warnings, conflicts, error?...}]}"""
        root = personal_root(root)
        paths = _note_paths(paths)
        emit = post_event or (lambda name, data: None)
        results = []
        for index, path in enumerate(paths):
            emit("notesCapture", {"root": root, "path": path, "index": index, "total": len(paths), "status": "running"})
            try:
                result = self.run("capture-note", root, _model(model) + ["--", path], timeout=900)
                result["path"] = path  # as the page sent it
                status = "done"
            except Exception as error:
                result = {"path": path, "status": "error", "error": str(error) or type(error).__name__,
                          "title": Path(path).stem, "topics": [], "warnings": [], "conflicts": []}
                status = "error"
            results.append(result)
            emit("notesCapture", {"root": root, "path": path, "index": index, "total": len(paths), "status": status, "result": result})
        emit("notesCaptureDone", {"root": root, "results": results})
        return {"results": results}

    def notes_status(self, root, paths):
        """Each note's capture status: "new", "changed" (edited since it was captured) or
        "captured". Worked out from the notes and the ledger; no request to Claude."""
        root = personal_root(root)
        out = []
        for chunk in _chunks(_note_paths(paths)):
            out += self.run("notes-status", root, ["--", *chunk], timeout=60)
        return out

    def list_conflicts(self, root):
        """Conflicts between notes and sessions, waiting for the person: [{id, topic, note_text,
        session_text, session_ref, note_ref, found, status}]."""
        return self.run("conflicts", personal_root(root), timeout=30)

    def resolve_conflict(self, root, conflict_id, resolution):
        if not isinstance(conflict_id, str) or not re.fullmatch(r"c-[0-9a-f]{10}", conflict_id):
            raise ValueError("Bad conflict id.")
        if resolution not in ("keep_note", "accept_session", "dismiss"):
            raise ValueError("Bad resolution.")
        return self.run("resolve-conflict", personal_root(root), [conflict_id, resolution], timeout=60)

    def skip(self, root, session_id):
        return self.run("skip", root, [_session_id(session_id), "--reason", "Skipped in WikiApp."], timeout=30)

    # ---- The Review tab: the wiki reviewer ----

    def review_list(self, root):
        """Every topic, the ones due for review first."""
        return self.run("review-list", root, ["--all"], timeout=60)

    def review(self, root, topic, model=None):
        """One request to the wiki reviewer (Sonnet 5.5 unless another model is picked): it rewrites the topic page's current state."""
        result = self.run("review", root, [_session_id(topic)] + _model(model), timeout=900)
        if result.get("errors"):
            raise RuntimeError(result["errors"][0]["error"])
        return result["reviewed"][0]

    def folders_suggest(self, root):
        """Tags enough topics share to become a folder. Worked out from the pages; no request to Claude."""
        return self.run("folders-suggest", root, timeout=60)

    def folders_apply(self, root, folder):
        topics = [_session_id(t) for t in folder.get("topics") or []]
        extra = ["--tag", _session_id(folder.get("tag")), "--topics", ",".join(topics), "--title", str(folder.get("title") or "")]
        return self.run("folders-apply", root, extra, timeout=60)

    def merges_suggest(self, root, model=None):
        """One request to Claude: topics that are the same work, tags that are the same theme."""
        return self.run("merge-suggest", root, _model(model), timeout=900)

    def merges_apply(self, root, merge):
        kind = merge.get("kind")
        if kind not in ("topic", "tag"):
            raise ValueError("Bad merge.")
        names = [_session_id(m) for m in merge.get("merge") or []]
        return self.run("merge-apply", root, ["--kind", kind, "--keep", _session_id(merge.get("keep")), "--merge", ",".join(names)], timeout=60)

    def stop(self):
        """Ends every capture still running (the app is closing)."""
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            _kill(process)


def personal_root(root=None):
    """The personal wiki's folder: the one given, or else the open wiki whose role is "personal"
    (Settings; pathlist.wiki_roles). sb.py refuses a given folder that isn't the personal wiki."""
    if isinstance(root, str) and root:
        return root
    import pathlist
    found = pathlist.wiki_with_role("personal")
    if not found:
        raise ValueError("Choose your personal wiki in Settings first.")
    return found["root"]


def _note_paths(paths):
    """The notes' full paths, checked: Markdown files that exist, inside one of the open folders."""
    if not isinstance(paths, list) or not paths:
        raise ValueError("Give the notes to capture.")
    import pathlist
    roots = [os.path.normcase(os.path.abspath(w["root"])) for w in pathlist.read_workspace()]
    out = []
    for value in paths:
        if not isinstance(value, str) or not os.path.isabs(value):
            raise ValueError("A note must be given by its full path.")
        full = os.path.abspath(value)
        if os.path.splitext(full)[1].lower() not in (".md", ".markdown") or not os.path.isfile(full):
            raise ValueError(f"Not a note: {value}")
        norm = os.path.normcase(full)
        if roots and not any(norm.startswith(r.rstrip("\\/") + os.sep) for r in roots):
            raise ValueError(f"That note isn't in one of the open folders: {value}")
        if value not in out:
            out.append(value)
    return out


def _chunks(paths, limit=20000):
    """Paths in groups short enough for one command line."""
    group, size = [], 0
    for path in paths:
        if group and size + len(path) > limit:
            yield group
            group, size = [], 0
        group.append(path)
        size += len(path) + 3
    if group:
        yield group


def _model(value):
    """The --model argument for a model picked in the app, or nothing for the default."""
    if not value:
        return []
    if not isinstance(value, str) or not all(c.isalnum() or c in "-_.[]" for c in value):
        raise ValueError("Bad model id.")
    return ["--model", value]


def _session_id(value):
    if not isinstance(value, str) or not value or not all(c.isalnum() or c in "-_" for c in value):
        raise ValueError("Bad session id.")
    return value


def _kill(process):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                           capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass
