"""WikiApp host for Windows and macOS: a window that runs the HTML/JS app in ../app, using
pywebview (WebView2 on Windows, WebKit on macOS). The page talks to it through JSON messages;
see app/js/bridge.js for the other side. It does what WikiApp.cs does, so the page works the
same under either host.

Start it with WikiApp.cmd (Windows) or WikiApp.command (macOS), which set up the Python
environment first. Folders given on the command line join the workspace.

Per-user data lives in ~/.wikiapp (or WIKIAPP_DATA_DIR): settings.json, window.txt, ingest/,
ingest-runs/ and instance.json. WIKIAPP_DEBUG_PORT=<port> turns on remote debugging (WebView2).
"""

import ctypes
import http.server
import json
import mimetypes
import os
import secrets
import shutil
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

os.environ.setdefault("PYWEBVIEW_LOG", "warning")  # read when pywebview is imported
import webview

import notefiles
from ingestruns import IngestRuns, write_atomic

APP_FILES = Path(__file__).resolve().parent.parent
APP_DIR = APP_FILES / "app"
ICON = Path(__file__).resolve().parent / "app.ico"
APP_ID = "WikiApp.WikiApp"  # Windows taskbar identity: groups and pins the window as WikiApp
DATA_DIR = Path(os.environ.get("WIKIAPP_DATA_DIR") or Path.home() / ".wikiapp")
SETTINGS_FILE = DATA_DIR / "settings.json"
PLACEMENT_FILE = DATA_DIR / "window.txt"
INSTANCE_FILE = DATA_DIR / "instance.json"
BACKGROUND = "#1e1e1e"
MIME = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
        ".json": "application/json", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2"}


# ---- Settings file ----------------------------------------------------------------------------
# The page's settings (open folders, signature, colors, last view...) as one JSON object.
# See app/js/persist.js.

def settings_script():
    """Served as settings.js: the saved settings, and which host the page runs in."""
    saved = "null"
    try:
        text = SETTINGS_FILE.read_text(encoding="utf-8-sig").strip()
        if isinstance(json.loads(text), dict):  # only hand over a JSON object
            saved = text
    except (OSError, ValueError):
        pass  # no file yet, or a damaged one: the page starts from its defaults
    return f"window.__wikiappHost = 'python';\nwindow.__savedSettings = {saved};\n"


def save_settings(settings):
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    write_atomic(SETTINGS_FILE, json.dumps(settings, ensure_ascii=False))


def migrate_from_windows_host():
    """First start on a PC that used WikiApp.exe: bring over its settings, Ingest data and past runs.
    Copies only; WikiApp.exe keeps its own."""
    if os.name != "nt" or SETTINGS_FILE.exists() or "WIKIAPP_DATA_DIR" in os.environ:
        return
    old = Path(os.environ.get("LOCALAPPDATA", "")) / "WikiApp"
    old_runs = Path(os.environ.get("TEMP", "")) / "WikiApp" / "ingest-runs"
    try:
        if (old / "settings.json").exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            for name in ("settings.json", "window.txt"):
                if (old / name).exists():
                    shutil.copy2(old / name, DATA_DIR / name)
            if (old / "ingest").is_dir():
                shutil.copytree(old / "ingest", DATA_DIR / "ingest", dirs_exist_ok=True)
            if old_runs.is_dir():
                shutil.copytree(old_runs, DATA_DIR / "ingest-runs", dirs_exist_ok=True)
    except OSError:
        pass  # not worth failing the start over


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
    try:
        info = json.loads(INSTANCE_FILE.read_text(encoding="utf-8"))
        if os.name == "nt":
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # let it take the foreground
        url = f"http://127.0.0.1:{int(info['port'])}/{info['token']}/__focus"
        with urllib.request.urlopen(url, timeout=2) as reply:
            return reply.read() == b"ok"
    except (OSError, ValueError, KeyError):
        return False


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
        self.ingest = IngestRuns(DATA_DIR, self.post_event)
        self.server = AppServer(self)
        self.bounds = None  # the window's last normal (not maximized) x, y, width, height
        self.maximized = False
        self.minimized = False

    def dispatch(self, cmd, args):
        if cmd == "getStartupFolders":
            return self.startup_folders
        if cmd == "pickFolder":
            chosen = self.window.create_file_dialog(webview.FileDialog.FOLDER)
            return chosen[0] if chosen else None
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
            self.window.set_title(str(args.get("title") or "WikiApp"))
            return None
        return self.dispatch_ingest(cmd, args)

    def dispatch_ingest(self, cmd, args):
        """Ingest (see ingest/DESIGN.md). Progress comes back as "ingest" events."""
        if cmd == "ingestInfo":
            return self.ingest.info()
        if cmd == "saveIngestState":
            self.ingest.save_state(text(args, "state"))
            return None
        if cmd == "saveIngestNotes":
            self.ingest.save_notes(text(args, "text"))
            return None
        if cmd == "startIngest":
            return self.ingest.start(args.get("job"))
        if cmd == "reviseIngestCards":  # feedback: {cards: [{card, text}], accepted, rejected}
            self.ingest.revise(text(args, "runId"), args.get("feedback"))
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
        write_atomic(INSTANCE_FILE, json.dumps({"port": self.server.server_port, "token": self.server.token}))
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
        # debug=True keeps what WikiApp.exe allows: F5 to reload, F12 / Inspect for developer tools.
        # icon: the window's icon from the start (Windows), so the taskbar never shows Python's.
        webview.start(debug=True, private_mode=True, storage_path=str(web_profile_folder()),
                      icon=str(ICON) if ICON.exists() else None)

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
        save_placement(self.bounds, self.maximized)

    def on_closed(self):
        self.ingest.stop()
        try:
            INSTANCE_FILE.unlink()
        except OSError:
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
        parts = PLACEMENT_FILE.read_text(encoding="utf-8").strip().split(",")
        x, y, width, height = (int(p) for p in parts[:4])
    except (OSError, ValueError):
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


def web_profile_folder():
    """A web view profile folder for this run only. The browser engine of a window that just
    closed can hold its folder for a few seconds, and a new window can't open on a folder in
    use; pywebview deletes this one on close (private mode). Leftovers from crashed runs go here."""
    profiles = DATA_DIR / "webview"
    if profiles.is_dir():
        for old in profiles.iterdir():
            shutil.rmtree(old, ignore_errors=True)  # one still in use stays until next time
    return profiles / f"run-{os.getpid()}"


def save_placement(bounds, maximized):
    if not bounds:
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PLACEMENT_FILE.write_text(",".join(str(int(v)) for v in bounds) + ("," + ("1" if maximized else "0")), encoding="utf-8")
    except OSError:
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
    migrate_from_windows_host()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    if os.environ.get("WIKIAPP_DEBUG_PORT"):
        webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ["WIKIAPP_DEBUG_PORT"])
    set_app_identity()
    Host(startup_folders).run()


if __name__ == "__main__":
    main()
