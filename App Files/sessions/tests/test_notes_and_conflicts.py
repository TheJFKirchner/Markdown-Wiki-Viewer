"""Notes capture, source marks, conflicts and the progress folder, with every request to the model
going through agentlib's fake engine (no tokens spent). Run: python -m unittest discover tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from agentlib import fake
except ImportError:  # agentlib isn't installed in this Python
    fake = None

from secondbrain import cli, config, conflicts, ingest, llm, review, tags, wiki  # noqa: E402
from test_pipeline import SID, write_transcript  # noqa: E402

TODAY = __import__("datetime").date.today().isoformat()
RULES = "Give every client its own page, named after the client."


def capture(slug="stop-loss-analytics", entry="Set the quarterly reporting rule", worth=True, title="Stop loss", **over):
    data = {
        "worth_recording": worth, "skip_reason": "" if worth else "Nothing the analyst stated or confirmed",
        "title": title, "summary": "What was said." if worth else "",
        "decisions": [{"decision": "Report stop loss quarterly", "why": "Matches the contract"}],
        "findings": [], "open_questions": [], "data_findings": [],
        "new_tags": [],
        "topics": [{"slug": slug, "title": slug.replace("-", " ").capitalize(),
                    "summary": "Stop loss analytics", "tags": ["stop-loss"], "entry": entry, "supersedes": False}] if worth else [],
    }
    data.update(over)
    return data


@unittest.skipIf(fake is None, "agentlib is not installed in this Python")
class FakeEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.saved_env = {k: os.environ.pop(k, None) for k in ("WIKIAPP_DATA_DIR", "WIKIAPP_POINTER_FILE", "WIKIAPP_SKILLS_DIR")}
        os.environ["WIKIAPP_POINTER_FILE"] = str(self.base / "no-pointer.txt")   # never the user's real folder
        os.environ["WIKIAPP_SKILLS_DIR"] = str(self.base / "skills")
        self.wiki = self.base / "personal"
        self.notes = self.base / "work" / "Notes"
        self.notes.mkdir(parents=True)
        self.transcript = self.base / "projects" / "C--work" / f"{SID}.jsonl"
        write_transcript(self.transcript)
        self.cfg = config.Config({"personal_wiki": str(self.wiki), "transcripts_dir": str(self.base / "projects"),
                                  "engine": "fake"}, None)
        wiki.init_personal(self.wiki, "---\ntype: personal\n---\n")
        fake.reset()
        self.queues, self.prompts = {}, {}

    def tearDown(self):
        fake.reset()
        for key, value in self.saved_env.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        self.tmp.cleanup()

    # ---- helpers ----

    def model(self, name, *replies):
        """Queue the fake model's structured replies for an agent; each request takes the next one."""
        if name not in self.queues:
            self.queues[name], self.prompts[name] = [], []

            def turn(message, name=name):
                self.prompts[name].append(message)
                return [fake.output(self.queues[name].pop(0))]
            fake.script(name, [turn])
        for reply in replies:  # a well-formed review reply gets the parts a test doesn't care about
            if "state_markdown" in reply:
                for part, value in (("conflicts", []), ("related", []), ("tags", ["stop-loss"]), ("new_tags", [])):
                    reply.setdefault(part, value)
        self.queues[name].extend(replies)

    def note(self, name="Pricing call.md", text="---\ntitle: Pricing call\n---\nAgreed stop loss is reported quarterly. Attachment point is 250000.\n"):
        path = self.notes / name
        path.write_text(text, encoding="utf-8")
        return path

    def capture_note(self, path, *replies, **kw):
        self.model("executive-assistant", *replies)
        return ingest.ingest_note(self.cfg, str(path), **kw)

    def capture_session(self, *replies, sid=SID, **kw):
        self.model("executive-assistant", *replies)
        return ingest.ingest_session(self.cfg, sid, **kw)

    def page(self, slug="stop-loss-analytics"):
        return wiki.read_page(wiki.find_topic(self.wiki, slug))

    def log(self, slug="stop-loss-analytics"):
        return wiki.get_zone(self.page(slug)[1], "log")

    def state(self, slug="stop-loss-analytics"):
        return wiki.get_zone(self.page(slug)[1], "state")

    def last_prompt(self, name="executive-assistant"):
        return self.prompts[name][-1]

    def conflict_setup(self):
        """A note and a session on one topic that disagree, and a review that reports it."""
        note = self.note()
        noted = self.capture_note(note, capture(entry="Quarterly reporting agreed"))
        session = self.capture_session(capture(entry="Monthly reporting proposed", title="Monthly"))
        n_ref, s_ref = Path(noted["note"]).stem, Path(session["note"]).stem
        reply = {"state_markdown": "Stop loss is reported **quarterly**.", "summary": "Stop loss; quarterly",
                 "conflicts": [{"note_ref": n_ref, "session_ref": s_ref, "note_text": "Reported quarterly.",
                                "session_text": "Reported monthly."},
                               {"note_ref": "made-up", "session_ref": s_ref, "note_text": "x", "session_text": "y"}]}
        self.model("wiki-reviewer", reply)
        result = review.review_topic(self.cfg, "stop-loss-analytics")
        return note, n_ref, s_ref, reply, result

    # ---- notes ----

    def test_a_note_is_captured_into_the_personal_wiki(self):
        path = self.note()
        result = self.capture_note(path, capture())
        self.assertEqual(result["status"], "ingested")
        self.assertEqual(result["path"], str(path.resolve()))
        meta, body = wiki.parse(path.read_text(encoding="utf-8"))
        self.assertRegex(meta["capture_id"], r"^n-[0-9a-f]{12}$")
        self.assertEqual(meta["ingested"], TODAY)
        self.assertEqual(meta["title"], "Pricing call")                       # the person's own frontmatter kept
        self.assertIn("Attachment point is 250000.", body)                   # their text untouched
        record_meta, record_body = wiki.read_page(self.wiki / result["note"])
        self.assertEqual((record_meta["origin"], record_meta["capture_id"]), ("note", meta["capture_id"]))
        self.assertIn("From your note: [[Pricing call]]", record_body)
        self.assertEqual(result["topics"][0]["slug"], "stop-loss-analytics")
        prompt = self.last_prompt()
        self.assertIn("a note the analyst wrote themselves", prompt)
        self.assertIn("Attachment point is 250000.", prompt)                 # numbers in a note go to the model
        self.assertIn("**A note the analyst wrote.**", prompt)
        self.assertEqual(ingest.note_status(self.cfg, str(path))["status"], "captured")
        spend = wiki.load_spend(self.wiki)["capture"]                        # the ledger of spend, from the reply's usage
        self.assertEqual(spend["calls"], 1)
        self.assertGreater(spend["tokens_out"], 0)

    def test_a_renamed_note_is_not_captured_twice(self):
        path = self.note()
        first = self.capture_note(path, capture())
        moved = path.with_name("Pricing call (renamed).md")
        path.rename(moved)
        self.assertEqual(ingest.note_status(self.cfg, str(moved))["status"], "captured")
        second = ingest.ingest_note(self.cfg, str(moved))                    # no reply queued: the model isn't asked
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(len(self.prompts["executive-assistant"]), 1)
        self.assertEqual(second["note"], first["note"])
        self.assertEqual(len(wiki.session_notes(self.wiki)), 1)
        entry = wiki.load_ledger(self.wiki)["note:" + first["capture_id"]]
        self.assertEqual(entry["path"], str(moved.resolve()))

    def test_a_renamed_note_updates_its_records_link_and_nothing_else(self):
        path = self.note()
        first = self.capture_note(path, capture())
        record = self.wiki / first["note"]
        before = record.read_text(encoding="utf-8")
        self.assertIn("From your note: [[Pricing call]]", before)
        moved = path.with_name("Pricing call (renamed).md")
        path.rename(moved)
        self.assertEqual(ingest.ingest_note(self.cfg, str(moved))["status"], "unchanged")
        after = record.read_text(encoding="utf-8")
        self.assertIn("From your note: [[Pricing call (renamed)]]", after)
        self.assertIn("(renamed).md", after)
        self.assertEqual(after.replace('"Pricing call (renamed).md"', "Pricing call.md").replace("[[Pricing call (renamed)]]", "[[Pricing call]]"), before)
        self.assertEqual(len(self.prompts["executive-assistant"]), 1)

    def test_a_copied_note_is_a_new_note(self):
        path = self.note()
        first = self.capture_note(path, capture())
        copy = path.with_name("Copy.md")
        copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(ingest.note_status(self.cfg, str(copy))["status"], "new")
        second = self.capture_note(copy, capture(title="Copy"))
        self.assertNotEqual(second["capture_id"], first["capture_id"])
        self.assertEqual(len(wiki.session_notes(self.wiki)), 2)

    def test_an_edited_note_replaces_its_entries(self):
        path = self.note()
        first = self.capture_note(path, capture(entry="Quarterly reporting agreed"))
        path.write_text(path.read_text(encoding="utf-8").replace("quarterly", "half-yearly"), encoding="utf-8")
        self.assertEqual(ingest.note_status(self.cfg, str(path))["status"], "changed")
        second = self.capture_note(path, capture(entry="Half-yearly reporting agreed"))
        self.assertEqual(second["status"], "ingested")
        self.assertEqual(second["note"], first["note"])                     # the same record, rewritten
        log = self.log()
        self.assertIn("Half-yearly reporting agreed", log)
        self.assertNotIn("Quarterly reporting agreed", log)
        self.assertEqual(len(log.splitlines()), 1)
        self.assertEqual(self.page()[0]["entries_since_review"], 1)
        self.assertEqual(ingest.note_status(self.cfg, str(path))["status"], "captured")

    def test_log_entries_are_marked_with_their_source(self):
        noted = self.capture_note(self.note(), capture(entry="From the note"))
        session = self.capture_session(capture(entry="From the session"))
        lines = self.log().splitlines()
        by_source = {wiki.log_source(line): line for line in lines}
        self.assertEqual(set(by_source), {"note", "session"})
        self.assertIn(f"[note] — From the note ([[{Path(noted['note']).stem}]])", by_source["note"])
        self.assertIn(f"[session] — From the session ([[{Path(session['note']).stem}]])", by_source["session"])
        self.assertEqual(wiki.read_page(self.wiki / session["note"])[0]["origin"], "session")

    def test_a_session_with_nothing_capture_worthy_captures_nothing(self):
        result = self.capture_session(capture(worth=False))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(wiki.session_notes(self.wiki), [])
        self.assertEqual(wiki.topic_pages(self.wiki), [])
        prompt = self.last_prompt()
        self.assertIn("**A working session.** Capture only these three things", prompt)
        self.assertIn("a Claude Code working session", prompt)

    def test_a_captured_session_is_not_sent_again(self):
        self.capture_session(capture())
        again = ingest.ingest_session(self.cfg, SID, only_new=True)        # what the app asks
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(len(self.prompts["executive-assistant"]), 1)

    def test_a_malformed_reply_is_handled(self):
        path = self.note()
        before_topics = wiki.topic_pages(self.wiki)
        self.model("executive-assistant", {"nonsense": True}, {"title": 3})
        with self.assertRaises(llm.LLMError) as caught:
            ingest.ingest_note(self.cfg, str(path))
        self.assertIn("wrong shape", str(caught.exception))
        self.assertEqual(len(self.prompts["executive-assistant"]), 2)       # one retry, then it gives up
        self.assertEqual((wiki.session_notes(self.wiki), wiki.topic_pages(self.wiki)), ([], before_topics))
        meta = wiki.parse(path.read_text(encoding="utf-8"))[0]
        self.assertNotIn("ingested", meta)                                   # not marked as captured
        self.assertEqual(ingest.note_status(self.cfg, str(path))["status"], "new")
        self.assertEqual(wiki.load_spend(self.wiki)["capture"]["calls"], 2)  # both requests were still paid for
        # A review with a malformed reply leaves the page alone.
        self.capture_session(capture())
        before = wiki.find_topic(self.wiki, "stop-loss-analytics").read_text(encoding="utf-8")
        self.model("wiki-reviewer", {"summary": "no state"}, {"summary": "still none"})
        with self.assertRaises(llm.LLMError):
            review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(wiki.find_topic(self.wiki, "stop-loss-analytics").read_text(encoding="utf-8"), before)

    # ---- conflicts ----

    def test_a_note_session_conflict_is_surfaced(self):
        note, n_ref, s_ref, _, result = self.conflict_setup()
        self.assertEqual(len(result["conflicts"]), 1)
        c = result["conflicts"][0]
        self.assertEqual({k: c[k] for k in ("topic", "note_text", "session_text", "session_ref")},
                         {"topic": "stop-loss-analytics", "note_text": "Reported quarterly.",
                          "session_text": "Reported monthly.", "session_ref": s_ref})
        self.assertRegex(c["id"], r"^c-[0-9a-f]{10}$")
        self.assertEqual(len(result["warnings"]), 1)                         # the one naming a note it wasn't shown
        state = self.state()
        self.assertIn("Stop loss is reported **quarterly**.", state)         # the note's version is the fact
        self.assertIn(f"> **Conflict** ({c['id']})", state)
        self.assertIn("> Session ([[" + s_ref + "]]): Reported monthly.", state)
        self.assertIn("> Your note ([[" + n_ref + "]]): Reported quarterly.", state)
        self.assertEqual([x["id"] for x in conflicts.open_conflicts(self.wiki)], [c["id"]])
        prompt = self.last_prompt("wiki-reviewer")
        self.assertIn(f"### [[{n_ref}]] · ", prompt)
        self.assertIn(" · note — ", prompt)
        self.assertIn(" · session — ", prompt)

    def test_keep_note(self):
        note, *_, result = self.conflict_setup()
        cid = result["conflicts"][0]["id"]
        out = conflicts.resolve(self.cfg, cid, "keep_note")
        self.assertEqual(out["conflict"]["status"], "keep_note")
        self.assertNotIn("**Conflict**", self.state())
        self.assertIn("quarterly", self.state())
        self.assertEqual(conflicts.open_conflicts(self.wiki), [])
        with self.assertRaises(ValueError):
            conflicts.resolve(self.cfg, cid, "dismiss")                     # settled once only

    def test_accept_session(self):
        note, _, s_ref, _, result = self.conflict_setup()
        before = note.read_bytes()
        conflicts.resolve(self.cfg, result["conflicts"][0]["id"], "accept_session")
        state = self.state()
        self.assertNotIn("**Conflict**", state)
        self.assertIn("**Settled**", state)
        self.assertIn(f"Reported monthly. ([[{s_ref}]])", state)
        meta = self.page()[0]
        self.assertEqual((meta["needs_review"], meta["review_reason"]), (True, "conflict"))
        self.assertEqual(note.read_bytes(), before)                          # the person's note is never edited
        # The next review is told the session's version stands.
        self.model("wiki-reviewer", {"state_markdown": "Stop loss is reported monthly.", "summary": "Monthly", "conflicts": []})
        review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertIn("accepted the session's version, so state it as the fact: Reported monthly.", self.last_prompt("wiki-reviewer"))
        self.assertNotIn("**Settled**", self.state())

    def test_dismiss(self):
        *_, result = self.conflict_setup()
        conflicts.resolve(self.cfg, result["conflicts"][0]["id"], "dismiss")
        self.assertNotIn("**Conflict**", self.state())
        self.assertEqual(conflicts.open_conflicts(self.wiki), [])

    def test_a_settled_conflict_does_not_come_back_unless_the_text_changes(self):
        note, n_ref, s_ref, reply, result = self.conflict_setup()
        cid = result["conflicts"][0]["id"]
        conflicts.resolve(self.cfg, cid, "keep_note")
        self.model("wiki-reviewer", reply)                                    # the reviewer reports it again anyway
        again = review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(again["conflicts"], [])
        self.assertNotIn("**Conflict**", self.state())
        self.assertEqual(conflicts.open_conflicts(self.wiki), [])
        self.assertIn("## Settled conflicts", self.last_prompt("wiki-reviewer"))
        self.assertIn("the analyst kept the note's version: Reported quarterly.", self.last_prompt("wiki-reviewer"))
        # The session is captured again with something new in it: the conflict is a new one.
        self.capture_session(capture(entry="Monthly reporting proposed", title="Monthly", summary="Said something new."))
        self.model("wiki-reviewer", reply)
        third = review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(len(third["conflicts"]), 1)
        self.assertNotEqual(third["conflicts"][0]["id"], cid)

    def test_text_typed_in_the_notes_section_counts_as_a_note(self):
        session = self.capture_session(capture(entry="Monthly reporting proposed"))
        page = wiki.find_topic(self.wiki, "stop-loss-analytics")
        page.write_text(page.read_text(encoding="utf-8").replace("## Notes\n", "## Notes\nWe report quarterly.\n"), encoding="utf-8")
        s_ref = Path(session["note"]).stem
        self.model("wiki-reviewer", {"state_markdown": "Reported quarterly.", "summary": "Stop loss", "conflicts": [
            {"note_ref": "notes-section", "session_ref": s_ref, "note_text": "Quarterly.", "session_text": "Monthly."}]})
        result = review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(result["conflicts"][0]["note_ref"], "notes-section")
        self.assertIn("> Your notes on this page: Quarterly.", self.state())
        self.assertIn("We report quarterly.", wiki.get_zone(self.page()[1], "notes"))   # never touched

    def test_conflicts_through_the_command_line(self):
        *_, result = self.conflict_setup()
        cid = result["conflicts"][0]["id"]
        out = self._cli("conflicts")
        self.assertEqual([c["id"] for c in out], [cid])
        self.assertEqual(self._cli("resolve-conflict", cid, "dismiss")["conflict"]["status"], "dismiss")
        self.assertEqual(self._cli("conflicts"), [])

    def _cli(self, *argv):
        from io import StringIO
        from unittest import mock
        with mock.patch("sys.stdout", new=StringIO()) as out:
            cli.main([argv[0], "--json", "--personal", str(self.wiki), *argv[1:]])
        return json.loads(out.getvalue())

    # ---- personal capture rules ----

    def test_personal_capture_rules_reach_capture_and_review_but_not_promotion(self):
        folder = self.base / ".wiki"
        (folder / "prompts").mkdir(parents=True)
        (folder / "prompts" / "personal-capture-rules.md").write_text(f"<!-- a comment that is not sent -->\n{RULES}\n", encoding="utf-8")
        os.environ["WIKIAPP_DATA_DIR"] = str(folder)
        self.capture_note(self.note(), capture())
        self.assertIn(RULES, self.last_prompt())
        self.assertIn("## The analyst's own capture rules", self.last_prompt())
        self.assertNotIn("a comment that is not sent", self.last_prompt())
        self.capture_session(capture(entry="From a session"))
        self.assertIn(RULES, self.last_prompt())
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss", "conflicts": []})
        review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertIn(RULES, self.last_prompt("wiki-reviewer"))
        # Promotion (the team wiki manager, in ingest/) is never sent them.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingest"))
        import prompts as ingest_prompts

        class Wikis:
            aliases = ["team"]
            roots = {"team": self.base / "team"}

            def rules_text(self, alias):
                return "Team rules."
        with mock.patch.object(ingest_prompts.pathlist, "wiki_role_for_root", return_value="team"):   # the team wiki
            instructions = ingest_prompts.write_instructions(Wikis(), ingest_prompts.agent_prompt("team-wiki-manager"), TODAY)
        first = ingest_prompts.pathlist.read_prompt("prompt.promotion-first-message", date=TODAY)
        self.assertIn("Team rules.", instructions)
        self.assertNotIn(RULES, instructions + first)

    # ---- links between topics ----

    def two_topics(self, entry="Pricing and stop loss together"):
        """One capture filed under two topics: stop-loss-analytics and pricing-model."""
        data = capture(entry=entry)
        data["topics"].append({"slug": "pricing-model", "title": "Pricing model", "summary": "How prices are set",
                               "tags": ["pricing"], "entry": "Pricing side of it", "supersedes": False})
        return self.capture_note(self.note(), data)

    def test_log_entries_name_the_other_topics(self):
        result = self.two_topics()
        stem = Path(result["note"]).stem
        self.assertIn(f"([[{stem}]]) — also touches [[pricing-model]]", self.log())
        self.assertIn(f"([[{stem}]]) — also touches [[stop-loss-analytics]]", self.log("pricing-model"))
        self.assertEqual(wiki.log_source(self.log().splitlines()[0]), "note")
        self.capture_session(capture(entry="Only stop loss"))
        alone = next(line for line in self.log().splitlines() if "Only stop loss" in line)
        self.assertNotIn("also touches", alone)                              # nothing else to name

    def test_related_is_rebuilt_on_every_review(self):
        self.two_topics()
        self.capture_session(capture(slug="claims-lag", entry="Lag report", title="Lag"))   # shares the stop-loss tag
        page = wiki.find_topic(self.wiki, "stop-loss-analytics")
        old = page.read_text(encoding="utf-8")                                # a page from before Related existed
        page.write_text(old.replace("## Related\n" + wiki.NO_RELATED + "\n\n", ""), encoding="utf-8")
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss", "related": [
            {"topic": "pricing-model", "why": "Prices depend on the attachment point"},
            {"topic": "claims-lag", "why": "Same stop loss data"},
            {"topic": "ghost-topic", "why": "Not a real page"},
            {"topic": "stop-loss-analytics", "why": "Itself"}]})
        result = review.review_topic(self.cfg, "stop-loss-analytics")
        prompt = self.last_prompt("wiki-reviewer")
        self.assertIn("- [[pricing-model]] — filed together 1 time", prompt)
        self.assertIn("- [[claims-lag]] — shares tags: stop-loss", prompt)
        body = self.page()[1]
        related = wiki.get_zone(body, "related")
        self.assertEqual(related, "- [[pricing-model]] — Prices depend on the attachment point\n- [[claims-lag]] — Same stop loss data")
        self.assertLess(body.index("## Current state"), body.index("## Related"))
        self.assertLess(body.index("## Related"), body.index("## Notes"))
        self.assertEqual([r["topic"] for r in result["related"]], ["pricing-model", "claims-lag"])
        # The next review no longer supports one link: it is gone, not kept.
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss",
                                     "related": [{"topic": "claims-lag", "why": "Same stop loss data"}]})
        review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(wiki.get_zone(self.page()[1], "related"), "- [[claims-lag]] — Same stop loss data")

    def test_notes_section_links_are_candidates_and_never_touched(self):
        self.two_topics()
        page = wiki.find_topic(self.wiki, "stop-loss-analytics")
        page.write_text(page.read_text(encoding="utf-8").replace("## Notes\n", "## Notes\nSee [[pricing-model]] and [[no-such-page]].\n"), encoding="utf-8")
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss"})
        review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertIn("linked in the analyst's own notes", self.last_prompt("wiki-reviewer"))
        self.assertIn("See [[pricing-model]] and [[no-such-page]].", wiki.get_zone(self.page()[1], "notes"))

    def test_links_to_topics_that_dont_exist_are_removed(self):
        self.two_topics()
        self.model("wiki-reviewer", {"state_markdown": "Priced by [[pricing-model]]; see [[ghost-topic]] and [[old page|the old page]].",
                                     "summary": "Stop loss, see [[ghost-topic]]"})
        result = review.review_topic(self.cfg, "stop-loss-analytics")
        state = self.state()
        self.assertIn("Priced by [[pricing-model]]; see ghost-topic and the old page.", state)
        self.assertEqual(self.page()[0]["summary"], "Stop loss, see ghost-topic")
        self.assertTrue(any("ghost-topic" in w for w in result["warnings"]))
        self.assertIn("## Existing topics", self.last_prompt("wiki-reviewer"))

    def test_topics_have_no_kind(self):
        self.capture_session(capture())
        self.assertNotIn("kind", self.page()[0])
        self.assertNotIn('"kind"', json.dumps(__import__("secondbrain.prompts", fromlist=["x"]).CAPTURE_SCHEMA))

    # ---- tags ----

    def use_reference(self, text="| Tag | Meaning |\n|---|---|\n| stop-loss | Stop loss insurance work |\n| Client | A customer we serve |\n"):
        """A team's tag list, pointed at through the path list (tag_list_reference)."""
        folder = self.base / ".wiki"
        folder.mkdir(exist_ok=True)
        os.environ["WIKIAPP_DATA_DIR"] = str(folder)
        team = self.base / "team" / "Tags.md"
        team.parent.mkdir(exist_ok=True)
        team.write_bytes(text.encode("utf-8"))
        config.pathlist.set_path("tag_list_reference", str(team))
        return team

    def personal_tags(self):
        return self.wiki / "personal-tags.md"

    def test_tag_files_reach_all_four_prompts_but_not_promotion(self):
        self.use_reference("TEAM-TAGS-MARKER\n- client — a customer\n")
        self.personal_tags().write_text("MY-TAGS-MARKER, written my own way\n", encoding="utf-8")
        self.two_topics()
        self.capture_session(capture())
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss"},
                   {"topic_merges": [], "tag_merges": []})
        review.review_topic(self.cfg, "stop-loss-analytics")
        review.suggest_merges(self.cfg)
        prompts_seen = [*self.prompts["executive-assistant"], *self.prompts["wiki-reviewer"]]
        self.assertEqual(len(prompts_seen), 4)                               # note capture, session capture, review, merges
        for prompt in prompts_seen:
            self.assertIn("## Reference tag list (the team's, as written; read only)\n\nTEAM-TAGS-MARKER", prompt)
            self.assertIn("## Your personal tags (as written)\n\nMY-TAGS-MARKER, written my own way", prompt)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingest"))
        import prompts as ingest_prompts

        class Wikis:
            aliases = ["team"]

            def rules_text(self, alias):
                return "Team rules."
        promotion = (ingest_prompts.write_instructions(Wikis(), ingest_prompts.agent_prompt("team-wiki-manager"), TODAY)
                     + ingest_prompts.pathlist.read_prompt("prompt.promotion-first-message", date=TODAY))
        self.assertNotIn("TEAM-TAGS-MARKER", promotion)
        self.assertNotIn("MY-TAGS-MARKER", promotion)

    def test_personal_tags_file_is_made_only_when_a_tag_is_added(self):
        self.capture_session(capture())
        self.assertFalse(self.personal_tags().exists())
        data = capture(slug="pricing-model", title="Pricing")
        data["topics"][0]["tags"] = ["pricing-approach"]
        data["new_tags"] = [{"tag": "pricing-approach", "description": "how a product is priced for clients"}]
        result = self.capture_note(self.note(), data)
        self.assertEqual(result["new_tags"], [{"tag": "pricing-approach", "description": "how a product is priced for clients"}])
        text = self.personal_tags().read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\npricing-approach — how a product is priced for clients\n"))
        self.assertEqual(result["topics"][0]["tags"], ["pricing-approach"])
        self.assertEqual(result["topics"][0]["personal_tags"], ["pricing-approach"])   # no reference list: all personal

    def test_new_tags_are_appended_without_touching_what_is_there(self):
        mine = "My own words about tags.\n\n* weird-format :: whatever I like, far more than eight words long here\n"
        self.personal_tags().write_text(mine, encoding="utf-8")
        data = capture()
        data["topics"][0]["tags"] = ["stop-loss", "renewals"]
        data["new_tags"] = [{"tag": "renewals", "description": "yearly contract renewal work"}]
        result = self.capture_session(data)
        text = self.personal_tags().read_text(encoding="utf-8")
        self.assertTrue(text.startswith(mine))                               # the person's text, byte for byte; the new line follows its bullet style
        self.assertEqual(text[len(mine):], "* renewals — yearly contract renewal work\n")
        self.assertFalse(any("eight" in w or "8 words" in w for w in result["warnings"]))   # hand-written text isn't checked

    def test_a_new_tag_with_a_long_description_is_refused(self):
        data = capture()
        data["topics"][0]["tags"] = ["stop-loss", "verbose-tag"]
        data["new_tags"] = [{"tag": "verbose-tag", "description": "one two three four five six seven eight nine"}]
        result = self.capture_session(data)
        self.assertFalse(self.personal_tags().exists())
        self.assertEqual(result["new_tags"], [])
        self.assertNotIn("verbose-tag", self.page()[0]["tags"])
        self.assertTrue(any("verbose-tag" in w and "1 to 8 words" in w for w in result["warnings"]))
        # The reviewer is held to the same rule.
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss", "tags": ["stop-loss", "long-one"],
                                     "new_tags": [{"tag": "long-one", "description": "a b c d e f g h i"}]})
        reviewed = review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(reviewed["tags"], ["stop-loss"])
        self.assertFalse(self.personal_tags().exists())

    def test_review_tags_prefer_the_reference_list(self):
        self.use_reference()
        self.capture_session(capture())
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss", "tags": ["stop-loss", "client", "pricing-tier"],
                                     "new_tags": [{"tag": "pricing-tier", "description": "a band of prices for a product"}]})
        result = review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(result["tags"], ["stop-loss", "client", "pricing-tier"])
        self.assertEqual(result["personal_tags"], ["pricing-tier"])
        self.assertEqual([n["tag"] for n in result["new_tags"]], ["pricing-tier"])
        self.assertIn("pricing-tier — a band of prices for a product", self.personal_tags().read_text(encoding="utf-8"))
        listed = {t["slug"]: t["personal_tags"] for t in review.list_topics(self.cfg)}
        self.assertEqual(listed["stop-loss-analytics"], ["pricing-tier"])

    def test_reference_names_are_picked_leniently_and_never_required(self):
        team = self.use_reference("Our team uses a handful of labels, agreed in March.\nNothing here is a list at all\n")
        result = self.capture_session(capture())
        self.assertEqual(result["status"], "ingested")                      # nothing fails on the format
        self.assertTrue(any("No tag names could be picked out" in w for w in result["warnings"]))
        team.write_bytes("# Team tags\n\n#client #stop-loss\n- `Renewals`: yearly renewals\n".encode("utf-8"))
        tagset = __import__("secondbrain.tags", fromlist=["x"]).TagSet(self.wiki)
        self.assertEqual(sorted(tagset.reference.values()), ["client", "renewals", "stop-loss"])
        self.personal_tags().write_text("client — someone we work for\nbespoke — mine only\n", encoding="utf-8")
        tagset = __import__("secondbrain.tags", fromlist=["x"]).TagSet(self.wiki)
        self.assertTrue(any("'client' is also in the reference tag list" in w for w in tagset.warnings))
        self.assertEqual(tagset.personal_only(["client", "bespoke", "stop-loss"]), ["bespoke"])

    def test_the_reference_list_is_never_written(self):
        team = self.use_reference()
        before = team.read_bytes()
        self.personal_tags().write_text("renewals — yearly renewals\n", encoding="utf-8")
        data = capture()
        data["topics"][0]["tags"] = ["stop-loss", "renewals", "brand-new"]
        data["new_tags"] = [{"tag": "brand-new", "description": "a tag nobody had"}, {"tag": "client", "description": "dup of a reference tag"}]
        self.capture_session(data)
        self.assertEqual(team.read_bytes(), before)
        self.two_topics()
        self.assertEqual(team.read_bytes(), before)
        self.model("wiki-reviewer", {"state_markdown": "Quarterly.", "summary": "Stop loss", "tags": ["stop-loss", "another"],
                                     "new_tags": [{"tag": "another", "description": "yet another tag"}]})
        review.review_topic(self.cfg, "stop-loss-analytics")
        self.assertEqual(team.read_bytes(), before)
        self.model("wiki-reviewer", {"topic_merges": [], "tag_merges": [
            {"keep": "renewals", "merge": ["stop-loss"], "reason": "Would merge away a reference tag"},
            {"keep": "stop-loss", "merge": ["another"], "reason": "Same subject"}]})
        suggestions = review.suggest_merges(self.cfg)
        self.assertEqual([(s["keep"], s["merge"]) for s in suggestions if s["kind"] == "tag"], [("stop-loss", ["another"])])
        self.assertEqual(team.read_bytes(), before)
        with self.assertRaises(wiki.WikiError):
            wiki.merge_tags(self.wiki, "renewals", ["stop-loss"])          # a reference tag can't be merged away
        result = wiki.merge_tags(self.wiki, "stop-loss", ["another"])
        self.assertTrue(result["personal_tags_changed"])
        self.assertNotIn("another", self.personal_tags().read_text(encoding="utf-8"))
        self.assertNotIn("another", self.page()[0]["tags"])
        self.assertEqual(team.read_bytes(), before)
        with self.assertRaises(ValueError):
            config.pathlist.write_file("tag_list_reference", "overwrite")  # not even through the Paths window
        self.assertEqual(team.read_bytes(), before)

    def test_a_merge_renames_a_personal_tag_line_when_the_kept_tag_is_unlisted(self):
        self.personal_tags().write_text("Some intro.\n- old-name — a thing I track\nother — kept\n", encoding="utf-8")
        data = capture()
        data["topics"][0]["tags"] = ["old-name"]
        self.capture_session(data)
        wiki.merge_tags(self.wiki, "new-name", ["old-name"])
        self.assertEqual(self.personal_tags().read_text(encoding="utf-8"), "Some intro.\n- new-name — a thing I track\nother — kept\n")

    def test_a_new_tag_follows_the_files_bullet_style(self):
        for text, expect in (("- one — a\n- two — b\n", "- three — c\n"), ("* one — a\n", "* three — c\n"),
                             ("one — a\ntwo — b\n", "three — c\n"), ("Intro\n- one — a", "- three — c\n")):
            target = self.personal_tags()
            target.write_text(text, encoding="utf-8")
            tags.add_personal(self.wiki, [{"tag": "three", "description": "c"}])
            written = target.read_text(encoding="utf-8")
            self.assertTrue(written.startswith(text), text)                  # existing content untouched
            self.assertTrue(written.endswith(expect), (text, written))

    def test_a_log_line_does_not_repeat_the_date_the_entry_starts_with(self):
        path = self.note(text=f"---\ndate: {TODAY}\n---\nAgreed stop loss is reported quarterly.\n")
        self.capture_note(path, capture(entry=f"{TODAY}: Set the rule"))
        line = self.log().splitlines()[0]
        self.assertTrue(line.startswith(f"- {TODAY} [note] — Set the rule ("), line)

    def test_install_works_without_the_retired_note_taker(self):
        args = type("A", (), {"dest": str(self.base / "claude"), "force": False, "json": True})()
        cli.cmd_install(self.cfg, args)
        self.assertTrue((self.base / "claude" / "skills" / "executive-assistant" / "SKILL.md").is_file())
        self.assertFalse((self.base / "claude" / "skills" / "note-taker").exists())

    # ---- legacy notes ----

    def test_notes_from_the_old_flow_count_as_captured(self):
        path = self.note(text="---\ningested: 2026-01-05\n---\nAn old note.\n")
        status = ingest.note_status(self.cfg, str(path))
        self.assertEqual((status["status"], status["legacy"]), ("captured", True))
        result = self.capture_note(path, capture())                          # chosen deliberately: captured
        self.assertEqual(result["status"], "ingested")
        status = ingest.note_status(self.cfg, str(path))
        self.assertEqual((status["status"], status["legacy"]), ("captured", False))

    # ---- progress folder ----

    def test_progress_moves_to_the_progress_folder_and_old_data_is_copied(self):
        old = self.wiki / ".sb"
        old.mkdir(exist_ok=True)
        (old / "ledger.json").write_text(json.dumps({"abc": {"status": "skipped"}}), encoding="utf-8")
        (old / "spend.json").write_text(json.dumps({"capture": {"calls": 7}}), encoding="utf-8")
        folder = self.base / ".wiki"
        folder.mkdir()
        os.environ["WIKIAPP_DATA_DIR"] = str(folder)
        target = wiki.state_dir(self.wiki)
        self.assertEqual(target, folder / "progress" / "personal")
        self.assertEqual(wiki.load_ledger(self.wiki), {"abc": {"status": "skipped"}})
        self.assertTrue((target / wiki.COPIED_MARK).exists())
        self.assertTrue((old / "ledger.json").exists())                      # nothing deleted
        self.capture_session(capture())
        self.assertIn(SID, json.loads((target / "ledger.json").read_text(encoding="utf-8")))
        self.assertNotIn(SID, json.loads((old / "ledger.json").read_text(encoding="utf-8")))
        self.assertEqual(wiki.load_spend(self.wiki)["capture"]["calls"], 8)
        (target / "ledger.json").unlink()                                    # copied once only
        self.assertEqual(wiki.load_ledger(self.wiki), {})


class NoRawCallsTest(unittest.TestCase):
    def test_no_claude_subprocess_or_raw_sdk_in_sessions(self):
        package = Path(__file__).resolve().parent.parent / "secondbrain"
        for path in package.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("claude_agent_sdk", text, path.name)
            self.assertNotIn("subprocess", text, path.name)


if __name__ == "__main__":
    unittest.main()
