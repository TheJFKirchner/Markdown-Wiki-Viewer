"""Subagents folded into their session, readable session names, the minimum-turns filter, and the
personal wiki's role, all without a request to a model (the capture step is stubbed or runs on
agentlib's fake engine). Run: python -m unittest discover tests

The transcripts here copy the structure Claude Code writes (line types and keys), never content:
an Agent call answered by a foreground report (toolUseResult.status "completed") or, for one run in
the background, by "async_launched" and later a <task-notification> user line (origin.kind
"task-notification"); the subagent's own transcript in <session>/subagents/agent-<id>.jsonl with
agent-<id>.meta.json naming the call.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from secondbrain import config, ingest, llm, transcripts, wiki  # noqa: E402
from secondbrain.config import pathlist  # noqa: E402

try:
    from agentlib import fake
except ImportError:  # agentlib isn't installed in this Python
    fake = None

SID = "aaaaaaaa-1111-2222-3333-444444444444"
SYNC_REPORT = "SYNC-REPORT: the orders mart load failed on Monday."
ASYNC_REPORT = "ASYNC-REPORT: churn is computed from the orders mart."
INSTRUCTION = "Check the orders mart load log for last week and report what failed."


def line(kind, ts, content, **extra):
    base = {"sessionId": SID, "cwd": "C:\\work\\x", "isSidechain": False, "entrypoint": "cli", "type": kind,
            "timestamp": ts, "message": {"role": kind, "content": content}}
    base.update(extra)
    return json.dumps(base)


def notification(tool_use_id, status, summary, result):
    return ("<task-notification>\n<task-id>bg1</task-id>\n" + f"<tool-use-id>{tool_use_id}</tool-use-id>\n"
            f"<output-file>x.output</output-file>\n<status>{status}</status>\n<summary>{summary}</summary>\n"
            + (f"<result>{result}</result>\n" if result is not None else "")
            + "<usage><subagent_tokens>1</subagent_tokens><tool_uses>2</tool_uses></usage>\n</task-notification>")


def write_session(folder: Path, sid=SID, titles=(("custom-title", "customTitle", "Churn dashboard fix"),),
                  person=("Why did churn jump?", "Yes, confirmed: the failed load is the cause.", "Thanks, that's all."),
                  with_subagents=True, day="2026-11-10"):
    """A session: the person's messages, a foreground subagent, a background subagent reported by a
    <task-notification>, a background shell command's notification, a peer message, and titles."""
    ts = lambda i: f"{day}T10:{i:02d}:00Z"  # noqa: E731
    lines = [line("user", ts(0), person[0], origin={"kind": "human"}, sessionId=sid)]
    if with_subagents:
        lines += [
            line("assistant", ts(1), [{"type": "text", "text": "I'll ask two helpers."},
                                      {"type": "tool_use", "id": "t-sync", "name": "Agent",
                                       "input": {"description": "Check load log", "prompt": INSTRUCTION, "subagent_type": "general-purpose"}},
                                      {"type": "tool_use", "id": "t-async", "name": "Agent",
                                       "input": {"description": "Find churn source", "prompt": "Find where churn is computed.",
                                                 "subagent_type": "Explore", "run_in_background": True}}], sessionId=sid),
            line("user", ts(2), [{"type": "tool_result", "tool_use_id": "t-sync", "content": [{"type": "text", "text": SYNC_REPORT}]}],
                 toolUseResult={"status": "completed", "agentId": "a111", "prompt": INSTRUCTION, "content": [{"type": "text", "text": SYNC_REPORT}]},
                 sessionId=sid),
            line("user", ts(3), [{"type": "tool_result", "tool_use_id": "t-async", "content": "Async agent launched successfully."}],
                 toolUseResult={"status": "async_launched", "agentId": "a222", "isAsync": True}, sessionId=sid),
            line("assistant", ts(4), [{"type": "tool_use", "id": "t-bash", "name": "Bash",
                                       "input": {"command": "python long_job.py", "run_in_background": True}}], sessionId=sid),
            line("user", ts(5), notification("t-async", "completed", 'Agent "Find churn source" completed', ASYNC_REPORT),
                 origin={"kind": "task-notification"}, promptSource="system", sessionId=sid),
            line("user", ts(6), notification("t-bash", "completed", "Background command finished", "ROW-OUTPUT 998877665544"),
                 origin={"kind": "task-notification"}, sessionId=sid),
            line("user", ts(7), "A message from another session.", origin={"kind": "peer", "from": "x"}, sessionId=sid),
            line("assistant", ts(8), [{"type": "text", "text": "Both helpers think the failed load explains it. Is that right?"}], sessionId=sid),
        ]
    for i, text in enumerate(person[1:], 9):
        lines.append(line("user", ts(i), text, sessionId=sid))
        lines.append(line("assistant", ts(i), [{"type": "text", "text": "Noted."}], sessionId=sid))
    for kind, key, value in titles:
        lines.append(json.dumps({"type": kind, key: value, "sessionId": sid}))
    path = folder / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if with_subagents:
        sub = folder / sid / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        for agent, call, desc, last in (("a111", "t-sync", "Check load log", SYNC_REPORT),
                                        ("a222", "t-async", "Find churn source", ASYNC_REPORT)):
            (sub / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": "general-purpose", "description": desc,
                                                                       "toolUseId": call}), encoding="utf-8")
            (sub / f"agent-{agent}.jsonl").write_text("\n".join([
                line("user", ts(1), desc, isSidechain=True, agentId=agent, sessionId=sid),
                line("assistant", ts(2), [{"type": "tool_use", "id": "s1", "name": "Grep", "input": {"pattern": "load", "path": "logs"}},
                                          {"type": "tool_use", "id": "s2", "name": "Read", "input": {"file_path": "logs/load.log"}}],
                     isSidechain=True, agentId=agent, sessionId=sid),
                line("user", ts(3), [{"type": "tool_result", "tool_use_id": "s2", "content": "SUBAGENT-TOOL-OUTPUT"}],
                     isSidechain=True, agentId=agent, sessionId=sid),
                line("assistant", ts(4), [{"type": "text", "text": last}], isSidechain=True, agentId=agent, sessionId=sid),
            ]) + "\n", encoding="utf-8")
    return path


def sections(text: str) -> dict:
    """{header: [bodies]} of a condensed transcript."""
    out = {}
    for part in text.split("\n\n## "):
        head, _, body = part.lstrip("# ").partition("\n")
        out.setdefault(head, []).append(body)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved_env = {k: os.environ.pop(k, None) for k in ("WIKIAPP_DATA_DIR", "WIKIAPP_POINTER_FILE", "WIKIAPP_SKILLS_DIR")}
        os.environ["WIKIAPP_POINTER_FILE"] = str(self.base / "no-pointer.txt")   # never the user's real folder
        os.environ["WIKIAPP_SKILLS_DIR"] = str(self.base / "skills")
        self.projects = self.base / "projects"
        self.folder = self.projects / "C--work-x"
        self.wiki = self.base / "personal"
        self.cfg = config.Config({"personal_wiki": str(self.wiki), "transcripts_dir": str(self.projects), "min_turns": 0}, None)

    def tearDown(self):
        for key, value in self.saved_env.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        self.tmp.cleanup()

    def capture(self, ref=SID, title="Churn jump traced to the failed load"):
        reply = {"worth_recording": True, "title": title, "summary": "The analyst confirmed the cause.",
                 "decisions": [], "findings": ["The failed load caused the churn jump"], "open_questions": [],
                 "data_findings": [], "new_tags": [],
                 "topics": [{"slug": "churn-dashboard", "title": "Churn dashboard", "summary": "Weekly churn",
                             "tags": ["dashboard"], "entry": "Traced the jump to the failed load", "supersedes": False}]}
        with mock.patch.object(llm, "call_json", return_value=reply) as call:
            result = ingest.ingest_session(self.cfg, ref)
        self.prompt = call.call_args[0][1] if call.called else ""
        return result


class SubagentTest(Base):
    def setUp(self):
        super().setUp()
        self.path = write_session(self.folder)

    def test_subagent_reports_are_in_the_transcript_and_never_the_users(self):
        text = transcripts.condense(self.path, 100000)
        parts = sections(text)
        users = "\n".join(parts.get("USER", []))
        assistant = "\n".join(parts.get("ASSISTANT", []))
        subagent = "\n".join(parts.get(transcripts.SUBAGENT_ROLE, []))
        # Both reports reached the session, attributed to the subagent that wrote them.
        self.assertIn(f'SUBAGENT "Check load log" reported', subagent)
        self.assertIn(SYNC_REPORT, subagent)
        self.assertIn(f'SUBAGENT "Find churn source" reported', subagent)
        self.assertIn(ASYNC_REPORT, subagent)
        # The assistant's instructions to a subagent are the assistant's side.
        self.assertIn('instructions to SUBAGENT "Check load log": ' + INSTRUCTION, assistant)
        # Nothing a subagent wrote or was told, and no notification, is labelled USER.
        for banned in (SYNC_REPORT, ASYNC_REPORT, INSTRUCTION, "task-notification", "another session"):
            self.assertNotIn(banned, users)
        self.assertEqual(users.count("\n") + 1 if users else 0, 3)                    # the person's three messages
        self.assertIn("Why did churn jump?", users)
        # A background shell command keeps only its summary; its output (tool output) never appears.
        self.assertIn("background task finished: Background command finished", assistant)
        self.assertNotIn("ROW-OUTPUT", text)
        self.assertNotIn("SUBAGENT-TOOL-OUTPUT", text)                                  # a subagent's tool output neither
        self.assertIn("(its steps: Grep load logs; Read logs/load.log)", subagent)      # its steps, after the report

    def test_only_the_persons_messages_count_and_subagents_are_counted(self):
        meta = transcripts.read_meta(self.path)
        self.assertEqual(meta["user_messages"], 3)
        self.assertEqual(meta["subagents"], 2)
        self.assertEqual(meta["first_prompt"], "Why did churn jump?")

    def test_subagent_transcripts_are_never_listed_as_sessions(self):
        old_style = self.folder / "agent-a333.jsonl"   # where older versions kept a subagent's transcript
        old_style.write_text(line("user", "2026-11-10T09:00:00Z", "Hello", sessionId="x") + "\n", encoding="utf-8")
        listed = [m["session_id"] for m in transcripts.recent_sessions(self.cfg, 100000)]
        self.assertEqual(listed, [SID])
        with self.assertRaises(FileNotFoundError):
            transcripts.find_session(self.cfg, "agent-a333")

    def test_a_report_that_never_arrived_comes_from_the_subagents_own_transcript(self):
        text = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text("\n".join(l for l in text if "t-async</tool-use-id>" not in l) + "\n", encoding="utf-8")
        subagent = "\n".join(sections(transcripts.condense(self.path, 100000)).get(transcripts.SUBAGENT_ROLE, []))
        self.assertIn('SUBAGENT "Find churn source" reported (its last message; no report reached the session)', subagent)
        self.assertIn(ASYNC_REPORT, subagent)

    def test_a_tight_budget_keeps_the_report_before_the_steps(self):
        long_report = "REPORT-START " + "detail " * 600
        lines = self.path.read_text(encoding="utf-8").replace(SYNC_REPORT, long_report)
        self.path.write_text(lines, encoding="utf-8")
        text = transcripts.condense(self.path, 2500)
        self.assertLessEqual(len(text), 2500)
        self.assertIn("REPORT-START", text)
        self.assertNotIn('"Check load log" reported', "\n".join(sections(text).get("USER", [])))

    def test_capture_sends_the_labelled_transcript(self):
        wiki.init_personal(self.wiki, "---\ntype: personal\n---\n")
        self.capture()
        self.assertIn(ASYNC_REPORT, self.prompt)
        self.assertIn("## " + transcripts.SUBAGENT_ROLE, self.prompt)


class NameTest(Base):
    def setUp(self):
        super().setUp()
        wiki.init_personal(self.wiki, "---\ntype: personal\n---\n")

    def names(self):
        with mock.patch.object(llm, "call_json") as call:
            rows = ingest.list_sessions(self.cfg, 100000)["sessions"]
        self.assertFalse(call.called)                                                   # no model call
        return {r["session_id"]: r["name"] for r in rows}

    def test_a_name_is_given_once_from_the_title_and_stays(self):
        write_session(self.folder, with_subagents=False)
        self.assertEqual(self.names(), {SID: "2026-11-10-churn-dashboard-fix"})
        # Claude Code renames the session later: the name it was given stays.
        write_session(self.folder, with_subagents=False, titles=(("custom-title", "customTitle", "Something else entirely"),))
        self.assertEqual(self.names(), {SID: "2026-11-10-churn-dashboard-fix"})
        self.assertEqual(wiki.load_ledger(self.wiki)[SID]["name"], "2026-11-10-churn-dashboard-fix")   # kept in the ledger
        # Captured: the ledger entry keeps it, and the session can be named by it.
        result = self.capture(ref="2026-11-10-churn-dashboard-fix")
        self.assertEqual((result["status"], result["name"]), ("ingested", "2026-11-10-churn-dashboard-fix"))
        self.assertEqual(wiki.load_ledger(self.wiki)[SID]["name"], "2026-11-10-churn-dashboard-fix")

    def test_words_come_from_the_generated_title_else_the_first_message(self):
        other = "bbbbbbbb-1111-2222-3333-444444444444"
        write_session(self.folder, with_subagents=False, titles=(("ai-title", "aiTitle", "Investigate churn spike"),))
        write_session(self.folder, sid=other, with_subagents=False, titles=(), person=("Please tidy the returns forecast notes", "ok", "thanks"))
        self.assertEqual(self.names(), {SID: "2026-11-10-investigate-churn-spike",
                                        other: "2026-11-10-please-tidy-the-returns-forecast"})

    def test_a_clash_gets_a_short_suffix(self):
        other = "bbbbbbbb-1111-2222-3333-444444444444"
        write_session(self.folder, with_subagents=False)
        write_session(self.folder, sid=other, with_subagents=False)
        names = self.names()
        self.assertEqual(sorted(names.values()), ["2026-11-10-churn-dashboard-fix", "2026-11-10-churn-dashboard-fix-" +
                                                  (other if names[SID] == "2026-11-10-churn-dashboard-fix" else SID)[:4]])
        self.assertEqual(self.names(), names)                                           # stable

    def test_new_record_files_have_no_id_suffix_unless_needed(self):
        other = "bbbbbbbb-1111-2222-3333-444444444444"
        write_session(self.folder, with_subagents=False)
        write_session(self.folder, sid=other, with_subagents=False)
        first = self.capture()
        self.assertEqual(first["note"], "Sessions/2026-11-10-churn-jump-traced-to-the-failed-load.md")
        second = self.capture(ref=other)                                                # same title, same day
        self.assertEqual(second["note"], "Sessions/2026-11-10-churn-jump-traced-to-the-failed-load-bbbbbbbb.md")
        self.assertEqual(wiki.read_page(self.wiki / first["note"])[0]["session_id"], SID)   # the id stays in the record


class FilterTest(Base):
    def setUp(self):
        super().setUp()
        wiki.init_personal(self.wiki, "---\ntype: personal\n---\n")
        write_session(self.folder)                                                      # 3 of the person's messages
        self.short = "cccccccc-1111-2222-3333-444444444444"
        write_session(self.folder, sid=self.short, with_subagents=False, person=("Quick question?",))
        self.cfg.min_turns = None                                                       # the setting decides

    def test_the_filter_hides_short_sessions_and_capture_still_works(self):
        result = ingest.list_sessions(self.cfg, 100000)
        self.assertEqual(result["min_turns"], 3)                                        # the default
        self.assertEqual([r["session_id"] for r in result["sessions"]], [SID])
        self.assertEqual(result["hidden_count"], 1)
        row = result["sessions"][0]
        self.assertEqual((row["user_messages"], row["subagents"]), (3, 2))               # subagents never count as turns
        self.assertEqual(self.capture(ref=self.short)["status"], "ingested")             # chosen: captured anyway

    def test_the_setting_wins_then_config(self):
        data = self.base / "data"
        data.mkdir()
        os.environ["WIKIAPP_DATA_DIR"] = str(data)
        self.assertEqual(pathlist.set_sessions_filter(0), {"min_turns": 0, "options": [0, 3, 5, 10, 20]})
        self.assertEqual(ingest.list_sessions(self.cfg, 100000)["hidden_count"], 0)
        pathlist.set_sessions_filter(5)
        self.assertEqual(ingest.list_sessions(self.cfg, 100000)["hidden_count"], 2)
        with self.assertRaises(ValueError):
            pathlist.set_sessions_filter(4)
        os.environ.pop("WIKIAPP_DATA_DIR")
        old = config.Config({"personal_wiki": str(self.wiki), "min_user_messages": 1}, None)   # the older key, as a fallback
        self.assertEqual(old.hide_below(), 1)                                            # on the command line on its own
        self.assertEqual(config.Config({"personal_wiki": str(self.wiki)}, None).hide_below(), 3)

    def test_with_the_app_the_list_and_the_filter_always_agree(self):
        data = self.base / "data2"
        data.mkdir()
        os.environ["WIKIAPP_DATA_DIR"] = str(data)
        cfg = config.Config({"personal_wiki": str(self.wiki), "transcripts_dir": str(self.projects),
                             "min_user_messages": 1, "min_turns": 2}, None)              # a config.json the app ignores
        self.assertEqual(pathlist.get_sessions_filter()["min_turns"], 3)                 # never set: what the app shows...
        self.assertEqual(ingest.list_sessions(cfg, 100000)["min_turns"], 3)              # ...is what sb.py uses
        pathlist.set_sessions_filter(10)                                                 # once set, the stored filter wins
        self.assertEqual((pathlist.get_sessions_filter()["min_turns"], cfg.hide_below()), (10, 10))


class RoleTest(Base):
    """The personal wiki is the open wiki whose role is "personal" (WikiApp's private folder)."""

    def setUp(self):
        super().setUp()
        self.data = self.base / "data"
        self.data.mkdir()
        os.environ["WIKIAPP_DATA_DIR"] = str(self.data)
        self.wiki.mkdir()                                                               # no WIKI.md at all
        self.northwind = self.base / "northwind"
        self.northwind.mkdir()
        (self.northwind / "WIKI.md").write_text("---\ntype: personal\n---\n", encoding="utf-8")   # says personal; the role decides
        self.team = self.base / "team"
        self.team.mkdir()
        (self.data / "settings.json").write_text(json.dumps({"workspace": [
            {"alias": "mine", "root": str(self.wiki)}, {"alias": "Northwind", "root": str(self.northwind)},
            {"alias": "team", "root": str(self.team)}]}), encoding="utf-8")
        pathlist.set_wiki_role("mine", "personal")
        pathlist.set_wiki_role("team", "team")
        write_session(self.folder, with_subagents=False)

    def test_the_personal_role_is_enough_and_set_up_makes_no_wiki_md(self):
        created = wiki.init_personal(self.wiki, "---\ntype: personal\n---\n")            # "Set up"
        self.assertEqual(created, ["Sessions/", "promotion-queue.md", "index.md"])        # exactly what it made
        self.assertFalse((self.wiki / "WIKI.md").exists())
        self.assertEqual(wiki.init_personal(self.wiki, ""), [])                           # again: nothing new
        self.assertEqual(self.capture()["status"], "ingested")
        # An existing WIKI.md is left alone, whatever it says: the role decides.
        (self.wiki / "WIKI.md").write_text("---\ntype: team\n---\nmine\n", encoding="utf-8")
        self.assertEqual(wiki.init_personal(self.wiki, "x"), [])
        self.assertEqual((self.wiki / "WIKI.md").read_text(encoding="utf-8"), "---\ntype: team\n---\nmine\n")

    def test_the_command_line_on_its_own_still_marks_and_checks_wiki_md(self):
        os.environ.pop("WIKIAPP_DATA_DIR")                                               # no private folder
        alone = self.base / "alone"
        created = wiki.init_personal(alone, "---\ntype: personal\n---\n")
        self.assertEqual(created, ["WIKI.md", "Sessions/", "promotion-queue.md", "index.md"])
        bare = self.base / "bare"
        bare.mkdir()
        with self.assertRaises(wiki.WikiError):
            wiki.require_personal(bare)                                                   # no WIKI.md: refused

    def test_a_view_only_or_team_wiki_is_refused_in_plain_words(self):
        for root, words in ((self.northwind, "Northwind is view only"), (self.team, "team is your team wiki")):
            cfg = config.Config({"personal_wiki": str(root), "transcripts_dir": str(self.projects)}, None)
            with mock.patch.object(llm, "call_json") as call, self.assertRaises(wiki.WikiError) as caught:
                ingest.ingest_session(cfg, SID)
            self.assertIn(words, str(caught.exception))
            self.assertFalse(call.called)                                               # refused before any request
            with self.assertRaises(wiki.WikiError):
                wiki.init_personal(root, "---\ntype: personal\n---\n")
            self.assertFalse((root / "Sessions").exists())
            self.assertFalse((root / "index.md").exists())

    def test_a_folder_outside_the_open_wikis_is_refused_while_a_personal_wiki_is_set(self):
        stray = self.base / "stray"
        wiki.write_text(stray / "WIKI.md", "---\ntype: personal\n---\n")
        with self.assertRaises(wiki.WikiError) as caught:
            wiki.require_personal(stray)
        self.assertIn("mine is", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
