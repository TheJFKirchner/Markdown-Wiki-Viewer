"""Command line for session capture. Every command takes --json for use by an app."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import config, conflicts, ingest, prompts, review, transcripts, wiki
from .config import ROOT


def _out(args, payload, text: str) -> None:
    # JSON is ASCII-escaped so a caller reads it correctly whatever its console encoding.
    print(json.dumps(payload, indent=1) if args.json else text)


def cmd_init(cfg, args):
    template = (ROOT / "templates" / "personal-WIKI.md").read_text(encoding="utf-8")
    created = wiki.init_personal(cfg.personal, template)
    _out(args, {"wiki": str(cfg.personal), "created": created}, f"Personal wiki ready at {cfg.personal}")


def cmd_status(cfg, args):
    """Whether the folder is set up as a personal wiki, and how much is in it."""
    root = cfg.personal
    out = {"wiki": str(root), "exists": root.is_dir(), "type": None, "personal": False, "role": wiki.app_role(root),
           "topics": 0, "tags": 0, "folders": 0, "sessions": 0, "review_due": 0, "queue_pending": 0, "spend": {}}
    if (root / "WIKI.md").exists():
        out["type"] = wiki.read_page(root / "WIKI.md")[0].get("type") or None
    out["personal"] = root.is_dir() and wiki.is_personal(root)
    out["set_up"] = out["personal"] and (root / wiki.SESSIONS_DIR).is_dir() and (root / "index.md").is_file()
    if out["personal"]:
        wiki.upgrade_layout(root)  # a wiki from the first version: tags/ and session-notes/
        topics = review.list_topics(cfg)
        out["topics"] = len(topics)
        out["review_due"] = sum(t["due"] for t in topics)
        out["tags"] = len(wiki.all_tags(root))
        out["folders"] = len(wiki.folder_hubs(root))
        out["sessions"] = len(wiki.session_notes(root))
        out["spend"] = wiki.load_spend(root)  # running totals by kind: capture, review, merge
        queue = root / "promotion-queue.md"
        if queue.exists():
            out["queue_pending"] = sum(ln.startswith("- [ ]") for ln in queue.read_text(encoding="utf-8").splitlines())
    text = (f"{root}: personal wiki, {out['topics']} topics ({out['review_due']} due for review), {out['sessions']} session notes, "
            f"{out['queue_pending']} findings waiting for promotion") if out["personal"] else \
           f"{root}: not set up as a personal wiki (type: {out['type']}). Run 'sb.py init'."
    _out(args, out, text)


def cmd_list(cfg, args):
    result = ingest.list_sessions(cfg, args.days, include_done=args.all, min_turns=args.min_turns)
    if args.json:
        return _out(args, result, "")
    hidden = (f"{result['hidden_count']} session(s) with fewer than {result['min_turns']} of your messages hidden."
              if result["hidden_count"] else "")
    if not result["sessions"]:
        return print("\n".join(x for x in ("Nothing waiting to be ingested.", hidden) if x))
    for r in result["sessions"]:
        extra = f" +{r['subagents']} subagent(s)" if r["subagents"] else ""
        print(f"{r['status']:<9} {r['name']:<48} {r['user_messages']:>3} msgs{extra}  {r['title']}")
    if hidden:
        print(hidden)


def cmd_ingest(cfg, args):
    result = ingest.ingest_session(cfg, args.session_id, args.dry_run, args.force, args.only_new)
    _out(args, result, _describe(result))


def cmd_ingest_file(cfg, args):
    result = ingest.ingest_file(cfg, args.path, args.date, args.dry_run)
    _out(args, result, _describe(result))


def cmd_capture_note(cfg, args):
    result = ingest.ingest_note(cfg, args.path, args.dry_run, args.force)
    _out(args, result, _describe(result))


def cmd_notes_status(cfg, args):
    wiki.require_personal(cfg.personal)
    rows = [ingest.note_status(cfg, p) for p in args.paths]
    _out(args, rows, "\n".join(f"{r['status']:<9} {r['path']}" for r in rows) or "No notes given.")


def cmd_conflicts(cfg, args):
    wiki.require_personal(cfg.personal)
    rows = conflicts.open_conflicts(cfg.personal)
    _out(args, rows, "\n\n".join(f"{c['id']}  {c['topic']}\n  note:    {c['note_text']}\n  session: {c['session_text']} ([[{c['session_ref']}]])"
                                 for c in rows) or "No conflicts are waiting.")


def cmd_resolve_conflict(cfg, args):
    result = conflicts.resolve(cfg, args.id, args.resolution)
    _out(args, result, f"Settled {args.id} on {result['topic']}: {args.resolution}")


def _describe(result: dict) -> str:
    if result["status"] == "unchanged":
        return f"Not sent again: {result['reason']}"
    if result["status"] == "skipped":
        return f"Skipped: {result['reason']}" + ("\n" + _spend_line(result.get("spend")) if result.get("spend", {}).get("calls") else "")
    if result["status"] == "dry-run":
        return json.dumps(result["extraction"], indent=1, ensure_ascii=False)
    lines = [f"Ingested: {result['title']}", f"  note: {result['note']}"]
    for t in result["topics"]:
        flags = ", ".join(f for f, on in (("new", t["created"]), ("due for review", t["review_due"])) if on)
        lines.append(f"  topic: {t['slug']}" + (f" ({flags})" if flags else "") + (f"  tags: {', '.join(t['tags'])}" if t["tags"] else ""))
    if result["queued_findings"]:
        lines.append(f"  queued for promotion: {result['queued_findings']}")
    lines += [f"  warning: {w}" for w in result["warnings"]]
    lines.append(_spend_line(result.get("spend")))
    return "\n".join(l for l in lines if l)


def _spend_line(spend) -> str:
    if not spend or not spend.get("calls"):
        return ""
    return f"  cost: ${spend['cost']:.4f} at API prices, {spend.get('model') or 'model unknown'} ({spend['tokens_in']:,} tokens in, {spend['tokens_out']:,} out)"


def cmd_skip(cfg, args):
    result = ingest.skip_session(cfg, args.session_id, args.reason)
    _out(args, result, f"Skipped {result['session_id']}")


def cmd_review_list(cfg, args):
    wiki.require_personal(cfg.personal)
    topics = [t for t in review.list_topics(cfg) if t["due"] or args.all]
    if args.json:
        return _out(args, topics, "")
    if not topics:
        return print("No topics are due for review.")
    for t in topics:
        print(f"{'due' if t['due'] else '   '}  {t['slug']:<40} {t['why']:<28} {t['folder']}")


def cmd_review(cfg, args):
    slugs = [t["slug"] for t in review.list_topics(cfg) if t["due"]] if args.due else [wiki.slugify(args.topic)]
    results, errors = [], []
    for slug in slugs:
        try:
            results.append(review.review_topic(cfg, slug))
        except Exception as e:
            errors.append({"slug": slug, "error": str(e)})
    _out(args, {"reviewed": results, "errors": errors},
         "\n".join([f"Reviewed {r['slug']} from {r['sessions_used']} sessions" for r in results]
                   + [f"Failed {e['slug']}: {e['error']}" for e in errors]) or "No topics are due for review.")
    return 1 if errors else 0


def cmd_folders_suggest(cfg, args):
    wiki.require_personal(cfg.personal)
    suggestions = wiki.suggest_folders(cfg.personal, cfg.folder_after_topics)
    text = "\n".join(f"{'new folder ' if s['new'] else 'add to '}{s['tag']}: {', '.join(s['topics'])}" for s in suggestions)
    _out(args, suggestions, text or "No tag is shared by enough topics to become a folder.")


def cmd_folders_apply(cfg, args):
    wiki.require_personal(cfg.personal)
    topics = [wiki.slugify(t) for t in args.topics.split(",") if t.strip()]
    with wiki.Lock(cfg.personal):
        result = wiki.apply_folder(cfg.personal, args.tag, args.title or "", topics, datetime.now().date().isoformat())
    _out(args, result, f"Folder {result['tag']}: moved {', '.join(result['moved']) or 'nothing'}")


def cmd_merge_suggest(cfg, args):
    suggestions = review.suggest_merges(cfg)
    text = "\n".join(f"{s['kind']}: {', '.join(s['merge'])} -> {s['keep']}\n    {s['reason']}" for s in suggestions)
    _out(args, suggestions, text or "Nothing to merge.")


def cmd_merge_apply(cfg, args):
    wiki.require_personal(cfg.personal)
    merge = [wiki.slugify(t) for t in args.merge.split(",") if t.strip()]
    with wiki.Lock(cfg.personal):
        result = (wiki.merge_topics if args.kind == "topic" else wiki.merge_tags)(cfg.personal, wiki.slugify(args.keep), merge)
    _out(args, result, f"Merged {', '.join(result['merged'])} into {result['keep']}")


def cmd_reindex(cfg, args):
    if args.wiki == "team":
        if not cfg.team:
            raise config.ConfigError("team_wiki is not set in config.json")
        n = wiki.write_team_index(cfg.team)
        return _out(args, {"wiki": str(cfg.team), "pages": n}, f"Team index rebuilt: {n} pages")
    wiki.require_personal(cfg.personal)
    wiki.write_index(cfg.personal)
    _out(args, {"wiki": str(cfg.personal)}, "Personal index rebuilt")


def cmd_condense(cfg, args):
    print(transcripts.condense(ingest.resolve_session(cfg, args.session_id), cfg.max_transcript_chars))


def cmd_install(cfg, args):
    """Puts the three agents' prompt files, the helper skills and the lookup agent in a .claude folder."""
    dest = Path(args.dest).expanduser()
    prompts.agent_body("executive-assistant")  # makes agentfiles importable
    import agentfiles
    written, kept = [], []
    for agent_id in agentfiles.IDS:
        target = agentfiles.skill_file(agent_id, dest / "skills")  # an agent's prompt is never replaced, even with --force
        (written if agentfiles.seed(agent_id, dest / "skills") else kept).append(str(target))
    values = {
        "PERSONAL_WIKI": cfg.personal.as_posix(),
        "TEAM_WIKI": cfg.team.as_posix() if cfg.team else "(team_wiki not set in config.json)",
        "SB_HOME": ROOT.as_posix(),
    }
    for folder in ("skills", "agents"):
        for src in sorted((ROOT / folder).rglob("*.md")):
            target = dest / folder / src.relative_to(ROOT / folder)
            if target.exists() and not args.force:
                kept.append(str(target))
                continue
            text = src.read_text(encoding="utf-8")
            for key, value in values.items():
                text = text.replace("{{" + key + "}}", value)
            wiki.write_text(target, text)
            written.append(str(target))
    _out(args, {"written": written, "kept_existing": kept},
         "\n".join([f"wrote {p}" for p in written] + [f"kept existing {p} (use --force to replace)" for p in kept]))


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="print machine-readable JSON")
    common.add_argument("--config", help="path to config.json")
    common.add_argument("--personal", help="personal wiki folder (overrides config.json)")
    common.add_argument("--team", help="team wiki folder (overrides config.json)")
    common.add_argument("--model", help="the model for this command's request to Claude, by exact id (overrides config.json)")
    p = argparse.ArgumentParser(prog="sb.py", description="Capture sessions into a personal wiki of topics.")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, parents=[common], help=help_)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "create the personal wiki skeleton")
    add("status", cmd_status, "whether the personal wiki is set up, and what it holds")
    sp = add("list", cmd_list, "sessions waiting to be ingested")
    sp.add_argument("--days", type=int, help="lookback window (default from config)")
    sp.add_argument("--all", action="store_true", help="include ingested and skipped sessions")
    sp.add_argument("--min-turns", type=int, help="hide sessions with fewer of your messages than this (0: hide none; "
                                                  "default: WikiApp's Sessions filter, else config, else 3)")
    sp = add("ingest", cmd_ingest, "ingest one session (by id or readable name)")
    sp.add_argument("session_id")
    sp.add_argument("--dry-run", action="store_true", help="show the extraction without writing anything")
    sp.add_argument("--force", action="store_true", help="accepted for older callers; a chosen session is always captured")
    sp.add_argument("--only-new", action="store_true", help="don't send a session again that was captured and hasn't changed since")
    sp = add("capture-note", cmd_capture_note, "capture one of your notes (a Markdown file) into the personal wiki")
    sp.add_argument("path")
    sp.add_argument("--dry-run", action="store_true", help="show the extraction without writing anything")
    sp.add_argument("--force", action="store_true", help="send it again even if it hasn't changed since it was captured")
    sp = add("notes-status", cmd_notes_status, "whether notes are new, changed since capture, or captured (no model call)")
    sp.add_argument("paths", nargs="*")
    add("conflicts", cmd_conflicts, "conflicts between your notes and sessions, waiting to be settled")
    sp = add("resolve-conflict", cmd_resolve_conflict, "settle a conflict")
    sp.add_argument("id")
    sp.add_argument("resolution", choices=conflicts.RESOLUTIONS)
    sp = add("ingest-file", cmd_ingest_file, "ingest a meeting summary or notes file")
    sp.add_argument("path")
    sp.add_argument("--date", help="date of the meeting, YYYY-MM-DD (default: file modified date)")
    sp.add_argument("--dry-run", action="store_true")
    sp = add("skip", cmd_skip, "mark a session as not worth ingesting")
    sp.add_argument("session_id")
    sp.add_argument("--reason", default="")
    sp = add("review-list", cmd_review_list, "topics due for review")
    sp.add_argument("--all", action="store_true", help="every topic, not only those due")
    sp = add("review", cmd_review, "have the wiki reviewer rewrite a topic's current state")
    sp.add_argument("topic", nargs="?")
    sp.add_argument("--due", action="store_true", help="review every topic that is due")
    add("folders-suggest", cmd_folders_suggest, "tags that enough topics share to become a folder (no model call)")
    sp = add("folders-apply", cmd_folders_apply, "turn a tag into a folder and move topics into it")
    sp.add_argument("--tag", required=True)
    sp.add_argument("--title", help="for a new folder's page")
    sp.add_argument("--topics", required=True, help="comma-separated topic names")
    add("merge-suggest", cmd_merge_suggest, "have the wiki reviewer suggest topics and tags to merge")
    sp = add("merge-apply", cmd_merge_apply, "merge topics, or tags, into one")
    sp.add_argument("--kind", choices=("topic", "tag"), required=True)
    sp.add_argument("--keep", required=True, help="the one that stays")
    sp.add_argument("--merge", required=True, help="comma-separated names to fold into it")
    sp = add("reindex", cmd_reindex, "regenerate index.md")
    sp.add_argument("--wiki", choices=("personal", "team"), default="personal")
    sp = add("condense", cmd_condense, "print the cut-down transcript the model would see")
    sp.add_argument("session_id")
    sp = add("install", cmd_install, "copy the agents' prompts, helper skills and lookup agent into a .claude folder")
    sp.add_argument("--dest", default="~/.claude")
    sp.add_argument("--force", action="store_true", help="replace the helper skills and lookup agent if they exist (never an agent's prompt)")
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "review" and not args.due and not args.topic:
        parser.error("review needs a topic name or --due")
    try:
        cfg = config.load(args.config, {"personal_wiki": args.personal, "team_wiki": args.team})
        if args.model:
            cfg.extract_model = cfg.review_model = args.model
        return args.fn(cfg, args) or 0
    except config.ConfigError as e:
        code, message = 2, str(e)
    except Exception as e:
        code, message = 1, f"{type(e).__name__}: {e}"
    if args.json:
        print(json.dumps({"error": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    return code
