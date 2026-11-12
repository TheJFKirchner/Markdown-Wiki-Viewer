"""Tests for the private .wiki folder and the path list (host/pathlist.py, host/appfolder.py).
No model is called. Every test works in a temporary folder: the pointer file, the old data
folders and the shipped defaults are all redirected there.

Run from App Files:  .venv/Scripts/python.exe -m unittest discover -s host/tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP_FILES = Path(__file__).resolve().parents[2]
for folder in ("host", "agents", "ingest"):
    if str(APP_FILES / folder) not in sys.path:
        sys.path.insert(0, str(APP_FILES / folder))

import agentfiles  # noqa: E402
import appfolder  # noqa: E402
import pathlist  # noqa: E402
from ingestruns import IngestRuns  # noqa: E402


def snapshot(folder: Path) -> dict:
    """Every file under folder -> its bytes (and every folder -> None)."""
    out = {}
    if folder.exists():
        for p in sorted(folder.rglob("*")):
            out[p.relative_to(folder).as_posix()] = p.read_bytes() if p.is_file() else None
    return out


class FolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"WIKIAPP_POINTER_FILE": str(self.base / "pointer.txt")})
        self.env.start()
        for name in ("WIKIAPP_DATA_DIR", "WIKIAPP_SKILLS_DIR", "SECOND_BRAIN_CONFIG"):
            os.environ.pop(name, None)
        # Older versions' places, all inside the temporary folder.
        self.old = {"data": self.base / "old-home" / ".wikiapp", "skills": self.base / "old-home" / ".claude" / "skills",
                    "retired": None, "retired_runs": None}
        self.old_patch = mock.patch.object(appfolder, "old_locations", lambda: dict(self.old))
        self.old_patch.start()
        self.place = self.base / "place"
        self.place.mkdir()
        self.folder = self.place / ".wiki"

    def tearDown(self):
        self.old_patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def choose(self):
        return appfolder.choose_location(str(self.place))

    def make_wiki(self, name="team", templates=False):
        root = self.base / "wikis" / name
        (root / "Notes").mkdir(parents=True)
        (root / "Page.md").write_text("---\ndescription: A page\n---\n# Page\n", encoding="utf-8")
        if templates:
            (root / "Templates" / "Pages").mkdir(parents=True)
            (root / "Templates" / "Pages" / "Own.md").write_text("---\ndescription: own\n---\n# x\n", encoding="utf-8")
        return root

    def write_settings(self, folder, wikis):
        workspace = json.dumps([{"alias": a, "root": str(r)} for a, r in wikis])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "settings.json").write_text(json.dumps({"workspace": workspace, "__rev": "3"}), encoding="utf-8")


class FreshStartTest(FolderTest):
    def test_fresh_start_with_no_pointer_file_creates_nothing(self):
        home = Path.home()
        project_wiki = APP_FILES.parent / ".wiki"
        before_home = ((home / ".wiki").exists(), (home / pathlist.POINTER_NAME).exists(), project_wiki.exists())
        wiki = self.make_wiki()
        before = snapshot(self.base)

        state = appfolder.first_run_state()
        self.assertFalse(state["chosen"])
        self.assertEqual(state["suggested"], str(project_wiki))          # the app's own project folder
        self.assertTrue(state["valid"])
        self.assertTrue(state["preview"]["items"])                       # it says what it would do...
        self.assertTrue(all(i["action"] in ("create", "copy", "found") for i in state["preview"]["items"]))
        entries = {e["name"]: e for e in pathlist.list_paths()}
        self.assertEqual((entries["settings"]["path"], entries["settings"]["state"]), ("", "unset"))
        self.assertFalse(entries["prompt.team-wiki-manager"]["exists"])
        appfolder.startup()
        pathlist.sync_slots()
        for name in pathlist.slot_names():
            self.assertTrue(pathlist.read_prompt(name) is not None)   # the shipped defaults still read
        self.assertIn("# Executive assistant", agentfiles.system("executive-assistant"))
        self.assertEqual(appfolder.open_path("settings")["ok"], False)
        import wikis
        texts = wikis.Wikis([{"alias": "team", "root": str(wiki)}]).write_indexes("2026-11-12")
        self.assertIn("team:Page.md", texts["team"])
        with self.assertRaises(pathlist.PathMissing):
            IngestRuns(lambda *a: None).save_state("{}")
        with self.assertRaises(pathlist.PathMissing):
            pathlist.set_path("transcripts", str(self.base))
        with self.assertRaises(pathlist.PathMissing):
            pathlist.reset_prompt("prompt.wikis-section")

        self.assertEqual(snapshot(self.base), before)                    # ...but writes nothing
        self.assertFalse((wiki / ".wiki").exists())
        self.assertEqual(((home / ".wiki").exists(), (home / pathlist.POINTER_NAME).exists(), project_wiki.exists()),
                         before_home)

    def test_the_project_folder_s_wiki_folder_is_git_ignored(self):
        ignored = (APP_FILES.parent / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".wiki/", [line.strip() for line in ignored])


class ChooseTest(FolderTest):
    def test_choosing_a_folder_that_has_files_overwrites_none_of_them(self):
        (self.folder / "prompts").mkdir(parents=True)
        (self.folder / "templates" / "Notes").mkdir(parents=True)
        mine = {
            "prompts/team-wiki-manager.md": "---\nname: x\n---\nMY OWN MANAGER\n",
            "settings.json": '{"mine": "yes"}',
            "templates/Notes/Daily.md": "MY DAILY\n",
            "prompts/personal-capture-rules.md": "My rule\n",
            "something-else.txt": "keep me",
        }
        for rel, text in mine.items():
            (self.folder / rel).write_text(text, encoding="utf-8")
        self.old["data"].mkdir(parents=True)
        (self.old["data"] / "settings.json").write_text('{"old": "yes"}', encoding="utf-8")
        before = snapshot(self.folder)

        state = self.choose()
        self.assertTrue(state["chosen"])
        self.assertEqual(pathlist.app_folder(), self.folder)
        after = snapshot(self.folder)
        for rel, data in before.items():
            self.assertEqual(after[rel], data, rel)
        self.assertTrue((self.folder / "prompts" / "wikis-section.md").is_file())       # missing ones were added
        entries = {e["name"]: e for e in pathlist.list_paths()}
        self.assertEqual(entries["prompt.team-wiki-manager"]["status"], "customised")
        self.assertEqual(entries["template.daily"]["status"], "customised")
        self.assertEqual(entries["prompt.wikis-section"]["status"], "default")

    def test_a_parent_folder_or_the_wiki_folder_itself_can_be_picked(self):
        self.assertEqual(pathlist.folder_for(str(self.place)), self.folder)
        self.assertEqual(pathlist.folder_for(str(self.folder)), self.folder)

    def test_first_run_checks_the_typed_place(self):
        for typed, words in (("", "Give a folder"), ("   ", "Give a folder"), ("relative\\place", "full path"),
                             (str(self.base / "no" / "such"), "doesn't exist")):
            state = appfolder.first_run_state(typed)
            self.assertFalse(state["valid"], typed)
            self.assertIn(words, state["error"], typed)
        state = appfolder.first_run_state(str(self.place))
        self.assertTrue(state["valid"])
        self.assertEqual(state["error"], "")
        self.assertEqual(state["preview"]["folder"], str(self.folder))
        with self.assertRaises(ValueError):
            appfolder.choose_location("relative\\place")
        self.assertFalse(pathlist.pointer_file().exists())

    def test_first_run_knows_the_wikis_and_spots_an_old_index_folder(self):
        wiki = self.make_wiki("team")
        (wiki / ".wiki").mkdir()
        (wiki / ".wiki" / "index.md").write_text("old index", encoding="utf-8")
        self.write_settings(self.old["data"], [("team", wiki)])       # an older version's settings
        state = appfolder.first_run_state(str(wiki))
        self.assertEqual(state["wiki_roots"], [str(wiki)])
        self.assertTrue(state["preview"]["old_wiki_index"])
        self.assertEqual(state["preview"]["inside_wiki"], str(wiki))
        clean = appfolder.first_run_state(str(self.place))["preview"]
        self.assertEqual((clean["old_wiki_index"], clean["inside_wiki"]), (False, ""))


class SlotTest(FolderTest):
    def setUp(self):
        super().setUp()
        # A copy of the shipped defaults, so a test can play "the app shipped a newer default".
        self.shipped = self.base / "app" / "App Files"
        for rel in ("agents", "app/templates", "sessions/templates"):
            shutil.copytree(APP_FILES / rel, self.shipped / rel, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
        self.app_patch = mock.patch.object(pathlist, "APP_FILES", self.shipped)
        self.app_patch.start()
        self.choose()

    def tearDown(self):
        self.app_patch.stop()
        super().tearDown()

    def status(self, name):
        return {e["name"]: e for e in pathlist.list_paths()}[name]

    def test_reset_restores_the_shipped_default(self):
        file = self.folder / "prompts" / "wiki-reviewer.md"
        file.write_text("EDITED\n", encoding="utf-8")
        self.assertEqual(self.status("prompt.wiki-reviewer")["status"], "customised")
        self.assertTrue(self.status("prompt.wiki-reviewer")["can_reset"])
        entry = pathlist.reset_prompt("prompt.wiki-reviewer")
        self.assertEqual(entry["status"], "default")
        self.assertFalse(entry["can_reset"])
        self.assertEqual(file.read_text(encoding="utf-8"), pathlist.shipped_text("prompt.wiki-reviewer"))

    def test_an_unedited_copy_follows_a_newer_default_and_an_edited_one_does_not(self):
        edited = self.folder / "prompts" / "wikis-section.md"
        edited.write_text("MY WIKIS SECTION\n", encoding="utf-8")
        for rel in ("agents/team-wiki-manager/SKILL.md", "agents/messages/wikis-section.md"):
            shipped = self.shipped / rel
            shipped.write_text(shipped.read_text(encoding="utf-8") + "\nA NEWER DEFAULT LINE\n", encoding="utf-8")

        report = pathlist.sync_slots()           # what each start does
        self.assertIn("prompt.team-wiki-manager", report["updated"])
        self.assertNotIn("prompt.wikis-section", report["updated"])
        self.assertIn("A NEWER DEFAULT LINE", (self.folder / "prompts" / "team-wiki-manager.md").read_text(encoding="utf-8"))
        self.assertEqual(edited.read_text(encoding="utf-8"), "MY WIKIS SECTION\n")
        self.assertEqual(self.status("prompt.team-wiki-manager")["status"], "default")
        self.assertEqual(self.status("prompt.wikis-section")["status"], "customised_newer_default")
        pathlist.reset_prompt("prompt.wikis-section")
        self.assertIn("A NEWER DEFAULT LINE", edited.read_text(encoding="utf-8"))

    def test_a_slot_can_point_at_an_existing_file_such_as_a_skill(self):
        skill = self.base / "skills" / "team-wiki-manager" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: team-wiki-manager\n---\nMY SKILL\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            pathlist.set_path("prompt.team-wiki-manager", str(self.base / "nope.md"))
        entry = pathlist.set_path("prompt.team-wiki-manager", str(skill))
        self.assertEqual((entry["path"], entry["status"]), (str(skill), "customised"))
        self.assertTrue(agentfiles.system("team-wiki-manager").startswith("MY SKILL"))
        with self.assertRaises(ValueError):                               # a skill keeps its frontmatter
            agentfiles.save("team-wiki-manager", "no frontmatter")
        agentfiles.save("team-wiki-manager", "---\nname: team-wiki-manager\n---\nSAVED\n")
        self.assertIn("SAVED", skill.read_text(encoding="utf-8"))
        pathlist.set_path("prompt.team-wiki-manager", "")                      # back to the default place
        self.assertEqual(pathlist.path("prompt.team-wiki-manager"), self.folder / "prompts" / "team-wiki-manager.md")

    def test_personal_capture_rules_are_never_overwritten(self):
        name = "personal_capture_rules"
        file = pathlist.path(name)
        self.assertEqual(file, self.folder / "prompts" / "personal-capture-rules.md")
        self.assertEqual(pathlist.read_prompt(name), "")               # the starter is only comments
        entry = self.status(name)
        self.assertEqual((entry["status"], entry["can_reset"], entry["group"]), (None, False, "Prompts"))
        with self.assertRaises(ValueError):
            pathlist.reset_prompt(name)
        file.write_text("<!-- note -->\n- Give every client its own page.\n", encoding="utf-8")
        starter = self.shipped / "agents" / "messages" / "personal-capture-rules.md"
        starter.write_text("A NEWER STARTER\n", encoding="utf-8")       # an app update
        pathlist.sync_slots()
        appfolder.startup()
        self.assertEqual(file.read_text(encoding="utf-8"), "<!-- note -->\n- Give every client its own page.\n")
        self.assertEqual(pathlist.read_prompt(name), "- Give every client its own page.")
        self.assertIsNone(self.status(name)["status"])

    def test_personal_capture_rules_already_there_before_setup_are_kept(self):
        other = self.base / "place2"
        (other / ".wiki" / "prompts").mkdir(parents=True)
        rules = other / ".wiki" / "prompts" / "personal-capture-rules.md"
        rules.write_text("ALREADY MINE\n", encoding="utf-8")
        appfolder.relocate(str(other), "adopt")
        self.assertEqual(rules.read_text(encoding="utf-8"), "ALREADY MINE\n")
        self.assertEqual(pathlist.read_prompt("personal_capture_rules"), "ALREADY MINE")

    def test_a_missing_configured_path_is_reported_not_recreated(self):
        transcripts = self.base / "transcripts"
        transcripts.mkdir()
        mine = self.base / "my-tasks.md"
        mine.write_text("MINE\n", encoding="utf-8")
        pathlist.set_path("transcripts", str(transcripts))
        pathlist.set_path("prompt.wikis-section", str(mine))
        transcripts.rmdir()
        mine.unlink()
        (self.folder / "templates" / "Notes" / "Daily.md").unlink()   # deleted at its usual place
        pathlist.sync_slots()
        appfolder.startup()
        entries = {e["name"]: e for e in pathlist.list_paths()}
        for name in ("transcripts", "prompt.wikis-section", "template.daily"):
            self.assertFalse(entries[name]["exists"], name)
        self.assertFalse(transcripts.exists())
        self.assertFalse(mine.exists())
        self.assertFalse((self.folder / "templates" / "Notes" / "Daily.md").exists())
        with self.assertRaises(pathlist.PathMissing) as caught:
            pathlist.read_prompt("prompt.wikis-section")
        self.assertIn(str(mine), str(caught.exception))
        # A whole private folder that has gone is reported too, and not made again.
        shutil.rmtree(self.folder)
        self.assertEqual(appfolder.startup(), {"chosen": True, "missing": True})
        self.assertFalse(appfolder.first_run_state()["location_exists"])
        with self.assertRaises(pathlist.PathMissing):
            IngestRuns(lambda *a: None).save_state("{}")
        self.assertFalse(self.folder.exists())


class MigrationTest(FolderTest):
    def test_migration_copies_and_deletes_nothing(self):
        wiki = self.make_wiki("team")
        (wiki / ".wiki").mkdir()
        (wiki / ".wiki" / "index.md").write_text("old index", encoding="utf-8")
        data = self.old["data"]
        self.write_settings(data, [("team", wiki)])
        (data / "window.txt").write_text("1,2,800,600,0", encoding="utf-8")
        (data / "ingest").mkdir()
        (data / "ingest" / "pending-promotion.json").write_text('{"cards": []}', encoding="utf-8")
        (data / "ingest-runs" / "2026-11-01_100000").mkdir(parents=True)
        (data / "ingest-runs" / "2026-11-01_100000" / "job.json").write_text("{}", encoding="utf-8")
        skills = self.old["skills"]
        (skills / "team-wiki-manager").mkdir(parents=True)
        (skills / "team-wiki-manager" / "SKILL.md").write_text("---\nname: team-wiki-manager\n---\nMY EDITED MANAGER\n", encoding="utf-8")
        (skills / "wiki-reviewer").mkdir(parents=True)
        (skills / "wiki-reviewer" / "SKILL.md").write_text(pathlist.shipped_text("prompt.wiki-reviewer"), encoding="utf-8")
        before = snapshot(self.base / "old-home"), snapshot(wiki)

        preview = appfolder.first_run_state(str(self.place))["preview"]
        actions = {i["name"]: i["action"] for i in preview["items"]}
        self.assertEqual((actions["settings"], actions["prompt.team-wiki-manager"], actions["prompt.wikis-section"]),
                         ("copy", "copy", "create"))
        self.choose()

        self.assertEqual((snapshot(self.base / "old-home"), snapshot(wiki)), before)    # nothing deleted or changed
        self.assertEqual((self.folder / "window.txt").read_text(encoding="utf-8"), "1,2,800,600,0")
        self.assertTrue((self.folder / "ingest" / "pending-promotion.json").is_file())
        self.assertTrue((self.folder / "ingest-runs" / "2026-11-01_100000" / "job.json").is_file())
        self.assertEqual(pathlist.read_workspace()[0]["alias"], "team")
        entries = {e["name"]: e for e in pathlist.list_paths()}
        self.assertEqual(entries["prompt.team-wiki-manager"]["status"], "customised")  # the edits count as the person's
        self.assertIn("MY EDITED MANAGER", pathlist.read_prompt("prompt.team-wiki-manager"))
        self.assertEqual(entries["prompt.wiki-reviewer"]["status"], "default")
        self.assertEqual(entries["wiki.team.rules"]["path"], str(wiki / "wiki_rules.md"))
        kinds = sorted(item["kind"] for item in appfolder.read_leftovers())
        self.assertEqual(kinds, ["old_app_folder", "old_index", "old_skill", "old_skill"])
        appfolder.dismiss_leftovers()
        self.assertEqual(appfolder.first_run_state()["leftovers"], [])

    def test_the_retired_note_takers_files_are_not_carried_forward(self):
        retired = {"prompt.note-taker", "prompt.ingest-first-message", "pending_notes"}
        data = self.old["data"]
        (data / "ingest").mkdir(parents=True)
        (data / "settings.json").write_text("{}", encoding="utf-8")
        (data / "ingest" / "pending.json").write_text('{"cards": [1]}', encoding="utf-8")
        (data / "ingest" / "user-notes.md").write_text("ALWAYS LINK PEOPLE", encoding="utf-8")
        (self.old["skills"] / "note-taker").mkdir(parents=True)
        (self.old["skills"] / "note-taker" / "SKILL.md").write_text("---\nname: note-taker\n---\nOLD\n", encoding="utf-8")
        names = {i["name"] for i in appfolder.first_run_state(str(self.place))["preview"]["items"]}
        self.assertFalse(names & retired)
        self.choose()
        self.assertFalse((self.folder / "ingest" / "pending.json").exists())
        self.assertFalse((self.folder / "prompts" / "note-taker.md").exists())
        self.assertFalse((self.folder / "prompts" / "ingest-first-message.md").exists())
        self.assertFalse({e["name"] for e in pathlist.list_paths()} & retired)
        for name in retired:
            with self.assertRaises(ValueError):
                pathlist.set_path(name, "")
        prompts_text = "".join(p.read_text(encoding="utf-8") for p in (self.folder / "prompts").glob("*.md"))
        self.assertNotIn("ALWAYS LINK PEOPLE", prompts_text)
        self.assertIn(str(self.old["skills"] / "note-taker"), [i["path"] for i in appfolder.read_leftovers()])
        self.assertNotIn("note-taker", [a["id"] for a in agentfiles.info()])


class RelocateTest(FolderTest):
    def test_move_takes_the_contents_and_needs_an_empty_place(self):
        self.choose()
        (self.folder / "prompts" / "wikis-section.md").write_text("EDITED", encoding="utf-8")
        busy = self.base / "busy" / ".wiki"
        busy.mkdir(parents=True)
        (busy / "x.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            appfolder.relocate(str(busy.parent), "move")                 # never merged
        self.assertEqual((busy / "x.txt").read_text(encoding="utf-8"), "x")
        new = self.base / "new"
        new.mkdir()
        appfolder.relocate(str(new), "move")
        self.assertEqual(pathlist.app_folder(), new / ".wiki")
        self.assertEqual((new / ".wiki" / "prompts" / "wikis-section.md").read_text(encoding="utf-8"), "EDITED")
        self.assertFalse(self.folder.exists())

    def test_adopt_uses_what_is_there_and_leaves_the_old_folder(self):
        self.choose()
        other = self.base / "other" / ".wiki"
        other.mkdir(parents=True)
        (other / "settings.json").write_text('{"theirs": "1"}', encoding="utf-8")
        with self.assertRaises(pathlist.PathMissing):
            appfolder.relocate(str(self.base / "nothing-here"), "adopt")
        appfolder.relocate(str(other.parent), "adopt")
        self.assertEqual(pathlist.app_folder(), other)
        self.assertEqual((other / "settings.json").read_text(encoding="utf-8"), '{"theirs": "1"}')
        self.assertTrue((self.folder / "prompts" / "wikis-section.md").is_file())  # the old one is untouched


class EngineAndAgentlibTest(FolderTest):
    def test_engine_settings_round_trip_and_keep_other_engines_fields(self):
        self.choose()
        got = pathlist.get_engine_settings()
        self.assertEqual(got["engine"], "claude")
        self.assertEqual(set(got["engines"]["claude"]["models"]), {"executive-assistant", "wiki-reviewer", "team-wiki-manager"})
        saved = pathlist.set_engine_settings({"engines": {"claude": {"models": {"team-wiki-manager": "claude-sonnet-5-5"}},
                                                          "future": {"api_url": "x"}}})
        self.assertEqual(saved["engines"]["claude"]["models"]["team-wiki-manager"], "claude-sonnet-5-5")
        self.assertEqual(saved["engines"]["claude"]["models"]["wiki-reviewer"], "claude-sonnet-5-5")
        self.assertEqual(saved["engines"]["future"], {"api_url": "x"})
        with self.assertRaises(ValueError):
            pathlist.set_engine_settings({"engine": "nope"})

    def test_one_model_per_agent_is_the_stored_default_the_tabs_read_and_write(self):
        self.choose()
        self.assertEqual(pathlist.agent_model("wiki-reviewer"), "claude-sonnet-5-5")       # the shipped default
        pathlist.set_agent_model("wiki-reviewer", "claude-opus-5")                          # a tab's menu changes it
        self.assertEqual(pathlist.agent_model("wiki-reviewer"), "claude-opus-5")
        self.assertEqual(pathlist.get_engine_settings()["engines"]["claude"]["models"]["wiki-reviewer"], "claude-opus-5")
        saved = json.loads((self.folder / "engine.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["engines"]["claude"]["models"]["wiki-reviewer"], "claude-opus-5")
        pathlist.set_agent_model("wiki-reviewer", "")                                       # back to the default
        self.assertEqual(pathlist.agent_model("wiki-reviewer"), "claude-sonnet-5-5")
        with self.assertRaises(ValueError):
            pathlist.set_agent_model("note-taker", "claude-haiku-5-5")                     # retired
        with self.assertRaises(ValueError):
            pathlist.set_agent_model("wiki-reviewer", "bad id; rm")
        # A model the retired note taker had saved in an older engine.json is dropped.
        (self.folder / "engine.json").write_text(json.dumps({"engine": "claude", "engines": {"claude": {
            "models": {"note-taker": "claude-opus-5", "wiki-reviewer": "claude-opus-5"}}}}), encoding="utf-8")
        models = pathlist.get_engine_settings()["engines"]["claude"]["models"]
        self.assertNotIn("note-taker", models)
        self.assertEqual(models["wiki-reviewer"], "claude-opus-5")

    def test_connection_status_and_test_on_the_fake_engine(self):
        from agentlib import fake
        from agentlib.connection import CHECK_AGENT
        status = appfolder.connection_status("fake")                                     # free: sends nothing
        self.assertEqual(set(status), {"engine", *appfolder.STATUS_FIELDS})
        self.assertIsInstance(status["problems"], list)
        result = appfolder.test_connection("fake")
        self.assertEqual(set(result), {"engine", "ok", "model", "cost_usd", "error", "fix", "report"})
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["report"])
        fake.script(CHECK_AGENT, [[fake.fail("Not logged in - Please run /login")]])
        try:
            failed = appfolder.test_connection("fake")
        finally:
            fake.reset()
        self.assertFalse(failed["ok"])
        self.assertTrue(failed["error"])
        with mock.patch.object(pathlist, "agentlib_installed", lambda: False):
            self.assertFalse(appfolder.test_connection("fake")["ok"])
            self.assertFalse(appfolder.connection_status("fake")["ok"])

    def test_open_path_opens_what_exists_and_says_why_not(self):
        self.choose()
        opened = []
        with mock.patch.object(appfolder, "system_open", opened.append):
            self.assertEqual(appfolder.open_path("prompts"), {"ok": True})
            self.assertEqual(appfolder.open_path("prompt.wikis-section"), {"ok": True})
            self.assertFalse(appfolder.open_path("run_history")["ok"])                    # not made yet
            self.assertFalse(appfolder.open_path("tag_list_reference")["ok"])             # unset
            self.assertFalse(appfolder.open_path("no-such-entry")["ok"])
        self.assertEqual(opened, [self.folder / "prompts", self.folder / "prompts" / "wikis-section.md"])

    def test_row_states_and_clearing_an_optional_entry(self):
        wiki = self.make_wiki("team")
        self.write_settings(self.folder, [("team", wiki)])
        self.choose()
        rows = {e["name"]: e for e in pathlist.list_paths()}
        self.assertTrue(all(e["state"] in pathlist.STATES for e in rows.values()))
        self.assertEqual(rows["prompt.wikis-section"]["state"], "ok")
        self.assertEqual(rows["settings"]["state"], "ok")
        for name in ("run_history", "engine_settings", "window_placement", "pending_promotion", "wiki.team.index",
                     "wiki.team.progress", "wiki.team.rules"):
            self.assertEqual(rows[name]["state"], "not_created", name)
        self.assertEqual((rows["tag_list_reference"]["state"], rows["tag_list_reference"]["can_clear"]), ("unset", False))
        self.assertFalse(rows["settings"]["can_clear"])
        tags = self.base / "team-tags.md"
        tags.write_text("- planet\n", encoding="utf-8")
        entry = pathlist.set_path("tag_list_reference", str(tags))
        self.assertEqual((entry["state"], entry["can_clear"]), ("ok", True))
        tags.unlink()
        self.assertEqual(pathlist.describe("tag_list_reference")["state"], "missing")
        cleared = pathlist.set_path("tag_list_reference", "")                              # clear
        self.assertEqual((cleared["path"], cleared["state"], cleared["can_clear"]), ("", "unset", False))
        (self.folder / "prompts" / "wikis-section.md").unlink()                                    # deleted at its usual place
        self.assertEqual(pathlist.describe("prompt.wikis-section")["state"], "missing")
        gone = self.base / "gone"
        gone.mkdir()
        pathlist.set_path("transcripts", str(gone))
        gone.rmdir()
        self.assertEqual(pathlist.describe("transcripts")["state"], "missing")

    def test_agentlib_is_found_beside_the_project_folder(self):
        project = self.base / "projects" / "MyApp"
        project.mkdir(parents=True)

        def library(where):
            (where / "agentlib").mkdir(parents=True)
            (where / "agentlib" / "__init__.py").write_text("", encoding="utf-8")
            (where / "pyproject.toml").write_text("[project]\nname='agentlib'\n", encoding="utf-8")
        self.assertEqual(pathlist.find_agentlib(project), [])
        library(self.base / "projects" / "Shared" / "agentlib")
        (self.base / "projects" / "Shared" / "deeper" / "agentlib").mkdir(parents=True)   # two levels in: not looked at
        self.assertEqual(pathlist.find_agentlib(project), [self.base / "projects" / "Shared" / "agentlib"])
        library(self.base / "projects" / "agentlib")
        self.assertEqual(len(pathlist.find_agentlib(project)), 2)


class PromptTextTest(FolderTest):
    """With the shipped defaults, the messages read exactly as they did when they were in code."""

    def test_messages_match_the_old_wording(self):
        import prompts
        card = {"id": "C1", "kind": "edit", "page": "team:Page.md", "summary": "S"}
        old_feedback = ("The reviewer has gone through the cards. Accepted: C2 (written to the wiki; leave them).\n\nFeedback on card C1:\n\n"
                        '<feedback card="C1" kind="edit" page="team:Page.md" summary="S">\nfix it\n</feedback>\n\n'
                        "Revise each of those proposals to follow its feedback: call propose_page again for the same page, which "
                        "replaces that card. Read pages first if you need to. If feedback means a change shouldn't be made at all, "
                        "don't call a tool for it; say so in one sentence that names the card. Don't propose anything else.")
        self.assertEqual(prompts.write_feedback_message([(card, "fix it")], {"C2": "accepted"}), old_feedback)
        old_answers = ("The reviewer answered your questions.\n\n"
                       '<answer question="q1" about="A">\n(Skipped. Leave this point out.)\n</answer>\n\n'
                       "Now propose the changes, following these answers: read any page you still need first. "
                       "A skipped question means that point is left out. Do not ask anything more.")
        self.assertEqual(prompts.write_answers_message([{"id": "q1", "about": "A"}], {}), old_answers)
        self.assertTrue(prompts.wikis_section().startswith("## Wikis\n\nEach wiki has an alias"))
        self.assertEqual(pathlist.read_prompt("prompt.promotion-first-message", date="2026-11-12"),
                         "Today is 2026-11-12. Promote what is durable in the personal pages below into the team wiki.\n")


class BridgeTest(FolderTest):
    """The page's commands, through the host's dispatch (no window is opened)."""

    def setUp(self):
        super().setUp()
        import wikiapp
        self.wikiapp = wikiapp
        self.host = wikiapp.Host([])

    def tearDown(self):
        self.host.server.server_close()
        super().tearDown()

    def test_first_run_paths_models_connection_and_open_commands(self):
        call = self.host.dispatch
        self.assertFalse(call("firstRunState", {"candidate": ""})["valid"])
        self.assertTrue(call("firstRunState", {})["valid"])
        call("chooseFolder", {"path": str(self.place)})
        rows = call("listPaths", {})
        self.assertTrue(all({"state", "can_clear"} <= set(r) for r in rows))
        saved = call("setEngineSettings", {"settings": {"engines": {"claude": {"models": {"team-wiki-manager": "claude-opus-5"}}}}})
        self.assertEqual(saved["engines"]["claude"]["models"]["team-wiki-manager"], "claude-opus-5")
        got = call("setAgentModel", {"agent": "executive-assistant", "model": "claude-sonnet-5-5"})
        self.assertEqual(got["engines"]["claude"]["models"]["executive-assistant"], "claude-sonnet-5-5")
        self.assertEqual(call("getEngineSettings", {})["engines"]["claude"]["models"]["team-wiki-manager"], "claude-opus-5")
        self.assertEqual(call("ingestInfo", {})["state"], None)                 # defaults to the promotion cards
        with mock.patch.object(appfolder, "system_open", lambda target: None):
            self.assertEqual(call("openPath", {"name": "app_folder"}), {"ok": True})
        with mock.patch.object(appfolder, "test_connection", lambda: {"ok": True, "via": "fake"}), \
                mock.patch.object(appfolder, "connection_status", lambda: {"ok": True, "via": "fake"}):
            self.assertEqual(call("testConnection", {}), {"ok": True, "via": "fake"})   # never a real request here
            self.assertEqual(call("connectionStatus", {}), {"ok": True, "via": "fake"})

    def test_a_second_start_during_the_first_run_finds_the_first(self):
        import socket
        with socket.socket() as probe:              # a free port of our own: never a real running copy's
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        brought = []
        self.host.bring_to_front = lambda: brought.append(True)
        with mock.patch.object(self.wikiapp, "guard_port", lambda: port):
            self.assertFalse(self.wikiapp.ask_running_copy_to_focus())          # nothing running yet
            guard = self.wikiapp.start_guard(self.host)
            self.assertIsNotNone(guard)
            try:
                self.assertIsNone(self.wikiapp.start_guard(self.host))         # a second copy can't take the port
                self.assertFalse(pathlist.is_chosen())                          # no instance.json to find it by
                self.assertTrue(self.wikiapp.ask_running_copy_to_focus())
                self.assertEqual(brought, [True])
            finally:
                guard.shutdown()
                guard.server_close()


class WikisTest(FolderTest):
    def test_templates_rules_and_index_come_from_the_path_list(self):
        import wikis
        own = self.make_wiki("team", templates=True)
        bare = self.make_wiki("personal")
        self.write_settings(self.place / ".wiki", [("team", own), ("personal", bare)])
        self.choose()
        model = wikis.Wikis([{"alias": "team", "root": str(own)}, {"alias": "personal", "root": str(bare)}])
        self.assertEqual([p.name for p in model.page_templates("team")], ["Own"])               # its own folder
        self.assertEqual([p.name for p in model.page_templates("personal")], ["Sample page"])  # the private ones
        self.assertIn("## Summary", model.pages["personal:Templates/Pages/Sample page.md"].text)
        self.assertIsNone(model.rules_text("team"))
        rules = self.base / "elsewhere-rules.md"
        rules.write_text("RULES FROM ELSEWHERE", encoding="utf-8")
        pathlist.set_path("wiki.team.rules", str(rules))
        model = wikis.Wikis([{"alias": "team", "root": str(own)}])
        self.assertEqual(model.rules_text("team"), "RULES FROM ELSEWHERE")
        model.write_indexes("2026-11-12")
        self.assertTrue((self.folder / "indexes" / "team.md").is_file())
        self.assertFalse((own / ".wiki").exists())                      # never written into the wiki
        self.assertFalse((bare / "Templates").exists())                 # and no Templates folder seeded


if __name__ == "__main__":
    unittest.main()
