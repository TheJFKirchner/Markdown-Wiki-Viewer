"""The text the agent is given: its instructions, its first message, and a feedback message.

  agent_prompt()            the agent's own prompt file (agents/agentfiles.py).
  write_instructions()      the instructions (the "system prompt"): that prompt, then each wiki's role,
                            and the team wiki's rules (the only rules file Promotion is sent).
  write_first_message()     the first message: today's date, each wiki's index, then the personal pages.
  write_feedback_message()  the message that continues a run with the reviewer's feedback.
  write_answers_message()   the message that continues a promotion with the reviewer's answers.

The wording is in prompt files the person can edit (the path list's prompt slots, see
host/pathlist.py; the shipped defaults are in agents/messages/). The structure around it (the
<index>, <note>, <feedback> and <answer> blocks) stays here, because the agent's tools and the
app rely on it.

Every word here reaches the agent: keep ingest/AGENT.md in step with it.
"""

import sys
from pathlib import Path

from wikis import Wikis, frontmatter

APP_FILES = Path(__file__).resolve().parent.parent
for _folder in (APP_FILES / "agents", APP_FILES / "host"):
    if str(_folder) not in sys.path:
        sys.path.append(str(_folder))
import agentfiles  # noqa: E402
import pathlist  # noqa: E402

SKIPPED_ANSWER = "(Skipped. Leave this point out.)"


def agent_prompt(agent_id: str) -> str:
    """The body of the agent's prompt file."""
    return agentfiles.system(agent_id)


def wikis_section() -> str:
    return pathlist.read_prompt("prompt.wikis-section").strip()


ROLE_NOTES = {   # after each wiki's heading: what the agent may do there (its role in Settings)
    "team": "the team wiki: the only wiki you propose changes to",
    "personal": "the personal wiki: where the pages come from; read only",
    "view": "view only: read it for context; never propose changes or new pages for it",
}


def write_instructions(wikis: Wikis, prompt: str, today: str) -> str:
    """The prompt, the Wikis section, then one heading per open wiki naming its role. Only the team
    wiki's heading is followed by its rules file: it is the only wiki changes are proposed to. The
    personal wiki's rules are the capture rules (never sent to Promotion), and a view-only wiki's
    rules file is not used (its pages can still be read for context)."""
    rules = []
    for alias in wikis.aliases:
        root = (getattr(wikis, "roots", None) or {}).get(alias)
        role = (pathlist.wiki_role_for_root(root) if root else None) or "view"
        heading = f'### Wiki "{alias}" ({ROLE_NOTES[role]})'
        if role != "team":
            rules.append(heading)
            continue
        text = wikis.rules_text(alias)
        text = text.strip() if text is not None else "No rules file. Follow the existing pages' style."
        rules.append(f"{heading}\n\n<rules>\n{text}\n</rules>")
    return prompt.strip().replace("{{date}}", today) + "\n\n" + wikis_section() + "\n\n" + "\n\n".join(rules) + "\n"


def write_first_message(wikis: Wikis, indexes: dict[str, str], note_ids: list[str], today: str) -> str:
    """A promotion's first message: the opening line, each wiki's index, then the personal pages."""
    parts = [pathlist.read_prompt("prompt.promotion-first-message", date=today).strip()]
    for alias in wikis.aliases:
        parts.append(f'<index wiki="{alias}">\n{indexes[alias].strip()}\n</index>')
    for note_id in note_ids:
        note = wikis.pages[note_id]
        properties, _ = frontmatter(note.text)
        attrs = "".join(
            f' {key}="{properties[key]}"' for key in ("type", "started", "ended") if isinstance(properties.get(key), str)
        )
        parts.append(f'<note id="{note_id}"{attrs}>\n{note.text.strip()}\n</note>')
    return "\n\n".join(parts) + "\n"


def page_name(card: dict) -> str:
    return card.get("page") or f"{card['wiki']}:{card['path']}"


def write_feedback_message(asked: list[tuple[dict, str]], decided: dict[str, str]) -> str:
    """One message for a whole review round: what was decided, then the feedback on each card.
    asked: (card, feedback text) pairs; decided: card id -> "accepted" or "rejected"."""
    summary = ""
    for how in ("accepted", "rejected"):
        ids = [c for c, h in decided.items() if h == how]
        if ids:
            summary += f" {how.capitalize()}: {', '.join(ids)}" + (" (written to the wiki; leave them)." if how == "accepted" else " (dropped).")
    feedback = "\n\n".join(
        f'<feedback card="{card["id"]}" kind="{"new page" if card["kind"] == "new" else "edit"}" page="{page_name(card)}" summary="{card["summary"]}">\n{text.strip()}\n</feedback>'
        for card, text in asked)
    count = f"card {asked[0][0]['id']}" if len(asked) == 1 else f"{len(asked)} cards"
    template = pathlist.read_prompt("prompt.ingest-feedback").strip()
    return pathlist.fill(template, {"decided": summary, "count": count, "feedback": feedback})


def write_answers_message(questions: list[dict], answers: dict[str, str]) -> str:
    """The message that continues a promotion with the reviewer's answers to the agent's questions.
    answers: question id -> the answer's text, or "" for a question the reviewer skipped."""
    blocks = []
    for q in questions:
        answer = (answers.get(q["id"]) or "").strip()
        blocks.append(f'<answer question="{q["id"]}" about="{q["about"]}">\n' + (answer or SKIPPED_ANSWER) + "\n</answer>")
    template = pathlist.read_prompt("prompt.ingest-answers").strip()
    if not blocks:
        template = template.replace("{{answers}}\n\n", "").replace("\n\n{{answers}}", "")
    return pathlist.fill(template, {"answers": "\n\n".join(blocks)})
