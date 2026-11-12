"""WikiApp host for Windows and macOS: a window that runs the HTML/JS app in ../app, using
pywebview (the Edge web view on Windows, WebKit on macOS). The page talks to it through JSON
messages; see app/js/bridge.js for the other side.

Start it with WikiApp.cmd (Windows) or WikiApp.command (macOS), which set up the Python
environment first. Folders given on the command line join the workspace.

Per-user data lives in one private folder named .wiki, at a place the person chooses on the first
start (see appfolder.py); every path in it, and every other path the app uses, comes from the
path list (pathlist.py). Until a place is chosen nothing is written. WIKIAPP_DATA_DIR names the
folder directly (developer and test runs). WIKIAPP_DEBUG_PORT=<port> turns on remote debugging
(Windows).
"""

import ctypes
import hashlib
import http.server
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

os.environ.setdefault("PYWEBVIEW_LOG", "warning")  # read when pywebview is imported
import webview

import appfolder
import notefiles
import pathlist
from ingestruns import IngestRuns, write_atomic
from sessionruns import SessionRuns

APP_FILES = Path(__file__).resolve().parent.parent
APP_DIR = APP_FILES / "app"
ICON = Path(__file__).resolve().parent / "app.ico"
APP_ID = "WikiApp.WikiApp"  # Windows taskbar identity: groups and pins the window as WikiApp
BACKGROUND = "#1e1e1e"
CLOSE_WAIT = 4.0  # seconds a page that doesn't answer "closeRequested" gets; a click after that closes
MIME = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
        ".json": "application/json", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2"}


# ---- Settings file ----------------------------------------------------------------------------
# The page's settings (open folders, signature, colors, last view...) as one JSON object.
# See app/js/persist.js.

def settings_script():
    """Served as settings.js: the saved settings, the mark that tells the page it runs in the app
    rather than a plain browser, and whether a place for the private folder has been chosen (if
    not, the page asks first: see firstRunState)."""
    saved = "null"
    file = pathlist.path("settings")
    try:
        text = file.read_text(encoding="utf-8-sig").strip() if file else ""
        if text and isinstance(json.loads(text), dict):  # only hand over a JSON object
            saved = text
    except (OSError, ValueError):
        pass  # no file yet, or a damaged one: the page starts from its defaults
    chosen = "true" if pathlist.is_chosen() else "false"
    return (f"window.__wikiappHost = 'python';\nwindow.__wikiappFolderChosen = {chosen};\n"
            f"window.__savedSettings = {saved};\n")


def save_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    file = pathlist.path("settings")
    if file is None:  # no place chosen yet: nothing is written anywhere
        raise pathlist.PathMissing("Choose where WikiApp keeps its private folder first.")
    write_atomic(file, json.dumps(settings, ensure_ascii=False))

# Older versions' data (~/.wikiapp, and what the retired Windows-only version left in
# %LOCALAPPDATA%\WikiApp and %TEMP%\WikiApp\ingest-runs) is copied in when the person chooses a
# place for the private folder: appfolder.migrate.


# ---- Serving the app ---------------------------------------------------------------------------
# The page is served on 127.0.0.1 under a random secret path, so nothing else on the computer
# (another program, a web page in a browser) can read its files or settings. The page's writes
# never go through this server: they use the pywebview bridge below.

class AppServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host):
        self.token = secrets.token_urlsafe(16)
        self.wikiapp = host
        super().__init__(("127.0.0.1", 0), AppRequest)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_port}/{self.token}/"


class AppRequest(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        prefix = f"/{self.server.token}/"
        path = urllib.parse.unquote(self.path.split("?", 1)[0])
        if not path.startswith(prefix):
            return self._send(404, b"", "text/plain")
        relative = path[len(prefix):]
        if relative == "settings.js":
            return self._send(200, settings_script().encode("utf-8"), "text/javascript")
        if relative == "__focus":  # another start of the app asks this one to come forward
            self.server.wikiapp.bring_to_front()
            return self._send(200, b"ok", "text/plain")
        file = (APP_DIR / relative).resolve()
        if APP_DIR.resolve() not in file.parents or not file.is_file():
            return self._send(404, b"", "text/plain")
        kind = MIME.get(file.suffix.lower()) or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
        self._send(200, file.read_bytes(), kind)

    def _send(self, status, body, kind):
        self.send_response(status)
        charset = "; charset=utf-8" if kind.startswith("text/") or kind == "application/json" else ""
        self.send_header("Content-Type", kind + charset)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # an edited file shows up on the next reload
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# ---- One window --------------------------------------------------------------------------------
# Starting the app again brings the open window to the front instead of opening a second copy.

def ask_running_copy_to_focus():
    """True when another copy is running (it was asked to come forward). It is found through
    instance.json in the private folder, or, before a place for that folder is chosen (the first
    start), through the guard port below."""
    try:
        info = json.loads(pathlist.path("instance").read_text(encoding="utf-8"))
        if os.name == "nt":
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # let it take the foreground
        url = f"http://127.0.0.1:{int(info['port'])}/{info['token']}/__focus"
        with urllib.request.urlopen(url, timeout=2) as reply:
            if reply.read() == b"ok":
                return True
    except (OSError, ValueError, KeyError, AttributeError):  # AttributeError: no place chosen yet
        pass
    try:
        if os.name == "nt":
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        with urllib.request.urlopen(f"http://127.0.0.1:{guard_port()}{GUARD_PATH}", timeout=2) as reply:
            return reply.read() == GUARD_REPLY
    except (OSError, ValueError):
        return False


# During the first start there is no private folder, so no instance.json. A copy started then
# listens on a fixed local port worked out from where the app is; it answers one request (come
# forward) and nothing else. Nothing is written to disk. If the port is taken, there's no guard.
GUARD_PATH = "/wikiapp-focus"
GUARD_REPLY = b"wikiapp-ok"


def guard_port():
    digest = hashlib.sha256(os.path.normcase(str(APP_FILES)).encode("utf-8")).digest()
    return 20000 + int.from_bytes(digest[:2], "big") % 20000


class GuardRequest(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == GUARD_PATH
        if ok:
            self.server.wikiapp.bring_to_front()
        body = GUARD_REPLY if ok else b""
        self.send_response(200 if ok else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class GuardServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = False  # never share the port (Windows would let a second copy bind it too)
    daemon_threads = True


def start_guard(host):
    """The first-start guard server, or None when the port is taken."""
    try:
        server = GuardServer(("127.0.0.1", guard_port()), GuardRequest)
    except OSError:
        return None
    server.daemon_threads = True
    server.wikiapp = host
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---- Messages from the page --------------------------------------------------------------------
# Request: { id, cmd, args }    Reply: { id, ok, result | error }    Events: { event, data }

class Api:
    """What pywebview exposes to the page: one method. pywebview runs each call on its own thread."""

    def __init__(self, host):
        self._host = host

    def call(self, msg):
        msg = msg if isinstance(msg, dict) else {}
        reply = {"id": msg.get("id")}
        try:
            reply["result"] = self._host.dispatch(msg.get("cmd"), msg.get("args") or {})
            reply["ok"] = True
        except Exception as error:  # every failure goes back to the page as a message
            reply["ok"] = False
            reply["error"] = str(error) or type(error).__name__
        return reply


class Host:
    def __init__(self, startup_folders):
        self.startup_folders = startup_folders
        self.window = None
        self.watcher = notefiles.Watcher(lambda root: self.post_event("vaultChanged", {"root": root}))
        self.ingest = IngestRuns(self.post_event)
        self.sessions = SessionRuns()
        self.server = AppServer(self)
        self.bounds = None  # the window's last normal (not maximized) x, y, width, height
        self.maximized = False
        self.minimized = False
        self.page_ready = False      # the page has loaded and can be asked before closing
        self.close_allowed = False   # the page said yes (closeWindow)
        self.close_asked = 0.0       # when the page was asked (0: not asked)
        self.close_asking = False    # the page is asking the user about unsaved text

    def dispatch(self, cmd, args):
        if cmd == "getStartupFolders":
            return self.startup_folders
        if cmd == "pickFolder":
            chosen = self.window.create_file_dialog(webview.FileDialog.FOLDER)
            return chosen[0] if chosen else None
        if cmd == "pickFile":  # start: a folder (or a file in it) to open the picker at
            return self.pick_file(args.get("start"))
        if cmd == "scanVault":  # watch: false previews a folder in the Add folder window
            vault = notefiles.scan(text(args, "path"))
            if args.get("watch") is not False:
                self.watcher.watch(vault["root"])
            return vault
        if cmd == "unwatchFolder":
            self.watcher.unwatch(text(args, "path"))
            return None
        if cmd == "editLines":  # fails without writing if those lines changed on disk
            notefiles.edit_lines(text(args, "root"), text(args, "path"), int(args["start"]),
                                 lines(args, "expect"), lines(args, "replace"))
            return None
        if cmd == "appendLines":
            notefiles.append_lines(text(args, "root"), text(args, "path"), lines(args, "lines"), lines(args, "header"))
            return None
        if cmd == "readText":
            return notefiles.read_text(text(args, "root"), text(args, "path"))
        if cmd == "createNote":
            notefiles.create_note(text(args, "root"), text(args, "path"), lines(args, "lines"))
            return None
        if cmd == "saveSettings":
            save_settings(args.get("settings"))
            return None
        if cmd == "openExternal":
            open_external(args.get("url"))
            return None
        if cmd == "setTitle":  # the page's document title, for the window and the taskbar/Dock
            self.page_ready = True  # the page sends it as soon as it loads
            self.window.set_title(str(args.get("title") or "WikiApp"))
            return None
        if cmd == "closeWindow":  # the page's answers to "closeRequested"
            answer = args.get("answer")
            if answer == "asking":    # it's alive and asking the user: wait as long as that takes
                self.close_asking = True
            elif answer == "no":      # the user kept the window open: the next click asks again
                self.close_asking = False
                self.close_asked = 0.0
            else:                     # nothing left unsaved
                self.close_allowed = True
                self.window.destroy()
            return None
        return self.dispatch_paths(cmd, args)

    def dispatch_paths(self, cmd, args):
        """The private folder, the path list, prompt files and engine settings (pathlist.py, appfolder.py)."""
        if cmd == "firstRunState":  # candidate: a place being considered (checked: valid, error), previewed
            candidate = args.get("candidate")
            return appfolder.first_run_state(str(candidate) if "candidate" in args and candidate is not None else None)
        if cmd == "chooseFolder":  # the first start: the place the person picked (the .wiki folder or its parent)
            result = appfolder.choose_location(text(args, "path"))
            self.write_instance()
            return result
        if cmd == "relocateFolder":  # mode: "move" | "adopt"
            if self.ingest.running():
                raise RuntimeError("Wait for the ingest run to finish first.")
            result = appfolder.relocate(text(args, "path"), text(args, "mode"))
            self.write_instance()
            return result
        if cmd == "dismissLeftovers":
            appfolder.dismiss_leftovers()
            return None
        if cmd == "listPaths":
            return pathlist.list_paths()
        if cmd == "setPath":  # path "" puts the entry back to its default
            entry = pathlist.set_path(text(args, "name"), args.get("path") or "")
            if entry["name"] == "agentlib" and entry["exists"]:
                self.install_agentlib()  # in the background; an "agentlibInstalled" event follows
                entry = {**entry, "installing": True}
            return entry
        if cmd == "customisePrompt":  # an agent's prompt: make its editable copy in .wiki/prompts
            return pathlist.customise_prompt(text(args, "name"))
        if cmd == "resetPrompt":  # a note template: the shipped text back; an agent's prompt: delete the copy
            return pathlist.reset_prompt(text(args, "name"))
        if cmd == "readPathFile":  # a prompt or template slot, or a wiki's rules file...
            return pathlist.read_file(text(args, "name"))
        if cmd == "writePathFile":  # expect: the text last read; refused if the file changed since
            expect = args.get("expect")
            return pathlist.write_file(text(args, "name"), text(args, "text"), expect if isinstance(expect, str) else None)
        if cmd == "openPath":  # a file in its default app, a folder in the file manager
            return appfolder.open_path(text(args, "name"))
        if cmd == "getEngineSettings":  # also each agent's model: engines.<engine>.models.<agent id>
            return pathlist.get_engine_settings()
        if cmd == "setEngineSettings":  # e.g. {engines: {claude: {models: {"wiki-reviewer": "claude-opus-5"}}}}
            return pathlist.set_engine_settings(args.get("settings"))
        if cmd == "setAgentModel":  # the same, for one agent: {agent, model}; model "" = the default
            return pathlist.set_agent_model(text(args, "agent"), args.get("model") or "")
        if cmd == "getWikiRoles":  # {roles: {alias: personal|team|view}, needs_team, needs_personal}
            return pathlist.wiki_roles(persist=True)
        if cmd == "setWikiRole":  # {alias, role}: also demoted (the alias that lost the role, or null)
            return pathlist.set_wiki_role(text(args, "alias"), text(args, "role"))
        if cmd == "getSessionsFilter":  # {min_turns, options: [0, 3, 5, 10, 20]}
            return pathlist.get_sessions_filter()
        if cmd == "setSessionsFilter":  # {min_turns}
            return pathlist.set_sessions_filter(args.get("min_turns"))
        if cmd == "connectionStatus":  # free: sends nothing
            return appfolder.connection_status()
        if cmd == "testConnection":  # ONE tiny real request (a fraction of a cent)
            return appfolder.test_connection()
        if cmd == "agentlibStatus":
            return appfolder.agentlib_status()
        if cmd == "installAgentlib":
            self.install_agentlib()
            return None
        return self.dispatch_ingest(cmd, args)

    def pick_file(self, start=None):
        folder = ""
        if isinstance(start, str) and start.strip():
            start_path = Path(start.strip())
            folder = str(start_path if start_path.is_dir() else start_path.parent)
            if not Path(folder).is_dir():
                folder = ""
        chosen = self.window.create_file_dialog(webview.FileDialog.OPEN, directory=folder)
        if not chosen:
            return None
        return chosen[0] if isinstance(chosen, (list, tuple)) else str(chosen)

    def install_agentlib(self):
        def work():
            try:
                result = appfolder.install_agentlib()
            except Exception as error:
                result = {"ok": False, "message": str(error)}
            self.post_event("agentlibInstalled", result)
        threading.Thread(target=work, daemon=True).start()

    def write_instance(self):
        """instance.json: how a second start of the app finds this one. Only once a place is chosen."""
        file = pathlist.path("instance")
        if file is None or not file.parent.is_dir():
            return
        try:
            write_atomic(file, json.dumps({"port": self.server.server_port, "token": self.server.token}))
        except (OSError, pathlist.PathMissing):
            pass

    def dispatch_ingest(self, cmd, args):
        """Ingest (see ingest/DESIGN.md). Progress comes back as "ingest" events."""
        if cmd == "ingestInfo":  # name: "promotion" (the only cards left; the Notes tab's are retired)
            return self.ingest.info(args.get("name") or "promotion")
        if cmd == "saveIngestState":
            self.ingest.save_state(text(args, "state"), args.get("name") or "promotion")
            return None
        if cmd == "agentsInfo":  # the four agents and their prompt files (Claude Code skills)
            return self.ingest.agents()
        if cmd == "saveAgentPrompt":
            self.ingest.save_agent(text(args, "id"), text(args, "text"))
            return None
        if cmd == "startIngest":
            return self.ingest.start(args.get("job"))
        if cmd == "reviseIngestCards":  # feedback: {cards: [{card, text}], accepted, rejected}
            self.ingest.revise(text(args, "runId"), args.get("feedback"))
            return None
        if cmd == "answerIngestQuestions":  # a promotion: answers {question id: text}
            self.ingest.answer(text(args, "runId"), args.get("answers"))
            return None
        if cmd == "listIngestModels":  # takes a few seconds: Claude Code starts and stops
            return self.ingest.models()
        if cmd == "cancelIngest":
            self.ingest.stop()
            return None
        if cmd == "runIngestSetup":
            self.ingest.open_setup()
            return None
        if cmd == "listIngestRuns":
            return self.ingest.list_runs(30)
        if cmd == "openIngestRun":
            folder = self.ingest.run_dir(text(args, "runId"))
            if folder.is_dir():
                open_folder(folder)
            return None
        return self.dispatch_sessions(cmd, args)

    def dispatch_sessions(self, cmd, args):
        """The Ingest view's Sessions tab (see sessions/INTEGRATION.md). root: the personal wiki's folder."""
        if cmd == "sessionsStatus":  # is the folder set up as a personal wiki, and what's in it
            return self.sessions.status(text(args, "root"))
        if cmd == "sessionsSetup":
            return self.sessions.setup(text(args, "root"))
        # {sessions: [rows with name, title, user_messages, subagents...], hidden_count, min_turns}
        if cmd == "sessionsList":  # Claude Code sessions not captured yet; takes a few seconds
            return self.sessions.list(text(args, "root"), args.get("days"), bool(args.get("all")))
        if cmd == "sessionsIngest":  # one request to Claude: 20 seconds to a couple of minutes
            return self.sessions.ingest(text(args, "root"), text(args, "id"), bool(args.get("force")), args.get("model"))
        if cmd == "sessionsSkip":
            return self.sessions.skip(text(args, "root"), text(args, "id"))
        if cmd == "reviewList":  # the Review tab: every topic, those due first
            return self.sessions.review_list(text(args, "root"))
        if cmd == "reviewTopic":  # one request to Claude
            return self.sessions.review(text(args, "root"), text(args, "topic"), args.get("model"))
        if cmd == "suggestFolders":  # tags that could become folders; no request to Claude
            return self.sessions.folders_suggest(text(args, "root"))
        if cmd == "applyFolder":  # moves the topic pages into the tag's folder
            return self.sessions.folders_apply(text(args, "root"), args.get("folder") or {})
        if cmd == "suggestMerges":  # one request to Claude; changes nothing
            return self.sessions.merges_suggest(text(args, "root"), args.get("model"))
        if cmd == "applyMerge":  # folds topics, or tags, into one
            return self.sessions.merges_apply(text(args, "root"), args.get("merge") or {})
        # The Notes tab: notes captured into the personal wiki like sessions. root may be left out:
        # the personal wiki picked in the app is used.
        if cmd == "captureNotes":  # one request to Claude per note; "notesCapture" events as each finishes
            return self.sessions.capture_notes(args.get("root"), args.get("paths"), args.get("model"), self.post_event)
        if cmd == "notesStatus":  # each note: "new", "changed" since it was captured, or "captured"; no request
            return self.sessions.notes_status(args.get("root"), args.get("paths"))
        if cmd == "listConflicts":  # notes and sessions that disagree, waiting for the person
            return self.sessions.list_conflicts(args.get("root"))
        if cmd == "resolveConflict":  # resolution: keep_note | accept_session | dismiss
            return self.sessions.resolve_conflict(args.get("root"), text(args, "id"), text(args, "resolution"))
        raise ValueError(f"Unknown command: {cmd}")

    def post_event(self, name, data):
        if self.window is None:
            return
        payload = json.dumps({"event": name, "data": data}, ensure_ascii=False)
        try:
            self.window.run_js(f"window.__wikiappReceive && window.__wikiappReceive({payload})")
        except Exception:
            pass  # the page is loading or the window is closing

    # ---- The window ----

    def run(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.write_instance()
        if not pathlist.is_chosen():
            self.guard = start_guard(self)  # the first start: no instance.json yet
        x, y, width, height, maximized = restore_placement()
        self.bounds = (x, y, width, height) if x is not None else None
        self.window = webview.create_window(
            "WikiApp", self.server.base_url + "index.html", js_api=Api(self),
            x=x, y=y, width=width, height=height, maximized=maximized, min_size=(640, 420),
            background_color=BACKGROUND, text_select=True, zoomable=True)
        events = self.window.events
        events.moved += self.on_moved
        events.resized += self.on_resized
        events.maximized += self.on_maximized
        events.minimized += self.on_minimized
        events.restored += self.on_restored
        events.closing += self.on_closing
        events.closed += self.on_closed
        events.shown += self.on_shown
        # debug=True allows F12 / Inspect for developer tools (and remote debugging, when asked for).
        # icon: the window's icon from the start (Windows), so the taskbar never shows Python's.
        # No storage_path: in private mode the web view keeps its profile in a new temporary folder
        # each run (so a window that just closed can't hold it), and nothing goes in .wiki.
        webview.start(debug=True, private_mode=True, icon=str(ICON) if ICON.exists() else None)

    def on_maximized(self):
        self.maximized, self.minimized = True, False

    def on_minimized(self):
        self.minimized = True

    def on_restored(self):
        if not self.minimized:  # back from maximized (from minimized, it returns to what it was)
            self.maximized = False
        self.minimized = False

    def on_moved(self, x, y):
        if self.bounds and not self.maximized and not self.minimized and x > -10000:  # minimized: -32000
            self.bounds = (x, y, self.bounds[2], self.bounds[3])

    def on_resized(self, width, height):
        if self.bounds and not self.maximized and not self.minimized and width > 200:
            self.bounds = (self.bounds[0], self.bounds[1], width, height)

    def on_shown(self):
        if self.bounds is None:
            self.bounds = (self.window.x, self.window.y, self.window.width, self.window.height)
        style_window(self.window)

    def on_closing(self):
        """The close button: first the page saves what's typed and asks about anything unsaved
        ("closeRequested"), then it answers closeWindow. If the page doesn't answer (it's broken
        or still loading), a second click after a few seconds closes anyway."""
        if self.page_ready and not self.close_allowed:
            if self.close_asking:
                return False  # the page is asking the user (returning False cancels this close)
            waited = time.monotonic() - self.close_asked
            if not self.close_asked or waited < CLOSE_WAIT:
                if not self.close_asked:
                    self.close_asked = time.monotonic()
                    # Not from here: this runs on the window's thread, which posting an event waits for.
                    threading.Thread(target=self.post_event, args=("closeRequested", {}), daemon=True).start()
                return False
            # The page never answered: close.
        save_placement(self.bounds, self.maximized)

    def on_closed(self):
        self.ingest.stop()
        self.sessions.stop()
        try:
            pathlist.path("instance").unlink()
        except (OSError, AttributeError):
            pass

    def bring_to_front(self):
        if self.window is None:
            return
        if self.minimized:
            self.window.restore()
        self.window.show()
        native = getattr(self.window, "native", None)
        try:
            if os.name == "nt" and native is not None:
                ctypes.windll.user32.SetForegroundWindow(native.Handle.ToInt64())
            elif sys.platform == "darwin":
                from AppKit import NSApplication
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass  # coming forward is a nicety


# ---- Window size and position, kept between runs ------------------------------------------------
# window.txt: "x,y,width,height,maximized". Ignored if it would put the window off screen.

def restore_placement():
    try:  # first start: 80% of the main screen, centered
        screen = webview.screens[0]
        default = (None, None, screen.width * 8 // 10, screen.height * 8 // 10, False)
    except Exception:
        default = (None, None, 1280, 800, False)
    try:
        parts = pathlist.path("window_placement").read_text(encoding="utf-8").strip().split(",")
        x, y, width, height = (int(p) for p in parts[:4])
    except (OSError, ValueError, AttributeError):  # AttributeError: no place chosen yet
        return default
    if width < 400 or height < 300:
        return default
    try:
        visible = any(min(x + width, s.x + s.width) - max(x, s.x) >= 200 and
                      min(y + height, s.y + s.height) - max(y, s.y) >= 100 for s in webview.screens)
    except Exception:
        visible = True
    if not visible:
        return default
    return x, y, width, height, len(parts) > 4 and parts[4] == "1"


def save_placement(bounds, maximized):
    file = pathlist.path("window_placement")
    if not bounds or file is None:
        return
    try:
        write_atomic(file, ",".join(str(int(v)) for v in bounds) + ("," + ("1" if maximized else "0")))
    except (OSError, pathlist.PathMissing):
        pass  # not worth failing the close over


def style_window(window):
    """Windows: a dark title bar to match the app (Windows 10 20H1+ / 11), and the taskbar
    identity that makes the window pinnable."""
    if os.name != "nt":
        return
    try:
        form = window.native
        hwnd = form.Handle.ToInt64()
        dark = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 20, ctypes.byref(dark), ctypes.sizeof(dark))
        from System import Action
        form.Invoke(Action(lambda: set_taskbar_identity(hwnd)))
    except Exception:
        pass  # looks only


def set_taskbar_identity(hwnd):
    """Without this, Windows sees a Python window it can't relaunch, so "Pin to taskbar" is
    missing. These properties name the app and give the command and icon a pinned button uses.
    Must run on the window's thread."""
    from win32com.propsys import propsys, pscon
    import pythoncom

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    command = f'"{pythonw}" "{Path(__file__).resolve()}"'
    store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
    for key, value in ((pscon.PKEY_AppUserModel_ID, APP_ID),
                       (pscon.PKEY_AppUserModel_RelaunchCommand, command),
                       (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "WikiApp"),
                       (pscon.PKEY_AppUserModel_RelaunchIconResource, f"{ICON},0")):
        store.SetValue(key, propsys.PROPVARIANTType(value, pythoncom.VT_LPWSTR))
    store.Commit()


def set_app_identity():
    """Windows: group the taskbar button as WikiApp rather than Python. macOS: the Dock icon."""
    try:
        if os.name == "nt":
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        elif sys.platform == "darwin" and ICON.exists():
            from AppKit import NSApplication, NSImage
            image = NSImage.alloc().initWithContentsOfFile_(str(ICON))
            if image is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        pass


# ---- Helpers -----------------------------------------------------------------------------------

def text(args, name):
    value = args.get(name)
    if not isinstance(value, str):
        raise ValueError("Missing argument: " + name)
    return value


def lines(args, name):
    value = args.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a list: " + name)
    return [str(item) for item in value]


def open_external(url):
    """Links in notes open in the default browser; the window only ever shows the app."""
    if isinstance(url, str) and url.lower().startswith(("http://", "https://", "mailto:")):
        webbrowser.open(url)


def open_folder(folder):
    if os.name == "nt":
        os.startfile(folder)
    elif sys.platform == "darwin":
        import subprocess
        subprocess.Popen(["open", str(folder)])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", str(folder)])


def setup_needed():
    """Started without a launcher (a pinned taskbar button): if requirements.txt changed since the
    last setup, hand over to the launcher, which shows the install and then starts the app."""
    sys.path.insert(0, str(APP_FILES))
    try:
        import setup
        if setup.is_current():
            return False
        launcher = APP_FILES.parent / ("WikiApp.cmd" if os.name == "nt" else "WikiApp.command")
        if os.name == "nt":
            os.startfile(launcher)
        else:
            import subprocess
            subprocess.Popen(["open", str(launcher)])
        return True
    except Exception:
        return False  # no launcher next to the app: start as it is
    finally:
        sys.path.remove(str(APP_FILES))


def main():
    startup_folders = [notefiles.full_path(arg) for arg in sys.argv[1:]]
    if not startup_folders and ask_running_copy_to_focus():
        return
    if setup_needed():
        return
    try:
        appfolder.startup()  # with a place chosen: the prompt and template copies, up to date
        pathlist.wiki_roles(persist=True, upgrade=True)  # an older setup's personal (and team) wiki, kept as roles
    except (OSError, pathlist.PathMissing):
        pass  # a read-only or unreachable folder: the app starts, and says so when it's needed
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    if os.environ.get("WIKIAPP_DEBUG_PORT"):
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["WIKIAPP_DEBUG_PORT"])
    set_app_identity()
    Host(startup_folders).run()


if __name__ == "__main__":
    main()
