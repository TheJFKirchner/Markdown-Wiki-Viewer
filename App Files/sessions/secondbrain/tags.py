"""Tags: the reference tag list, the person's own tags, and how capture and review use them.

Tags are how topics relate: what kind of thing a topic is (an analysis area, a trend, a report...)
and what it belongs to (a client). Two free-form Markdown files make up the tag list the model is
given, each passed to it verbatim and labelled:

    tag_list_reference  (path list; unset by default) any existing tags file, typically the team's
                        tag list in a team wiki. READ ONLY: no code here ever opens it for writing.
    personal_tags       (path list; default personal-tags.md in the personal wiki) the person's own
                        tags, written however they like. The only tags file the tool adds to, and
                        not made until the first new tag is added.

Nothing depends on the files' format. Tag names are picked out of them on a best-effort basis, only
for warnings (a personal tag the reference list also has) and for saying which of a topic's tags are
personal-only; that may find nothing, and nothing fails because of it. The one format the tool
controls is the line it appends to personal_tags for a new tag the model needed:

    tag — description           (the description 8 words at most, checked on the model's reply)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import wiki
from .config import ROOT, pathlist

FILE_NAME = "personal-tags.md"
STARTER = ROOT.parent / "agents" / "messages" / "sessions-personal-tags.md"
MAX_WORDS = 8
MAX_FILE_CHARS = 20000
# Best-effort name picking: #hashtags, a table's first column, a list item or a line's lead-in.
_HASHTAG = re.compile(r"(?:^|\s)#([A-Za-z0-9][\w/-]*)")
_TABLE_ROW = re.compile(r"^\s*\|([^|]+)\|")
_LEAD = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*`?([A-Za-z0-9][\w /&-]{0,40}?)`?\s*(?:—|–|:|\s-\s|$)")
_LINE_TAG = re.compile(r"^(\s*(?:[-*+]\s+)?`?)([A-Za-z0-9][\w-]*)(`?\s*(?:—|–|:|\s-\s))")
_HEADER_WORDS = {"tag", "tags", "name", "names", "label", "description", "meaning"}


def words(text: str) -> int:
    return len(str(text or "").split())


def key(name: str) -> str:
    """A tag name for comparing: case, spaces, dashes and underscores don't count."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def as_tag(name: str) -> str:
    """A name as the wiki stores tags (lower-case, dashes)."""
    return wiki.slugify(name, 40)


def personal_path(root: Path) -> Path:
    try:
        return Path(pathlist.personal_tags_path(root))
    except Exception:
        return Path(root) / FILE_NAME


def reference_path() -> Path | None:
    try:
        found = pathlist.reference_tags_path()
    except Exception:
        return None
    return Path(found) if found else None


def names_in(text: str) -> list[str]:
    """Tag names picked out of a tags file in whatever format it is (best effort; may be empty):
    #hashtags, a table's first column, list items, and lines of the form "tag — ..." or "tag: ..."."""
    found: list[str] = []
    _, body = wiki.parse(text.replace("\r\n", "\n"))
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if fenced or not line.strip():
            continue
        if re.match(r"^\s*#{1,6}\s", line):           # a heading: only hashtags in it count
            found += _HASHTAG.findall(line)
            continue
        hashtags = _HASHTAG.findall(line)
        if hashtags:
            found += hashtags
            continue
        row = _TABLE_ROW.match(line)
        if row:
            cell = row.group(1).strip().strip("`*")
            if cell and not set(cell) <= set("-: ") and cell.lower() not in _HEADER_WORDS and words(cell) <= 4:
                found.append(cell)
            continue
        lead = _LEAD.match(line)
        if lead and (re.match(r"^\s*([-*+]|\d+[.)])\s", line) or re.search(r"(—|–|:|\s-\s)", line)):
            name = lead.group(1).strip()
            if name and words(name) <= 4 and name.lower() not in _HEADER_WORDS:
                found.append(name)
    out, seen = [], set()
    for name in found:
        k = key(name)
        if k and k not in seen:
            seen.add(k)
            out.append(as_tag(name))
    return out


def _read(path: Path | None) -> str | None:
    """A tags file's text, or None when it is missing or can't be read. Read only."""
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            return f.read()
    except OSError:
        return None


class TagSet:
    """The effective tag list: the reference list's text, then the personal tags' text."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.warnings: list[str] = []
        self.reference_file = reference_path()
        self.reference_text = _read(self.reference_file)
        if self.reference_file is not None and self.reference_text is None:
            self.warnings.append(f"The reference tag list ({self.reference_file.name}) can't be read, so it was left out.")
        self.reference = {key(t): t for t in names_in(self.reference_text or "")}
        if self.reference_text and not self.reference:
            self.warnings.append(f"No tag names could be picked out of the reference tag list ({self.reference_file.name}). "
                                 "Its text is still sent as it is; only the checks that compare tags with it are off.")
        self.personal_file = personal_path(self.root)
        self.personal_text = _read(self.personal_file) or ""
        self.personal = {key(t): t for t in names_in(self.personal_text)}
        for k, tag in self.personal.items():
            if k in self.reference:
                self.warnings.append(f"Your personal tag '{tag}' is also in the reference tag list, which counts instead. "
                                     "Remove it from your personal tags, or accept a merge.")

    @property
    def has_reference(self) -> bool:
        return self.reference_text is not None

    def canonical(self, tag: str) -> str | None:
        """The tag as a list has it (the reference first), or None when none is known to have it."""
        k = key(tag)
        return self.reference.get(k) or self.personal.get(k)

    def is_reference(self, tag: str) -> bool:
        return key(tag) in self.reference

    def personal_only(self, tags) -> list[str]:
        """A topic's tags that the reference list isn't known to have (all of them when no
        reference list is set): what would need flagging if the topic went to a team wiki."""
        return [t for t in tags if not self.is_reference(t)]

    def prompt_sections(self) -> list[tuple[str, str]]:
        """Both files verbatim, labelled."""
        sections = []
        if self.has_reference:
            sections.append(("Reference tag list (the team's, as written; read only)",
                             self.reference_text.strip()[:MAX_FILE_CHARS] or "(the file is empty)"))
        sections.append(("Your personal tags (as written)", self.personal_text.strip()[:MAX_FILE_CHARS] or "(none yet)"))
        return sections

    def check_new(self, items) -> tuple[list[dict], set[str], list[str]]:
        """The model's new tags, checked: a description of 1 to 8 words (the only rule enforced).
        A tag a list is already known to have is not added again.
        -> (accepted [{tag, description}], rejected tag names, warnings)"""
        accepted, rejected, warnings = [], set(), []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            tag = as_tag(item.get("tag") or "")
            desc = " ".join(str(item.get("description") or "").split())
            if tag == "untitled" or self.canonical(tag) or any(key(a["tag"]) == key(tag) for a in accepted):
                continue
            if not desc or words(desc) > MAX_WORDS:
                rejected.add(tag)
                warnings.append(f"The new tag '{tag}' was left out: its description must be 1 to {MAX_WORDS} words.")
                continue
            accepted.append({"tag": tag, "description": desc})
        return accepted, rejected, warnings

    def settle(self, topic_tags: list[str], rejected: set[str]) -> list[str]:
        """One topic's tags from the model: rejected new tags dropped, and a tag a list is known to
        have written the way that list has it."""
        out = []
        for tag in topic_tags:
            if tag in rejected:
                continue
            final = self.canonical(tag) or tag
            if final not in out:
                out.append(final)
        return out


def add_personal(root: Path, new: list[dict]) -> list[dict]:
    """Appends `tag — description` lines for new tags at the end of the personal tags file (made
    from the starter the first time), without touching what is already there. Never touches the
    reference list. Call while holding the Lock. -> the tags added."""
    if not new:
        return []
    target = personal_path(root)
    if not target.exists():
        if not target.parent.is_dir():
            raise wiki.WikiError(f"The folder for your personal tags ({target.parent}) doesn't exist.")
        try:
            with open(target, "x", encoding="utf-8", newline="\n") as f:  # "x": never over an existing file
                f.write(STARTER.read_text(encoding="utf-8"))
        except FileExistsError:
            pass
    with open(target, encoding="utf-8", newline="") as f:
        raw = f.read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    last = next((ln for ln in reversed(raw.splitlines()) if ln.strip()), "")
    mark = re.match(r"^\s*([-*])\s+\S", last)   # the file's own list style, when it is a bulleted list
    bullet = mark.group(1) + " " if mark else ""
    lines = "".join(f"{bullet}{n['tag']} — {n['description']}{nl}" for n in new)
    with open(target, "a", encoding="utf-8", newline="") as f:
        f.write(("" if not raw or raw.endswith(("\n", "\r")) else nl) + lines)
    return new


def merge_personal(root: Path, keep: str, merged: list[str]) -> bool:
    """An accepted tag merge, in the personal tags file only (best effort): a line that starts with
    a merged tag's name ("tag — ...", "- tag: ...") is removed, or, if the kept tag is in neither
    list, the first such line gets the kept name instead. Nothing else in the file changes, and a
    file where no such line is found is left alone. -> whether the file changed."""
    target = personal_path(root)
    if not target.is_file():
        return False
    keep_listed = bool(TagSet(root).canonical(keep))
    merged_keys = {key(m) for m in merged}
    with open(target, encoding="utf-8", newline="") as f:
        raw = f.read()
    out, changed = [], False
    for line in raw.splitlines(keepends=True):
        m = _LINE_TAG.match(line)
        if m and key(m.group(2)) in merged_keys:
            changed = True
            if not keep_listed:
                out.append(m.group(1) + keep + line[m.end(2):])
                keep_listed = True
            continue
        out.append(line)
    if changed:  # a hidden temp file, then swapped in; line endings kept as they were
        temp = target.with_name(f".{target.name}.sb.tmp")
        with open(temp, "w", encoding="utf-8", newline="") as f:
            f.write("".join(out))
        os.replace(temp, target)
    return changed
