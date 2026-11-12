"""Wiki roles (personal, team, view only) and the Sessions filter, kept in the private folder
(host/pathlist.py). No model is called; everything is in a temporary folder.

Run from App Files:  .venv/Scripts/python.exe -m unittest discover -s host/tests
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP_FILES = Path(__file__).resolve().parents[2]
for folder in ("host", "agents", "ingest"):
    if str(APP_FILES / folder) not in sys.path:
        sys.path.insert(0, str(APP_FILES / folder))

import pathlist  # noqa: E402
import sessionruns  # noqa: E402


class RolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.data = self.base / ".wiki"
        self.data.mkdir()
        self.env = mock.patch.dict(os.environ, {"WIKIAPP_DATA_DIR": str(self.data),
                                                "WIKIAPP_POINTER_FILE": str(self.base / "pointer.txt")})
        self.env.start()
        self.roots = {}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def open_wikis(self, *aliases, **settings):
        """Saves the open wikis as the page does (settings.json), making each folder."""
        workspace = []
        for alias in aliases:
            root = self.roots.get(alias) or self.base / "wikis" / alias.lower()
            root.mkdir(parents=True, exist_ok=True)
            self.roots[alias] = root
            workspace.append({"alias": alias, "root": str(root)})
        (self.data / "settings.json").write_text(json.dumps({"workspace": json.dumps(workspace), **settings}), encoding="utf-8")

    def stored(self):
        return json.loads((self.data / "wiki-settings.json").read_text(encoding="utf-8"))

    # ---- upgrading an older setup ----

    def test_upgrade_personal_and_one_other_becomes_team(self):
        self.open_wikis("personal", "Northwind")
        # Only the upgrade of an existing installation (the host's start-up) works roles out of the
        # older settings; any other read with nothing saved sees every wiki as view only.
        self.assertEqual(pathlist.wiki_roles()["roles"], {"personal": "view", "Northwind": "view"})
        roles = pathlist.wiki_roles(persist=True, upgrade=True)
        self.assertEqual(roles, {"roles": {"personal": "personal", "Northwind": "team"}, "needs_team": False, "needs_personal": False})
        self.assertEqual(sorted(e["role"] for e in self.stored()["roles"].values()), ["personal", "team"])
        # A wiki opened later starts as view only; the first result doesn't change.
        self.open_wikis("personal", "Northwind", "Acme")
        self.assertEqual(pathlist.wiki_roles(persist=True, upgrade=True)["roles"],
                         {"personal": "personal", "Northwind": "team", "Acme": "view"})

    def test_upgrade_with_several_others_makes_them_view_and_asks_for_a_team_wiki(self):
        self.open_wikis("Mine", "Northwind", "Acme", sessionsWiki="Mine")              # the Sessions tab's old choice
        roles = pathlist.wiki_roles(persist=True, upgrade=True)
        self.assertEqual(roles["roles"], {"Mine": "personal", "Northwind": "view", "Acme": "view"})
        self.assertTrue(roles["needs_team"])
        self.assertFalse(roles["needs_personal"])

    def test_upgrade_finds_a_wiki_marked_personal(self):
        self.open_wikis("Home", "Team")
        (self.roots["Home"] / "WIKI.md").write_text("---\ntype: personal\n---\n", encoding="utf-8")
        self.assertEqual(pathlist.wiki_roles(upgrade=True)["roles"], {"Home": "personal", "Team": "team"})

    def test_a_fresh_setup_starts_every_wiki_as_view_whatever_its_alias(self):
        self.open_wikis()
        self.assertEqual(pathlist.wiki_roles(persist=True, upgrade=True), {"roles": {}, "needs_team": False, "needs_personal": False})
        self.assertFalse((self.data / "wiki-settings.json").exists())                  # settled as "none" in paths.json
        self.open_wikis("personal", "team", sessionsWiki="personal")                    # opened afterwards
        for kwargs in ({}, {"persist": True}, {"persist": True, "upgrade": True}):      # the next start-up included
            roles = pathlist.wiki_roles(**kwargs)
            self.assertEqual(roles["roles"], {"personal": "view", "team": "view"})
        self.assertTrue(roles["needs_personal"] and roles["needs_team"])

    def test_choosing_a_fresh_private_folder_settles_roles_as_none(self):
        import appfolder
        pointer = self.base / "pointer2.txt"
        with mock.patch.dict(os.environ, {"WIKIAPP_POINTER_FILE": str(pointer)}), \
                mock.patch.object(appfolder, "old_locations", lambda: {"data": self.base / "no-old", "skills": self.base / "no-skills",
                                                                         "retired": None, "retired_runs": None}):
            os.environ.pop("WIKIAPP_DATA_DIR")
            place = self.base / "place"
            place.mkdir()
            appfolder.choose_location(str(place))
            folder = place / ".wiki"
            (folder / "settings.json").write_text(json.dumps({"workspace": [{"alias": "personal", "root": str(self.base)}]}),
                                                  encoding="utf-8")
            self.assertEqual(pathlist.wiki_roles(persist=True, upgrade=True)["roles"], {"personal": "view"})

    def test_a_wiki_not_saved_yet_is_reported_as_view(self):
        self.open_wikis("personal", "team")
        pathlist.wiki_roles(persist=True, upgrade=True)
        new = {"alias": "Later", "root": str(self.base / "later")}
        roles = pathlist.wiki_roles(workspace=[*pathlist.read_workspace(), new])
        self.assertEqual(roles["roles"]["Later"], "view")
        self.assertIsNone(pathlist.wiki_role_for_root(self.base / "later"))            # not an open wiki

    # ---- choosing roles ----

    def test_one_personal_and_one_team_at_most_with_demotion(self):
        self.open_wikis("A", "B", "C")
        pathlist.wiki_roles(persist=True)
        result = pathlist.set_wiki_role("A", "personal")
        self.assertEqual((result["roles"]["A"], result["demoted"]), ("personal", None))
        result = pathlist.set_wiki_role("B", "team")
        self.assertEqual(result["roles"], {"A": "personal", "B": "team", "C": "view"})
        result = pathlist.set_wiki_role("C", "team")                                    # a second team wiki
        self.assertEqual((result["roles"], result["demoted"]), ({"A": "personal", "B": "view", "C": "team"}, "B"))
        result = pathlist.set_wiki_role("C", "personal")                                # the team wiki made personal
        self.assertEqual((result["roles"], result["demoted"]), ({"A": "view", "B": "view", "C": "personal"}, "A"))
        self.assertTrue(result["needs_team"])
        self.assertEqual(set(result), {"roles", "needs_team", "needs_personal", "demoted"})
        with self.assertRaises(ValueError):
            pathlist.set_wiki_role("C", "owner")
        with self.assertRaises(ValueError):
            pathlist.set_wiki_role("Nope", "view")

    def test_a_role_survives_an_alias_change_and_is_never_written_in_the_wiki(self):
        self.open_wikis("Work", "Team")
        pathlist.set_wiki_role("Work", "personal")
        self.roots["Mine"] = self.roots.pop("Work")
        self.open_wikis("Mine", "Team")                                                 # renamed in the app
        self.assertEqual(pathlist.wiki_roles()["roles"]["Mine"], "personal")
        self.assertEqual(pathlist.wiki_role_for_root(self.roots["Mine"]), "personal")
        self.assertEqual(pathlist.wiki_with_role("personal")["alias"], "Mine")
        self.assertEqual(sorted(p.name for p in self.roots["Mine"].iterdir()), [])        # nothing in the wiki

    def test_the_personal_wiki_for_capture_comes_from_the_role(self):
        self.open_wikis("personal", "Work")
        pathlist.set_wiki_role("Work", "personal")                                      # not the alias "personal"
        self.assertEqual(sessionruns.personal_root(), str(self.roots["Work"]))
        self.assertEqual(pathlist.path("personal_tags"), self.roots["Work"] / "personal-tags.md")
        pathlist.set_wiki_role("Work", "view")
        with self.assertRaises(ValueError) as caught:
            sessionruns.personal_root()
        self.assertIn("Settings", str(caught.exception))

    def test_refusals_name_the_role_in_plain_words(self):
        self.assertEqual(pathlist.role_refusal("Northwind", "view", "team"), "Northwind is view only; choose a team wiki in Settings.")
        self.assertIn("personal wiki", pathlist.role_refusal("Northwind", "view", "personal"))
        self.assertIn("team wiki", pathlist.role_refusal("Team", "team", "personal"))

    # ---- the path list ----

    def test_wiki_rows_carry_their_role_and_only_the_team_wiki_has_a_rules_row(self):
        self.open_wikis("Mine", "Team", "Northwind")
        pathlist.set_wiki_role("Mine", "personal")
        pathlist.set_wiki_role("Team", "team")
        rows = {r["name"]: r for r in pathlist.list_paths()}
        self.assertEqual(rows["wiki.Team.rules"]["role"], "team")
        self.assertEqual([r["name"] for r in rows.values() if r["name"].endswith(".rules")], ["wiki.Team.rules"])
        self.assertNotIn("wiki.Mine.rules", rows)                                       # the capture rules are the personal wiki's
        self.assertEqual(rows["wiki.Mine.progress"]["role"], "personal")
        self.assertEqual(rows["wiki.Northwind.index"]["role"], "view")                 # read for context: kept
        self.assertIn("wiki.Northwind.templates", rows)                                 # the New note menu: kept
        self.assertNotIn("wiki.Northwind.rules", rows)
        self.assertNotIn("wiki.Northwind.progress", rows)
        self.assertEqual(rows["wiki_settings"]["state"], "ok")

    # ---- prompts ----

    def test_back_to_built_in_removes_the_empty_prompts_folder(self):
        pathlist.customise_prompt("prompt.wiki-reviewer")
        pathlist.customise_prompt("prompt.executive-assistant")
        pathlist.reset_prompt("prompt.wiki-reviewer")
        self.assertTrue((self.data / "prompts").is_dir())                               # another copy is still there
        pathlist.reset_prompt("prompt.executive-assistant")
        self.assertFalse((self.data / "prompts").exists())
        self.assertEqual(pathlist.describe("prompt.executive-assistant")["status"], "built_in")

    # ---- the Sessions filter ----

    def test_sessions_filter(self):
        self.assertEqual(pathlist.get_sessions_filter(), {"min_turns": 3, "options": [0, 3, 5, 10, 20]})
        self.assertIsNone(pathlist.stored_min_turns())
        self.assertEqual(pathlist.set_sessions_filter(10)["min_turns"], 10)
        self.assertEqual(pathlist.get_sessions_filter()["min_turns"], 10)
        for bad in (4, "5", True, None):
            with self.assertRaises(ValueError):
                pathlist.set_sessions_filter(bad)
        self.open_wikis("A")
        pathlist.set_wiki_role("A", "personal")                                         # one file holds both
        self.assertEqual(self.stored()["sessions"], {"min_turns": 10})


if __name__ == "__main__":
    unittest.main()
