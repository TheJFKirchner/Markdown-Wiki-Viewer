"""Builds a clean copy of WikiApp, the app only, to send to another computer or person.

    python make_share.py [output folder]

Writes <output>/WikiApp/ and <output>/WikiApp.zip (default output: Share/ next to this file):
  App Files/      without .venv or Python caches (the launchers set it up on each computer)
  WikiApp.cmd, WikiApp.command, the docs, .gitignore, .gitattributes
In the zip, WikiApp.command is marked runnable, so a Mac can double-click it once unzipped.

No wiki content goes with it: Sample Wikis/ is never copied, nor the WikiApp.lnk shortcut (it holds
this computer's path), nor anything outside this folder, such as your settings in ~/.wikiapp
(or %LOCALAPPDATA%\\WikiApp for the exe). Afterwards every copied file is checked for your Windows user name.
"""

import getpass
import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOP_FILES = ["WikiApp.cmd", "WikiApp.command", "README.md", "TECHNICAL.md", "CLAUDE.md", ".gitignore", ".gitattributes"]
SKIP_DIRS = {".venv", "__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
MARKER = ".made-by-make_share"  # next to a WikiApp folder this script built, so a rebuild may replace it


def ignore(folder, names):
    return [n for n in names if n in SKIP_DIRS or Path(n).suffix in SKIP_SUFFIXES]


def remove(folder):
    # OneDrive marks the folders it syncs read-only, which stops a plain delete: clear the flag
    # and try that item again.
    def writable_then_retry(func, path, *_):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(folder, onexc=writable_then_retry)
    else:
        shutil.rmtree(folder, onerror=writable_then_retry)


def build(out):
    target = out / "WikiApp"
    if target.exists():
        if not (out / MARKER).exists():
            sys.exit(f"{target} already exists and wasn't made by this script. Move it or pick another folder.")
        remove(target)
    target.mkdir(parents=True)
    (out / MARKER).touch()

    shutil.copytree(ROOT / "App Files", target / "App Files", ignore=ignore)
    for name in TOP_FILES:
        shutil.copy2(ROOT / name, target / name)
    return target, write_zip(target, out / "WikiApp.zip")


def write_zip(folder, zip_path):
    """Like any zip, plus Unix permissions: files 644, and the Mac launcher 755 (runnable)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo.from_file(path, Path(folder.name) / path.relative_to(folder))
            mode = 0o755 if path.suffix == ".command" else 0o644
            info.create_system = 3  # "made on Unix", or unzip tools ignore the permissions below
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return zip_path


def mentions_of_user(folder):
    """Files whose bytes contain this Windows user's name (as text or UTF-16, any case)."""
    name = getpass.getuser()
    needles = [name.lower().encode("utf-8"), name.lower().encode("utf-16-le")]
    found = []
    for path in folder.rglob("*"):
        if path.is_file():
            data = path.read_bytes().lower()
            if any(n in data for n in needles):
                found.append(path.relative_to(folder))
    return name, found


def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "Share"
    inside = [ROOT / "App Files", ROOT / "Sample Wikis"]
    if out == ROOT or any(out == f or f in out.parents for f in inside):
        sys.exit("Pick an output folder that isn't part of the app or the wikis.")

    target, zip_path = build(out)
    files = sum(1 for p in target.rglob("*") if p.is_file())
    print(f"Copied {files} files to {target}")
    print(f"Zipped to {zip_path} ({zip_path.stat().st_size // 1024} KB)")

    name, found = mentions_of_user(target)
    if found:
        print(f"\nWarning: your user name '{name}' appears in:")
        for path in found:
            print(f"  {path}")
        return 1
    print(f"Checked: no file mentions your user name '{name}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
