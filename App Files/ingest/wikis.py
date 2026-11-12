"""The wikis as the ingest agent sees them, and the index it chooses pages from.

Scans each wiki folder the way the app's host does (dot-folders and hidden files are skipped),
finds the page a [[link]] points to with the same rules as app/js/vault.js, and builds one index
per wiki: a line per page with its id, description, tags, sections and links, then the wiki's
page templates. A copy of each index is kept in the app's private folder (the path list's
"wiki.<alias>.index"), never in the wiki.

Where each wiki's rules file and templates folder are comes from the path list
(host/pathlist.py): by default <wiki>/wiki_rules.md, and the wiki's own Templates folder if it has
one, otherwise the app's private templates. A job may also give them per wiki ("rules",
"templates").

On its own:  python wikis.py team="C:\\wikis\\team" personal="C:\\wikis\\personal" [--notes-dir Notes]
"""

import difflib
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

_HOST = str(Path(__file__).resolve().parent.parent / "host")
if _HOST not in sys.path:
    sys.path.append(_HOST)
import pathlist  # noqa: E402  (every path in the app comes from the path list)

NOTE_EXT = re.compile(r"\.(md|markdown)$", re.I)
SCRIPT_EXT = re.compile(r"\.(sql|py|ipynb|r|js|mjs|ts|ps1|psm1|sh|bash|bat|cmd|vbs|rb|pl|lua|kql|dax)$", re.I)
WIKILINK = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
FRONTMATTER = re.compile(r"^---\n(?:([\s\S]*?)\n)?---[ \t]*(?:\n|$)")
CODE = re.compile(r"```[\s\S]*?```|`[^`\n]*`")
TEMPLATES_DIR = "Templates"               # everything in it is a template, never a wiki page:
PAGE_TEMPLATES_DIR = "Templates/Pages"    #   page templates, for the agent's new pages
                                          #   (Templates/Notes: quick-note templates, for the app)
RULES_FILE = "wiki_rules.md"              # the usual name of a wiki's rules file (the path list decides)
INDEX_DIR = ".wiki"                       # older versions wrote <wiki>/.wiki/index.md; nothing is written there now
MAX_TEXT_BYTES = 2 * 1024 * 1024


@dataclass
class Page:
    id: str        # "alias:path/inside/wiki.md"
    wiki: str      # alias
    path: str      # path inside the wiki, forward slashes
    name: str      # file name without .md (with the extension for scripts)
    kind: str      # page | note | template | page_template | rules | script
    root: Path
    _text: str | None = field(default=None, repr=False)
    source: Path | None = None   # the file, when it isn't root/path (a template kept outside the wiki)

    @property
    def file(self) -> Path:
        return self.source or self.root / self.path

    @property
    def text(self) -> str:
        """The file's text: BOM removed, line endings as \\n (the form edits are made against)."""
        if self._text is None:
            self._text = read_text(self.file)
        return self._text


def read_text(file: Path) -> str:
    if file.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError(f"{file.name} is over 2 MB")
    return file.read_bytes().decode("utf-8-sig", errors="replace").replace("\r\n", "\n")


def parse_link(inner: str) -> tuple[str, str]:
    """'team:Target#Heading|Text' -> ('team', 'Target'), like parseLink in vault.js."""
    inner = inner.strip()
    if inner.startswith("[[") and inner.endswith("]]"):
        inner = inner[2:-2]
    ref = inner.split("|", 1)[0]
    folder = ""
    colon, hash_ = ref.find(":"), ref.find("#")
    if colon > 0 and (hash_ < 0 or colon < hash_):
        folder, ref = ref[:colon].strip(), ref[colon + 1:]
    target = ref.split("#", 1)[0].strip()
    return folder, NOTE_EXT.sub("", target)


def frontmatter(text: str) -> tuple[dict, str]:
    """-> (properties, body). Values stay strings (like the app's CORE_SCHEMA)."""
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.load(match.group(1) or "", Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        data = None
    return (data if isinstance(data, dict) else {}), text[match.end():]


def description_of(text: str) -> str:
    """The page's frontmatter `description`, or ''."""
    value = frontmatter(text)[0].get("description")
    return value.strip() if isinstance(value, str) else ""


def tags_of(properties: dict) -> list[str]:
    raw = properties.get("tags", properties.get("tag"))
    items = raw if isinstance(raw, list) else re.split(r"[,\s]+", raw) if isinstance(raw, str) else []
    tags = [str(t).strip().lstrip("#").lower() for t in items]
    return list(dict.fromkeys(t for t in tags if t))


def links_in(text: str) -> list[str]:
    """Link targets as written ('Titan', 'team:Saturn'), in order, without repeats."""
    found = []
    for match in WIKILINK.finditer(CODE.sub("", text)):
        folder, target = parse_link(match.group(1))
        if target:
            found.append(f"{folder}:{target}" if folder else target)
    return list(dict.fromkeys(found))


def sections_in(body: str) -> list[str]:
    sections, fence = [], False
    for line in body.split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            fence = not fence
        elif not fence and (m := re.match(r"^##[ \t]+(.*?)[ \t]*$", line)):
            sections.append(m.group(1))
    return sections


def is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        return bool(path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
    except (AttributeError, OSError):
        return False


class Wikis:
    """Every open wiki, in workspace order (earlier wikis win ties, as in the app)."""

    def __init__(self, wikis: list[dict], notes_dir: str = "Notes"):
        """wikis: [{"alias", "root"}], in workspace order. Each may also give "rules" (its rules
        file) and "templates" (its templates folder); otherwise the path list says where they are."""
        self.aliases = [w["alias"] for w in wikis]
        self.roots = {w["alias"]: Path(w["root"]) for w in wikis}
        self.order = {alias: i for i, alias in enumerate(self.aliases)}
        self.notes_dir = notes_dir.strip("/") or "Notes"
        self.rules_files: dict[str, Path | None] = {}
        self.templates_dirs: dict[str, Path | None] = {}
        self.index_files: dict[str, Path | None] = {}
        for w in wikis:
            places = pathlist.wiki_paths(w["alias"], w["root"])
            self.rules_files[w["alias"]] = Path(w["rules"]) if w.get("rules") else places["rules"]
            self.templates_dirs[w["alias"]] = Path(w["templates"]) if w.get("templates") else places["templates"]
            self.index_files[w["alias"]] = places["index"]
        self.pages: dict[str, Page] = {}
        self.folders: dict[str, list[str]] = {}
        self.private_files = self._private_files()
        for alias in self.aliases:
            self._scan(alias)
            self._scan_outside_templates(alias)

    def _private_files(self) -> list[Path]:
        """The person's own tag files and capture rules file: not wiki pages, so Promotion's agent
        can neither list nor read them even when they sit inside a wiki folder."""
        found: list[Path] = []
        for name in ("personal_capture_rules", "tag_list_reference"):
            try:
                value = pathlist.path(name)
            except Exception:
                value = None
            if value:
                found.append(Path(value))
        for root in self.roots.values():
            try:
                found.append(Path(pathlist.personal_tags_path(root)))
            except Exception:
                pass
        return found

    def _is_private(self, file: Path) -> bool:
        return any(_same(file, other) for other in self.private_files)

    def _scan(self, alias: str) -> None:
        root = self.roots[alias]
        folders = []
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if not is_hidden(here / d))
            folders += [(here / d).relative_to(root).as_posix() for d in dirnames]
            for name in sorted(filenames):
                file = here / name
                if is_hidden(file) or self._is_private(file):
                    continue
                path = file.relative_to(root).as_posix()
                if NOTE_EXT.search(name):
                    kind = self._kind(path, alias)
                    page = Page(f"{alias}:{path}", alias, path, NOTE_EXT.sub("", name), kind, root)
                elif SCRIPT_EXT.search(name):
                    page = Page(f"{alias}:{path}", alias, path, name, "script", root)
                else:
                    continue
                self.pages[page.id] = page
        self.folders[alias] = folders

    def _scan_outside_templates(self, alias: str) -> None:
        """Page templates kept outside the wiki (the app's private templates, or a folder the path
        list points to): their Pages/ files join the wiki as page templates, read-only, with ids
        as if they were in the wiki's Templates/Pages folder."""
        folder = self.templates_dirs.get(alias)
        root = self.roots[alias]
        if folder is None or _same(folder, root / TEMPLATES_DIR) or not (folder / "Pages").is_dir():
            return
        pages = folder / "Pages"
        for file in sorted(pages.rglob("*")):
            if not file.is_file() or not NOTE_EXT.search(file.name) or any(is_hidden(p) for p in file.relative_to(pages).parents if p.name) or is_hidden(file):
                continue
            path = f"{PAGE_TEMPLATES_DIR}/{file.relative_to(pages).as_posix()}"
            page_id = f"{alias}:{path}"
            if page_id not in self.pages:
                self.pages[page_id] = Page(page_id, alias, path, NOTE_EXT.sub("", file.name), "page_template", root, source=file)

    def _kind(self, path: str, alias: str | None = None) -> str:
        lower = path.lower()
        if lower.startswith(self.notes_dir.lower() + "/"):
            return "note"
        if path.startswith(PAGE_TEMPLATES_DIR + "/"):
            return "page_template"
        if path.startswith(TEMPLATES_DIR + "/"):
            return "template"
        rules = self.rules_files.get(alias) if alias else None
        if rules is not None and alias in self.roots:
            if _same(self.roots[alias] / path, rules):
                return "rules"
        elif lower == RULES_FILE:
            return "rules"
        return "page"

    def rules_text(self, alias: str) -> str | None:
        """The wiki's rules (the whole file), or None when it has no rules file."""
        page = next((p for p in self.pages.values() if p.wiki == alias and p.kind == "rules"), None)
        if page is not None:
            return page.text
        rules = self.rules_files.get(alias)
        if rules is not None and rules.is_file():
            return read_text(rules)
        return None

    def wiki_pages(self, alias: str | None = None) -> list[Page]:
        return [p for p in self.pages.values() if p.kind == "page" and (alias is None or p.wiki == alias)]

    def page_templates(self, alias: str) -> list[Page]:
        return sorted((p for p in self.pages.values() if p.kind == "page_template" and p.wiki == alias), key=lambda p: p.name.lower())

    # ---- Links, followed like resolveLink / resolveScript in vault.js -------------------

    def find_page(self, link: str, from_wiki: str | None = None, pages_first: bool = False) -> str | None:
        """The id of the page a link points to ('Saturn', 'Planets/Saturn', 'team:Saturn'), or None.
        pages_first: when a wiki page and a quick note (or template) share the name, take the page.
        The app's links don't do that, so it's off when following links, to match them."""
        folder, target = parse_link(link)
        if not target:
            return None
        is_script = bool(SCRIPT_EXT.search(target))
        t = target.lower()
        candidates = []
        for page in self.pages.values():
            if (page.kind == "script") != is_script:
                continue
            bare = page.path.lower() if is_script else NOTE_EXT.sub("", page.path).lower()
            if ("/" in t and (bare == t or bare.endswith("/" + t))) or ("/" not in t and page.name.lower() == t):
                candidates.append(page)
        if folder:
            candidates = [p for p in candidates if p.wiki.lower() == folder.lower()]
        elif from_wiki:
            own = [p for p in candidates if p.wiki == from_wiki]
            candidates = own or candidates
        if pages_first:
            candidates = [p for p in candidates if p.kind in ("page", "script", "page_template")] or candidates
        if not candidates:
            return None
        candidates.sort(key=lambda p: (self.order.get(p.wiki, 99), len(p.path)))
        return candidates[0].id

    def similar_pages(self, link: str, n: int = 5) -> list[str]:
        """Page ids whose name or path looks like `link`, for a link that didn't lead anywhere."""
        _, target = parse_link(link)
        options = {}
        for page in self.pages.values():
            if page.kind in ("page", "script", "page_template"):
                options[page.name.lower()] = page.id
                options[NOTE_EXT.sub("", page.path).lower()] = page.id
        names = difflib.get_close_matches(target.lower(), list(options), n=n * 2, cutoff=0.5)
        return list(dict.fromkeys(options[name] for name in names))[:n]

    # ---- The index ------------------------------------------------------------------------

    def index_text(self, alias: str, today: str | None = None) -> str:
        lines = [
            f"<!-- Index of wiki \"{alias}\", built by WikiApp's ingest on {today or date.today().isoformat()}.",
            "     Each line: page name | page id | description | tags | sections | links. -->",
            "",
        ]
        for page in sorted(self.wiki_pages(alias), key=lambda p: p.path.lower()):
            try:
                text = page.text
            except (OSError, ValueError) as err:  # too big, locked, or a cloud-only file while offline
                lines.append(f"- {page.name} | {page.id} | (could not be read: {err})")
                continue
            properties, body = frontmatter(text)
            parts = [page.name, page.id]
            description = properties.get("description")
            if not (isinstance(description, str) and description.strip()):
                description = properties.get("summary")   # personal topic pages keep their one-liner here
            parts.append(description.strip() if isinstance(description, str) and description.strip() else "(no description)")
            tags = tags_of(properties)
            if tags:
                parts.append("tags: " + ", ".join(tags))
            sections = sections_in(body)
            if sections:
                parts.append("sections: " + "; ".join(sections))
            links = links_in(text)
            if links:
                parts.append("links: " + ", ".join(links))
            lines.append("- " + " | ".join(parts))
        scripts = sorted((p for p in self.pages.values() if p.kind == "script" and p.wiki == alias), key=lambda p: p.path.lower())
        if scripts:
            lines += ["", "Scripts (link targets only, written with their extension: [[name.sql]]):"]
            lines += [f"- {p.name} | {p.id}" for p in scripts]
        templates = self.page_templates(alias)
        if templates:
            lines += ["", "Page templates (for new pages; each line: template name | id | when to use it):"]
            lines += [f"- {p.name} | {p.id} | {self._description(p) or '(no description)'}" for p in templates]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _description(page: Page) -> str:
        try:
            return description_of(page.text)
        except (OSError, ValueError):
            return ""

    def write_indexes(self, today: str | None = None) -> dict[str, str]:
        """Builds every wiki's index, and keeps a copy of each where the path list says (by default
        <private folder>/indexes/<alias>.md), to look at. The run uses the text, so when there is no
        private folder, or its folder is gone, nothing is written and the run still works.
        Nothing is ever written into a wiki. -> alias -> index text."""
        texts = {}
        for alias in self.aliases:
            text = self.index_text(alias, today)
            target = self.index_files.get(alias)
            if target is not None:
                try:
                    pathlist.ensure_parent(target)
                    pathlist.write_text_atomic(target, text)
                except (OSError, pathlist.PathMissing):
                    pass
            texts[alias] = text
        return texts


def main(argv: list[str]) -> int:
    notes_dir = "Notes"
    wikis = []
    args = iter(argv)
    for arg in args:
        if arg == "--notes-dir":
            notes_dir = next(args, "Notes")
        elif "=" in arg:
            alias, root = arg.split("=", 1)
            wikis.append({"alias": alias, "root": root})
    if not wikis:
        print(__doc__)
        return 2
    model = Wikis(wikis, notes_dir)
    for alias in model.write_indexes():
        target = model.index_files.get(alias)
        where = f"Wrote {target}" if target is not None and target.is_file() else "Built (no private folder to keep a copy in)"
        print(f"{where}: index of {alias} ({len(model.wiki_pages(alias))} pages)")
    return 0


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
