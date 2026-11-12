"""The three agents behind the Ingest view, and where each one's prompt lives.

Each agent has exactly one prompt file: an advanced slot in the app's path list (host/pathlist.py),
"prompt.<agent id>". By default the agent reads this folder's shipped file (agents/<agent id>/SKILL.md)
directly ("built_in"); nothing is copied. The person can ask for an editable copy (customise:
<the private .wiki folder>/prompts/<agent id>.md), or point the slot at any other file, such as a
Claude Code skill they already have; saving a built-in prompt makes the copy first, so the app's
own file is never written. Reset deletes the copy and goes back to the shipped file.

What an agent is sent = the body of its prompt file (everything after any frontmatter), then
whatever the code adds for that one request (the material to work on, each wiki's rules, the reply
format). The added parts are not in the file, so editing a prompt can't break a run. (There is no
shared task guide any more: the agents never write or change tasks.)

The `base` arguments below name a skills folder (<base>/<agent id>/SKILL.md) for `sb.py install`,
which puts the prompts into a .claude folder only when the person runs it.
"""

import re
import sys
from pathlib import Path

DEFAULTS_DIR = Path(__file__).resolve().parent
_HOST = str(DEFAULTS_DIR.parent / "host")
if _HOST not in sys.path:
    sys.path.append(_HOST)
import pathlist  # noqa: E402  (every path in the app comes from the path list)

# (The Notes tab's note taker is retired: notes are captured into the personal wiki by the
# executive assistant's pipeline, see sessions/. Its prompt slot is gone from the path list.)
AGENTS = [
    {"id": "executive-assistant", "name": "Executive assistant", "tab": "Sessions",
     "job": "Reads a Claude Code session and writes its session note, topics and tags into your personal wiki."},
    {"id": "wiki-reviewer", "name": "Wiki reviewer", "tab": "Review",
     "job": "Rewrites a topic page's summary once new sessions have landed on it, and suggests merging duplicate topics and tags."},
    {"id": "team-wiki-manager", "name": "Team wiki manager", "tab": "Promotion",
     "job": "Reads personal pages and queued data findings and proposes changes to the team wiki, which you accept or reject."},
]
IDS = [a["id"] for a in AGENTS]
_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.S)


def _check(agent_id):
    if agent_id not in IDS:
        raise ValueError(f"Unknown agent: {agent_id}")


def slot(agent_id):
    """The agent's prompt slot in the path list."""
    _check(agent_id)
    return "prompt." + agent_id


def skill_file(agent_id, base=None):
    """The agent's prompt file: <base>/<agent id>/SKILL.md when a skills folder is given, otherwise
    wherever the path list says (None when no private folder has been chosen yet)."""
    _check(agent_id)
    if base:
        return Path(base) / agent_id / "SKILL.md"
    return pathlist.path(slot(agent_id))


def default_text(agent_id):
    return pathlist.shipped_text(slot(agent_id))


def seed(agent_id, base=None, extra=""):
    """Copies the shipped default into a skills folder (`sb.py install`) if the agent has no file
    there yet. -> whether it did. Without base it does nothing: the app's own copies are made when
    its private folder is set up (pathlist.sync_slots)."""
    if not base:
        return False
    path = skill_file(agent_id, base)
    if path.exists():
        return False
    text = default_text(agent_id)
    if extra.strip():
        text = text.rstrip("\n") + "\n\n## My own instructions\n\n" + extra.strip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def read(agent_id, base=None):
    """The agent's whole prompt file: the person's copy, or the shipped default when there's none."""
    if base:
        path = skill_file(agent_id, base)
        return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n") if path.exists() else default_text(agent_id)
    return pathlist.read_prompt(slot(agent_id))


def body(agent_id, base=None):
    """What the agent is sent from its file: the text without any frontmatter."""
    return _FRONTMATTER.sub("", read(agent_id, base), count=1).strip()


def system(agent_id, base=None):
    """The agent's system prompt: its own prompt file's body."""
    return body(agent_id, base)


def save(agent_id, text, base=None):
    """Saves the agent's prompt. A file that starts with frontmatter (a Claude Code skill) must keep it."""
    text = (text or "").replace("\r\n", "\n")
    path = skill_file(agent_id, base)
    had_frontmatter = path is not None and path.is_file() and _FRONTMATTER.match(path.read_text(encoding="utf-8-sig"))
    if (base or had_frontmatter) and not _FRONTMATTER.match(text):
        raise ValueError("Keep the lines between the two --- at the top: Claude Code needs the skill's name and description.")
    if base:
        path.parent.mkdir(parents=True, exist_ok=True)
        pathlist.write_text_atomic(path, text)
        return
    pathlist.write_file(slot(agent_id), text)


def info(base=None):
    """For the Agents window: every agent with its job, its file, its prompt and the slot's state
    (status "built_in" (the app's own file) | "customised" | "customised_newer_default", or None when
    a file it was pointed at is missing). Saving a built-in prompt makes the editable copy first."""
    entries = {} if base else {e["name"]: e for e in pathlist.list_paths() if e["name"].startswith("prompt.")}
    out = []
    for agent in AGENTS:
        path = skill_file(agent["id"], base)
        try:
            text = read(agent["id"], base)
        except pathlist.PathMissing as error:
            text = ""
            missing = str(error)
        else:
            missing = ""
        default = default_text(agent["id"])
        entry = entries.get(slot(agent["id"]), {})
        out.append({**agent, "slot": slot(agent["id"]), "path": str(path) if path else "", "text": text,
                    "default": default, "changed": text != default, "exists": bool(path) and path.is_file(),
                    "status": entry.get("status"), "can_reset": entry.get("can_reset", False),
                    "can_customise": entry.get("can_customise", False), "error": missing})
    return out
