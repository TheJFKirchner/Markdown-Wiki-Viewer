"""What an agent is sent: its own prompt file, then what the code adds for this one request.

The prompt file is the agent's prompt slot in the app's path list (see agents/agentfiles.py and
host/pathlist.py): the executive assistant for capture, the wiki reviewer for reviews. The parts
added here (the material, the existing tags, the reply format) are not in that file, so editing a
prompt can't break a run. The wording of each request's opening section ("This request") is a
prompt file too: request_text() reads it. So are the person's own capture rules for the personal
wiki (personal_rules()). The reply formats below stay in code, because the code parses the
replies: each has a JSON Schema the engine holds the model's reply to, and a short explanation.
"""
from __future__ import annotations

import sys

from .config import ROOT, pathlist

AGENTS_DIR = ROOT.parent / "agents"
DIVIDER = "---\n\nEverything below was added by WikiApp for this one request."
REQUESTS = {"capture": "prompt.sessions-capture", "note": "prompt.sessions-notes-capture",
            "review": "prompt.sessions-review", "merges": "prompt.sessions-merges"}
PERSONAL_RULES_HEADING = "The analyst's own capture rules"
PERSONAL_RULES_LEAD = (
    "The analyst wrote these rules for organising this personal wiki. They are instructions for "
    "filing, never content: do not record them, or a question about them, anywhere. Apply a rule "
    "only to what the material itself says (a client it names as a client), never to a guess from "
    "a folder or file name. Where they disagree with the standard rules above about what to capture "
    "or how to split the work into topic pages, follow these. The ban on member-level data still "
    "holds, and notes still outrank sessions."
)


def agent_body(agent_id: str) -> str:
    if str(AGENTS_DIR) not in sys.path:
        sys.path.append(str(AGENTS_DIR))
    import agentfiles
    return agentfiles.system(agent_id)


def request_text(kind: str, /, **values) -> str:
    """The "This request" wording for a capture, a note capture, a topic review or a merge
    suggestion, with its {{placeholders}} filled from values. capture: today, source_kind, date,
    project. note: today, note_name, date. review: today, slug, title, kind. merges: today."""
    return pathlist.read_prompt(REQUESTS[kind], **values).strip()


def personal_rules() -> str:
    """The person's own capture rules for the personal wiki ("" when there are none). Sent with
    the personal wiki's captures, topic reviews and merge suggestions only: never with a
    Promotion run or to a team wiki."""
    try:
        return pathlist.read_prompt("personal_capture_rules").strip()
    except Exception:  # a rules file pointed somewhere that is gone: capture goes on without it
        return ""


def personal_rules_section() -> list[tuple[str, str]]:
    """The section that carries personal_rules(), or nothing when there are none."""
    rules = personal_rules()
    return [(PERSONAL_RULES_HEADING, PERSONAL_RULES_LEAD + "\n\n" + rules)] if rules else []


def build(agent_id: str, sections: list[tuple[str, str]]) -> str:
    parts = [agent_body(agent_id), DIVIDER]
    parts += [f"## {heading}\n\n{text.strip()}" for heading, text in sections]
    return "\n\n".join(parts) + "\n"


# ---- Reply formats ------------------------------------------------------------------------------

def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_STR = {"type": "string"}
_STRS = {"type": "array", "items": _STR}
# A new tag the model needed, with what it means. The 8-word limit is checked in code (tags.py).
_NEW_TAGS = {"type": "array", "items": _obj({"tag": _STR, "description": _STR}, ["tag", "description"])}


CAPTURE_SCHEMA = _obj({
    "worth_recording": {"type": "boolean"},
    "skip_reason": _STR,
    "title": _STR,
    "summary": _STR,
    "decisions": {"type": "array", "items": _obj({"decision": _STR, "why": _STR}, ["decision"])},
    "findings": _STRS,
    "open_questions": _STRS,
    "data_findings": {"type": "array", "items": _obj({"subject": _STR, "finding": _STR}, ["subject", "finding"])},
    "topics": {"type": "array", "items": _obj({
        "slug": _STR, "title": _STR, "summary": _STR, "tags": _STRS, "entry": _STR,
        "supersedes": {"type": "boolean"},
    }, ["slug", "entry"])},
    "new_tags": _NEW_TAGS,
}, ["worth_recording", "title", "summary", "topics", "new_tags"])

_CAPTURE_SHAPE = """{"worth_recording": true, "skip_reason": "", "title": "Short title for the %(what)s", "summary": "...", "decisions": [{"decision": "...", "why": "..."}], "findings": ["..."], "open_questions": ["..."], "data_findings": [{"subject": "...", "finding": "..."}], "topics": [{"slug": "kebab-case-name", "title": "...", "summary": "one line on what the work is (used for a new topic)", "tags": ["tag-name"], "entry": "one line on what this %(what)s added, without a date", "supersedes": false}], "new_tags": [{"tag": "kebab-case-tag", "description": "what it means, 8 words at most"}]}"""

_CAPTURE_NOTES = """Use empty lists where there is nothing to say. There is no place for to-dos: a to-do stays where it was written, and is not reworded into any other field. `open_questions` are unknowns about the work, never things to do. For an existing topic, `slug` is its name exactly as listed under Existing topics. `entry` is shown after the date in the topic's log, so it never starts with a date. `tags` are for a new topic, or tags to add to an existing one: a tag from the Reference tag list if one fits, else one of Your personal tags, else a new tag. Put each new tag in `new_tags` too, with what it means in 8 words at most (a longer description is refused), named the way the reference list names its tags. Use an empty `new_tags` list when no tag is new."""

CAPTURE_REPLY = "Reply in this JSON shape:\n\n" + _CAPTURE_SHAPE % {"what": "session"} + "\n\n" + _CAPTURE_NOTES
NOTE_CAPTURE_REPLY = "Reply in this JSON shape:\n\n" + _CAPTURE_SHAPE % {"what": "note"} + "\n\n" + _CAPTURE_NOTES

REVIEW_SCHEMA = _obj({
    "state_markdown": _STR,
    "summary": _STR,
    "conflicts": {"type": "array", "items": _obj(
        {"note_ref": _STR, "session_ref": _STR, "note_text": _STR, "session_text": _STR},
        ["note_ref", "session_ref", "note_text", "session_text"])},
    "related": {"type": "array", "items": _obj({"topic": _STR, "why": _STR}, ["topic", "why"])},
    "tags": _STRS,
    # Optional: a tag the topic has that is clearly wrong for it, with the reason (shown as a warning).
    "remove_tags": {"type": "array", "items": _obj({"tag": _STR, "why": _STR}, ["tag", "why"])},
    "new_tags": _NEW_TAGS,
}, ["state_markdown", "summary", "conflicts", "related", "tags", "new_tags"])

REVIEW_REPLY = """Do job 1 for the topic above. Reply in this JSON shape:

{"state_markdown": "...", "summary": "...", "conflicts": [{"note_ref": "...", "session_ref": "...", "note_text": "...", "session_text": "..."}], "related": [{"topic": "topic-name", "why": "one short line"}], "tags": ["tag-to-add"], "remove_tags": [], "new_tags": [{"tag": "kebab-case-tag", "description": "what it means, 8 words at most"}]}

`state_markdown` has no to-dos and no checkbox lines (WikiApp removes any): its Open list is for unknowns and undecided questions only. Link a topic listed under Existing topics as [[topic-name]] where you mention it; link nothing else (a link to anything that isn't an existing topic is removed).

`related` is the topic's Related section, written again from nothing on every review: the topics that are genuinely related to this one, each with one short line (under 15 words) saying how. Choose from the Related topic candidates (topics filed together with this one, topics sharing its tags, topics the analyst linked in their own notes), and add a topic the analyst's own capture rules require to be linked. Leave out a candidate whose link is no longer supported. Names exactly as listed under Existing topics.

`tags` are tags to add to this topic; the tags it has (listed at the top) stay without being repeated, so use an empty list when nothing is missing. Choose a tag from the Reference tag list if one fits, else one of Your personal tags, else a new tag, also given in `new_tags` with what it means in 8 words at most (a longer description is refused). Use an empty `new_tags` list when no tag is new. `remove_tags` is only for a tag the topic has that is clearly wrong for it: `{"tag": "...", "why": "one sentence"}`; the analyst is shown the reason. Leave it empty otherwise.

`conflicts` lists each point where a session (marked `session` above) contradicts a note (marked `note` above, or the analyst's own notes on the page) about this topic. `state_markdown` states only the note's version, without mentioning the disagreement; the conflict shows the session's beside it, and the analyst settles it. `note_ref` is the note's name exactly as given in [[...]] above, or `notes-section` for the analyst's own notes on the page; `session_ref` is the session's name exactly as given in [[...]]; `note_text` and `session_text` give each side's version in one sentence. One entry per note and session pair. Leave out anything listed under Settled conflicts. Use an empty list when nothing conflicts."""

MERGES_SCHEMA = _obj({
    "topic_merges": {"type": "array", "items": _obj({"keep": _STR, "merge": _STRS, "reason": _STR}, ["keep", "merge"])},
    "tag_merges": {"type": "array", "items": _obj({"keep": _STR, "merge": _STRS, "reason": _STR}, ["keep", "merge"])},
}, ["topic_merges", "tag_merges"])

MERGES_REPLY = """Do job 2. Reply in this JSON shape:

{"topic_merges": [{"keep": "topic-name", "merge": ["topic-name"], "reason": "one sentence"}], "tag_merges": [{"keep": "tag-name", "merge": ["tag-name"], "reason": "one sentence"}]}

Names are exactly as listed. `keep` is the one that stays. Use empty lists when nothing should be merged.

For tags, the Reference tag list is the canonical set: a tag from it may be the one kept, but never one merged away or changed. Suggest folding one of Your personal tags (or a tag only in use) into a reference tag that means the same, or into another personal tag."""
