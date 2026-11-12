"""The agent's tools: read a page, propose a change to a page, and (a promotion only) ask the reviewer.

A tool is an ordinary function that the agent can ask us to run. Each tool below has:
  - a name and a description, which the agent reads to know what the tool does and when to use it;
  - its inputs: the values the agent must fill in when it asks for the tool;
  - the function itself, which runs here on this computer and returns text for the agent to read.

No tool writes anything to the wikis.
  read_page     returns a page's text (from any wiki in the run, view-only ones included).
  propose_page  checks a proposed change and, if it's sound, turns it into a card that the person
                accepts or rejects in the app. A change that fails a check goes back to the agent
                as an error message, so it can fix the change and try again. Only the team wiki
                (its role in Settings) can be changed: any other wiki is refused here, in code.
  ask_reviewer  (a promotion only) sends up to five questions to the app, and ends the agent's turn.

The descriptions are part of what the agent sees: keep them in step with ingest/AGENT.md.
"""

import os
import re
from pathlib import Path

import yaml
from agentlib import Tool

from wikis import FRONTMATTER, NOTE_EXT, Wikis, links_in
import pathlist  # noqa: E402  (on the path through wikis.py: each wiki's role)


class ToolError(Exception):
    """What was wrong with the agent's request, sent back to it so it can try again."""


class RunMemory:
    """What the tools remember during one run (and its feedback rounds)."""

    def __init__(self, wikis: Wikis, run_id: str, note_ids: list[str], tell_app, targets: list[str] | None = None):
        self.wikis = wikis
        self.run_id = run_id
        self.note_ids = note_ids           # the notes being ingested (for a promotion: the personal pages)
        self.targets = targets or None     # the only wikis changes may be proposed in (a promotion: the team wiki)
        # Each wiki's role (Settings): changes are only ever proposed to the "team" wiki. A view-only
        # (or personal) wiki can still be read with read_page, for context.
        self.roles = {alias: pathlist.wiki_role_for_root(root) for alias, root in wikis.roots.items()}
        self.tell_app = tell_app           # sends a progress line to the app
        self.pages_read: dict[str, str] = {}   # page id -> its text when the agent read it
        self.cards: dict[str, dict] = {}       # page id (or "alias:new/path.md") -> the card for it
        self.decided: dict[str, str] = {}      # card id -> "accepted" or "rejected" (feedback rounds)
        self.questions: list[dict] = []        # what the agent asked the reviewer (a promotion only)
        self.asked = False                     # it has asked: one round of questions per run
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
    if memory.roles.get(wiki) != "team":
        teams = [a for a, r in memory.roles.items() if r == "team" and (not memory.targets or a in memory.targets)]
        raise ToolError(pathlist.role_refusal(wiki, memory.roles.get(wiki), "team")
                        + (f" Changes may only be proposed in: {', '.join(teams)}." if teams else ""))
    if memory.targets and wiki not in memory.targets:
        raise ToolError("Changes may only be proposed in: " + ", ".join(memory.targets) + f'. "{wiki}" is where the pages came from.')
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
    if is_reserved(memory.wikis, wiki, path):
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


def is_reserved(wikis: Wikis, wiki: str, path: str) -> bool:
    """True when a new page at `path` (inside `wiki`) would land where pages don't go: the wiki's
    rules file or templates folder (where the path list says they are), or anywhere the wiki scan
    wouldn't count as a page (the notes folder, Templates/). Dot-folders, such as the .wiki folder
    older versions wrote, are already refused by the path check."""
    file = wikis.roots[wiki] / path
    rules = wikis.rules_files.get(wiki)
    if rules is not None and _key(file) == _key(rules):
        return True
    templates = wikis.templates_dirs.get(wiki)
    if templates is not None and _key(file).startswith(_key(templates).rstrip("\\/") + os.sep):
        return True
    return wikis._kind(path, wiki) != "page"


def _key(path: Path) -> str:
    """A path for comparing: absolute, one kind of slash, and case-blind (as on Windows and macOS)."""
    return os.path.normcase(os.path.abspath(path)).replace("/", os.sep).lower()


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


# ---- Tool 3: ask_reviewer (a promotion only) ---------------------------------------------------
# A personal page says what happened on one piece of work. Where a point belongs in the team
# wiki, and whether it holds in general, is often something only the person knows. Rather than
# guess, the agent may ask once, before it proposes anything. The run then stops; the app shows
# the questions, and the answers come back as the next message of the same conversation.

MAX_QUESTIONS = 5

ASK_REVIEWER = {
    "name": "ask_reviewer",
    "description": (
        "Ask the reviewer up to 5 questions before proposing, when where a point belongs in the team wiki (or "
        "whether it holds in general) is unclear and the answer changes what you would write. Each question has "
        "`about` (the point it concerns, in a few words), `question` (one plain question), and for a question of "
        "where something goes, `options`: the candidate destinations as page ids or new-page paths. You can call "
        "this once per run. After calling it, stop and wait for the answers."
    ),
    "inputs": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "about": {"type": "string"},
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["about", "question"],
                },
            },
        },
        "required": ["questions"],
        "additionalProperties": False,
    },
}


def ask_reviewer(memory: RunMemory, questions: list) -> str:
    if memory.asked:
        raise ToolError("You have already asked your questions in this run. Propose with what you know, and leave out what is still unclear.")
    asked = []
    for q in questions if isinstance(questions, list) else []:
        if not isinstance(q, dict) or not str(q.get("question") or "").strip():
            continue
        options = [str(o).strip() for o in q.get("options") or [] if str(o).strip()][:6]
        asked.append({"id": f"q{len(asked) + 1}", "about": str(q.get("about") or "").strip(),
                      "question": str(q["question"]).strip(), "options": options})
    if not asked:
        raise ToolError("Give at least one question, each with `about` and `question`.")
    if len(asked) > MAX_QUESTIONS:
        raise ToolError(f"Ask at most {MAX_QUESTIONS} questions: keep the ones whose answer changes what you would write.")
    memory.questions, memory.asked = asked, True
    memory.tell_app({"type": "questions", "questions": asked})
    return (f"{len(asked)} question{'s' if len(asked) != 1 else ''} sent to the reviewer. Stop now: reply with just \"Waiting.\" "
            "and call no more tools. The answers arrive as the next message.")


TOOLS = [(READ_PAGE, read_page), (PROPOSE_PAGE, propose_page)]


def tools_of(memory: RunMemory) -> list:
    """The run's tools: the two every run has, and ask_reviewer in a promotion."""
    return TOOLS + ([(ASK_REVIEWER, ask_reviewer)] if memory.targets else [])


# ---- Handing the tools to the agent ---------------------------------------------------------------
# Plumbing: agentlib takes each tool as a Tool (name, description, inputs, the function to run) and
# serves them to the model itself. Claude sees them as mcp__<server>__<tool>; agent.py names the
# server "wiki", so it sees mcp__wiki__read_page and so on. A function that raises ToolError sends
# its message back to the agent as an error result, which agentlib writes as
# "error: ToolError: <message>"; the turn goes on, so the agent can fix its request.

def tools_for_agent(memory: RunMemory) -> list[Tool]:
    def wrap(spec: dict, function) -> Tool:
        known = spec["inputs"]["properties"]

        def run(**inputs):
            try:
                return function(memory, **{k: v for k, v in inputs.items() if k in known})
            except TypeError as err:  # a required input was left out
                raise ToolError(f"Missing input: {err}") from None

        # ask_reviewer ends the agent's turn as soon as it succeeds: the questions go to the app,
        # and the answers come back as the next message of the same conversation.
        return Tool(name=spec["name"], description=spec["description"], schema=spec["inputs"], handler=run,
                    ends_turn=spec["name"] == ASK_REVIEWER["name"])

    return [wrap(spec, function) for spec, function in tools_of(memory)]
