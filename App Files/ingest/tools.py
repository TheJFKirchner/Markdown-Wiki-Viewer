"""The agent's two tools: read a page, and propose a change to a page.

A tool is an ordinary function that the agent can ask us to run. Each tool below has:
  - a name and a description, which the agent reads to know what the tool does and when to use it;
  - its inputs: the values the agent must fill in when it asks for the tool;
  - the function itself, which runs here on this computer and returns text for the agent to read.

Neither tool writes anything to the wikis.
  read_page     returns a page's text.
  propose_page  checks a proposed change and, if it's sound, turns it into a card that the person
                accepts or rejects in the app. A change that fails a check goes back to the agent
                as an error message, so it can fix the change and try again.

The descriptions are part of what the agent sees: keep them in step with ingest/AGENT.md.
"""

import re

import yaml
from claude_agent_sdk import create_sdk_mcp_server, tool

from wikis import FRONTMATTER, INDEX_DIR, NOTE_EXT, RULES_FILE, TEMPLATES_DIR, Wikis, links_in


class ToolError(Exception):
    """What was wrong with the agent's request, sent back to it so it can try again."""


class RunMemory:
    """What the tools remember during one run (and its feedback rounds)."""

    def __init__(self, wikis: Wikis, run_id: str, note_ids: list[str], tell_app):
        self.wikis = wikis
        self.run_id = run_id
        self.note_ids = note_ids           # the notes being ingested
        self.tell_app = tell_app           # sends a progress line to the app
        self.pages_read: dict[str, str] = {}   # page id -> its text when the agent read it
        self.cards: dict[str, dict] = {}       # page id (or "alias:new/path.md") -> the card for it
        self.decided: dict[str, str] = {}      # card id -> "accepted" or "rejected" (feedback rounds)
        self.read_count = 0


# ---- Tool 1: read_page ------------------------------------------------------------------------

READ_PAGE = {
    "name": "read_page",
    "description": (
        "Read a wiki page or script. `page` is a link as you would write it in the wiki: a title (Saturn), "
        "a path (Planets/Saturn), or either with a wiki alias (team:Saturn). Returns the page id, its outgoing "
        "links resolved to page ids, and its full text. If nothing matches, returns the closest page names; "
        "try one of those."
    ),
    "inputs": {
        "type": "object",
        "properties": {"page": {"type": "string"}},
        "required": ["page"],
        "additionalProperties": False,
    },
}


def read_page(memory: RunMemory, page: str) -> str:
    link = str(page or "").strip()
    page_id = memory.wikis.find_page(link, pages_first=True) if link else None
    if not page_id:
        similar = memory.wikis.similar_pages(link) if link else []
        raise ToolError(f'No page matches "{link}".' + (f" Closest: {', '.join(similar)}" if similar else ""))

    found = memory.wikis.pages[page_id]
    if found.kind not in ("page", "script", "page_template"):
        raise ToolError(f"{page_id} is not a wiki page (it is a {found.kind} file).")
    try:
        text = found.text
    except (OSError, ValueError) as err:
        raise ToolError(f"Could not read {page_id}: {err}") from None

    memory.pages_read[page_id] = text
    memory.read_count += 1
    memory.tell_app({"type": "read", "page": page_id})

    # A short header first: the page's id and where its links lead, so the agent can follow them.
    links = []
    if found.kind != "script":
        for target in links_in(text):
            links.append(f"{target} -> {memory.wikis.find_page(target, found.wiki) or '(no page yet)'}")
    header = [f"id: {page_id}", "links: " + ("; ".join(links) if links else "(none)")]
    if found.kind == "script":
        header.append("This is a script: you can link to it, but not propose changes to it.")
    if found.kind == "page_template":
        header.append("This is a page template: follow it for a new page of this kind, and give its id as `template`. "
                      "Don't propose changes to it.")
    return "\n".join(header) + "\n---\n" + text


# ---- Tool 2: propose_page ---------------------------------------------------------------------

PROPOSE_PAGE = {
    "name": "propose_page",
    "description": (
        "Propose every change to one page, for a person to accept or reject. Call once per page; calling again "
        "for the same page replaces the earlier proposal. For an existing page, read it first, then give `edits`: "
        "each `find` is text copied exactly from the page as read_page returned it, long enough to occur exactly "
        "once, and `replace` is what it becomes. To add text, find the lines it goes after and repeat them in "
        "`replace` followed by the addition. For a new page, give `new_path` (folders and file name ending in .md, "
        "relative to the wiki) and `content` (the whole page, frontmatter first), and `template` if it follows a "
        "page template. `summary` is one sentence shown to the reviewer; `from_notes` lists the ids of the notes "
        "the change came from."
    ),
    "inputs": {
        "type": "object",
        "properties": {
            "wiki": {"type": "string", "description": "Alias of the wiki the page is in"},
            "page": {"type": "string", "description": "Page id from read_page, for a change to an existing page"},
            "new_path": {"type": "string", "description": "For a new page: path inside the wiki, ending in .md"},
            "template": {"type": "string", "description": "For a new page: id of the page template it follows, if any"},
            "summary": {"type": "string"},
            "from_notes": {"type": "array", "items": {"type": "string"}},
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"find": {"type": "string"}, "replace": {"type": "string"}},
                    "required": ["find", "replace"],
                    "additionalProperties": False,
                },
            },
            "content": {"type": "string"},
        },
        "required": ["wiki", "summary", "from_notes"],
        "additionalProperties": False,
    },
}


def propose_page(memory: RunMemory, wiki: str, summary: str, from_notes: list, page: str = "",
                 new_path: str = "", template: str = "", edits: list | None = None, content: str = "") -> str:
    wiki = str(wiki or "").strip()
    if wiki not in memory.wikis.aliases:
        raise ToolError(f'Unknown wiki "{wiki}". Wikis: {", ".join(memory.wikis.aliases)}.')
    summary = str(summary or "").strip()
    if not summary:
        raise ToolError("Give a one-sentence summary for the reviewer.")
    from_notes = [str(n) for n in from_notes or []]
    if not from_notes or any(n not in memory.note_ids for n in from_notes):
        raise ToolError("from_notes must list ids of notes in this run: " + ", ".join(memory.note_ids))
    page, new_path = str(page or "").strip(), str(new_path or "").strip()
    if bool(page) == bool(new_path):
        raise ToolError("Give either `page` with `edits` (an existing page) or `new_path` with `content` (a new page).")

    if page:
        change = change_existing_page(memory, wiki, page, edits or [])
    else:
        change = make_new_page(memory, wiki, new_path, str(content or ""), str(template or "").strip())
    check_frontmatter(change["after"])

    # One card per page: proposing the same page again replaces its card (same id), unless the
    # reviewer has already decided on that card.
    earlier = memory.cards.get(change["key"])
    if earlier and earlier["id"] in memory.decided:
        raise ToolError(f"The reviewer already {memory.decided[earlier['id']]} card {earlier['id']} for this page. Leave it as it is.")
    card = {"run": memory.run_id, "wiki": wiki, "summary": summary, "fromNotes": from_notes, **change,
            "id": earlier["id"] if earlier else f"c{len(memory.cards) + 1}"}
    memory.cards[card["key"]] = card
    memory.tell_app({"type": "card", "card": card})
    return f"Proposed: {card['page'] or card['wiki'] + ':' + card['path']} (card {card['id']})."


def change_existing_page(memory: RunMemory, wiki: str, page_id: str, edits: list) -> dict:
    """Applies the agent's find/replace edits to the page as it read it. -> the change."""
    # The agent sometimes names the page as it asked for it ("team:Planets/Jupiter") rather than
    # by the id read_page returned ("team:Planets/Jupiter.md"); both mean the same page.
    if page_id not in memory.pages_read:
        page_id = memory.wikis.find_page(page_id, wiki, pages_first=True) or page_id
    page = memory.wikis.pages.get(page_id)
    if not page or page_id not in memory.pages_read:
        raise ToolError(f"Read {page_id} with read_page before proposing changes to it (use the id read_page returns).")
    if page.wiki != wiki:
        raise ToolError(f"{page_id} is in wiki \"{page.wiki}\", not \"{wiki}\".")
    if page.kind != "page":
        raise ToolError(f"{page_id} is a {page.kind.replace('_', ' ')}; only wiki pages can be changed.")
    if not edits:
        raise ToolError("Give at least one edit.")
    before = memory.pages_read[page_id]
    after = before
    for n, edit in enumerate(edits, 1):
        find, replace = str(edit.get("find", "")), str(edit.get("replace", ""))
        if not find:
            raise ToolError(f"Edit {n}: `find` is empty.")
        count = after.count(find)
        if count != 1:
            raise ToolError(
                f"Edit {n}: find text occurs {count} times in {page_id}"
                + (" (after the edits before it)" if n > 1 else "")
                + ". Copy it exactly from the page, with enough lines to be unique."
            )
        after = after.replace(find, replace, 1)
    if after == before:
        raise ToolError("These edits don't change the page.")
    return {"key": page_id, "kind": "edit", "page": page_id, "path": page.path, "title": page.name, "before": before, "after": after}


BAD_PATH_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def make_new_page(memory: RunMemory, wiki: str, new_path: str, content: str, template: str) -> dict:
    """Checks a new page's path, text and template. -> the change."""
    path = new_path.replace("\\", "/").strip("/")
    parts = path.split("/")
    if not NOTE_EXT.search(path) or not path.lower().endswith(".md"):
        raise ToolError("new_path must end in .md.")
    if any(not p or p in (".", "..") or p.startswith(".") or BAD_PATH_CHARS.search(p) for p in parts):
        raise ToolError(f'"{new_path}" is not a usable path inside the wiki.')
    lower = path.lower()
    notes_dir = memory.wikis.notes_dir.lower() + "/"
    if lower.startswith(notes_dir) or lower.startswith(TEMPLATES_DIR.lower() + "/") or lower == RULES_FILE or lower.startswith(INDEX_DIR + "/"):
        raise ToolError("New pages can't go in the notes folder, Templates, or be wiki_rules.md.")
    if any(p.wiki == wiki and p.path.lower() == lower for p in memory.wikis.pages.values()):
        raise ToolError(f"{wiki}:{path} already exists. Read it and propose edits instead.")
    if not content.strip():
        raise ToolError("Give the new page's `content`.")
    content = content.replace("\r\n", "\n")
    if not content.endswith("\n"):
        content += "\n"

    change = {"key": f"{wiki}:{lower}", "kind": "new", "page": None, "path": path,
              "title": NOTE_EXT.sub("", parts[-1]), "before": "", "after": content}
    if template:
        template_id = memory.wikis.find_page(template, wiki) or template
        used = memory.wikis.pages.get(template_id)
        if not used or used.kind != "page_template" or used.wiki != wiki:
            raise ToolError(f'"{template}" is not a page template of wiki "{wiki}". Use an id from its Page templates list.')
        if template_id not in memory.pages_read:
            raise ToolError(f"Read the template {template_id} with read_page first, and follow it.")
        change.update(template=template_id, templateName=used.name)
    return change


def check_frontmatter(text: str) -> None:
    if not text.startswith("---\n"):
        return
    match = FRONTMATTER.match(text)
    if not match:
        raise ToolError("The frontmatter has no closing --- line.")
    try:
        data = yaml.load(match.group(1) or "", Loader=yaml.BaseLoader)
    except yaml.YAMLError as err:
        raise ToolError(f"The frontmatter is not valid YAML: {err}") from None
    if data is not None and not isinstance(data, dict):
        raise ToolError('The frontmatter must be "key: value" lines.')


# ---- Handing the tools to Claude Code -----------------------------------------------------------
# Plumbing: Claude Code takes tools as a small in-process "MCP server". It names them
# mcp__<server>__<tool>, so the agent sees mcp__wiki__read_page and mcp__wiki__propose_page.

TOOLS = [(READ_PAGE, read_page), (PROPOSE_PAGE, propose_page)]
TOOL_NAMES = [f"mcp__wiki__{spec['name']}" for spec, _ in TOOLS]


def tools_for_claude(memory: RunMemory):
    def wrap(spec: dict, function):
        known = spec["inputs"]["properties"]

        @tool(spec["name"], spec["description"], spec["inputs"])
        async def run(inputs: dict) -> dict:
            try:
                text, failed = function(memory, **{k: v for k, v in inputs.items() if k in known}), False
            except ToolError as err:
                text, failed = str(err), True
            except TypeError as err:  # a required input was left out
                text, failed = f"Missing input: {err}", True
            result = {"content": [{"type": "text", "text": text}]}
            if failed:
                result["is_error"] = True
            return result

        return run

    return create_sdk_mcp_server(name="wiki", version="1.0.0", tools=[wrap(spec, function) for spec, function in TOOLS])
