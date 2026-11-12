"""Runs the prompt evaluation against real models (it spends real tokens; see README.md).

    python run_eval.py --work <scratch folder outside the project> [--label NAME] [--rounds N]
                       [--only C1,R2] [--capture-model ID] [--review-model ID] [--jobs N]

Everything happens inside --work: a private .wiki folder, a personal wiki, a small team wiki,
transcripts and notes, all invented (cases.py). Each case gets its own copy of the wiki and of the
.wiki folder, found through WIKIAPP_DATA_DIR, so nothing reaches the user's own folders.

Captures run with --dry-run (nothing written, the reply is checked). Reviews run on records
written straight into the copy, so a review is tested on its own. A chain case captures for real
and then reviews. The Promotion case runs ingest/run.py on a synthetic topic.
Prints PASS or FAIL per expectation, then a table over all rounds, and the cost.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cases as C

HERE = Path(__file__).resolve().parent
SESSIONS_DIR = HERE.parents[1]          # App Files/sessions
APP = SESSIONS_DIR.parent               # App Files
PROJECT = APP.parent
SB = SESSIONS_DIR / "sb.py"
RUN_PY = APP / "ingest" / "run.py"
sys.path.insert(0, str(APP / "host"))
import pathlist  # noqa: E402  (root_key: how a wiki's role is keyed)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def env_for(case_dir: Path) -> dict:
    env = dict(os.environ)
    env.update({"WIKIAPP_DATA_DIR": str(case_dir / ".wiki"), "WIKIAPP_POINTER_FILE": str(case_dir / "pointer.txt"),
                "WIKIAPP_SKILLS_DIR": str(case_dir / "skills"), "PYTHONIOENCODING": "utf-8"})
    env.pop("SECOND_BRAIN_CONFIG", None)
    return env


def sb(case_dir: Path, *args: str, timeout: int = 400) -> dict:
    cmd = [sys.executable, "-X", "utf8", str(SB), args[0], "--json", "--personal", str(case_dir / "personal"), *args[1:]]
    p = subprocess.run(cmd, cwd=SESSIONS_DIR, env=env_for(case_dir), capture_output=True, text=True,
                       encoding="utf-8", timeout=timeout)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"error": f"exit {p.returncode}: {p.stdout[-500:]} {p.stderr[-1500:]}"}


def topic_page(slug: str, title: str, tags: list[str], summary: str, state: str = "", notes: str = "") -> str:
    reviewed = bool(state)
    return ("---\n"
            f"title: {title}\ntype: topic\ntags: {json.dumps(tags)}\nfolder: \"\"\nsummary: {json.dumps(summary)}\n"
            "created: 2026-11-01\nupdated: 2026-11-10\n"
            f"state_as_of: {'2026-11-11' if reviewed else json.dumps('')}\nentries_since_review: 0\nneeds_review: false\n"
            "review_reason: \"\"\n---\n"
            f"# {title}\n\n## Current state\n{state or '_Not yet summarised. See the log below._'}\n\n"
            "## Related\n_None yet. A review fills this in._\n\n"
            f"## Notes\n{notes}\n\n## Log\n")


def record(stem, origin, date, topics, title, body) -> tuple[str, str]:
    tags = sorted({t for s in topics for t in C.BASE_TOPICS.get(s, ("", [], ""))[1]})
    text = ("---\n"
            f"title: {json.dumps(title)}\ntype: session\norigin: {origin}\ndate: {date}\n"
            f"session_id: {json.dumps(('note:' if origin == 'note' else '') + stem[-8:])}\n"
            f"source: {'note' if origin == 'note' else 'claude-code'}\nproject: {json.dumps(title + '.md' if origin == 'note' else '')}\n"
            f"topics: {json.dumps(topics)}\ntags: {json.dumps(tags)}\n"
            f"entries: {json.dumps([f'{s}: {title}' for s in topics])}\ningested: \"{date}T12:00:00-05:00\"\n---\n"
            f"# {title}\n\nTopics: " + " · ".join(f"[[{s}]]" for s in topics) + "\n\n" + body)
    return f"Sessions/{stem}.md", text


def build_base(work: Path) -> Path:
    """The shared, read-only material and the wiki every case starts from."""
    base = work / "base"
    for key, (sid, cwd, day, turns, title) in C.SESSIONS.items():
        folder = re.sub(r"[^A-Za-z0-9]", "-", cwd)
        write(work / "transcripts" / folder / f"{sid}.jsonl", C.transcript(sid, cwd, day, turns, title))
    for key, (name, text) in C.NOTES.items():
        write(work / "notes" / name, text)
    write(work / "team" / "wiki_rules.md", C.TEAM_RULES)
    write(work / "team" / "team-tags.md", C.REFERENCE_TAGS)
    for rel, text in C.TEAM_PAGES.items():
        write(work / "team" / rel, text)
    if (base / "personal" / "WIKI.md").exists():
        return base
    wiki_dir = base / ".wiki"
    write(wiki_dir / "engine.json", json.dumps({"engine": "claude", "engines": {"claude": {"models": {
        "executive-assistant": "claude-haiku-5-5", "wiki-reviewer": "claude-haiku-5-5",
        "team-wiki-manager": "claude-haiku-5-5"}}}}, indent=1))
    write(wiki_dir / "paths.json", json.dumps({"version": 1, "overrides": {
        "transcripts": str(work / "transcripts"), "tag_list_reference": str(work / "team" / "team-tags.md")},
        "slots": {}}, indent=1))
    write(wiki_dir / "prompts" / "personal-capture-rules.md", C.CAPTURE_RULES)
    out = sb(base, "init")
    if "error" in out:
        raise SystemExit(f"init failed: {out}")
    write(base / "personal" / "personal-tags.md", C.PERSONAL_TAGS)
    for slug, (title, tags, summary) in C.BASE_TOPICS.items():
        write(base / "personal" / f"{slug}.md", topic_page(slug, title, tags, summary))
    sb(base, "reindex")
    return base


def fresh_case(base: Path, case_dir: Path) -> None:
    if case_dir.exists():
        shutil.rmtree(case_dir)
    shutil.copytree(base / ".wiki", case_dir / ".wiki")
    shutil.copytree(base / "personal", case_dir / "personal")
    # The case's open wikis, as the app saves them, and their roles as Settings saves them:
    # "personal" is the personal wiki and "team" the team wiki (pathlist.wiki_roles).
    wikis = {"personal": case_dir / "personal", "team": case_dir / "team"}
    write(case_dir / ".wiki" / "settings.json", json.dumps({"workspace": [{"alias": a, "root": str(r)} for a, r in wikis.items()]}))
    write(case_dir / ".wiki" / "wiki-settings.json", json.dumps({"version": 1, "roles": {
        pathlist.root_key(r): {"role": a, "root": str(r), "alias": a} for a, r in wikis.items()}}))


def state_of(page: Path) -> tuple[str, str]:
    """(Current state without its header and Conflict blocks, the Conflict blocks)."""
    text = page.read_text(encoding="utf-8")
    m = re.search(r"^## Current state\n(.*?)(?=^## )", text, re.S | re.M)
    zone = m.group(1) if m else ""
    lines = [ln for ln in zone.splitlines() if not ln.startswith("_As of")]
    return ("\n".join(ln for ln in lines if not ln.startswith(">")).strip(),
            "\n".join(ln for ln in lines if ln.startswith(">")).strip())


def page_tags(page: Path) -> list[str]:
    m = re.search(r"^tags: (.*)$", page.read_text(encoding="utf-8"), re.M)
    return json.loads(m.group(1)) if m else []


def run_review(case_dir: Path, slug: str, review_model: str) -> dict:
    page = case_dir / "personal" / f"{slug}.md"
    before = page_tags(page)
    out = sb(case_dir, "review", slug, "--model", review_model)
    reviewed = (out.get("reviewed") or [{}])[0] if isinstance(out, dict) else {}
    state, blocks = state_of(page)
    return {"result": reviewed, "errors": out.get("errors") or out.get("error"), "state": state, "blocks": blocks,
            "tags_before": before, "cost": (reviewed.get("spend") or {}).get("cost", 0)}


def run_case(case: dict, base: Path, case_dir: Path, models: dict) -> dict:
    fresh_case(base, case_dir)
    kind = case["kind"]
    if kind == "session":
        sid = C.SESSIONS[case["source"]][0]
        out = sb(case_dir, "ingest", sid, "--dry-run", "--force", "--model", models["capture"])
        out["cost"] = (out.get("spend") or {}).get("cost", 0)
        return out
    if kind == "note":
        name = C.NOTES[case["source"]][0]
        note = case_dir / "notes" / name
        write(note, C.NOTES[case["source"]][1])
        out = sb(case_dir, "capture-note", str(note), "--dry-run", "--force")
        out["cost"] = (out.get("spend") or {}).get("cost", 0)
        return out
    if kind == "review":
        root = case_dir / "personal"
        title, tags, summary = C.BASE_TOPICS[case["topic"]]
        write(root / f"{case['topic']}.md", topic_page(case["topic"], title, tags, summary, notes=case.get("notes_section", "")))
        for rec in case["records"]:
            rel, text = record(*rec)
            write(root / rel, text)
        return run_review(case_dir, case["topic"], models["review"])
    if kind == "chain":
        cost, captures, dated = 0.0, [], []
        for key in case["notes"]:
            note = case_dir / "notes" / C.NOTES[key][0]
            write(note, C.NOTES[key][1])
            captures.append(sb(case_dir, "capture-note", str(note), "--force"))
        for key in case["sessions"]:
            captures.append(sb(case_dir, "ingest", C.SESSIONS[key][0], "--force", "--model", models["capture"]))
        for c in captures:
            cost += (c.get("spend") or {}).get("cost", 0)
        for rec in (case_dir / "personal" / "Sessions").glob("*.md"):
            m = re.search(r"^entries: (.*)$", rec.read_text(encoding="utf-8"), re.M)
            for entry in json.loads(m.group(1)) if m else []:
                if C.DATE_START.match(entry.split(": ", 1)[-1]):
                    dated.append(entry)
        out = run_review(case_dir, case["topic"], models["review"])
        # Everything capture and review wrote: the records and the topic pages (not the promotion
        # queue, whose lines are checkboxes by design, and not the notes themselves).
        root = case_dir / "personal"
        written = [*sorted((root / "Sessions").glob("*.md")),
                   *(p for p in sorted(root.glob("*.md")) if p.name not in ("promotion-queue.md", "personal-tags.md"))]
        out.update({"captures": captures, "dated_entries": dated, "cost": cost + out["cost"],
                    "wiki_text": "\n\n".join(p.read_text(encoding="utf-8") for p in written)})
        return out
    if kind == "promotion":
        title, tags, summary = C.BASE_TOPICS[case["topic"]]
        write(case_dir / "personal" / f"{case['topic']}.md",
              topic_page(case["topic"], title, tags, summary, state=case["state"], notes=case.get("notes_section", "")))
        team = case_dir / "team"
        shutil.copytree(base.parent / "team", team)
        run_dir = case_dir / ".wiki" / "ingest-runs" / "eval"
        job = {"date": C.TODAY, "notesDir": "Notes",
               "wikis": [{"alias": "personal", "root": str(case_dir / "personal")}, {"alias": "team", "root": str(team)}],
               "notes": [f"personal:{case['topic']}.md"],
               "settings": {"logRaw": False, "model": models["promotion"], "maxBudgetUsd": 0.3},
               "agent": "team-wiki-manager", "targets": ["team"], "runId": "eval"}
        write(run_dir / "job.json", json.dumps(job))
        p = subprocess.run([sys.executable, "-X", "utf8", str(RUN_PY), str(run_dir / "job.json")], cwd=RUN_PY.parent,
                           env=env_for(case_dir), capture_output=True, text=True, encoding="utf-8", timeout=600)
        cards, done = {}, {}
        for line in p.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") == "card":
                cards[item["card"].get("key") or len(cards)] = item["card"]
            elif item.get("type") == "done":
                done = item
        return {"cards": list(cards.values()), "questions": done.get("questions"), "cost": done.get("cost") or 0,
                "error": None if done.get("ok") else (done.get("message") or p.stderr[-800:])}
    raise ValueError(kind)


def check(case: dict, result: dict) -> list[tuple[str, bool, str]]:
    if result.get("error") and not result.get("cards") and "extraction" not in result and "state" not in result:
        return [(name, False, f"run failed: {str(result['error'])[:300]}") for name, _ in case["expect"]]
    out = []
    for name, fn in case["expect"]:
        try:
            ok, detail = fn(result)
        except Exception as e:  # a check that can't read the result counts as a failure
            ok, detail = False, f"check error: {e}"
        out.append((name, bool(ok), detail))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True, help="scratch folder, outside the project")
    ap.add_argument("--label", default="run")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--capture-model", default="claude-haiku-5-5")
    ap.add_argument("--review-model", default="claude-haiku-5-5")
    ap.add_argument("--promotion-model", default="claude-haiku-5-5")
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()
    work = Path(args.work).resolve()
    if work == PROJECT or PROJECT in work.parents:
        raise SystemExit("--work must be outside the project folder.")
    models = {"capture": args.capture_model, "review": args.review_model, "promotion": args.promotion_model}
    base = build_base(work)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    chosen = [c for c in C.CASES if not only or c["id"] in only]
    jobs = [(r, c) for r in range(1, args.rounds + 1) for c in chosen]
    out_dir = work / args.label

    def one(job):
        r, case = job
        case_dir = out_dir / f"r{r}" / case["id"]
        try:
            result = run_case(case, base, case_dir, models)
        except Exception as e:  # noqa: BLE001  one broken case must not stop the others
            result = {"error": repr(e), "cost": 0}
        write(case_dir / "result.json", json.dumps(result, indent=1, ensure_ascii=False))
        return r, case, result, check(case, result)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        done = list(pool.map(one, jobs))

    table: dict[tuple[str, str], list[bool]] = {}
    total = 0.0
    for r, case, result, checks in sorted(done, key=lambda d: (d[0], d[1]["id"])):
        total += float(result.get("cost") or 0)
        print(f"\n[round {r}] {case['id']} ({case['kind']}): {case['tempts']}")
        for name, ok, detail in checks:
            table.setdefault((case["id"], name), []).append(ok)
            print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -- {detail[:300]}"))
    print(f"\n==== {args.label}: {args.rounds} round(s), models {models}")
    for (cid, name), oks in table.items():
        print(f"  {sum(oks)}/{len(oks)}  {cid}  {name}")
    passed = sum(sum(v) for v in table.values())
    count = sum(len(v) for v in table.values())
    print(f"  total {passed}/{count} expectations passed; cost ${total:.4f}")
    write(out_dir / "summary.json", json.dumps({"label": args.label, "rounds": args.rounds, "models": models, "cost": total,
                                                 "table": {f"{c} | {n}": v for (c, n), v in table.items()}}, indent=1))


if __name__ == "__main__":
    main()
