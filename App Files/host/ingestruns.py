"""Promotion runs, for the host: one at a time, ingest/run.py in this app's Python with no
window (the agent itself runs through agentlib; see ingest/agent.py). Each line it prints (a
JSON object) goes to the page as an "ingest" event, and an "ingestExit" event follows when it ends.

Files (where the path list says, see pathlist.py): the cards waiting for review
("pending_promotion") and one folder per run in "run_history"/<run id>, all in the app's private
folder by default.
"""

import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import appfolder
import pathlist

APP_DIR = Path(__file__).resolve().parent.parent
CODE_DIR = APP_DIR / "ingest"
sys.path.insert(0, str(APP_DIR / "agents"))
import agentfiles  # noqa: E402  (the four agents' prompt files)

RUN_SCRIPT = CODE_DIR / "run.py"
MODELS_SCRIPT = CODE_DIR / "models.py"
SETUP_SCRIPT = APP_DIR / "setup.py"


def console_python():
    """This environment's python, never pythonw (a run's output is read through a pipe)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return exe.with_name("python.exe")
    return exe


class IngestRuns:
    # Cards waiting for an answer: the Promotion tab's file. (Runs are Promotion runs only; notes
    # reach the personal wiki through the Sessions tab.)
    STATE_ENTRIES = {"promotion": "pending_promotion"}

    def __init__(self, post_event):
        self._post = post_event
        self._process = None
        self._run_id = None
        self._lock = threading.Lock()

    @property
    def runs_dir(self):
        """The past runs' folder (None when no private folder is chosen yet). Asked each time, so
        moving the private folder or pointing the entry elsewhere takes effect at once."""
        return pathlist.path("run_history")

    # ---- What the Ingest view asks for ----

    def info(self, name="promotion"):
        running = self.running()
        ready = pathlist.agentlib_installed()
        folder = pathlist.app_folder()
        return {
            "ready": ready,
            "message": "" if ready else appfolder.agentlib_status()["message"],
            "running": running,
            "runId": self._run_id if running else None,
            "state": _read_or_none(self._state_file(name)),
            "dataDir": str(folder) if folder else "",
        }

    def _state_file(self, name):
        if name not in self.STATE_ENTRIES:
            raise ValueError(f'Bad state name: "{name}" (only "promotion" has cards).')
        return pathlist.path(self.STATE_ENTRIES[name])

    def save_state(self, text, name="promotion"):
        file = self._state_file(name)
        if file is None:
            raise pathlist.PathMissing("Choose where WikiApp keeps its private folder first.")
        write_atomic(file, text)

    def agents(self):
        """The four agents with their prompt files, for the Agents window."""
        return agentfiles.info()

    def save_agent(self, agent_id, text):
        agentfiles.save(agent_id, text)

    def run_dir(self, run_id):
        if not run_id or not all(c.isalnum() or c in "-_" for c in run_id):
            raise ValueError("Bad run id.")
        runs = self.runs_dir
        if runs is None:
            raise pathlist.PathMissing("Choose where WikiApp keeps its private folder first.")
        return runs / run_id

    def list_runs(self, limit=30):
        """Past runs, newest first: [{ runId, transcript (the text of transcript.json, or None) }]."""
        runs = self.runs_dir
        if runs is None or not runs.is_dir():
            return []
        folders = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name.lower(), reverse=True)
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
            pathlist.ensure_parent(folder)  # the runs folder: made only inside the private folder
            folder.mkdir(exist_ok=True)
            job["runId"] = run_id
            job_file = folder / "job.json"
            job_file.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            self._launch(run_id, [str(job_file)])
            return run_id

    def revise(self, run_id, feedback):
        """A feedback round: run.py continues the run's conversation with the reviewer's feedback
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

    def answer(self, run_id, answers):
        """A promotion's questions, answered: run.py resumes the run's Claude session with the
        answers ({question id: text, "" for one that was skipped}), and the agent proposes."""
        if not isinstance(answers, dict):
            raise ValueError("Missing argument: answers")
        with self._lock:
            if self.running():
                raise RuntimeError("Claude is still working. Wait for it to finish.")
            folder = self.run_dir(run_id)
            job_file = folder / "job.json"
            if not job_file.exists() or not (folder / "session.json").exists():
                raise RuntimeError("This run's folder is gone, so Claude can't continue it.")
            answers_file = folder / "answers.json"
            answers_file.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
            self._launch(run_id, [str(job_file), "--answers", str(answers_file)])

    def models(self):
        """The models the engine offers (agentlib's list_models, through ingest/models.py, in this
        app's Python): a JSON list of {id, name, description}. No request is made to the model."""
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
    write has its own temporary file: page calls can arrive on several threads at once. A missing
    folder is made only inside the app's private folder (pathlist.ensure_parent)."""
    pathlist.ensure_parent(path)
    pathlist.write_text_atomic(path, text)


def _read_or_none(path):
    if path is None:
        return None
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None


def _sh_quote(text):
    # For a command inside an AppleScript string: single quotes for the shell, no double quotes.
    return "'" + text.replace("'", "'\\''") + "'"
