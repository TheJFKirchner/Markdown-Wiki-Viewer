"""Sets up WikiApp's Python environment: App Files/.venv with the packages in requirements.txt,
and the agentlib library the AI features run on.

WikiApp.cmd (Windows) and WikiApp.command (macOS) run this before every start. When everything
is already installed it returns at once; it only installs on the first start, or after
requirements.txt (or the agentlib folder) changed. Needs Python 3.11 or newer (agentlib needs 3.11).

agentlib is a separate library, never copied into the app. It is looked for in the folders next
to the app's project folder, and one level inside each (today: ..\\General-Purpose-Productivity\\agentlib),
or wherever the app's Paths window points it (see host/pathlist.py). Exactly one found: it is
installed "editable", so the library is used where it is. None or several: the app still starts,
with the AI features off and a message saying why.

    python setup.py             set up, or bring up to date with requirements.txt
    python setup.py --upgrade   also update every package to its newest version
"""

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
REQUIREMENTS = HERE / "requirements.txt"
DONE = VENV / "wikiapp-setup.txt"           # what was installed at the last good setup (a hash)
AGENTLIB_NOTE = VENV / "wikiapp-agentlib.txt"  # why agentlib isn't installed, when it isn't

if str(HERE / "host") not in sys.path:
    sys.path.append(str(HERE / "host"))
import pathlist  # noqa: E402  (standard library only: works before the packages are installed)


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def agentlib_folder():
    """The agentlib folder to install: the one set in the app's Paths window, or the only one found."""
    try:
        return pathlist.path("agentlib")
    except Exception:
        return None


def wanted():
    """A hash of what should be installed: requirements.txt, and which agentlib (with its pyproject)."""
    digest = hashlib.sha256(REQUIREMENTS.read_bytes())
    folder = agentlib_folder()
    if folder is not None:
        digest.update(b"\0agentlib\0" + str(folder).encode("utf-8"))
        for name in ("pyproject.toml", "setup.py"):
            if (folder / name).is_file():
                digest.update((folder / name).read_bytes())
    return digest.hexdigest()


def is_current():
    """True when the packages match requirements.txt (also asked by the host when it's started
    without a launcher, such as from a pinned taskbar button)."""
    return (DONE.exists() and DONE.read_text(encoding="utf-8").strip() == wanted()
            and venv_works())


def mark_current():
    DONE.write_text(wanted(), encoding="utf-8")


def venv_works():
    """False when .venv's Python is gone or broken, as after the Python it was made from was
    upgraded or removed (a Homebrew upgrade on a Mac, say)."""
    try:
        return subprocess.call([str(venv_python()), "-c", ""], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30) == 0
    except (OSError, subprocess.SubprocessError):
        return False


def agentlib_note():
    """Why agentlib isn't installed, from the last setup ("" when it is, or no setup has run)."""
    try:
        return AGENTLIB_NOTE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def install_agentlib(python, folder, show=False):
    """pip install -e <folder> into the app's Python. -> (ok, message). show: let pip print to the
    console (the launcher's window) instead of capturing it."""
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(folder)]
    try:
        if show:
            ok, output = subprocess.call(command) == 0, ""
        else:
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=900, **options)
            ok, output = done.returncode == 0, (done.stderr or done.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as error:
        ok, output = False, str(error)
    if ok:
        message = ""
    else:
        last = output.splitlines()[-1] if output else "see the setup window for pip's messages"
        message = f"AI features are off: installing agentlib from {folder} failed ({last})."
    VENV.mkdir(exist_ok=True)
    AGENTLIB_NOTE.write_text(message, encoding="utf-8")
    return ok, message


def setup_agentlib():
    """Finds and installs agentlib. Never fails the setup: without it the app runs with AI off."""
    folder = agentlib_folder()
    if folder is not None:
        print(f"Installing agentlib (the AI features' library) from {folder}...", flush=True)
        ok, message = install_agentlib(venv_python(), folder, show=True)
        if not ok:
            print("\n" + message + "\nWikiApp will start without its AI features.", flush=True)
        return
    found = pathlist.find_agentlib()
    if found:
        message = ("AI features are off: more than one agentlib library was found ("
                   + "; ".join(str(p) for p in found) + "). Choose one in the app's Paths window.")
    else:
        message = ("AI features are off: the agentlib library wasn't found in the folders next to "
                   f"{HERE.parent.name} (or one level inside them). Set its folder in the app's Paths window.")
    print(message, flush=True)
    AGENTLIB_NOTE.write_text(message, encoding="utf-8")


def main():
    if sys.version_info < (3, 11):
        print(f"WikiApp needs Python 3.11 or newer; this is {sys.version.split()[0]}.")
        print("Install a newer one from https://www.python.org/downloads/ and try again.")
        return 1
    upgrade = "--upgrade" in sys.argv
    if not upgrade and is_current():
        return 0

    if not venv_python().exists():
        print("Setting up WikiApp: creating its Python environment...", flush=True)
        venv.create(VENV, with_pip=True)
    elif not venv_works():
        print("WikiApp's Python environment no longer works; making it again...", flush=True)
        venv.create(VENV, clear=True, with_pip=True)
    print("Installing packages. The first time takes a minute or two (about 200 MB).", flush=True)
    command = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)]
    if upgrade:
        command.append("--upgrade")
    if subprocess.call(command) != 0:
        print("\nSetup FAILED. Check the messages above, then start WikiApp again to retry.")
        return 1
    setup_agentlib()
    mark_current()
    print("\nWikiApp is set up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
