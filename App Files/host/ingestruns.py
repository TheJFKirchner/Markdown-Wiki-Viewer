"""Ingest runs, for the Python host: one at a time, ingest/run.py in this app's Python with no
window. Each line it prints (a JSON object) goes to the page as an "ingest" event, and an
"ingestExit" event follows when it ends. A port of the Ingest parts of WikiApp.cs.

Files: the user's data in <data>/ingest (cards waiting for review, notes for the agent) and one
folder per run in <data>/ingest-runs/<run id>.
"""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CODE_DIR = APP_DIR / "ingest"
RUN_SCRIPT = CODE_DIR / "run.py"
MODELS_SCRIPT = CODE_DIR / "models.py"
SHIPPED_PROMPT = CODE_DIR / "agent-prompt.md"
SETUP_SCRIPT = APP_DIR / "setup.py"


def console_python():
    """This environment's python, never pythonw (a run's output is read through a pipe)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return exe.with_name("python.exe")
    return exe


class IngestRuns:
    def __init__(self, data_dir, post_event):
        self.data_dir = Path(data_dir) / "ingest"
        self.runs_dir = Path(data_dir) / "ingest-runs"
        self.state_file = self.data_dir / "pending.json"
        self.notes_file = self.data_dir / "user-notes.md"
        self._post = post_event
        self._process = None
        self._run_id = None
        self._lock = threading.Lock()

    # ---- What the Ingest view asks for ----

    def info(self):
        running = self.running()
        return {
            "ready": importlib.util.find_spec("claude_agent_sdk") is not None,
            "running": running,
            "runId": self._run_id if running else None,
            "prompt": _read_or_none(SHIPPED_PROMPT),
            "userNotes": _read_or_none(self.notes_file) or "",
            "state": _read_or_none(self.state_file),
            "dataDir": str(self.data_dir),
        }

    def save_state(self, text):
        write_atomic(self.state_file, text)

    def save_notes(self, text):
        write_atomic(self.notes_file, text)

    def run_dir(self, run_id):
        if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
            raise ValueError("Bad run id.")
        return self.runs_dir / run_id

    def list_runs(self, limit=30):
        """Past runs, newest first: [{ runId, transcript (the text of transcript.json, or None) }]."""
        if not self.runs_dir.is_dir():
            return []
        folders = sorted((p for p in self.runs_dir.iterdir() if p.is_dir()), key=lambda p: p.name.lower(), reverse=True)
        return [{"runId": p.name, "transcript": _read_or_none(p / "transcript.json")} for p in folders[:limit]]

    # ---- Runs ----

    def running(self):
        return self._process is not None and self._process.poll() is None

    def start(self, job):
        if not isinstance(job, dict):
            raise ValueError("Missing argument: job")
        with self._lock:
            if self.running():
                raise RuntimeError("An ingest run is already going.")
            run_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            folder = self.run_dir(run_id)
            folder.mkdir(parents=True, exist_ok=True)
            job["runId"] = run_id
            job["userNotes"] = _read_or_none(self.notes_file) or ""
            job_file = folder / "job.json"
            job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            self._launch(run_id, [str(job_file)])
            return run_id

    def revise(self, run_id, feedback):
        """A feedback round: run.py resumes the run's Claude session with the reviewer's feedback
        ({"cards": [{"card", "text"}], "accepted": [ids], "rejected": [ids]})."""
        if not isinstance(feedback, dict) or not feedback.get("cards"):
            raise ValueError("Missing argument: feedback")
        with self._lock:
            if self.running():
                raise RuntimeError("Claude is still working. Wait for it to finish.")
            folder = self.run_dir(run_id)
            job_file = folder / "job.json"
            if not job_file.exists() or not (folder / "session.json").exists():
                raise RuntimeError("This run's folder is gone, so Claude can't continue it.")
            n = len(list(folder.glob("feedback-*.json"))) + 1
            feedback_file = folder / f"feedback-{n}.json"
            feedback_file.write_text(json.dumps(feedback, ensure_ascii=False), encoding="utf-8")
            self._launch(run_id, [str(job_file), "--feedback", str(feedback_file)])

    def models(self):
        """The models Claude Code offers, from ingest/models.py (a JSON list; no request to Claude)."""
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        try:
            done = subprocess.run([str(console_python()), "-X", "utf8", str(MODELS_SCRIPT)], cwd=str(CODE_DIR),
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=90, **options)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Claude Code didn't answer in time.")
        if done.returncode != 0:
            raise RuntimeError((done.stderr.strip().splitlines() or ["models.py failed."])[-1])
        return json.loads(done.stdout)

    def _launch(self, run_id, args):
        command = [str(console_python()), "-X", "utf8", str(RUN_SCRIPT)] + args
        options = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True  # its own process group, so stop() reaches Claude Code too
        process = subprocess.Popen(
            command, cwd=str(CODE_DIR), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **options)
        self._process, self._run_id = process, run_id
        errors = []

        def read_errors():
            size = 0
            for line in process.stderr:
                if size < 8000:
                    errors.append(line)
                    size += len(line)

        def read_output():
            for line in process.stdout:
                line = line.rstrip("\r\n")
                if line:
                    self._post("ingest", line)
            process.wait()
            error_reader.join(5)
            self._post("ingestExit", {"runId": run_id, "code": process.returncode, "errors": "".join(errors)})

        error_reader = threading.Thread(target=read_errors, daemon=True)
        error_reader.start()
        threading.Thread(target=read_output, daemon=True).start()

    def stop(self):
        """Stops the run and everything it started (Claude Code runs as a child process)."""
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                               capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass

    def open_setup(self):
        """Runs setup.py in a window the user can watch (it reinstalls or updates the packages)."""
        python = str(console_python())
        if os.name == "nt":
            # No shell=True: it would wrap this in a second cmd, and a path with & in it would split.
            subprocess.Popen(f'cmd /k ""{python}" "{SETUP_SCRIPT}" --upgrade"',
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        elif sys.platform == "darwin":
            command = f"{_sh_quote(python)} {_sh_quote(str(SETUP_SCRIPT))} --upgrade"
            command = command.replace("\\", "\\\\").replace('"', '\\"')  # inside an AppleScript string
            subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script "{command}"',
                              "-e", 'tell application "Terminal" to activate'])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e", python, str(SETUP_SCRIPT), "--upgrade"])


def write_atomic(path, text):
    """Written to a temporary file first, so a crash mid-write never leaves half a file. Each
    write has its own temporary file: page calls can arrive on several threads at once."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    temp.write_text(text, encoding="utf-8")
    with _replace_lock:  # Windows refuses two replaces of one file at the same moment
        os.replace(temp, path)


_replace_lock = threading.Lock()


def _read_or_none(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None


def _sh_quote(text):
    # For a command inside an AppleScript string: single quotes for the shell, no double quotes.
    return "'" + text.replace("'", "'\\''") + "'"
