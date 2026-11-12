"""The open folders on disk: scanning them, reading a file, the only code that writes notes, and
watching for changes.

Writes only touch .md files inside a folder the page names, keep the file's line endings and BOM,
and refuse to edit lines that changed since the page read them.
"""

import os
import stat
import threading
import time

NOTE_EXT = (".md", ".markdown")
MAX_NOTE_BYTES = 5 * 1024 * 1024  # bigger notes are listed without their text
MAX_TEXT_BYTES = 2 * 1024 * 1024  # readText limit
NEWLINE = "\r\n" if os.name == "nt" else "\n"  # for files this app creates


# ---- Reading --------------------------------------------------------------------------------

def scan(root):
    """{ root, name, folders: [relPath], files: [{ path, size, mtime, content? }] }.
    Paths are relative to root with forward slashes; only notes include their text."""
    root = full_path(root)
    if not os.path.isdir(root):
        raise FileNotFoundError("Folder not found: " + root)
    folders, files = [], []
    _walk(root, root, folders, files, set())
    return {"root": root, "name": os.path.basename(root), "folders": folders, "files": files}


def _walk(root, folder, folders, files, seen):
    real = os.path.realpath(folder)
    if real in seen:  # a link back up the tree
        return
    seen.add(real)
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
    except OSError:
        return
    subfolders = [e for e in entries if _is_dir(e) and not is_hidden(e)]
    for entry in subfolders:
        folders.append(_relative(root, entry.path))
        _walk(root, entry.path, folders, files, seen)
    for entry in entries:
        if _is_dir(entry) or is_hidden(entry):
            continue
        try:
            info = entry.stat()
        except OSError:
            continue
        item = {"path": _relative(root, entry.path), "size": info.st_size, "mtime": int(info.st_mtime * 1000)}
        if entry.name.lower().endswith(NOTE_EXT) and info.st_size <= MAX_NOTE_BYTES:
            try:
                item["content"] = _decode(_read_bytes(entry.path))
            except OSError:
                pass
        files.append(item)


def read_text(root, relative):
    """A file's text, for showing it. Only files inside root, up to 2 MB."""
    path = _inside(root, relative)
    if os.path.getsize(path) > MAX_TEXT_BYTES:
        raise ValueError("The file is too large to show (over 2 MB).")
    return _decode(_read_bytes(path))


# ---- Writing --------------------------------------------------------------------------------

# Each page call runs on its own thread, so two writes could both read a note before either
# writes it, and the second would undo the first. One write at a time.
_write_lock = threading.Lock()


def edit_lines(root, relative, start, expect, replace):
    """Replace `expect` (lines from 0-based `start`) with `replace`; fails if they changed on disk."""
    path = _note(root, relative)
    with _write_lock:
        lines, bom, newline = _read_lines(path)
        matches = 0 <= start and start + len(expect) <= len(lines) and lines[start:start + len(expect)] == expect
        if not matches:
            raise ValueError("The note changed on disk. It has been reloaded; try again.")
        lines[start:start + len(expect)] = replace
        _write(path, lines, bom, newline)


def append_lines(root, relative, add, header):
    """Append lines to a note, creating it (starting with `header`) if it doesn't exist."""
    path = _note(root, relative)
    with _write_lock:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write(path, list(header) + list(add) + [""], False, NEWLINE)
            return
        lines, bom, newline = _read_lines(path)
        while lines and lines[-1] == "":  # keep exactly one trailing empty line
            lines.pop()
        _write(path, lines + list(add) + [""], bom, newline)


def create_note(root, relative, lines):
    """A new note with these lines. Fails if the file already exists."""
    path = _note(root, relative)
    with _write_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "xb") as f:
                f.write(NEWLINE.join(lines).encode("utf-8"))
        except FileExistsError:
            raise ValueError("A note with that name already exists.") from None


# ---- Watching -------------------------------------------------------------------------------

class Watcher:
    """Checks each watched folder every second and calls on_change(root) once things go quiet.
    Polling needs no extra package and works the same on Windows and macOS."""

    INTERVAL = 1.0

    def __init__(self, on_change):
        self._on_change = on_change
        self._roots = {}  # root -> last fingerprint
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def watch(self, root):
        with self._lock:
            if root not in self._roots:
                self._roots[root] = fingerprint(root)

    def unwatch(self, root):
        with self._lock:
            self._roots.pop(full_path(root), None)

    def _loop(self):
        while True:
            time.sleep(self.INTERVAL)
            with self._lock:
                roots = list(self._roots.items())
            for root, before in roots:
                now = fingerprint(root)
                if now == before:
                    continue
                # Many changes arrive at once (an editor saving, a sync), so wait for a quiet moment.
                time.sleep(0.4)
                now = fingerprint(root)
                with self._lock:
                    if root not in self._roots:
                        continue
                    self._roots[root] = now
                self._on_change(root)


def fingerprint(root):
    """Every visible file's path, size and modified time: changes when anything is added,
    removed, renamed or saved."""
    parts = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        parts.extend((folder, d) for d in dirs)
        for name in files:
            if name.startswith("."):
                continue
            try:
                info = os.stat(os.path.join(folder, name))
            except OSError:
                continue
            parts.append((folder, name, info.st_size, info.st_mtime_ns))
    return hash(tuple(parts))


# ---- Helpers --------------------------------------------------------------------------------

def full_path(path):
    """Absolute, without a trailing separator (except a drive or disk root such as C:\\ or /)."""
    path = os.path.abspath(path)
    return path if os.path.dirname(path) == path else path.rstrip("\\/")


def _relative(root, path):
    return os.path.relpath(path, root).replace("\\", "/")


def _inside(root, relative):
    """The full path of `relative`, refusing anything outside `root`."""
    base = os.path.join(full_path(root), "")  # ends in one separator, also for a drive root (E:\)
    path = os.path.abspath(os.path.join(base, relative.replace("/", os.sep)))
    same = path.lower().startswith(base.lower()) if os.name == "nt" else path.startswith(base)
    if not same:
        raise PermissionError("That file is outside the folder.")
    return path


def _note(root, relative):
    path = _inside(root, relative)
    if not path.lower().endswith(NOTE_EXT):
        raise PermissionError("Only Markdown notes can be edited.")
    return path


def _is_dir(entry):
    try:
        return entry.is_dir()
    except OSError:
        return False


def is_hidden(entry):
    """Dot-folders (.git, .obsidian...) and files the system marks hidden are skipped."""
    if entry.name.startswith("."):
        return True
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    if getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0):
        return True
    return bool(getattr(info, "st_flags", 0) & getattr(stat, "UF_HIDDEN", 0))


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _decode(data):
    return data.decode("utf-8-sig", errors="replace")


def _read_lines(path):
    """A note's lines for editing. Strict: a note that isn't UTF-8 (an old ANSI or UTF-16 file) is
    refused, because writing it back would replace every character that didn't decode."""
    data = _read_bytes(path)
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("This note isn't saved as UTF-8 text, so the app won't change it. "
                         "Re-save it as UTF-8 in another editor to edit it here.") from None
    newline = "\r\n" if "\r\n" in text else "\n"
    return [line.rstrip("\r") for line in text.split("\n")], bom, newline


def _write(path, lines, bom, newline):
    """Writes the whole note to a hidden temp file next to it, then swaps it in, so a full disk or
    a crash mid-write leaves the old note whole instead of an empty or cut-off one."""
    data = (b"\xef\xbb\xbf" if bom else b"") + newline.join(lines).encode("utf-8")
    folder, name = os.path.split(path)
    temp = os.path.join(folder, f".{name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(temp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):  # another program (a sync client, a virus scanner) may hold it briefly
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
