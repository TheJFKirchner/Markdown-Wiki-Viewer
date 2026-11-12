"""What a topic review may and may not do to a page, on agentlib's fake engine (no tokens spent):
it adds tags and keeps the topic's own (removing one only with a reason, shown as a warning), and
it never copies tasks into Current state. Run: python -m unittest discover tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from agentlib import fake
except ImportError:  # agentlib isn't installed in this Python
    fake = None

from secondbrain import config, ingest, prompts, review, wiki  # noqa: E402
from test_pipeline import SID, write_transcript  # noqa: E402

SLUG = "stop-loss-analytics"


def capture(tags=("stop-loss", "client")):
    return {"worth_recording": True, "skip_reason": "", "title": "Stop loss", "summary": "What was said.",
            "decisions": [{"decision": "Report stop loss quarterly", "why": "Matches the contract"}],
            "findings": [], "open_questions": [], "data_findings": [], "new_tags": [],
            "topics": [{"slug": SLUG, "title": "Stop loss analytics", "summary": "Stop loss analytics",
                        "tags": list(tags), "entry": "Set the quarterly reporting rule", "supersedes": False}]}


@unittest.skipIf(fake is None, "agentlib is not installed in this Python")
class ReviewRulesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved_env = {k: os.environ.pop(k, None) for k in ("WIKIAPP_DATA_DIR", "WIKIAPP_POINTER_FILE", "WIKIAPP_SKILLS_DIR")}
        os.environ["WIKIAPP_POINTER_FILE"] = str(self.base / "no-pointer.txt")   # never the user's real folder
        os.environ["WIKIAPP_SKILLS_DIR"] = str(self.base / "skills")
        self.wiki = self.base / "personal"
        write_transcript(self.base / "projects" / "C--work" / f"{SID}.jsonl")
        self.cfg = config.Config({"personal_wiki": str(self.wiki), "transcripts_dir": str(self.base / "projects"),
                                  "engine": "fake"}, None)
        wiki.init_personal(self.wiki, "---\ntype: personal\n---\n")
        fake.reset()
        self.queues = {}

    def tearDown(self):
        fake.reset()
        for key, value in self.saved_env.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        self.tmp.cleanup()

    def model(self, name, reply):
        if name not in self.queues:
            self.queues[name] = []
            fake.script(name, [lambda message, name=name: [fake.output(self.queues[name].pop(0))]])
        self.queues[name].append(reply)

    def review(self, **reply):
        base = {"state_markdown": "Stop loss is reported quarterly.", "summary": "Stop loss; quarterly",
                "conflicts": [], "related": [], "tags": [], "new_tags": []}
        self.model("wiki-reviewer", {**base, **reply})
        return review.review_topic(self.cfg, SLUG)

    def captured(self, **kw):
        self.model("executive-assistant", capture(**kw))
        return ingest.ingest_session(self.cfg, SID)

    def page(self):
        return wiki.read_page(wiki.find_topic(self.wiki, SLUG))

    # ---- tags ----

    def test_review_adds_tags_and_keeps_the_topics_own(self):
        self.captured()
        result = self.review(tags=["renewals"], new_tags=[{"tag": "renewals", "description": "yearly contract renewals"}])
        self.assertEqual(self.page()[0]["tags"], ["stop-loss", "client", "renewals"])
        self.assertEqual(result["tags"], ["stop-loss", "client", "renewals"])
        self.assertFalse(any("removed" in w for w in result["warnings"]))

    def test_a_reply_that_leaves_tags_out_removes_nothing(self):
        self.captured()
        result = self.review(tags=["stop-loss"])          # the old full-set reading: "client" left out
        self.assertEqual(result["tags"], ["stop-loss", "client"])
        result = self.review(tags=[])
        self.assertEqual(result["tags"], ["stop-loss", "client"])

    def test_a_tag_is_removed_only_with_a_reason_and_a_warning(self):
        self.captured()
        result = self.review(tags=["pricing"], remove_tags=[{"tag": "client", "why": "This is a method, not a client"}])
        self.assertEqual(result["tags"], ["stop-loss", "pricing"])
        self.assertTrue(any("client" in w and "This is a method, not a client" in w for w in result["warnings"]))
        result = self.review(remove_tags=[{"tag": "stop-loss", "why": ""}])   # no reason: kept
        self.assertIn("stop-loss", result["tags"])
        self.assertTrue(any("stop-loss" in w and "kept" in w for w in result["warnings"]))

    def test_the_folder_tag_is_never_removed(self):
        self.captured()
        page = wiki.find_topic(self.wiki, SLUG)
        meta, body = wiki.read_page(page)
        meta["folder"] = "stop-loss"
        wiki.write_text(page, wiki.render(meta, body))
        result = self.review(remove_tags=[{"tag": "stop-loss", "why": "Too broad"}])
        self.assertIn("stop-loss", result["tags"])
        self.assertTrue(any("stop-loss" in w and "folder" in w for w in result["warnings"]))

    def test_removing_a_tag_the_topic_lacks_changes_nothing(self):
        self.captured()
        result = self.review(remove_tags=[{"tag": "nowhere", "why": "Wrong"}])
        self.assertEqual(result["tags"], ["stop-loss", "client"])
        self.assertFalse(any("nowhere" in w for w in result["warnings"]))

    def test_remove_tags_is_optional_in_the_reply_format(self):
        self.assertIn("remove_tags", prompts.REVIEW_SCHEMA["properties"])
        self.assertNotIn("remove_tags", prompts.REVIEW_SCHEMA["required"])

    # ---- tasks ----

    def test_tasks_are_not_copied_into_current_state(self):
        self.captured()
        page = wiki.find_topic(self.wiki, SLUG)       # the analyst's own to-do, typed in the page's Notes
        page.write_text(page.read_text(encoding="utf-8").replace("## Notes\n", "## Notes\n- [ ] Rerun the trend report\n"),
                        encoding="utf-8")
        state = ("Stop loss is reported quarterly.\n\n**Open**\n- [ ] Rerun the trend report\n"
                 "- [/] Draft the renewal memo\n    - 2026-11-03: Waiting on finance\n1. [x] Old done task\n"
                 "- Whether the attachment point changes in 2027")
        result = self.review(state_markdown=state)
        body = self.page()[1]
        current = wiki.get_zone(body, "state")
        self.assertNotIn("Rerun the trend report", current)
        self.assertNotIn("Draft the renewal memo", current)
        self.assertNotIn("Waiting on finance", current)           # a note under a dropped task goes with it
        self.assertNotIn("Old done task", current)
        self.assertIn("**Open**\n- Whether the attachment point changes in 2027", current)
        self.assertTrue(any("task" in w.lower() for w in result["warnings"]))
        self.assertIn("- [ ] Rerun the trend report", wiki.get_zone(body, "notes"))   # where it was written, untouched

    def test_an_open_list_left_empty_by_removed_tasks_goes_too(self):
        self.captured()
        result = self.review(state_markdown="Stop loss is reported quarterly.\n\n**Open**\n- [ ] Rerun the trend report\n")
        current = wiki.get_zone(self.page()[1], "state")
        self.assertNotIn("**Open**", current)
        self.assertIn("Stop loss is reported quarterly.", current)
        self.assertTrue(result["warnings"])

    def test_the_reviewer_is_told_not_to_copy_tasks(self):
        self.captured()
        self.review()
        self.assertIn("remove_tags", prompts.REVIEW_REPLY)
        self.assertIn("no to-dos and no checkbox lines", prompts.REVIEW_REPLY)
        self.assertIn("**To-dos.**", review_prompt := self.review_prompt())
        self.assertNotIn("## Tasks in this wiki", review_prompt)

    def test_the_task_guide_is_gone_and_an_old_entry_for_it_is_harmless(self):
        import agentfiles
        pathlist = config.pathlist
        self.assertNotIn("prompt.tasks", pathlist.slot_names())
        self.assertFalse((Path(pathlist.APP_FILES) / "agents" / "TASKS.md").exists())
        for agent in agentfiles.IDS:
            self.assertNotIn("## Tasks in this wiki", agentfiles.system(agent))
        # A private folder from before: an edited TASKS.md and its path-list entry stay, unused.
        folder = self.base / ".wiki"
        (folder / "prompts").mkdir(parents=True)
        (folder / "prompts" / "TASKS.md").write_text("MY OLD GUIDE\n", encoding="utf-8")
        (folder / "paths.json").write_text('{"version": 1, "overrides": {"prompt.tasks": "%s"}, "slots": {"prompt.tasks": {"base": "x", "seeded": true}}}'
                                           % str(folder / "prompts" / "TASKS.md").replace("\\", "\\\\"), encoding="utf-8")
        os.environ["WIKIAPP_DATA_DIR"] = str(folder)
        pathlist.sync_slots(folder)
        names = [e["name"] for e in pathlist.list_paths()]
        self.assertNotIn("prompt.tasks", names)
        self.assertEqual((folder / "prompts" / "TASKS.md").read_text(encoding="utf-8"), "MY OLD GUIDE\n")
        self.assertNotIn("MY OLD GUIDE", agentfiles.system("wiki-reviewer"))

    def review_prompt(self):
        seen = []
        self.queues.setdefault("wiki-reviewer", [])
        fake.script("wiki-reviewer", [lambda message: (seen.append(message), [fake.output(
            {"state_markdown": "Quarterly.", "summary": "Stop loss", "conflicts": [], "related": [], "tags": [], "new_tags": []})])[1]])
        review.review_topic(self.cfg, SLUG)
        return seen[-1]


if __name__ == "__main__":
    unittest.main()
