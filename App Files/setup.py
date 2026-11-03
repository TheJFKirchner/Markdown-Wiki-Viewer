"""Sets up WikiApp's Python environment: App Files/.venv with the packages in requirements.txt.

WikiApp.cmd (Windows) and WikiApp.command (macOS) run this before every start. When everything
is already installed it returns at once; it only installs on the first start, or after
requirements.txt changed. Needs Python 3.10 or newer.

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
DONE = VENV / "wikiapp-setup.txt"  # requirements.txt's hash at the last good install


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def wanted():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def is_current():
    """True when the packages match requirements.txt (also asked by the host when it's started
    without a launcher, such as from a pinned taskbar button)."""
    return (DONE.exists() and DONE.read_text(encoding="utf-8").strip() == wanted()
            and venv_works())


def venv_works():
    """False when .venv's Python is gone or broken, as after the Python it was made from was
    upgraded or removed (a Homebrew upgrade on a Mac, say)."""
    try:
        return subprocess.call([str(venv_python()), "-c", ""], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30) == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    if sys.version_info < (3, 10):
        print(f"WikiApp needs Python 3.10 or newer; this is {sys.version.split()[0]}.")
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
    DONE.write_text(wanted(), encoding="utf-8")
    print("\nWikiApp is set up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
