"""End-to-end tests with the model call stubbed out. Run: python -m unittest discover tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from secondbrain import config, ingest, llm, review, transcripts, wiki  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"


def _line(**kw):
    return json.dumps(kw)


def write_transcript(path: Path, extra_user: str = "", entrypoint: str = "cli"):
    base = {"sessionId": SID, "cwd": "C:\\work\\claims", "isSidechain": False, "entrypoint": entrypoint}
    lines = [
        _line(type="user", timestamp="2026-11-03T15:00:00Z", message={"role": "user", "content": "<system-reminder>ignore me</system-reminder>Why do the claim counts differ?"}, **base),
        _line(type="assistant", timestamp="2026-11-03T15:00:05Z", message={"role": "assistant", "content": [
            {"type": "thinking", "thinking": "SECRET-THOUGHT"},
            {"type": "text", "text": "I'll compare the two sources."},
            {"type": "tool_use", "name": "Bash", "input": {"command": "python compare.py --year 2022 --member 123456789"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "sqlcmd -Q \"select * from claims where member_name = 'JANE DOE' and id = 4455667788\""}},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "C:/work/claims/run_20261103.sql"}},
        ]}, **base),
        _line(type="user", timestamp="2026-11-03T15:00:09Z", message={"role": "user", "content": [
            {"type": "tool_result", "content": "MEMBER-ROW-OUTPUT 12345"}]}, **base),
        _line(type="assistant", timestamp="2026-11-03T15:00:12Z", message={"role": "assistant", "content": [
            {"type": "text", "text": "CCW excludes denied claims."}]}, **base),
        _line(type="user", timestamp="2026-11-03T15:01:00Z", message={"role": "user", "content": "OK, use CLAIMSDB then." + extra_user}, **base),
        _line(type="custom-title", customTitle="Claim count mismatch", sessionId=SID),
        "not json",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def extraction(**over):
    data = {
        "worth_recording": True, "title": "Claim count mismatch: CCW vs CLAIMSDB", "summary": "Compared sources.",
        "decisions": [{"decision": "Use CLAIMSDB claims for denial analysis", "why": "CCW excludes denied claims"}],
        "findings": ["CCW excludes denied claims"], "open_questions": [],
        "data_findings": [{"subject": "CCW claims", "finding": "Excludes denied claims"}],
        "topics": [{"slug": "Denial Analysis", "title": "Denial analysis", "kind": "analysis", "tags": ["Denials", "claims"],
                    "summary": "Denial rates by plan", "entry": "Chose CLAIMSDB as the source", "supersedes": False}],
    }
    data.update(over)
    return data


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        os.environ["WIKIAPP_SKILLS_DIR"] = str(base / "skills")  # never the real ~/.claude/skills
        # Never the user's real private folder: no pointer file, so no .wiki folder (progress stays in <wiki>/.sb).
        self.saved_env = {k: os.environ.pop(k, None) for k in ("WIKIAPP_DATA_DIR", "WIKIAPP_POINTER_FILE")}
        os.environ["WIKIAPP_POINTER_FILE"] = str(base / "no-pointer.txt")
        self.wiki = base / "personal"
        self.transcript = base / "projects" / "C--work-claims" / f"{SID}.jsonl"
        write_transcript(self.transcript)
        # min_turns 0: these two-message sessions are listed (the filter has tests of its own)
        self.cfg = config.Config({"personal_wiki": str(self.wiki), "transcripts_dir": str(base / "projects"), "min_turns": 0}, None)
        wiki.init_personal(self.wiki, "---\ntype: personal\n---\n")

    def tearDown(self):
        os.environ.pop("WIKIAPP_SKILLS_DIR", None)
        for key, value in self.saved_env.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        self.tmp.cleanup()

    def listed(self, **kw):
        return ingest.list_sessions(self.cfg, **kw)["sessions"]

    def ingest(self, data, sid=SID, **kw):
        with mock.patch.object(llm, "call_json", return_value=data) as m:
            result = ingest.ingest_session(self.cfg, sid, **kw)
        self.prompt = m.call_args[0][1] if m.called else ""
        return result

    def more_sessions(self, slugs, tags=("denials",)):
        """One more ingested session per slug, each under its own topic."""
        for i, slug in enumerate(slugs):
            sid = f"0000000{i}-2222-3333-4444-555555555555"
            write_transcript(self.transcript.with_name(f"{sid}.jsonl"))
            data = extraction(data_findings=[])
            data["topics"][0].update(slug=slug, title=slug, tags=list(tags), entry=f"Worked on {slug}")
            self.ingest(data, sid=sid)

    def topic(self, slug="denial-analysis"):
        return wiki.find_topic(self.wiki, slug)

    # ---- what the model is shown ----

    def test_condense_drops_tool_output_and_masks_values(self):
        text = transcripts.condense(self.transcript, 100000)
        self.assertIn("Why do the claim counts differ?", text)
        self.assertIn("> Bash: python compare.py --year 2022 --member #", text)
        self.assertIn("> Bash: sqlcmd -Q '?'", text)                     # a query's quoted values are masked
        self.assertIn("> Read C:/work/claims/run_20261103.sql", text)   # which file, unmasked
        for banned in ("MEMBER-ROW-OUTPUT", "SECRET-THOUGHT", "ignore me", "123456789", "JANE DOE", "4455667788"):
            self.assertNotIn(banned, text)

    def test_condense_respects_budget(self):
        big = self.transcript.with_name("big.jsonl")
        write_transcript(big, extra_user="x" * 50000)
        self.assertLessEqual(len(transcripts.condense(big, 3000)), 3000)

    def test_sdk_and_internal_sessions_are_never_listed(self):
        write_transcript(self.transcript.with_name("22222222-0000-0000-0000-000000000000.jsonl"), entrypoint="sdk-py")
        p = self.transcript.with_name("99999999-0000-0000-0000-000000000000.jsonl")
        p.write_text(_line(type="user", message={"role": "user", "content": transcripts.SENTINEL + "\nprompt"}) + "\n", encoding="utf-8")
        self.assertEqual([r["session_id"] for r in self.listed()], [SID])

    # ---- capture ----

    def test_ingest_writes_note_topic_index_queue(self):
        result = self.ingest(extraction())
        self.assertEqual(result["status"], "ingested")
        self.assertTrue(result["note"].startswith("Sessions/2026-11-03-"))       # one flat folder
        note = self.wiki / result["note"]
        meta, body = wiki.read_page(note)
        self.assertEqual((meta["topics"], meta["tags"]), (["denial-analysis"], ["denials", "claims"]))
        self.assertIn("Topics: [[denial-analysis]]", body)
        self.assertNotIn("MEMBER-ROW-OUTPUT", self.prompt)
        self.assertIn("# Executive assistant", self.prompt)   # the agent's own prompt file comes first
        self.assertIn("## Existing topics", self.prompt)
        page = self.topic()
        self.assertEqual(page, self.wiki / "denial-analysis.md")                 # at the top of the wiki
        self.assertEqual(wiki.read_page(page)[0]["tags"], ["denials", "claims"])
        self.assertIn(f"Chose CLAIMSDB as the source ([[{note.stem}]])", page.read_text(encoding="utf-8"))
        self.assertIn("[[denial-analysis]] — Denial rates by plan · #denials #claims", (self.wiki / "index.md").read_text(encoding="utf-8"))   # tags are the kind
        self.assertIn("- [ ] 2026-11-03 · **CCW claims**", (self.wiki / "promotion-queue.md").read_text(encoding="utf-8"))
        self.assertEqual(self.listed(), [])
        self.assertEqual(self.listed(include_done=True)[0]["status"], "ingested")
        # The next capture is shown the topic and the tags, so it can reuse them.
        self.more_sessions(["another"])
        self.assertIn("- [[denial-analysis]]", self.prompt)
        self.assertIn("- denials (1 topic)", self.prompt)

    def test_pages_carry_no_marker_comments_and_old_ones_are_converted(self):
        first = self.ingest(extraction())
        for path in wiki.wiki_files(self.wiki):
            self.assertNotIn("<!--", path.read_text(encoding="utf-8"), path.name)
        page = self.topic()
        self.assertIn("## Current state\n_Not yet summarised", page.read_text(encoding="utf-8"))
        # A page written by the earlier version, markers and all, with a note of the person's own.
        stem = Path(first["note"]).stem
        page.write_text(page.read_text(encoding="utf-8").split("## Current state")[0] + (
            "## Current state\n<!-- sb:state:start -->\nOLD STATE\n<!-- sb:state:end -->\n\n"
            "## Notes\n<!-- Yours. Automation never edits this section. -->\nMY NOTE\n\n"
            f"## Log\n<!-- sb:log:start -->\n- 2026-11-03 — An old line ([[{stem}]])\n- 2026-01-01 — Hand-typed line\n<!-- sb:log:end -->\n"), encoding="utf-8")
        queue = self.wiki / "promotion-queue.md"
        queue.write_text("# Promotion queue\n\nIntro.\n\n<!-- sb:queue:start -->\n- [x] 2026-01-01 · **Old** — kept ([[x]])\n<!-- sb:queue:end -->\n", encoding="utf-8")
        self.ingest(extraction(title="Again"))
        text = page.read_text(encoding="utf-8")
        self.assertNotIn("<!--", text)
        self.assertIn("## Current state\nOLD STATE\n", text)
        self.assertIn("## Notes\nMY NOTE\n", text)
        self.assertIn(f"## Log\n- 2026-11-03 [session] — Chose CLAIMSDB as the source ([[{stem}]])\n", text)   # rebuilt from the note, marked with its source
        self.assertNotIn("Hand-typed line", text)                                                   # the log is the tool's
        self.assertEqual(wiki.read_page(page)[0]["entries_since_review"], 1)                         # same session, not counted twice
        q = queue.read_text(encoding="utf-8")
        self.assertNotIn("<!--", q)
        self.assertIn("## Findings\n- [x] 2026-01-01 · **Old** — kept ([[x]])\n- [ ] 2026-11-03 · **CCW claims**", q)

    def test_a_page_with_a_renamed_heading_is_left_alone(self):
        self.ingest(extraction())
        page = self.topic()
        before = page.read_text(encoding="utf-8").replace("## Log", "## History")
        page.write_text(before, encoding="utf-8")
        with self.assertRaises(wiki.WikiError) as caught:
            self.ingest(extraction(title="Again"))
        self.assertIn("'## Log'", str(caught.exception))
        self.assertEqual(page.read_text(encoding="utf-8"), before)

    def test_a_topic_cannot_take_an_existing_pages_name(self):
        (self.wiki / "Gear").mkdir()
        (self.wiki / "Gear" / "Denial-Analysis.md").write_text("# mine\n", encoding="utf-8")
        with self.assertRaises(wiki.WikiError):
            self.ingest(extraction())

    def test_prompt_comes_from_the_skill_file_when_there_is_one(self):
        skill = Path(os.environ["WIKIAPP_SKILLS_DIR"]) / "executive-assistant" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: executive-assistant\ndescription: x\n---\nMY EDITED PROMPT\n", encoding="utf-8")
        self.ingest(extraction())
        self.assertTrue(self.prompt.startswith("MY EDITED PROMPT"))
        self.assertNotIn("description: x", self.prompt)
        self.assertNotIn("## Tasks in this wiki", self.prompt)   # no task guide: the agents never touch tasks
        self.assertNotIn("## Open tasks", self.prompt)

    def test_reingest_is_idempotent_and_preserves_notes(self):
        first = self.ingest(extraction())
        page = self.topic()
        page.write_text(page.read_text(encoding="utf-8").replace("## Notes\n", "## Notes\nMY OWN NOTE\n"), encoding="utf-8")
        queue = self.wiki / "promotion-queue.md"
        queue.write_text(queue.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")
        second = self.ingest(extraction(title="A different title"))
        self.assertEqual(first["note"], second["note"])
        text = page.read_text(encoding="utf-8")
        self.assertEqual(text.count("Chose CLAIMSDB as the source"), 1)
        self.assertIn("MY OWN NOTE", text)
        self.assertEqual(wiki.read_page(page)[0]["entries_since_review"], 1)
        self.assertEqual(queue.read_text(encoding="utf-8").count("CCW claims"), 1)
        self.assertEqual(len(wiki.session_notes(self.wiki)), 1)

    def test_reingest_with_changed_topic_moves_log_line(self):
        self.ingest(extraction())
        other = extraction()
        other["topics"][0].update(slug="source-comparison", title="Source comparison")
        self.ingest(other)
        self.assertNotIn("Chose CLAIMSDB", self.topic().read_text(encoding="utf-8"))
        self.assertIn("Chose CLAIMSDB", self.topic("source-comparison").read_text(encoding="utf-8"))
        why = {t["slug"]: t["why"] for t in review.list_topics(self.cfg)}
        self.assertEqual(why["denial-analysis"], "a session was taken off it")   # not "a decision was reversed"

    def test_updated_status_after_session_continues(self):
        self.ingest(extraction())
        t = self.transcript.stat().st_mtime + 60
        os.utime(self.transcript, (t, t))
        self.assertEqual(self.listed()[0]["status"], "updated")

    def test_not_worth_recording_is_skipped(self):
        result = self.ingest(extraction(worth_recording=False, skip_reason="Just a lookup"))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(wiki.session_notes(self.wiki), [])
        self.assertEqual(self.listed(), [])

    def test_dry_run_writes_nothing(self):
        result = self.ingest(extraction(), dry_run=True)
        self.assertEqual(result["status"], "dry-run")
        self.assertIsNone(self.topic())
        self.assertEqual(self.listed()[0]["status"], "new")

    def test_short_session_is_hidden_from_the_list_but_can_still_be_captured(self):
        # The minimum-turns filter replaced the old skip-by-rule: a short session is left out of the
        # list (so "ingest all", which works through the list, skips it), but captured when chosen.
        self.cfg.min_turns = 5
        result = ingest.list_sessions(self.cfg)
        self.assertEqual((result["sessions"], result["hidden_count"], result["min_turns"]), ([], 1, 5))
        self.assertEqual(ingest.list_sessions(self.cfg, min_turns=0)["hidden_count"], 0)
        self.assertEqual(self.ingest(extraction())["status"], "ingested")   # chosen explicitly: no force needed

    def test_refuses_to_write_to_a_team_wiki(self):
        (self.wiki / "WIKI.md").write_text("---\ntype: team\n---\n", encoding="utf-8")
        with self.assertRaises(wiki.WikiError):
            self.ingest(extraction())

    def test_ingest_file(self):
        f = Path(self.tmp.name) / "teams-recap.md"
        f.write_text("Recap: agreed to use CLAIMSDB.", encoding="utf-8")
        with mock.patch.object(llm, "call_json", return_value=extraction()):
            result = ingest.ingest_file(self.cfg, str(f), date="2026-11-05")
        self.assertEqual(result["status"], "ingested")
        self.assertTrue(result["note"].startswith("Sessions/2026-11-05-"))

    # ---- review ----

    def test_capture_never_rewrites_a_summary(self):
        self.ingest(extraction())
        data = extraction()
        data["topics"][0]["supersedes"] = True
        with mock.patch.object(llm, "call_json", return_value=data) as m:
            result = ingest.ingest_session(self.cfg, SID)
        self.assertEqual(m.call_count, 1)                        # the capture call only
        self.assertTrue(result["topics"][0]["review_due"])       # it waits for the Review tab
        self.assertEqual(review.list_topics(self.cfg)[0]["why"], "a decision was reversed")
        self.assertIn("Not yet summarised", wiki.get_zone(wiki.read_page(self.topic())[1], "state"))

    def test_new_topic_is_not_due_on_supersede(self):
        data = extraction()
        data["topics"][0]["supersedes"] = True
        self.assertFalse(self.ingest(data)["topics"][0]["review_due"])

    def test_review_rewrites_the_state_zone_only(self):
        self.ingest(extraction())
        self.assertFalse(review.is_due(self.cfg, "denial-analysis"))
        self.assertFalse(review.list_topics(self.cfg)[0]["reviewed"])           # so it can't be promoted yet
        self.cfg.review_after_entries = 1
        self.assertEqual([t["slug"] for t in review.list_topics(self.cfg) if t["due"]], ["denial-analysis"])
        reply = {"state_markdown": "## Current state\n**Decisions in force**\n- Use CLAIMSDB", "summary": "Denials; CLAIMSDB chosen"}
        with mock.patch.object(llm, "call_json", return_value=reply) as m:
            review.review_topic(self.cfg, "denial-analysis")
        self.assertIn("# Wiki reviewer", m.call_args[0][1])
        meta, body = wiki.read_page(self.topic())
        state = wiki.get_zone(body, "state")
        self.assertIn("- Use CLAIMSDB", state)
        self.assertNotIn("## Current state", state)
        self.assertIn("Chose CLAIMSDB as the source", wiki.get_zone(body, "log"))
        self.assertEqual((meta["entries_since_review"], meta["needs_review"], meta["summary"]), (0, False, "Denials; CLAIMSDB chosen"))
        self.assertTrue(review.list_topics(self.cfg)[0]["reviewed"])
        self.assertTrue(meta["changed"] > "2026")                                # promotion sees it changed

    # ---- folders and merges ----

    def test_a_shared_tag_becomes_a_folder(self):
        self.ingest(extraction())
        self.assertEqual(wiki.suggest_folders(self.wiki), [])                    # one topic isn't a folder
        self.more_sessions(["denial-rates-by-plan", "denial-appeals"])
        suggestions = wiki.suggest_folders(self.wiki)
        self.assertEqual([(s["tag"], s["new"], len(s["topics"])) for s in suggestions], [("denials", True, 3)])
        self.assertEqual(self.topic().parent, self.wiki)                         # suggesting moves nothing
        s = suggestions[0]
        result = wiki.apply_folder(self.wiki, s["tag"], s["title"], s["topics"], "2026-11-10")
        self.assertEqual(sorted(result["moved"]), sorted(s["topics"]))
        self.assertEqual(self.topic().parent.name, "denials")
        self.assertEqual(wiki.read_page(self.topic())[0]["folder"], "denials")
        hub = (self.wiki / "denials" / "denials.md").read_text(encoding="utf-8")
        self.assertIn("- [[denial-appeals]]", hub)
        index = (self.wiki / "index.md").read_text(encoding="utf-8")
        self.assertIn("## Folder: [[denials]]", index)
        self.assertEqual(index.count("[[denial-analysis]]"), 1)
        # A later session still finds the moved page, and a new topic with the tag is offered to the folder.
        self.ingest(extraction(title="Again"))
        self.assertEqual(len(list(self.wiki.rglob("denial-analysis.md"))), 1)
        self.more_sessions(["denial-letters"])
        self.assertEqual([(s["tag"], s["new"], s["topics"]) for s in wiki.suggest_folders(self.wiki)], [("denials", False, ["denial-letters"])])

    def test_a_tag_cannot_become_a_folder_over_someone_elses(self):
        (self.wiki / "denials").mkdir()
        (self.wiki / "denials" / "mine.md").write_text("# mine\n", encoding="utf-8")
        self.ingest(extraction())
        self.more_sessions(["denial-rates-by-plan", "denial-appeals"])
        self.assertEqual(wiki.suggest_folders(self.wiki), [])
        with self.assertRaises(wiki.WikiError):
            wiki.apply_folder(self.wiki, "denials", "", ["denial-analysis"], "2026-11-10")

    def test_merging_topics_keeps_everything(self):
        self.ingest(extraction())
        self.more_sessions(["denials-study"], tags=("appeals",))
        old = self.topic("denials-study")
        old.write_text(old.read_text(encoding="utf-8").replace("## Notes\n", "## Notes\nNOTE ON THE OLD PAGE\n"), encoding="utf-8")
        other = self.wiki / "My page.md"
        other.write_bytes(b"See [[denials-study]] and [[denials-study|the study]].\r\n")
        reply = {"topic_merges": [{"keep": "denial-analysis", "merge": ["denials-study", "nope"], "reason": "Same work"}],
                 "tag_merges": [{"keep": "denials", "merge": ["appeals"], "reason": "Same theme"}]}
        with mock.patch.object(llm, "call_json", return_value=reply):
            suggestions = review.suggest_merges(self.cfg)
        self.assertEqual([(s["kind"], s["keep"], s["merge"]) for s in suggestions],
                         [("topic", "denial-analysis", ["denials-study"]), ("tag", "denials", ["appeals"])])
        wiki.merge_topics(self.wiki, "denial-analysis", ["denials-study"])
        self.assertIsNone(self.topic("denials-study"))
        meta, body = wiki.read_page(self.topic())
        self.assertIn("Worked on denials-study", wiki.get_zone(body, "log"))
        self.assertIn("NOTE ON THE OLD PAGE", body)
        self.assertEqual(meta["tags"], ["denials", "claims", "appeals"])
        self.assertEqual(review.list_topics(self.cfg)[0]["why"], "topics were merged into it")
        self.assertEqual(other.read_bytes(), b"See [[denial-analysis]] and [[denial-analysis|the study]].\r\n")
        notes = [m["topics"] for _, m, _ in wiki.session_notes(self.wiki)]
        self.assertEqual(notes, [["denial-analysis"], ["denial-analysis"]])
        wiki.merge_tags(self.wiki, "denials", ["appeals"])
        self.assertEqual(wiki.read_page(self.topic())[0]["tags"], ["denials", "claims"])
        self.assertEqual(sorted(wiki.all_tags(self.wiki)), ["claims", "denials"])

    # ---- to-dos: the AI never touches them ----

    def test_capture_writes_no_task_anywhere(self):
        """A reply that slips a to-do into any field (or still sends the old task lists) leaves no
        checkbox line in the record, the topic page, the log or the index."""
        data = extraction(
            summary="Compared sources.\n- [ ] Rerun the denial report",
            decisions=[{"decision": "Use CLAIMSDB claims for denial analysis", "why": "CCW excludes denied claims"},
                       {"decision": "[ ] Email finance", "why": ""}],
            findings=["CCW excludes denied claims", "- [x] Checked the 2021 gap"],
            open_questions=["Is the 2021 gap real?", "[/] Ask finance about the 2021 gap"],
            tasks=[{"text": "Rerun the denial report with CLAIMSDB", "due": "2026-11-20"}],
            task_updates=[{"id": "T1", "status": "done", "note": ""}])
        data["topics"][0]["entry"] = "- [ ] Rerun it"
        mine = self.wiki / "Tasks.md"
        mine.write_bytes(b"# Tasks\r\n\r\n- [ ] Book the room [[denial-analysis]] ~alex\r\n")
        result = self.ingest(data)
        self.assertNotIn("tasks", result)
        self.assertNotIn("tasks_updated", result)
        record = (self.wiki / result["note"]).read_text(encoding="utf-8")
        page = self.topic().read_text(encoding="utf-8")
        for text in (record, page, (self.wiki / "index.md").read_text(encoding="utf-8")):
            self.assertEqual([ln for ln in text.splitlines() if wiki.TASK_LINE.match(ln)], [])
        self.assertNotIn("## Tasks", record)
        self.assertIn("CCW excludes denied claims", record)          # the knowledge beside the to-dos is kept
        self.assertIn("Is the 2021 gap real?", record)
        self.assertIn("Compared sources.", record)
        self.assertEqual(mine.read_bytes(), b"# Tasks\r\n\r\n- [ ] Book the room [[denial-analysis]] ~alex\r\n")   # never updated

    def test_a_recapture_keeps_an_old_records_task_lines_as_they_are(self):
        first = self.ingest(extraction())
        record = self.wiki / first["note"]
        old = "## Tasks\n- [x] Rerun the denial report [[denial-analysis]] done:2026-11-04\n    - 2026-11-04: Took two tries\n"
        record.write_text(record.read_text(encoding="utf-8") + old, encoding="utf-8")
        self.ingest(extraction(title="Again"))
        self.assertIn(old.strip(), record.read_text(encoding="utf-8"))   # an earlier version's lines, untouched

    # ---- files ----

    def test_frontmatter_round_trip(self):
        meta = {"title": "A: tricky \"title\"", "n": 3, "flag": False, "tags": ["a", "b"], "path": "C:\\x\\y", "empty": ""}
        self.assertEqual(wiki.parse(wiki.render(meta, "body\n"))[0], meta)

    def test_index_is_never_written_over_someone_elses(self):
        (self.wiki / "index.md").write_text("# My own index\n", encoding="utf-8")
        with self.assertRaises(wiki.WikiError):
            self.ingest(extraction())
        self.assertEqual((self.wiki / "index.md").read_text(encoding="utf-8"), "# My own index\n")

    def test_team_index(self):
        team = Path(self.tmp.name) / "team"
        wiki.write_text(team / "data" / "subject-areas" / "claims.md", "---\ntitle: Claims\ntype: subject-area\nsummary: Which claims source to use\n---\n")
        wiki.write_text(team / "sources" / "raw.md", "raw")
        wiki.write_text(team / "wiki_rules.md", "rules")
        self.assertEqual(wiki.write_team_index(team), 1)
        self.assertIn("[[claims]] — Which claims source to use", (team / "index.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
