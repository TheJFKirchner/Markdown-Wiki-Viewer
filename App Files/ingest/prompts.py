"""The text the agent is given: its instructions, its first message, and a feedback message.

  write_instructions()      the instructions (the "system prompt"): agent-prompt.md, with the user's
                            own notes and each wiki's rules filled in.
  write_first_message()     the first message: today's date, each wiki's index, then the notes.
  write_feedback_message()  the message that continues a run with the reviewer's feedback.

Every word here reaches the agent: keep ingest/AGENT.md in step with it.
"""

from pathlib import Path

from wikis import Wikis, frontmatter

INSTRUCTIONS_FILE = Path(__file__).resolve().parent / "agent-prompt.md"


def write_instructions(wikis: Wikis, users_notes: str, today: str) -> str:
    rules = []
    for alias in wikis.aliases:
        rules_page = next((p for p in wikis.pages.values() if p.wiki == alias and p.kind == "rules"), None)
        text = rules_page.text.strip() if rules_page else "No rules file. Follow the existing pages' style."
        rules.append(f'### Wiki "{alias}"\n\n<rules>\n{text}\n</rules>')
    notes = ""
    if users_notes.strip():
        notes = "## Notes from the user\n\n<user_notes>\n" + users_notes.strip() + "\n</user_notes>\n"
    text = INSTRUCTIONS_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    return (text.replace("{{user_notes}}", notes)
                .replace("{{wikis}}", "\n\n".join(rules))
                .replace("{{date}}", today))


def write_first_message(wikis: Wikis, indexes: dict[str, str], note_ids: list[str], today: str) -> str:
    parts = [f"Today is {today}. Ingest the notes below into the wikis."]
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


FEEDBACK_MESSAGE = """The reviewer has gone through the cards.{decided}

Feedback on {count}:

{feedback}

Revise each of those proposals to follow its feedback: call propose_page again for the same page, which replaces that card. Read pages first if you need to. If feedback means a change shouldn't be made at all, don't call a tool for it; say so in one sentence that names the card. Don't propose anything else."""


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
    return FEEDBACK_MESSAGE.format(decided=summary, count=count, feedback=feedback)
