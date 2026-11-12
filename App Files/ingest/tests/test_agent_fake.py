"""The ingest agent (Promotion runs, feedback rounds, the reviewer's questions) and the model menu,
run on agentlib's fake engine: scripted, zero tokens, nothing leaves this computer.

Each test works in a temporary folder: two small wikis, the app's private folder
(WIKIAPP_DATA_DIR), the agents' prompt files (WIKIAPP_SKILLS_DIR) and the run folder. The engine
choice is patched to "fake", which is what the engine settings would say for a fake engine.

Run from App Files:  .venv/Scripts/python.exe -m unittest discover -s ingest/tests
"""
import asyncio
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

APP_FILES = Path(__file__).resolve().parents[2]
for folder in ("ingest", "host", "agents"):
    if str(APP_FILES / folder) not in sys.path:
        sys.path.insert(0, str(APP_FILES / folder))

from agentlib import AgentError, ModelInfo, fake  # noqa: E402

import agent  # noqa: E402
import models  # noqa: E402
import tools  # noqa: E402
from wikis import Wikis  # noqa: E402

TOPIC = "personal:saturn-trip.md"
SATURN = "team:Planets/Saturn.md"
NAME = "team-wiki-manager"   # the agent's name, which fake.script() is keyed by


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def propose_edit(summary="Adds the sighting.", replace="Saturn has rings. A sighting on 10-28.", wiki="team"):
    return fake.call("propose_page", {"wiki": wiki, "page": SATURN, "summary": summary, "from_notes": [TOPIC],
                                      "edits": [{"find": "Saturn has rings.", "replace": replace}]})


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.team, self.personal = base / "team", base / "personal"
        write(self.team / "wiki_rules.md", "# Team rules\n\nOne page per planet.\n")
        write(self.team / "Planets" / "Saturn.md", "---\ndescription: The ringed planet.\n---\n# Saturn\n\nSaturn has rings.\n")
        write(self.personal / "WIKI.md", "---\ntype: personal\n---\n")
        write(self.personal / "saturn-trip.md", "---\ntype: topic\n---\n# Saturn trip\n\nSaw Titan on 10-28.\n")
        (base / "data").mkdir()
        (base / "skills").mkdir()
        # The open wikis, as the app saves them: "personal" is the personal wiki and the one other
        # wiki the team wiki (the roles an older setup gets; see pathlist.wiki_roles).
        write(base / "data" / "settings.json", json.dumps({"workspace": [
            {"alias": "team", "root": str(self.team)}, {"alias": "personal", "root": str(self.personal)}]}))
        self.run_folder = base / "data" / "ingest-runs" / "2026-11-12_100000"
        self.run_folder.mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"WIKIAPP_DATA_DIR": str(base / "data"),
                                                "WIKIAPP_SKILLS_DIR": str(base / "skills")})
        self.env.start()
        import pathlist
        pathlist.wiki_roles(persist=True, upgrade=True)   # as the host's start-up saves an older setup's roles
        self.events = []
        self.patches = [mock.patch.object(agent, "tell_app", self.events.append),
                        mock.patch.object(agent, "engine_choice", lambda: ("fake", {}))]
        for p in self.patches:
            p.start()
        fake.reset()

    def tearDown(self):
        fake.reset()
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    # ---- helpers ----

    def job(self, **settings):
        return {"runId": self.run_folder.name, "date": "2026-11-12", "notesDir": "Notes",
                "wikis": [{"alias": "team", "root": str(self.team)}, {"alias": "personal", "root": str(self.personal)}],
                "notes": [TOPIC], "agent": NAME, "targets": ["team"], "settings": settings}

    def of(self, kind):
        return [e for e in self.events if e.get("type") == kind]

    def done(self):
        found = self.of("done")
        self.assertEqual(len(found), 1, self.events)
        return found[0]

    def session(self):
        return json.loads((self.run_folder / "session.json").read_text(encoding="utf-8"))

    def transcript(self):
        return json.loads((self.run_folder / "transcript.json").read_text(encoding="utf-8"))

    def all_calls(self):
        return [c for step in self.transcript()["steps"] for c in step["tools"]]

    def start_run(self, job=None):
        return asyncio.run(agent.promote(job or self.job(), self.run_folder))

    # ---- a Promotion run ----

    def test_promotion_run_proposes_pages(self):
        fake.script(NAME, [[
            fake.say("Plan: the Titan sighting goes on Saturn."),
            fake.call("read_page", {"page": "team:Saturn"}),
            propose_edit(wiki="personal"),            # not a target: sent back as an error
            propose_edit(),
            fake.call("propose_page", {"wiki": "team", "new_path": "Moons/Titan.md", "summary": "A page for Titan.",
                                       "from_notes": [TOPIC], "content": "# Titan\n\nSeen from the trip.\n"}),
            fake.say("Done."),
        ]])
        self.assertEqual(self.start_run(), 0)

        done = self.done()
        self.assertTrue(done["ok"], done)
        self.assertEqual(done["questions"], 0)
        self.assertEqual(done["cards"], 2)
        self.assertEqual(done["reads"], 1)
        self.assertEqual(done["requests"], 1)
        self.assertGreater(done["cost"], 0)
        self.assertIn("plainClaudeCode", done)
        self.assertEqual(set(done["tokens"]), {"input", "cacheWrite", "cacheRead", "output"})

        cards = [e["card"] for e in self.of("card")]
        self.assertEqual([(c["id"], c["kind"]) for c in cards], [("c1", "edit"), ("c2", "new")])
        self.assertIn("A sighting on 10-28.", cards[0]["after"])
        self.assertEqual(self.of("read"), [{"type": "read", "page": SATURN}])
        self.assertTrue(any(e.get("stage") == "reading" for e in self.of("stage")))

        session = self.session()
        self.assertTrue(session["sessionId"])
        self.assertIn(SATURN, session["read"])
        self.assertGreater(session["totalCostUsd"], 0)

        transcript = self.transcript()
        self.assertTrue(transcript["ok"])
        self.assertEqual(len(transcript["cards"]), 2)
        calls = self.all_calls()
        self.assertEqual([c["tool"] for c in calls], ["read_page", "propose_page", "propose_page", "propose_page"])
        self.assertEqual(calls[0]["page"], SATURN)
        self.assertIn("Changes may only be proposed in: team", calls[1]["error"])
        self.assertNotIn("error", calls[2])
        # The system prompt is the agent's prompt file, then the Wikis section and each wiki's rules.
        system = (self.run_folder / "system.md").read_text(encoding="utf-8")
        self.assertIn('### Wiki "team"', system)
        self.assertIn("One page per planet.", system)
        # The first message opens with the promotion line (the only kind of run there is).
        first = (self.run_folder / "first-message.md").read_text(encoding="utf-8")
        self.assertTrue(first.startswith("Today is 2026-11-12. Promote"), first[:80])

    # ---- Promotion only ----

    def test_only_promotion_jobs_run(self):
        for job, why in ((dict(self.job(), agent="note-taker"), "team wiki manager only"),
                         (dict(self.job(), targets=[]), "no target wiki")):
            self.events.clear()
            self.assertEqual(self.start_run(job), 1)
            done = self.done()
            self.assertFalse(done["ok"])
            self.assertIn(why, done["message"])
        self.assertFalse(hasattr(agent, "DEFAULT_AGENT"))
        # A job that leaves out "agent" is a promotion all the same.
        fake.script(NAME, [[fake.say("Done.")]])
        self.events.clear()
        job = self.job()
        del job["agent"]
        self.assertEqual(self.start_run(job), 0)

    # ---- Wiki roles: only the team wiki is ever proposed to ----

    def with_northwind(self):
        """A third open wiki, Northwind, with a page; it starts as view only. -> the job's wikis."""
        import pathlist
        northwind = Path(self.tmp.name) / "northwind"
        write(northwind / "Moons.md", "---\ndescription: Moons.\n---\n# Moons\n\nTitan is a moon.\n")
        write(northwind / "wiki_rules.md", "# Northwind rules\n\nNORTHWIND-RULES\n")
        write(self.personal / "wiki_rules.md", "# Personal rules\n\nPERSONAL-RULES\n")
        wikis = [{"alias": "team", "root": str(self.team)}, {"alias": "personal", "root": str(self.personal)},
                 {"alias": "Northwind", "root": str(northwind)}]
        write(Path(self.tmp.name) / "data" / "settings.json", json.dumps({"workspace": wikis}))   # opened later
        self.assertEqual(pathlist.wiki_roles()["roles"], {"team": "team", "personal": "personal", "Northwind": "view"})
        return wikis

    def test_a_view_only_wiki_is_read_but_never_proposed_to(self):
        wikis = self.with_northwind()
        fake.script(NAME, [[
            fake.call("read_page", {"page": "Northwind:Moons"}),           # reading it for context is fine
            fake.call("propose_page", {"wiki": "Northwind", "page": "Northwind:Moons.md", "summary": "x", "from_notes": [TOPIC],
                                       "edits": [{"find": "Titan is a moon.", "replace": "Titan is a big moon."}]}),
            fake.call("propose_page", {"wiki": "Northwind", "new_path": "Titan.md", "summary": "x", "from_notes": [TOPIC],
                                       "content": "# Titan\n"}),
            fake.say("Done."),
        ]])
        self.assertEqual(self.start_run(dict(self.job(), wikis=wikis, targets=["team", "Northwind"])), 1)
        self.assertIn("Northwind is view only; choose a team wiki in Settings.", self.done()["message"])  # the job itself refused
        self.events.clear()
        self.assertEqual(self.start_run(dict(self.job(), wikis=wikis)), 0)
        calls = self.all_calls()
        self.assertNotIn("error", calls[0])
        for call in calls[1:]:
            self.assertIn("Northwind is view only; choose a team wiki in Settings.", call["error"])
        self.assertEqual(self.of("card"), [])
        system = (self.run_folder / "system.md").read_text(encoding="utf-8")
        self.assertIn('### Wiki "Northwind" (view only', system)
        self.assertIn('### Wiki "team" (the team wiki', system)
        # Only the team wiki's rules file is sent: not the personal wiki's, not a view-only wiki's.
        self.assertIn("One page per planet.", system)
        self.assertNotIn("NORTHWIND-RULES", system)
        self.assertNotIn("PERSONAL-RULES", system)
        self.assertEqual(system.count("<rules>"), 1)

    def test_promotion_refuses_a_target_that_is_not_the_team_wiki(self):
        import pathlist
        wikis = self.with_northwind()
        pathlist.set_wiki_role("Northwind", "team")                       # team demoted to view
        self.assertEqual(self.start_run(dict(self.job(), wikis=wikis)), 1)
        self.assertIn("team is view only; choose a team wiki in Settings.", self.done()["message"])
        self.events.clear()
        self.assertEqual(self.start_run(dict(self.job(), wikis=wikis, targets=["personal"])), 1)
        self.assertIn("personal is your personal wiki", self.done()["message"])

    def test_state_is_the_promotion_tabs_only(self):
        from ingestruns import IngestRuns
        runs = IngestRuns(lambda *a: None)
        self.assertEqual(set(runs.STATE_ENTRIES), {"promotion"})
        self.assertIn("state", runs.info())                            # the default is the Promotion tab
        with self.assertRaises(ValueError):
            runs.info("notes")
        with self.assertRaises(ValueError):
            runs.save_state("{}", "notes")

    def test_default_model_comes_from_the_engine_settings(self):
        """The engine settings' per-agent model is the one place a Promotion run's default model is
        kept (the app reads and writes it); a model the job names still wins."""
        import pathlist
        pathlist.set_engine_settings({"engines": {"claude": {"models": {NAME: "fake-small"}}}})
        real = lambda: ("fake", pathlist.get_engine_settings()["engines"]["claude"])
        with mock.patch.object(agent, "engine_choice", real):
            self.assertEqual(agent.model_for(self.job()), "fake-small")
            self.assertEqual(agent.model_for(self.job(model="fake-large")), "fake-large")
            fake.script(NAME, [[fake.say("Done.")], [fake.say("Done.")]])
            self.start_run()
            self.assertEqual(self.transcript()["model"], "fake-small")   # the model that ran
            self.events.clear()
            self.start_run(self.job(model="fake-large"))
            self.assertEqual(self.transcript()["model"], "fake-large")
        # No model anywhere: the engine's own default.
        self.assertIsNone(agent.model_for(self.job(), {"models": {}}))

    def test_the_index_falls_back_to_summary_and_leaves_out_the_persons_tag_files(self):
        write(self.personal / "saturn-trip.md", "---\ntype: topic\nsummary: Trip notes.\n---\n# Saturn trip\n")
        write(self.personal / "personal-tags.md", "---\ntype: tag-list\n---\n# My tags\n")
        model = Wikis(self.job()["wikis"])
        index = model.index_text("personal")
        self.assertIn("Trip notes.", index)
        self.assertNotIn("(no description) | tags", index.split("saturn-trip")[1].split("\n")[0])
        self.assertNotIn("personal-tags", index)
        self.assertNotIn("personal:personal-tags.md", model.pages)

    def test_agent_settings(self):
        memory = tools.RunMemory(Wikis(self.job()["wikis"]), "r", [TOPIC], lambda e: None, ["team"])
        (self.run_folder / "system.md").write_text("Be brief.", encoding="utf-8")
        with mock.patch.object(agent, "engine_choice", lambda: ("fake", {"models": {NAME: "fake-small"}})):
            made = agent.make_agent(self.job(), self.run_folder, memory)
            self.assertEqual(made.model, "fake-small")                  # the engine settings' model for the agent
            self.assertEqual(agent.make_agent(self.job(model="fake-large"), self.run_folder, memory).model, "fake-large")
        self.assertEqual(made.engine, "fake")
        self.assertEqual(made.permission_mode, "never_ask")
        self.assertEqual(made.max_budget_usd, agent.MAX_COST_USD)
        self.assertEqual(made.tool_server, "wiki")
        self.assertEqual([t.name for t in made.tools], ["read_page", "propose_page", "ask_reviewer"])
        self.assertEqual(made.instructions, "Be brief.")
        # Claude's environment switches stay; another engine gets none of them.
        claude_env = agent.engine_env("claude", {"env": {"EXTRA": "1"}})
        self.assertEqual(claude_env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")
        self.assertEqual(claude_env["EXTRA"], "1")
        self.assertEqual(agent.engine_env("fake", {}), {})

    # ---- a feedback round ----

    def test_feedback_round_continues_the_same_conversation(self):
        received = []
        fake.script(NAME, [
            [fake.call("read_page", {"page": SATURN}), propose_edit(), fake.say("Done.")],
            lambda message: received.append(message) or [
                propose_edit(summary="Only the Titan sighting.", replace="Saturn has rings. Titan seen on 10-28."),
                fake.say("Revised c1."),
            ],
        ])
        self.assertEqual(self.start_run(), 0)
        first = self.session()
        first_cost = self.transcript()["totals"]["cost"]
        # Steps as far as they can be seen: read; then propose (after the read's result); then "Done.".
        self.assertEqual(len(self.transcript()["steps"]), 3)
        self.events.clear()

        feedback = {"cards": [{"card": "c1", "text": "Only keep the Titan observation."}], "accepted": [], "rejected": []}
        self.assertEqual(asyncio.run(agent.revise_cards(self.job(), self.run_folder, feedback)), 0)

        self.assertEqual(len(received), 1)
        self.assertIn('<feedback card="c1"', received[0])
        self.assertIn("Only keep the Titan observation.", received[0])
        reply = self.of("reply")[0]
        self.assertEqual(reply["revised"], ["c1"])
        self.assertEqual(reply["text"], "Revised c1.")
        card = self.of("card")[0]["card"]
        self.assertEqual(card["id"], "c1")                              # the same card, replaced
        self.assertIn("Titan seen on 10-28.", card["after"])
        done = self.done()
        self.assertTrue(done["ok"] and done["feedback"], done)
        self.assertEqual(done["cards"], ["c1"])                         # the round's card ids
        self.assertEqual(done["cardCount"], 1)                          # the run's card count
        self.assertEqual(done["requests"], 2)                          # the run's totals, this round included
        self.assertGreater(done["round"]["cost"], 0)
        self.assertAlmostEqual(done["cost"], round(first_cost + done["round"]["cost"], 4), places=4)

        self.assertEqual(self.session()["sessionId"], first["sessionId"])
        transcript = self.transcript()
        self.assertEqual(len(transcript["feedback"]), 1)
        entry = transcript["feedback"][0]
        self.assertTrue(entry["revised"])
        self.assertEqual(entry["firstStep"], 4)                         # the run window shows the round there
        self.assertEqual(transcript["steps"][-1]["round"], 1)

    # ---- the reviewer's questions ----

    def test_reviewer_question_and_answer(self):
        received = []
        fake.script(NAME, [
            [fake.call("ask_reviewer", {"questions": [
                {"about": "Titan sighting", "question": "Saturn's page or a new Titan page?",
                 "options": [SATURN, "team:Moons/Titan.md"]},
                {"about": "Gear", "question": "Is the telescope note general?"}]}),
             fake.say("never reached: ask_reviewer ends the turn")],
            lambda message: received.append(message) or [
                fake.call("read_page", {"page": SATURN}), propose_edit(), fake.say("Done.")],
        ])
        self.assertEqual(self.start_run(), 0)
        questions = self.of("questions")[0]["questions"]
        self.assertEqual([q["id"] for q in questions], ["q1", "q2"])
        self.assertEqual(questions[0]["options"], [SATURN, "team:Moons/Titan.md"])
        done = self.done()
        self.assertTrue(done["ok"])
        self.assertEqual(done["questions"], 2)
        self.assertNotIn("never reached", json.dumps(self.transcript()))
        self.assertTrue(self.session()["asked"])
        self.events.clear()

        answers = {"q1": SATURN, "q2": ""}
        self.assertEqual(asyncio.run(agent.answer_questions(self.job(), self.run_folder, answers)), 0)
        self.assertEqual(len(received), 1)
        self.assertIn('<answer question="q1" about="Titan sighting">\n' + SATURN, received[0])
        self.assertIn("(Skipped. Leave this point out.)", received[0])
        self.assertEqual([e["card"]["id"] for e in self.of("card")], ["c1"])
        done = self.done()
        self.assertTrue(done["ok"] and done["answers"], done)
        self.assertEqual(done["cards"], 1)
        transcript = self.transcript()
        self.assertEqual([q["answer"] for q in transcript["questions"]], [SATURN, ""])
        self.assertEqual(len(transcript["cards"]), 1)

    def test_second_question_round_is_refused(self):
        ask = fake.call("ask_reviewer", {"questions": [{"about": "x", "question": "Where?"}]})
        fake.script(NAME, [[ask], [ask, fake.say("Proposing with what I know.")]])
        self.start_run()
        self.events.clear()
        asyncio.run(agent.answer_questions(self.job(), self.run_folder, {"q1": "There."}))
        self.assertEqual(self.of("questions"), [])
        self.assertIn("already asked", self.all_calls()[-1]["error"])

    # ---- limits and permissions ----

    def test_spending_cap_stops_the_run(self):
        fake.script(NAME, [[
            fake.call("read_page", {"page": SATURN}),
            fake.spend(0.05),
            propose_edit(),
            fake.say("Done."),
        ]])
        self.assertEqual(self.start_run(self.job(maxBudgetUsd=0.01)), 1)
        done = self.done()
        self.assertFalse(done["ok"])
        self.assertEqual(done["message"], "The run hit its cost limit before finishing.")
        self.assertEqual(done["errorKind"], "budget")
        self.assertEqual(self.of("card"), [])                           # it stopped before proposing
        transcript = self.transcript()
        self.assertFalse(transcript["ok"])
        self.assertEqual(transcript["message"], "The run hit its cost limit before finishing.")

    def test_tool_not_given_is_denied_in_never_ask_mode(self):
        fake.script(NAME, [[
            fake.call("Bash", {"command": "rm -rf Planets"}),
            fake.call("read_page", {"page": SATURN}),
            propose_edit(),
            fake.say("Done."),
        ]])
        self.assertEqual(self.start_run(), 0)
        self.assertTrue(self.done()["ok"])                              # a denied tool doesn't end the run
        bash = self.all_calls()[0]
        self.assertEqual(bash["tool"], "Bash")
        self.assertIn("never_ask", bash["error"])
        self.assertTrue((self.team / "Planets" / "Saturn.md").exists())
        self.assertEqual(len(self.of("card")), 1)

    def test_engine_failure_is_reported(self):
        fake.script(NAME, [[fake.say("Reading."), fake.fail("the engine stopped")]])
        self.assertEqual(self.start_run(), 1)
        done = self.done()
        self.assertFalse(done["ok"])
        self.assertIn("the engine stopped", done["message"])
        self.assertFalse(self.transcript()["ok"])

    def test_missing_conversation_is_reported(self):
        fake.script(NAME, [[fake.call("read_page", {"page": SATURN}), propose_edit()]])
        self.start_run()
        fake.reset()                                                    # the saved conversation is gone
        self.events.clear()
        feedback = {"cards": [{"card": "c1", "text": "Shorter."}]}
        self.assertEqual(asyncio.run(agent.revise_cards(self.job(), self.run_folder, feedback)), 1)
        self.assertIn("can't be found", self.done()["message"])

    # ---- the tools' own checks ----

    def test_new_pages_cannot_go_where_pages_dont(self):
        wikis = Wikis(self.job()["wikis"])
        self.assertTrue(tools.is_reserved(wikis, "team", "wiki_rules.md"))
        self.assertTrue(tools.is_reserved(wikis, "team", "Templates/Pages/Planet.md"))
        self.assertTrue(tools.is_reserved(wikis, "team", "Notes/today.md"))
        self.assertFalse(tools.is_reserved(wikis, "team", "Moons/Titan.md"))


class ModelMenuTest(unittest.TestCase):
    def setUp(self):
        fake.reset()
        self.patch = mock.patch.object(agent, "engine_choice", lambda: ("fake", {}))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        fake.reset()

    def test_lists_models(self):
        fake.models([ModelInfo(id="fake-large", name="Large", description="Most capable", is_default=True),
                     {"id": "fake-small", "name": "Small", "description": "Fastest"}])
        self.assertEqual(models.models(), [
            {"id": "fake-large", "name": "Large", "description": "Most capable"},
            {"id": "fake-small", "name": "Small", "description": "Fastest"},
        ])

    def test_keeps_only_real_model_ids(self):
        fake.models(["default", "fake-small"])
        with mock.patch.dict(models.ID_PREFIX, {"fake": "fake-"}):
            self.assertEqual([m["id"] for m in models.models()], ["fake-small"])

    def test_failure(self):
        fake.models(fail="Claude Code isn't signed in.")
        with self.assertRaises(AgentError):
            models.models()
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            self.assertEqual(models.main(), 1)
        self.assertIn("isn't signed in", err.getvalue())
        self.assertEqual(out.getvalue(), "")


class CostsTest(unittest.TestCase):
    def test_tokens_from_usage_and_from_a_dict(self):
        import costs
        from agentlib import Usage
        want = {"input": 1, "cacheWrite": 2, "cacheRead": 3, "output": 4}
        self.assertEqual(costs.tokens_of(Usage(input_tokens=1, cache_write_tokens=2, cache_read_tokens=3, output_tokens=4)), want)
        # sessions/secondbrain/llm.py passes the API's names.
        self.assertEqual(costs.tokens_of({"input_tokens": 1, "cache_creation_input_tokens": 2,
                                          "cache_read_input_tokens": 3, "output_tokens": 4}), want)
        self.assertEqual(costs.tokens_of(None), {"input": 0, "cacheWrite": 0, "cacheRead": 0, "output": 0})


class NoAgentSdkTest(unittest.TestCase):
    def test_no_direct_sdk_import(self):
        """Agent code goes through agentlib: nothing in the app imports an agent SDK itself."""
        pattern = re.compile(r"^\s*(from|import)\s+claude_agent_sdk\b", re.M)
        found = [str(p.relative_to(APP_FILES)) for p in APP_FILES.rglob("*.py")
                 if ".venv" not in p.parts and pattern.search(p.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
