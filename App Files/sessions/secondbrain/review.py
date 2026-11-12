"""The wiki reviewer's two jobs: rewrite a topic page's 'Current state', and suggest merges.

A current state is always rebuilt from the topic's session notes, never by editing the previous
state, so it cannot drift. Only the state zone is replaced; the Notes section and the log are
left exactly as they are. Capture never does this itself: a topic becomes due for review (three
new sessions, a decision reversed, a session taken off it, or a merge) and waits for the Review
tab or `sb.py review`.

Merges tidy what capture gets wrong over time: two topics for the same work, or two tags for the
same theme. The reviewer only suggests; `wiki.merge_topics` and `wiki.merge_tags` do the work
once a suggestion is accepted.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import conflicts, llm, prompts, wiki
from . import tags as taglists

MAX_NOTES = 40
MAX_NOTE_CHARS = 2500
REASONS = {"reversed": "a decision was reversed", "removed": "a session was taken off it", "merged": "topics were merged into it",
           "conflict": "a session's version was accepted over a note"}


def _due(cfg, meta: dict) -> bool:
    return bool(meta.get("needs_review")) or int(meta.get("entries_since_review") or 0) >= cfg.review_after_entries


def is_due(cfg, slug: str) -> bool:
    path = wiki.find_topic(cfg.personal, slug)
    return bool(path) and _due(cfg, wiki.read_page(path)[0])


def is_reviewed(meta: dict) -> bool:
    """Reviewed since it last changed: what Promotion requires of a topic."""
    return bool(meta.get("state_as_of")) and not meta.get("needs_review") and not int(meta.get("entries_since_review") or 0)


def list_topics(cfg) -> list[dict]:
    """Every topic with what the Review tab shows: whether it's due, and why."""
    out = []
    tagset = taglists.TagSet(cfg.personal)
    for path, meta in wiki.topic_pages(cfg.personal):
        new = int(meta.get("entries_since_review") or 0)
        flagged = bool(meta.get("needs_review"))
        why = REASONS.get(str(meta.get("review_reason") or "reversed"), "marked for review") if flagged else (f"{new} new session{'s' if new != 1 else ''}" if new else "nothing new")
        out.append({
            "slug": path.stem,
            "title": meta.get("title") or path.stem,
            "folder": meta.get("folder") or "",
            "tags": wiki.clean_tags(meta.get("tags"), 20),
            # Tags the reference tag list isn't known to have: to flag if the topic goes to a team wiki.
            "personal_tags": tagset.personal_only(wiki.clean_tags(meta.get("tags"), 20)),
            "kind": meta.get("kind") or "",   # topics made before tags became the kind may still have one
            "summary": meta.get("summary") or "",
            "updated": str(meta.get("updated") or ""),
            "state_as_of": str(meta.get("state_as_of") or ""),
            "new_sessions": new,
            "why": why,
            "due": _due(cfg, meta),
            "reviewed": is_reviewed(meta),
            "path": path.relative_to(cfg.personal).as_posix(),
        })
    out.sort(key=lambda t: t["updated"], reverse=True)
    out.sort(key=lambda t: t["due"], reverse=True)
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _settled_text(settled: list[dict]) -> str:
    how = {"keep_note": "the analyst kept the note's version: {note_text}",
           "accept_session": "the analyst accepted the session's version, so state it as the fact: {session_text}",
           "dismiss": "the analyst said this is not a conflict"}
    return "\n".join(f"- [[{c['note_ref']}]] and [[{c['session_ref']}]]: " + how[c["status"]].format(**c) for c in settled)


def _charge(root, kind: str) -> None:
    """Records the spend of a request whose reply couldn't be used (it was still paid for)."""
    spend = llm.take_spend()
    if spend.get("calls"):
        with wiki.Lock(root):
            wiki.add_spend(root, kind, spend)


def review_topic(cfg, slug: str) -> dict:
    root = cfg.personal
    wiki.require_personal(root)
    path = wiki.find_topic(root, slug)
    if not path:
        raise FileNotFoundError(f"No topic page for '{slug}'")
    meta, body = wiki.read_page(path)
    records = wiki.records_for(root, slug)
    if not records:
        raise ValueError(f"The topic '{slug}' has no session notes to review")
    used = records[-MAX_NOTES:]
    # Each record is labelled with where it came from: a note outranks a session.
    material = "\n\n".join(
        f"### [[{p.stem}]] · {m.get('date')} · {wiki.origin_of(m)} — {m.get('title')}\n{b.strip()[:MAX_NOTE_CHARS]}"
        for p, m, b in used)
    own_notes = wiki._own_notes(body)
    sessions = {p.stem: b for p, m, b in used if wiki.origin_of(m) == "session"}
    notes = {p.stem: b for p, m, b in used if wiki.origin_of(m) == "note"}
    if own_notes:
        notes[conflicts.NOTES_SECTION] = own_notes
    settled = conflicts.settled_for(root, slug)
    tagset = taglists.TagSet(root)
    current_tags = wiki.clean_tags(meta.get("tags"), 20)
    candidates = related_candidates(root, slug)
    today = datetime.now().date().isoformat()
    prompt = prompts.build("wiki-reviewer", [
        ("This request", prompts.request_text("review", today=today, slug=slug, title=meta.get("title") or slug,
                                              tags=", ".join(current_tags) or "none", kind=meta.get("kind") or "topic")),
        *prompts.personal_rules_section(),   # the personal wiki's only rules: the capture rules file
        ("Existing topics", wiki.index_text(root) or "(none)"),
        *tagset.prompt_sections(),
        ("The analyst's own notes on this topic (note level, `notes-section`)", own_notes or "(none)"),
        ("Captured notes and sessions, oldest first", material),
        ("Settled conflicts", _settled_text(settled) or "(none)"),
        ("Related topic candidates", _candidates_text(candidates) or "(none)"),
        ("Reply format", prompts.REVIEW_REPLY),
    ])
    llm.take_spend()
    try:
        data = llm.call_json(cfg, prompt, cfg.review_model, thinking=cfg.review_thinking,
                             schema=prompts.REVIEW_SCHEMA, name="wiki-reviewer")
    except llm.LLMError:
        _charge(root, "review")
        raise
    spend = llm.take_spend()
    state = data.get("state_markdown")
    if not isinstance(state, str) or not state.strip():
        with wiki.Lock(root):
            wiki.add_spend(root, "review", spend)
        raise llm.LLMError("The reviewer's reply had no state_markdown")
    state = re.sub(r"\A\s*#+\s*Current state\s*\n", "", state, flags=re.I)  # the page already has the heading
    state = re.sub(r"^#{1,6}\s+", "", state, flags=re.M)  # no headings inside: the page's own headings mark its sections
    state, dropped_tasks = drop_task_lines(state)
    found, warnings = conflicts.from_review(slug, data.get("conflicts") or [], sessions, notes)
    warnings = [*tagset.warnings, *warnings]
    if dropped_tasks:
        warnings.append(f"Task lines were left out of Current state ({dropped_tasks}): a to-do stays where it was written.")
    n_notes = sum(1 for _, m, _ in used if wiki.origin_of(m) == "note")
    counts = " and ".join(x for x in (_plural(n_notes, "note") if n_notes else "",
                                      _plural(len(used) - n_notes, "session") if len(used) > n_notes else "") if x)
    header = f"_As of {today}, from {counts}._"
    new_tags, rejected, tag_warnings = tagset.check_new(data.get("new_tags"))
    warnings += tag_warnings
    added_tags = tagset.settle(wiki.clean_tags(data.get("tags"), 20), rejected) if isinstance(data.get("tags"), list) else []

    with wiki.Lock(root):
        path = wiki.find_topic(root, slug) or path  # it may have moved into a folder meanwhile
        meta, body = wiki.read_page(path)           # and a capture may have landed during the model call
        existing = {p.stem for p, _ in wiki.topic_pages(root)}
        # Links in Current state only ever point at topics that exist.
        state, unlinked = wiki.unlink_missing(state, existing)
        related = _related_lines(data.get("related"), slug, existing)
        if unlinked:
            warnings.append(f"Links to pages that aren't topics were removed from Current state: {', '.join(dict.fromkeys(unlinked))}.")
        found = conflicts.record_review(root, slug, found)
        body = wiki.set_zone(body, "state", header + "\n\n" + conflicts.with_blocks(state, found))
        body = wiki.set_zone(wiki.ensure_related(body), "related",
                             "\n".join(f"- [[{t}]] — {why}" for t, why in related) or "_No related topics._")
        meta["tags"], tag_notes = merge_tags(wiki.clean_tags(meta.get("tags"), 20), added_tags,
                                             data.get("remove_tags"), str(meta.get("folder") or ""))
        warnings += tag_notes
        meta["state_as_of"] = today
        meta["entries_since_review"] = 0
        meta["needs_review"] = False
        meta["review_reason"] = ""
        meta["changed"] = wiki.stamp()
        summary = " ".join(data["summary"].split()) if isinstance(data.get("summary"), str) else ""
        if summary:
            meta["summary"] = wiki.unlink_missing(summary, existing)[0]
        added = taglists.add_personal(root, [n for n in new_tags if n["tag"] in (meta.get("tags") or [])])
        wiki.write_text(path, wiki.render(meta, body))
        wiki.write_index(root)
        wiki.add_spend(root, "review", spend)
    final_tags = wiki.clean_tags(meta.get("tags"), 20)
    return {"slug": slug, "title": meta.get("title") or slug, "sessions_used": len(used), "notes_used": n_notes,
            "state_as_of": today, "spend": spend, "path": path.relative_to(root).as_posix(),
            "conflicts": [conflicts.public(c) for c in found], "warnings": warnings,
            "related": [{"topic": t, "why": why} for t, why in related], "tags": final_tags,
            "personal_tags": taglists.TagSet(root).personal_only(final_tags), "new_tags": added}


MAX_TAGS = 6
TASK_LINE = wiki.TASK_LINE   # a checkbox line in any list style: "- [ ] x", "* [x] x", "1. [/] x", "[ ] x"
_LABEL_LINE = re.compile(r"^\s*\*\*[^*]+\*\*:?\s*$")


def drop_task_lines(state: str) -> tuple[str, int]:
    """Current state without to-dos: every checkbox line (and the lines indented under it) is
    taken out, and a bold label left with nothing under it goes too. The tasks stay where they
    were written. -> (state, how many task lines were dropped)"""
    kept, dropped, task_indent = [], 0, None
    for line in state.split("\n"):
        indent = len(line) - len(line.lstrip())
        if task_indent is not None and line.strip() and indent > task_indent:
            continue                    # a note under a dropped task
        task_indent = None
        m = TASK_LINE.match(line)
        if m:
            dropped += 1
            task_indent = len(m.group(1))
            continue
        kept.append(line)
    if not dropped:
        return state, 0
    out = []
    for i, line in enumerate(kept):
        if _LABEL_LINE.match(line):
            rest = next((ln for ln in kept[i + 1:] if ln.strip()), None)
            if rest is None or _LABEL_LINE.match(rest):
                continue                # a list label with nothing left under it
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), dropped


def merge_tags(current: list[str], added: list[str], removals, folder: str) -> tuple[list[str], list[str]]:
    """The topic's tags after a review: the tags it had, plus the reviewer's additions. A tag is
    taken off only when the reviewer names it under remove_tags with a reason, and never the tag
    of the folder the topic is in. Every removal (and every refused one) becomes a warning.
    -> (tags, warnings)"""
    tags, warnings = list(current), []
    for item in removals if isinstance(removals, list) else []:
        if not isinstance(item, dict):
            continue
        name = wiki.slugify(str(item.get("tag") or ""), 40)
        why = " ".join(str(item.get("why") or "").split())
        if name not in tags:
            continue                    # not on the topic: nothing to remove
        if name == folder:
            warnings.append(f"The reviewer asked to remove the tag '{name}'; it was kept, because it is the topic's folder.")
        elif not why:
            warnings.append(f"The reviewer asked to remove the tag '{name}' without a reason; it was kept.")
        else:
            tags.remove(name)
            warnings.append(f"The reviewer removed the tag '{name}': {why}")
    removed = set(current) - set(tags)
    room = max(MAX_TAGS, len(tags))
    skipped = []
    for tag in added:
        if tag in tags or tag in removed:
            continue
        if len(tags) >= room:
            skipped.append(tag)
            continue
        tags.append(tag)
    if skipped:
        warnings.append(f"Not added, because the topic already has {room} tags: {', '.join(skipped)}.")
    if folder and folder not in tags:
        tags.insert(0, folder)
    return tags, warnings


def related_candidates(root, slug: str) -> list[dict]:
    """Topics that may be related to this one, worked out from the pages (no model): filed
    together in the same session or note (with how often), sharing a tag, or linked in the
    analyst's own Notes on the page. -> [{topic, together, shared_tags, in_your_notes}]"""
    pages = {p.stem: (p, m) for p, m in wiki.topic_pages(root)}
    if slug not in pages:
        return []
    together: dict[str, int] = {}
    for _, meta, _ in wiki.session_notes(root):
        listed = list(dict.fromkeys(meta.get("topics") or []))
        if slug in listed:
            for other in listed:
                if other != slug and other in pages:
                    together[other] = together.get(other, 0) + 1
    mine = set(wiki.clean_tags(pages[slug][1].get("tags"), 20))
    shared = {t: sorted(mine & set(wiki.clean_tags(m.get("tags"), 20))) for t, (_, m) in pages.items() if t != slug}
    _, body = wiki.read_page(pages[slug][0])
    by_lower = {t.lower(): t for t in pages}
    linked = {by_lower[n.lower()] for n in wiki.links_in(wiki._own_notes(body)) if n.lower() in by_lower} - {slug}
    names = set(together) | {t for t, s in shared.items() if s} | linked
    out = [{"topic": t, "together": together.get(t, 0), "shared_tags": shared.get(t, []), "in_your_notes": t in linked}
           for t in names]
    out.sort(key=lambda c: (-c["together"], -c["in_your_notes"], -len(c["shared_tags"]), c["topic"]))
    return out[:30]


def _candidates_text(candidates: list[dict]) -> str:
    lines = []
    for c in candidates:
        why = []
        if c["together"]:
            why.append(f"filed together {_plural(c['together'], 'time')}")
        if c["shared_tags"]:
            why.append("shares tags: " + ", ".join(c["shared_tags"]))
        if c["in_your_notes"]:
            why.append("linked in the analyst's own notes")
        lines.append(f"- [[{c['topic']}]] — " + "; ".join(why))
    return "\n".join(lines)


def _related_lines(items, slug: str, existing: set[str]) -> list[tuple[str, str]]:
    """The reviewer's Related links, checked: existing topics only, not the topic itself, each once."""
    by_lower = {t.lower(): t for t in existing}
    out, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("topic") or "").strip().strip("[]").split("|")[0].strip()
        topic = by_lower.get(name.lower()) or by_lower.get(wiki.slugify(name))
        if not topic or topic == slug or topic in seen:
            continue
        seen.add(topic)
        why = " ".join(wiki.unlink_missing(str(item.get("why") or ""), existing)[0].split())[:200]
        out.append((topic, why or "related"))
    return out


def suggest_merges(cfg) -> list[dict]:
    """Ask the reviewer which topics are the same work, and which tags the same theme.
    Nothing is changed here. -> [{kind: "topic"|"tag", keep, merge: [...], reason}]"""
    root = cfg.personal
    wiki.require_personal(root)
    topics = wiki.topic_pages(root)
    tags = wiki.all_tags(root)
    if len(topics) < 2:
        return []
    listing = "\n".join(
        f"- {p.stem} — {' '.join(str(m.get('summary') or m.get('title') or '').split())}"
        f"{' · tags: ' + ', '.join(wiki.clean_tags(m.get('tags'), 20)) if m.get('tags') else ''}" for p, m in topics)
    tagset = taglists.TagSet(root)
    prompt = prompts.build("wiki-reviewer", [
        ("This request", prompts.request_text("merges", today=datetime.now().date().isoformat())),
        *prompts.personal_rules_section(),   # e.g. "every client its own page": two clients are not duplicates
        *tagset.prompt_sections(),
        ("Topics", listing),
        ("Tags in use", wiki.tags_text(root) or "(none)"),
        ("Reply format", prompts.MERGES_REPLY),
    ])
    llm.take_spend()
    try:
        data = llm.call_json(cfg, prompt, cfg.review_model, thinking=cfg.review_thinking,
                             schema=prompts.MERGES_SCHEMA, name="wiki-reviewer")
    except llm.LLMError:
        _charge(root, "merge")
        raise
    with wiki.Lock(root):
        wiki.add_spend(root, "merge", llm.take_spend())
    # Tags: any in use may be merged away, but never a reference tag; the kept one may also be a
    # tag from either list that no topic carries yet.
    names = {"topic": {p.stem for p, _ in topics}, "tag": set(tags)}
    keepable = {"topic": names["topic"], "tag": set(tags) | set(tagset.reference.values()) | set(tagset.personal.values())}
    out = []
    for kind, key in (("topic", "topic_merges"), ("tag", "tag_merges")):
        used: set[str] = set()
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            keep = wiki.slugify(item.get("keep") or "")
            if kind == "tag":
                keep = tagset.canonical(keep) or keep
            merge = [m for m in dict.fromkeys(wiki.slugify(x) for x in item.get("merge") or [])
                     if m in names[kind] and m != keep and m not in used
                     and not (kind == "tag" and tagset.is_reference(m))]
            # The reviewer's reply, checked: only names that exist, and each used once.
            if keep not in keepable[kind] or keep in used or not merge:
                continue
            used.update([keep, *merge])
            out.append({"kind": kind, "keep": keep, "merge": merge, "reason": " ".join(str(item.get("reason") or "").split())})
    return out
