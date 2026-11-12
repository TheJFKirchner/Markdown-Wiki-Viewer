"""Conflicts between the person's notes and sessions, found by a topic review, and how each is settled.

Notes outrank sessions: when a session says something that contradicts a note about the same topic
(a captured note, or the text the person typed in the topic page's Notes section), the review writes
the note's version into the page's Current state, and a visible Conflict block under it shows the
session's version beside the note's. The person settles each one:

    keep_note       the note stands; the block goes.
    accept_session  Current state takes the session's version (a "Settled" line replaces the block
                    at once, and the next review writes it in). The person's note file is never edited.
    dismiss         not a real conflict; the block goes.

A conflict's id comes from the two records it is between and their text (not the model's wording),
so a settled conflict is not raised again by the next review unless one of the two texts changes.
They are kept in conflicts.json in the wiki's progress folder: {"conflicts": {id: {...}}}.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from . import wiki

NOTES_SECTION = "notes-section"   # note_ref for the text typed in the topic page's Notes section
RESOLUTIONS = ("keep_note", "accept_session", "dismiss")
ID_RE = re.compile(r"\Ac-[0-9a-f]{10}\Z")
_MAX_TEXT = 600


def _file(root):
    return wiki.state_dir(root) / "conflicts.json"


def load(root) -> dict:
    path = _file(root)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("conflicts") if isinstance(data.get("conflicts"), dict) else {}


def save(root, store: dict) -> None:
    wiki.write_text(_file(root), json.dumps({"conflicts": store}, indent=1, ensure_ascii=False))


def _one_line(text) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= _MAX_TEXT else text[: _MAX_TEXT - 1].rstrip() + "…"


def make_id(topic: str, session_ref: str, note_ref: str, basis: str) -> str:
    """The id of a conflict between two records, from their names and their text. The topic
    only counts for the page's own Notes section, which belongs to one page."""
    key = "\0".join([topic if note_ref == NOTES_SECTION else "", session_ref, note_ref, basis])
    return "c-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def basis_of(session_text: str, note_text: str) -> str:
    """A hash of the two underlying texts (the session's record and the note's record or Notes section)."""
    norm = lambda t: " ".join(str(t or "").split())
    return hashlib.sha1((norm(session_text) + "\0" + norm(note_text)).encode("utf-8")).hexdigest()


def public(c: dict) -> dict:
    """A conflict as the app is given it."""
    return {"id": c["id"], "topic": c["topic"], "note_text": c["note_text"], "session_text": c["session_text"],
            "session_ref": c["session_ref"], "note_ref": c.get("note_ref", ""), "found": c.get("found", ""),
            "status": c.get("status", "open")}


def from_review(slug: str, reported: list, sessions: dict[str, str], notes: dict[str, str]) -> tuple[list[dict], list[str]]:
    """The reviewer's conflicts, checked: each must name a session and a note it was shown.
    sessions / notes: record name -> its text (notes also has NOTES_SECTION). Several entries for
    the same pair become one. -> (conflicts, warnings)"""
    out: dict[str, dict] = {}
    warnings = []
    for item in reported if isinstance(reported, list) else []:
        if not isinstance(item, dict):
            continue
        s_ref = str(item.get("session_ref") or "").strip().strip("[]")
        n_ref = str(item.get("note_ref") or "").strip().strip("[]")
        s_text, n_text = _one_line(item.get("session_text")), _one_line(item.get("note_text"))
        if s_ref not in sessions or n_ref not in notes or not s_text or not n_text:
            warnings.append(f"A conflict the reviewer reported was left out: it didn't name a session and a note it was shown ({s_ref or '?'} / {n_ref or '?'}).")
            continue
        cid = make_id(slug, s_ref, n_ref, basis_of(sessions[s_ref], notes[n_ref]))
        if cid in out:
            out[cid]["note_text"] = _one_line(out[cid]["note_text"] + "; " + n_text)
            out[cid]["session_text"] = _one_line(out[cid]["session_text"] + "; " + s_text)
            continue
        out[cid] = {"id": cid, "topic": slug, "note_text": n_text, "session_text": s_text,
                    "session_ref": s_ref, "note_ref": n_ref}
    return list(out.values()), warnings


def record_review(root, slug: str, found: list[dict]) -> list[dict]:
    """Stores what one review of a topic found. Conflicts already settled are dropped; the topic's
    open conflicts become exactly the ones found now (a rebuilt Current state shows only those).
    Call while holding the Lock. -> the open conflicts for the topic."""
    store = load(root)
    for cid in [k for k, c in store.items() if c.get("topic") == slug and c.get("status") == "open"]:
        del store[cid]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    kept = []
    for c in found:
        if store.get(c["id"], {}).get("status") in RESOLUTIONS:
            continue   # settled before, and neither text has changed since
        store[c["id"]] = {**c, "status": "open", "found": now}
        kept.append(store[c["id"]])
    save(root, store)
    return kept


def settled_for(root, slug: str) -> list[dict]:
    """The conflicts on this topic the person has settled (for the reviewer to respect)."""
    return [c for c in load(root).values() if c.get("topic") == slug and c.get("status") in RESOLUTIONS]


def open_conflicts(root) -> list[dict]:
    """Every conflict waiting for the person, on topics that still exist."""
    topics = {p.stem for p, _ in wiki.topic_pages(root)}
    out = [public(c) for c in load(root).values() if c.get("status") == "open" and c.get("topic") in topics]
    out.sort(key=lambda c: (c["found"], c["topic"]), reverse=True)
    return out


# ---- The blocks in a topic page's Current state -------------------------------------------------

def _note_label(c: dict) -> str:
    return "Your notes on this page" if c.get("note_ref") == NOTES_SECTION else f"Your note ([[{c['note_ref']}]])"


def block(c: dict) -> str:
    return (f"> **Conflict** ({c['id']}): your note and a session disagree. Current state follows your note.\n"
            f"> {_note_label(c)}: {c['note_text']}\n"
            f"> Session ([[{c['session_ref']}]]): {c['session_text']}")


def settled_line(c: dict) -> str:
    return (f"> **Settled** ({c['id']}): you accepted the session's version over your note: "
            f"{c['session_text']} ([[{c['session_ref']}]])")


def with_blocks(state: str, found: list[dict]) -> str:
    """A Current state with a Conflict block for each open conflict under it."""
    return "\n\n".join([state.strip(), *(block(c) for c in found)]).strip()


def replace_block(state: str, cid: str, replacement: str = "") -> tuple[str, bool]:
    """The state with the block for this conflict taken out (or replaced). -> (state, found)"""
    lines = state.split("\n")
    marker = re.compile(r"^> \*\*(?:Conflict|Settled)\*\* \(" + re.escape(cid) + r"\)")
    for i, line in enumerate(lines):
        if marker.match(line):
            end = i + 1
            while end < len(lines) and lines[end].startswith(">") and not lines[end].startswith("> **"):
                end += 1
            new = lines[:i] + ([replacement] if replacement else []) + lines[end:]
            text = re.sub(r"\n{3,}", "\n\n", "\n".join(new)).strip()
            return text, True
    return state, False


def resolve(cfg, cid: str, resolution: str) -> dict:
    """Settles one conflict. -> {"conflict", "topic", "path", "changed"}"""
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise ValueError("Bad conflict id.")
    if resolution not in RESOLUTIONS:
        raise ValueError(f"Resolution must be one of: {', '.join(RESOLUTIONS)}.")
    root = cfg.personal
    wiki.require_personal(root)
    with wiki.Lock(root):
        store = load(root)
        c = store.get(cid)
        if not c:
            raise ValueError("There's no such conflict. It may have gone with the last review.")
        if c.get("status") != "open":
            raise ValueError(f"That conflict was already settled ({c.get('status')}).")
        c["status"] = resolution
        c["resolved"] = datetime.now().astimezone().isoformat(timespec="seconds")
        path = wiki.find_topic(root, c["topic"])
        changed = False
        if path:
            meta, body = wiki.read_page(path)
            state = wiki.get_zone(body, "state")
            state, found = replace_block(state, cid, settled_line(c) if resolution == "accept_session" else "")
            if found or resolution == "accept_session":
                if not found:  # the block was edited away by hand: the settled line still goes in
                    state = (state + "\n\n" + settled_line(c)).strip()
                body = wiki.set_zone(body, "state", state)
                meta["changed"] = wiki.stamp()
                if resolution == "accept_session":  # the next review writes the session's version in
                    meta["needs_review"], meta["review_reason"] = True, "conflict"
                wiki.write_text(path, wiki.render(meta, body))
                changed = True
        save(root, store)
    return {"conflict": public(c), "topic": c["topic"], "changed": changed,
            "path": path.relative_to(root).as_posix() if path else ""}
