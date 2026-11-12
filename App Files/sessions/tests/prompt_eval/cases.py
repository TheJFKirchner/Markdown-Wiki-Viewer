"""The prompt evaluation's fixtures and expectations. All content is invented.

Each case is designed to tempt one known failure of the capture, review or promotion prompts.
A case says what it runs (a note or session capture, a topic review, a chain of captures then a
review, or a Promotion run), the material, and its expectations: (name, check) pairs, where
check(result) returns (passed, detail). run_eval.py builds the workspace and runs them.
"""
from __future__ import annotations

import json
import re

TODAY = "2026-11-12"

# ---- the wiki every case starts from ------------------------------------------------------------

REFERENCE_TAGS = """# Team tags (reference list, kept by the team lead)

| Tag | Meaning |
|---|---|
| dashboard | A recurring report or dashboard |
| forecasting | Forecast models and their accuracy |
| customer-metrics | Churn, retention and lifetime value |
| data-quality | Known problems in source data |
| pricing | Prices, price tests and discounts |
| client | A client we deliver work for |
"""

PERSONAL_TAGS = """---
type: tag-list
---
# My tags

wholesale — wholesale buyers and their accounts
"""

CAPTURE_RULES = """<!-- My rules for the personal wiki. -->
- Give every client its own page (a topic named after the client), and link the work done for that client to it.
- Keep metric definitions (what a number means) on the topic they belong to.
"""

# slug -> (title, tags, summary). Pages made before any case runs.
BASE_TOPICS = {
    "churn-dashboard": ("Churn dashboard", ["dashboard", "customer-metrics"],
                        "Weekly customer churn dashboard built on the orders mart."),
    "harbor-lane-grocers": ("Harbor Lane Grocers", ["client", "wholesale"],
                            "Wholesale client buying the outdoor range; monthly returns forecast."),
    "returns-forecast": ("Returns forecast", ["forecasting"],
                         "The monthly product returns forecast and how it is built."),
}
CLIENT_SLUG_WORDS = ("harbor", "northgate", "kestrel", "ridgeway", "brightwater", "skyline")

TEAM_PAGES = {
    "Products/Returns forecast.md":
        "---\ntitle: Returns forecast\ndescription: The monthly product returns forecast.\ntags: [forecasting]\n---\n"
        "# Returns forecast\n\nForecasts product returns by month for planning.\n\n## Method\n\nNot yet chosen.\n",
    "Products/Churn dashboard.md":
        "---\ntitle: Churn dashboard\ndescription: The weekly customer churn dashboard and how churn is defined.\n"
        "tags: [dashboard, customer-metrics]\n---\n# Churn dashboard\n\nA weekly dashboard of customer churn.\n\n"
        "## Definition\n\nTo be confirmed.\n",
}
TEAM_RULES = ("# Team wiki rules\n\n- One page per product or metric. Pages start with frontmatter: title, description, tags.\n"
              "- Write for a new analyst: short, plain, no first person.\n- Never copy customer-level data.\n")


# ---- transcripts ---------------------------------------------------------------------------------

def _line(sid, cwd, kind, ts, content, **extra):
    return json.dumps({"sessionId": sid, "cwd": cwd, "isSidechain": False, "entrypoint": "cli", "type": kind,
                       "timestamp": ts, "message": {"role": kind, "content": content}, **extra})


def transcript(sid: str, cwd: str, day: str, turns: list, title: str) -> str:
    """turns: ("user", text) | ("assistant", text, [tool uses]) | ("result", tool id, text) |
    ("launched", tool id): a subagent started in the background (its report comes later) |
    ("notify", tool id, summary, report): that report, as Claude Code delivers it.
    An Agent tool use answered by ("result", ...) is a subagent that reported in the foreground."""
    out = []
    for i, turn in enumerate(turns):
        ts = f"{day}T10:{i:02d}:00Z"
        if turn[0] == "user":
            out.append(_line(sid, cwd, "user", ts, turn[1]))
        elif turn[0] == "assistant":
            content = [{"type": "text", "text": turn[1]}]
            for j, (name, inp) in enumerate(turn[2] if len(turn) > 2 else []):
                content.append({"type": "tool_use", "id": f"t{i}-{j}", "name": name, "input": inp})
            out.append(_line(sid, cwd, "assistant", ts, content))
        elif turn[0] == "launched":
            out.append(_line(sid, cwd, "user", ts, [{"type": "tool_result", "tool_use_id": turn[1], "content": "Async agent launched successfully."}],
                             toolUseResult={"status": "async_launched", "isAsync": True, "agentId": f"a{i}"}))
        elif turn[0] == "notify":
            text = (f"<task-notification>\n<task-id>b{i}</task-id>\n<tool-use-id>{turn[1]}</tool-use-id>\n<status>completed</status>\n"
                    f"<summary>{turn[2]}</summary>\n<result>{turn[3]}</result>\n</task-notification>")
            out.append(_line(sid, cwd, "user", ts, text, origin={"kind": "task-notification"}))
        else:
            out.append(_line(sid, cwd, "user", ts, [{"type": "tool_result", "tool_use_id": turn[1], "content": turn[2]}]))
    out.append(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": sid}))
    return "\n".join(out) + "\n"


SESSIONS = {}

# The session from the first live run: the folder it ran in names a made-up company, Claude
# reports query figures and explains a mechanism, the analyst corrects it, confirms only the cause,
# states the churn definition, and declines an unconfirmed suggestion.
SESSIONS["churn-jump"] = ("a1b2c3d4-1111-4aaa-8bbb-000000000001", "C:\\work\\brightwater\\churn", "2026-11-10", [
    ("user", "Can you look at why the churn numbers on the dashboard jumped last week?"),
    ("assistant", "I'll query the orders mart and compare last week's churned customers with the week before.",
     [("Bash", {"command": "sqlcmd -Q \"select week, count(*) from churn_weekly where region = 'NORTH' group by week\""})]),
    ("result", "t1-0", "2026-W44 1830\n2026-W45 2410"),
    ("assistant", "Churned customers went from 1,830 in W44 to 2,410 in W45, a 31.7% rise. The query returned 2,410 rows for W45 and the North region alone accounts for 640 of them. "
                  "My explanation: this is most likely caused by the loyalty-programme migration, which reset last-purchase dates for some customers, so they look inactive."),
    ("user", "No, that's wrong - the dashboard doesn't read last-purchase dates from the loyalty system at all. It reads them from the orders mart. Look somewhere else."),
    ("assistant", "Understood, the dashboard takes last-purchase dates from the orders mart, not the loyalty system. Let me check the orders mart load log.",
     [("Bash", {"command": "python check_loads.py --table orders_mart --since 2026-11-01"})]),
    ("result", "t5-0", "2026-11-03 load: 0 rows (failed)\n2026-11-04 load: 51230 rows"),
    ("assistant", "The 2026-11-03 load of the orders mart failed and loaded 0 rows; it was re-run on 11-04. Customers whose only purchase that week was on 11-03 would look churned when the dashboard refreshed on Monday 11-03. That fits the jump. Shall I treat the failed load as the cause?"),
    ("user", "Yes, confirmed - the failed Monday load is the cause. I checked with the data engineering team and they saw the same thing. Also, for the record: we define churn as 60 days with no purchase now, the retention lead changed it last month."),
    ("assistant", "Noted: the jump was caused by the failed 2026-11-03 orders mart load, and churn is now 60 days without a purchase. One more thought, unconfirmed: the Monday 06:00 refresh may be too early for the load, which often finishes around 06:30, so moving the refresh to 08:00 might avoid this. Want me to draft that?"),
    ("user", "Not now, thanks."),
], "Churn jump investigation")

# Incidental names in the working folder and in file paths the assistant read; the analyst
# corrects one thing and states one preference.
SESSIONS["price-test"] = ("b2c3d4e5-2222-4bbb-8ccc-000000000002", "C:\\work\\kestrel\\pricing-sandbox", "2026-11-11", [
    ("user", "Help me set up the analysis for the 2-person tent price test. Control is list price, test is 5% off."),
    ("assistant", "I'll look at the price list and the store split first.",
     [("Read", {"file_path": "C:\\work\\kestrel\\pricing-sandbox\\clients\\ridgeway\\price_list.csv"}),
      ("Read", {"file_path": "C:\\work\\kestrel\\pricing-sandbox\\store_split.sql"})]),
    ("assistant", "The price list has 214 SKUs and the split assigns 61 stores to test. I've assumed the test runs 6 weeks and the success metric is units sold per store-week."),
    ("user", "No, the test runs 4 weeks, not 6. And we judge it on gross margin per store-week, not units: a discount always lifts units."),
    ("assistant", "Got it: 4 weeks, judged on gross margin per store-week. I'll write the margin query. I'd also suggest a CUPED adjustment using last year's margin to reduce variance."),
    ("user", "Write the margin query for now."),
    ("assistant", "Done, the query is in margin_by_store_week.sql.",
     [("Write", {"file_path": "C:\\work\\kestrel\\pricing-sandbox\\margin_by_store_week.sql", "content": "select ..."})]),
], "Tent price test setup")

# The analyst confirms the cause only; Claude's surrounding explanation is not confirmed.
SESSIONS["renewals-drop"] = ("c3d4e5f6-3333-4ccc-8ddd-000000000003", "C:\\work\\analytics\\renewals", "2026-11-09", [
    ("user", "The renewal rate on the subscriptions report fell this month. Can you find out why?"),
    ("assistant", "Checking the CRM export against the billing table.",
     [("Bash", {"command": "python compare_exports.py --month 2026-10"})]),
    ("result", "t1-0", "crm rows 18422, billing rows 17010, duplicates 1412"),
    ("assistant", "The CRM export has 1,412 duplicated cancellation rows. My reading: each cancelled account is exported twice, which inflates the denominator and drags the renewal rate down by about 2.3 points. "
                  "That would also explain why the drop is concentrated in annual plans, since annual plans are exported in a separate overnight batch that runs twice. Is the duplication the cause?"),
    ("user", "Yes - the duplicated cancellations in the CRM export are the cause. Good catch."),
    ("assistant", "Great. Shall I add a de-duplication step to the report's load script?"),
    ("user", "I'll raise it with the CRM team first."),
], "Renewal rate drop")

# A substantial-looking session in which the analyst states, corrects and confirms nothing.
SESSIONS["basket-figures"] = ("d4e5f6a7-4444-4ddd-8eee-000000000004", "C:\\work\\analytics\\baskets", "2026-11-08", [
    ("user", "What's the average basket size this month compared with last month?"),
    ("assistant", "Running the basket query.", [("Bash", {"command": "python basket.py --months 2"})]),
    ("result", "t1-0", "2026-10 avg 45.78 n=12511\n2026-11 avg 47.20 n=12904"),
    ("assistant", "Average basket is 47.20 this month against 45.78 last month, up 3.1%, over 12,904 orders. The rise is probably driven by the autumn camping promotion, which bundles stoves with fuel."),
    ("user", "And by region?"),
    ("assistant", "North 51.10, South 44.95, West 46.30. North leads, likely because of colder weather pushing heavier gear."),
    ("user", "ok thanks"),
], "Basket size check")

# Claude explains a general concept; the analyst only acknowledges it.
SESSIONS["mape-explainer"] = ("e5f6a7b8-5555-4eee-8fff-000000000005", "C:\\work\\analytics\\forecasts", "2026-11-07", [
    ("user", "What's the difference between MAPE and WAPE?"),
    ("assistant", "MAPE averages the absolute percentage error of each period, so small-volume periods can dominate it. WAPE divides the total absolute error by total actuals, so it weights periods by volume. For intermittent demand WAPE is usually the safer choice, and many teams report both."),
    ("user", "makes sense, thanks"),
], "MAPE vs WAPE")

# The analyst states one fact and mentions two things they still have to do.
SESSIONS["todo-talk"] = ("f6a7b8c9-6666-4fff-8aaa-000000000006", "C:\\work\\analytics\\churn", "2026-11-11", [
    ("user", "Can you check the churn dashboard query still filters out test accounts?"),
    ("assistant", "Yes, the query excludes accounts flagged is_test = 1 in the customer table.",
     [("Read", {"file_path": "C:\\work\\analytics\\churn\\churn_weekly.sql"})]),
    ("user", "Good. For the record, test accounts must always be excluded from churn, that's a hard rule. "
             "I need to send the churn summary to the retention lead by Friday, and next week I'll rerun the W45 backfill."),
    ("assistant", "Understood. Want me to draft the summary?"),
    ("user", "No, I'll write it myself."),
], "Churn test-account check")

# Subagents: the assistant hands work to a helper, whose report comes back into the session. A
# report is the assistant's side: captured only when the analyst confirms it.
SESSIONS["subagent-confirmed"] = ("a7b8c9d0-7777-4aaa-8bbb-000000000007", "C:\\work\\analytics\\renewals", "2026-11-11", [
    ("user", "The CRM export and the billing table disagree on active subscriptions. Find out why."),
    ("assistant", "I'll have a helper compare the two sources.",
     [("Agent", {"description": "Compare CRM and billing", "subagent_type": "general-purpose",
                 "prompt": "Compare active subscriptions in the CRM export with the billing table and explain the gap."})]),
    ("result", "t1-0", "The billing table leaves out accounts still in their free trial, while the CRM export includes them. "
                       "That accounts for the whole gap: 1,212 trial accounts."),
    ("assistant", "The helper found that billing leaves out free-trial accounts and the CRM export includes them. Is that the explanation?"),
    ("user", "Yes, confirmed - billing excludes free-trial accounts. That's the difference."),
], "CRM vs billing subscriptions")

SESSIONS["subagent-ignored"] = ("b8c9d0e1-8888-4bbb-8ccc-000000000008", "C:\\work\\analytics\\sellthrough", "2026-11-11", [
    ("user", "Set up the weekly sell-through report for the camping range. For the record, we report sell-through weekly, Monday to Sunday."),
    ("assistant", "Noted: weekly, Monday to Sunday. I'll have a helper check the source table in the background while I draft the query.",
     [("Agent", {"description": "Audit store_sales table", "subagent_type": "Explore", "run_in_background": True,
                 "prompt": "Check the store_sales table for data problems in October."})]),
    ("launched", "t1-0"),
    ("assistant", "Drafting the sell-through query now.", [("Write", {"file_path": "C:\\work\\analytics\\sellthrough\\sellthrough.sql", "content": "select ..."})]),
    ("notify", "t1-0", 'Agent "Audit store_sales table" completed',
     "store_sales double-counts returns in October, so the October total is overstated by about 4.2%."),
    ("assistant", "The helper reports that store_sales double-counts returns in October, overstating the total by about 4.2%. The query is in sellthrough.sql."),
    ("user", "Thanks, that's enough for today."),
], "Sell-through report setup")

SESSIONS["subagent-instructions"] = ("c9d0e1f2-9999-4ccc-8ddd-000000000009", "C:\\work\\analytics\\margins", "2026-11-12", [
    ("user", "I need the gross margin by product line for the quarterly review. Margin is always net of returns, by the way."),
    ("assistant", "Understood, net of returns. I'll ask a helper to build the margin table.",
     [("Agent", {"description": "Build margin table", "subagent_type": "general-purpose",
                 "prompt": "Build gross margin by product line. The fiscal year starts in April, and wholesale accounts are excluded "
                           "from all margin figures. Margin is net of returns."})]),
    ("result", "t1-0", "Built the margin table by product line in margin_by_line.sql, net of returns, for the last quarter."),
    ("assistant", "The margin table is ready in margin_by_line.sql."),
    ("user", "Great, thanks."),
], "Margin by product line")

# ---- notes ---------------------------------------------------------------------------------------

NOTES = {
    # The first run's note: numbers, an ownership line and a checkbox task.
    "churn-sync": ("2026-11-05 Churn dashboard.md",
                   "---\ntitle: Churn dashboard sync\ncreated: 2026-11-05\n---\n# Churn dashboard sync\n\n"
                   "- The churn dashboard refreshes every Monday at 06:00 from the orders mart.\n"
                   "- Churn definition agreed with the retention lead: a customer has churned after **90 days** with no purchase.\n"
                   "- Dashboard owner is me; the retention lead signs off changes.\n"
                   "- [ ] Add a churn-by-region tab\n"),
    # Numbers to keep, and a checkbox task that must not be copied into decisions, findings or open questions.
    "churn-segments": ("2026-11-11 Churn segments.md",
                       "---\ntitle: Churn segments\ncreated: 2026-11-11\n---\n# Churn segments\n\n"
                       "- Split churners into 4 segments on the churn dashboard. SMB accounts are 38% of churners but only 12% of revenue lost.\n"
                       "- Decided to show revenue lost next to churner counts, because counts alone overstate SMB.\n"
                       "- [ ] Add a churn-by-region tab due:2026-11-20\n"),
    # A method that applies to every customer, written while working for one client; an existing
    # general topic (returns-forecast) fits it.
    "holdout-method": ("2026-11-10 Harbor Lane forecast review.md",
                       "---\ntitle: Harbor Lane forecast review\ncreated: 2026-11-10\n---\n# Harbor Lane forecast review\n\n"
                       "Went through the November returns forecast with Harbor Lane's planning team. They were happy: MAPE 10.8% on their range.\n\n"
                       "- The first backtest overfit, so from now on we hold out the last 3 months when backtesting any returns forecast, for every customer, not just Harbor Lane.\n"
                       "- Harbor Lane want the forecast split by store cluster from January.\n"),
    # A new client, and a check that applies to every client's files; no general topic exists yet.
    "delivery-check": ("2026-11-06 Northgate Supply kickoff.md",
                       "---\ntitle: Northgate Supply kickoff\ncreated: 2026-11-06\n---\n# Northgate Supply kickoff\n\n"
                       "New client: Northgate Supply, a regional chain buying our camping range. They want a weekly sell-through report.\n\n"
                       "- Their delivery files are CSV with a trailing summary row, which inflated row counts by one per file.\n"
                       "- Going forward I'll run a row-count reconciliation on every client's delivery file before loading it, whichever client it is. Northgate is just where it bit us.\n"),
    # Checkbox to-dos mixed with knowledge: the knowledge is captured, the to-dos appear nowhere.
    "mixed-todos": ("2026-11-12 Returns forecast notes.md",
                    "---\ntitle: Returns forecast notes\ncreated: 2026-11-12\n---\n# Returns forecast notes\n\n"
                    "- [ ] Email the planning team the December forecast\n"
                    "- Returns spike every January after the holiday season; the seasonal-naive model already captures it.\n"
                    "- [x] Fix the store-cluster mapping file\n"
                    "- The store-cluster mapping lives in the planning share and changes every quarter.\n"
                    "- [/] Write up the holdout method for the team\n"
                    "- Need to book a review with finance before the 20th.\n"),
    # A vendor named in passing: not a client, and not worth a page.
    "weather-trial": ("2026-11-04 Weather feed trial.md",
                      "---\ntitle: Weather feed trial\ncreated: 2026-11-04\n---\n# Weather feed trial\n\n"
                      "Trialled the weekly weather feed from Skyline Data (a vendor) as an input to the returns forecast.\n\n"
                      "- Adding temperature did not help: MAPE 11.2% with it, 11.1% without.\n"
                      "- Not worth paying for. Dropping it.\n"),
}

# ---- checks ---------------------------------------------------------------------------------------

DATE_START = re.compile(r"^\s*(\(?\d{4}-\d{2}-\d{2}|on \d{4}|\d{1,2} [A-Z][a-z]+ \d{4})", re.I)
FILING_TALK = re.compile(r"own (topic )?page|topic page|capture rule|\bis [^.?]{1,40} a client\b|needs? (its|a) (own )?(page|topic)", re.I)


def _blob(x) -> str:
    return json.dumps(x, ensure_ascii=False).lower()


def _ext(r):
    return r.get("extraction") or {}


def _record_text(r) -> str:
    """What a capture would write: everything but the topic list's metadata."""
    e = _ext(r)
    keep = {k: e.get(k) for k in ("title", "summary", "decisions", "findings", "open_questions", "data_findings")}
    keep["entries"] = [t.get("entry") for t in e.get("topics") or []]
    return _blob(keep)


def absent(*words, where=_record_text):
    def check(r):
        text = where(r)
        hits = [w for w in words if w.lower() in text]
        return (not hits, f"found {hits}" if hits else "")
    return check


def present(*words, where=_record_text, any_of=True):
    def check(r):
        text = where(r)
        hits = [w for w in words if w.lower() in text]
        ok = bool(hits) if any_of else len(hits) == len(words)
        return (ok, "" if ok else f"none of {list(words)}")
    return check


def worth(expected: bool):
    def check(r):
        got = _ext(r).get("worth_recording")
        if r.get("status") == "skipped":
            got = False
        return (got == expected, f"worth_recording={got} reason={_ext(r).get('skip_reason') or r.get('reason') or ''}")
    return check


def topics_include(slug):
    def check(r):
        slugs = [t["slug"] for t in _ext(r).get("topics") or []]
        return (slug in slugs, f"topics={slugs}")
    return check


def has_non_client_topic(r):
    slugs = [t["slug"] for t in _ext(r).get("topics") or []]
    ok = any(not any(w in s for w in CLIENT_SLUG_WORDS) for s in slugs)
    return (ok, f"topics={slugs}")


def no_topic_named(*words):
    def check(r):
        slugs = [t["slug"] for t in _ext(r).get("topics") or []]
        bad = [s for s in slugs if any(w in s for w in words)]
        return (not bad, f"topics={slugs}")
    return check


def no_dated_entries(r):
    bad = [t.get("entry") for t in _ext(r).get("topics") or [] if DATE_START.match(t.get("entry") or "")]
    return (not bad, f"entries start with a date: {bad}" if bad else "")


def no_filing_questions(r):
    e = _ext(r)
    items = [*(e.get("open_questions") or []), *(e.get("findings") or []), e.get("summary") or ""]
    bad = [x for x in items if FILING_TALK.search(x)]
    return (not bad, f"{bad}" if bad else "")


def tags_from_lists(r):
    """Every tag on a topic comes from the reference list, the personal tags, a tag in use, or is declared new."""
    e = _ext(r)
    known = {"dashboard", "forecasting", "customer-metrics", "data-quality", "pricing", "client", "wholesale"}
    declared = {n.get("tag") for n in e.get("new_tags") or []}
    bad = [t for topic in e.get("topics") or [] for t in topic.get("tags") or [] if t not in known | declared]
    return (not bad, f"undeclared tags {bad}" if bad else "")


def note_task_not_copied(*phrases):
    """No part of what capture would write (summary, decisions, findings, questions, log lines) repeats a to-do."""
    return absent(*phrases)


def wiki_text(r) -> str:
    return (r.get("wiki_text") or "").lower()


CAPTURE_COMMON = [
    ("log line does not start with a date", no_dated_entries),
    ("no questions or content about filing rules", no_filing_questions),
    ("tags come from the lists or are declared new", tags_from_lists),
]

# Review results: {"result": the review's JSON for the topic, "state": Current state without the
# Conflict blocks, "blocks": the Conflict blocks, "tags_before": the topic's tags before the review}


def _state(r) -> str:
    return (r.get("state") or "").lower()


def state_absent(*words):
    return absent(*words, where=_state)


def state_present(*words):
    return present(*words, where=_state)


def no_checkbox_in_state(r):
    bad = [ln for ln in (r.get("state") or "").splitlines() if re.match(r"\s*[-*]\s*\[[ xX/]\]", ln)]
    return (not bad, f"{bad}" if bad else "")


def tags_kept(r):
    before, after = set(r.get("tags_before") or []), set((r.get("result") or {}).get("tags") or [])
    lost = sorted(before - after)
    warned = [w for w in (r.get("result") or {}).get("warnings") or [] if any(t in w for t in lost)]
    ok = not lost or (len(warned) >= 1)
    return (ok, f"lost {lost} (warned: {bool(warned)}); after={sorted(after)}")


def conflict_raised(r):
    n = len((r.get("result") or {}).get("conflicts") or [])
    return (n >= 1, f"{n} conflicts")


def related_have_reasons(r):
    rel = (r.get("result") or {}).get("related") or []
    bad = [x for x in rel if len((x.get("why") or "").split()) < 3]
    return (not bad, f"related={rel}")


def no_filing_in_state(r):
    hits = FILING_TALK.findall(r.get("state") or "")
    return (not hits, f"{hits}" if hits else "")


# ---- the cases -----------------------------------------------------------------------------------

CASES = [
    {"id": "C1", "kind": "session", "source": "churn-jump",
     "tempts": "incidental folder name, query figures, Claude's mechanism, an unconfirmed suggestion",
     "expect": [
         ("worth recording", worth(True)),
         ("attaches to the existing churn-dashboard topic", topics_include("churn-dashboard")),
         ("nothing from the working-folder path (brightwater)", absent("brightwater", where=_blob)),
         ("no query figures (1,830 / 2,410 / 31.7 / 640 / 51230)", absent("1,830", "1830", "2,410", "2410", "31.7", " 640", "51230", "51,230")),
         ("captures the confirmed cause (failed load)", present("fail")),
         ("leaves out Claude's unconfirmed mechanism", absent("only purchase", "look churned", "looked churned", "appeared churned", "appear churned", "would look")),
         ("leaves out the declined suggestion (08:00 / 06:30)", absent("08:00", "06:30", "8:00")),
         ("keeps the analyst's stated definition (60 days)", present("60 days", "60-day")),
         ("keeps the analyst's correction (orders mart, not loyalty)", present("loyalty")),
         *CAPTURE_COMMON]},
    {"id": "C2", "kind": "session", "source": "price-test",
     "tempts": "client-like names in the working folder and in file paths; Claude's numbers and suggestion",
     "expect": [
         ("worth recording", worth(True)),
         ("nothing from folder or file paths (kestrel / ridgeway)", absent("kestrel", "ridgeway", where=_blob)),
         ("no topic for a name in a path", no_topic_named("kestrel", "ridgeway")),
         ("no figures from Claude (214 SKUs / 61 stores)", absent("214", "61 stores")),
         ("keeps the correction (4 weeks)", present("4 weeks", "four weeks", "4-week")),
         ("keeps the stated metric (gross margin)", present("margin")),
         ("leaves out Claude's unconfirmed suggestion (CUPED)", absent("cuped")),
         *CAPTURE_COMMON]},
    {"id": "C3", "kind": "session", "source": "renewals-drop",
     "tempts": "the analyst confirms the cause only; Claude's explanation of how it acts goes further",
     "expect": [
         ("worth recording", worth(True)),
         ("captures the confirmed cause (duplicated cancellations)", present("duplicat")),
         ("leaves out the unconfirmed mechanism (denominator / annual plans / batch)", absent("denominator", "annual", "batch")),
         ("no figures from tool output (1,412 / 18422 / 2.3)", absent("1,412", "1412", "18422", "18,422", "17010", "2.3")),
         *CAPTURE_COMMON]},
    {"id": "C4", "kind": "session", "source": "basket-figures",
     "tempts": "a long session with figures and explanations, and nothing the analyst stated or confirmed",
     "expect": [
         ("not worth recording", worth(False)),
         ("no figures if recorded anyway", absent("47.20", "45.78", "3.1%", "12,904", "12904", "51.10")),
         ("no unconfirmed explanation if recorded anyway", absent("promotion", "weather")),
         *CAPTURE_COMMON]},
    {"id": "C5", "kind": "session", "source": "mape-explainer",
     "tempts": "Claude explains a general concept; the analyst only says it makes sense",
     "expect": [("not worth recording", worth(False)), *CAPTURE_COMMON]},
    {"id": "N1", "kind": "note", "source": "churn-segments",
     "tempts": "numbers to keep; a checkbox task that could be copied into the record",
     "expect": [
         ("worth recording", worth(True)),
         ("attaches to the existing churn-dashboard topic", topics_include("churn-dashboard")),
         ("keeps the note's numbers (38%)", present("38%", "38 %")),
         ("the note's to-do is not copied anywhere in the record", note_task_not_copied("region")),
         *CAPTURE_COMMON]},
    {"id": "N5", "kind": "note", "source": "mixed-todos",
     "tempts": "checkbox to-dos (open, done, in progress) and a plain to-do mixed with knowledge",
     "expect": [
         ("worth recording", worth(True)),
         ("captures the knowledge (January spike, mapping changes quarterly)", present("january", any_of=True)),
         ("captures the second fact (mapping file)", present("quarter")),
         ("no to-do appears anywhere in the record (email / fix / write up / book)",
          note_task_not_copied("email the planning", "fix the store", "write up", "book a review", "finance")),
         *CAPTURE_COMMON]},
    {"id": "C6", "kind": "session", "source": "todo-talk",
     "tempts": "the analyst states a rule and says what they still need to do",
     "expect": [
         ("worth recording", worth(True)),
         ("keeps the stated rule (test accounts excluded)", present("test account")),
         ("the analyst's to-dos are not captured (summary by Friday / rerun backfill)",
          note_task_not_copied("friday", "backfill", "send the churn summary", "draft")),
         *CAPTURE_COMMON]},
    {"id": "S1", "kind": "session", "source": "subagent-confirmed",
     "tempts": "a subagent's finding, relayed by the assistant and confirmed by the analyst",
     "expect": [
         ("worth recording", worth(True)),
         ("captures the confirmed subagent finding (free trials)", present("trial")),
         ("leaves out the subagent's figure the analyst never confirmed (1,212)", absent("1,212", "1212")),
         *CAPTURE_COMMON]},
    {"id": "S2", "kind": "session", "source": "subagent-ignored",
     "tempts": "a background subagent reports a data problem the analyst never acknowledges",
     "expect": [
         ("worth recording (the analyst stated the reporting week)", worth(True)),
         ("keeps the analyst's own statement (weekly, Monday to Sunday)", present("monday", "weekly")),
         ("leaves out the unacknowledged subagent finding (double-counted returns / 4.2%)",
          absent("double", "4.2", "overstat")),
         ("no data finding from the subagent", lambda r: (not any("store_sales" in _blob(f) or "return" in _blob(f)
                                                                   for f in _ext(r).get("data_findings") or []),
                                                          f"data_findings={_ext(r).get('data_findings')}")),
         *CAPTURE_COMMON]},
    {"id": "S3", "kind": "session", "source": "subagent-instructions",
     "tempts": "the assistant's instructions to a subagent state facts the analyst never said",
     "expect": [
         ("worth recording (the analyst stated margin is net of returns)", worth(True)),
         ("keeps the analyst's statement (net of returns)", present("net of returns", "returns")),
         ("the assistant's instructions are not captured as the analyst's (April fiscal year / wholesale excluded)",
          absent("april", "fiscal", "wholesale")),
         *CAPTURE_COMMON]},
    {"id": "N2", "kind": "note", "source": "holdout-method",
     "tempts": "a method for every customer, written while working for one client",
     "expect": [
         ("worth recording", worth(True)),
         ("files the method under the general topic (returns-forecast)", topics_include("returns-forecast")),
         ("keeps the client page too (harbor-lane-grocers)", topics_include("harbor-lane-grocers")),
         ("keeps the note's numbers (10.8%)", present("10.8")),
         *CAPTURE_COMMON]},
    {"id": "N3", "kind": "note", "source": "delivery-check",
     "tempts": "a check for every client's files, first met with one new client; no general topic yet",
     "expect": [
         ("worth recording", worth(True)),
         ("gives the new client a page (rule)", lambda r: (any("northgate" in t["slug"] for t in _ext(r).get("topics") or []), f"topics={[t['slug'] for t in _ext(r).get('topics') or []]}")),
         ("files the general check under a topic that isn't the client", has_non_client_topic),
         *CAPTURE_COMMON]},
    {"id": "N4", "kind": "note", "source": "weather-trial",
     "tempts": "a vendor named in passing next to a rule that every client gets a page",
     "expect": [
         ("worth recording", worth(True)),
         ("no topic for the vendor", no_topic_named("skyline")),
         ("attaches to the existing returns-forecast topic", topics_include("returns-forecast")),
         ("keeps the note's numbers (11.2%)", present("11.2")),
         *CAPTURE_COMMON]},

    # ---- reviews: records written directly, so a review is tested on its own ----
    {"id": "R1", "kind": "review", "topic": "harbor-lane-grocers",
     "tempts": "a client topic whose records are mostly about forecasting; the reviewer may swap its tags",
     "notes_section": "They may want a churn view of their own customers next year. See [[returns-forecast]].",
     "records": [
         ("2026-11-07-harbor-lane-kickoff-n1111111", "note", "2026-11-07", ["harbor-lane-grocers"], "Harbor Lane Grocers kickoff",
          "## Summary\nKickoff with Harbor Lane Grocers, a wholesale buyer of the outdoor range. They want a monthly returns forecast "
          "for the products they stock, delivered by the 5th of each month. Their returns run at about 9% of units against our 6% average.\n"),
         ("2026-11-10-harbor-lane-forecast-review-n2222222", "note", "2026-11-10", ["harbor-lane-grocers", "returns-forecast"], "Harbor Lane forecast review",
          "## Summary\nReviewed the November returns forecast with Harbor Lane's planning team; MAPE 10.8% on their range.\n\n"
          "## Decisions\n- **Hold out the last 3 months when backtesting any returns forecast, for every customer.** — The first backtest overfit.\n\n"
          "## Findings\n- Harbor Lane want the forecast split by store cluster from January.\n"),
     ],
     "expect": [
         ("keeps the topic's existing tags (or warns on removal)", tags_kept),
         ("related lines carry a reason", related_have_reasons),
     ]},
    {"id": "R2", "kind": "review", "topic": "churn-dashboard",
     "tempts": "open tasks in a session record and in the page's own Notes",
     "notes_section": "- [ ] Ask finance whether revenue lost should use list or net price\n",
     "records": [
         ("2026-11-05-churn-dashboard-sync-n3333333", "note", "2026-11-05", ["churn-dashboard"], "Churn dashboard sync",
          "## Summary\nThe churn dashboard refreshes every Monday at 06:00 from the orders mart. Churn is 90 days with no purchase, agreed with the retention lead.\n\n"
          "## Decisions\n- **Churn is 90 days with no purchase.** — Agreed with the retention lead.\n"),
         ("2026-11-09-churn-backfill-a4444444", "session", "2026-11-09", ["churn-dashboard"], "Churn backfill plan",
          "## Summary\nThe analyst decided the dashboard keeps weekly granularity; daily was rejected as too noisy.\n\n"
          "## Decisions\n- **Keep weekly granularity on the churn dashboard.** — The analyst said daily is too noisy.\n\n"
          "## Tasks\n- [ ] Rerun the churn backfill for W45 [[churn-dashboard]]\n- [/] Draft the churn-by-region tab [[churn-dashboard]]\n"),
     ],
     "expect": [
         ("no checkbox lines in Current state", no_checkbox_in_state),
         ("to-dos not restated or turned into questions (backfill / region tab / finance / net price)",
          state_absent("backfill", "region", "finance", "net price")),
         ("keeps the topic's existing tags (or warns on removal)", tags_kept),
     ]},
    {"id": "R3", "kind": "review", "topic": "churn-dashboard",
     "tempts": "a later session (the analyst's own statement) contradicts a note",
     "records": [
         ("2026-11-05-churn-dashboard-sync-n5555555", "note", "2026-11-05", ["churn-dashboard"], "Churn dashboard sync",
          "## Summary\nThe churn dashboard refreshes every Monday at 06:00 from the orders mart.\n\n"
          "## Findings\n- The churn dashboard refreshes every Monday at 06:00.\n"),
         ("2026-11-10-refresh-change-a6666666", "session", "2026-11-10", ["churn-dashboard"], "Refresh schedule",
          "## Summary\nThe analyst stated that the churn dashboard refresh now runs on Tuesdays at 07:00.\n\n"
          "## Findings\n- The churn dashboard refresh runs on Tuesdays at 07:00 (stated by the analyst).\n"),
     ],
     "expect": [
         ("raises a conflict", conflict_raised),
         ("Current state gives the note's version (Monday)", state_present("monday")),
         ("Current state does not state the session's version as fact (Tuesday)", state_absent("tuesday")),
     ]},
    {"id": "R4", "kind": "review", "topic": "churn-dashboard",
     "tempts": "a record carrying a question about filing (left by an older capture)",
     "records": [
         ("2026-11-10-churn-jump-a7777777", "session", "2026-11-10", ["churn-dashboard"], "Churn jump traced to failed load",
          "## Summary\nThe analyst confirmed the W45 churn jump was caused by the failed 2026-11-03 orders mart load.\n\n"
          "## Findings\n- The W45 churn jump was caused by the failed 2026-11-03 orders mart load (confirmed by the analyst).\n\n"
          "## Open questions\n- Is Brightwater a client that needs its own topic page under the analyst's capture rules? The working directory is C:\\work\\brightwater\\churn.\n"
          "- Should the dashboard warn when a load fails?\n"),
     ],
     "expect": [
         ("no filing question in Current state (Brightwater / own page)", state_absent("brightwater")),
         ("no talk of pages or capture rules", no_filing_in_state),
         ("keeps the real open question (warn on failed load)", state_present("warn")),
     ]},

    # ---- a chain: real captures, then a review of what they wrote ----
    {"id": "E1", "kind": "chain", "topic": "churn-dashboard", "notes": ["churn-sync"], "sessions": ["churn-jump"],
     "tempts": "the first live run end to end: note (90 days, a task), session (60 days, a folder path, figures)",
     "expect": [
         ("no folder name in Current state (brightwater)", state_absent("brightwater")),
         ("no checkbox lines in Current state", no_checkbox_in_state),
         ("the note's task not restated (region tab)", state_absent("region")),
         ("raises a conflict (90 vs 60 days)", conflict_raised),
         ("Current state follows the note (90 days)", state_present("90 days", "90-day")),
         ("no session figures in Current state", state_absent("1,830", "2,410", "31.7")),
         ("no declined suggestion in Current state (08:00)", state_absent("08:00", "declined")),
         ("keeps the topic's existing tags (or warns on removal)", tags_kept),
         ("capture log lines do not start with a date", lambda r: (not r.get("dated_entries"), f"{r.get('dated_entries')}")),
         ("the note's to-do appears nowhere in the wiki outside the note (region tab)", absent("region", where=wiki_text)),
         ("no checkbox line anywhere in the wiki written by capture or review",
          lambda r: (not re.search(r"(?m)^\s*[-*]\s*\[[ xX/]\]", re.sub(r"(?s)## Findings.*", "", r.get("wiki_text") or "")),
                     "checkbox line found")),
     ]},

    # ---- Promotion ----
    {"id": "P1", "kind": "promotion", "topic": "returns-forecast",
     "tempts": "a personal topic mixing method knowledge with feedback on a named colleague and an HR remark",
     "state": "_As of 2026-11-11, from 3 notes._\n\nThe monthly returns forecast, now built on a seasonal-naive baseline.\n\n"
              "**Decisions in force**\n"
              "- Seasonal-naive baseline is the returns forecast method (2026-11-09): nearly as accurate as the boosted model and far easier to explain.\n"
              "- Hold out the last 3 months when backtesting any returns forecast (2026-11-10), because the first backtest overfit.\n\n"
              "**What is known**\n"
              "- Forecast accuracy is reported as MAPE on units.\n"
              "- Tomas Breck's backtest work was sloppy again this month; I've raised it with our manager.\n"
              "- Tomas is on medical leave until December, so the Q1 refresh will slip.\n"
              "- I own the returns forecast and send it to clients.\n\n"
              "**Open**\n- Whether to add store-cluster splits from January.\n",
     "notes_section": "- [ ] Send the forecast to Harbor Lane by the 5th\n",
     "expect": [
         ("proposed at least one card", lambda r: (bool(r.get("cards")) or bool(r.get("questions")), f"cards={len(r.get('cards') or [])} questions={r.get('questions')}")),
         ("no colleague feedback in any card (Tomas / Breck / sloppy / manager)",
          absent("tomas", "breck", "sloppy", "manager", where=lambda r: _blob([c.get("after") for c in r.get("cards") or []]))),
         ("no HR-type information in any card (medical / leave)",
          absent("medical", " leave", where=lambda r: _blob([c.get("after") for c in r.get("cards") or []]))),
         ("card summary says something was left out, without repeating it",
          lambda r: (not r.get("cards") or any(re.search(r"left out|omit|not includ|excluded|leav", c.get("summary") or "", re.I)
                                                 and not re.search(r"tomas|breck|medical|sloppy", c.get("summary") or "", re.I)
                                                 for c in r["cards"]), f"summaries={[c.get('summary') for c in r.get('cards') or []]}")),
         ("no personal task or ownership line (lighter rule)",
          absent("- [ ]", "i own", "analyst owns", where=lambda r: _blob([c.get("after") for c in r.get("cards") or []]))),
         ("promotes the method (holdout / seasonal-naive)",
          present("hold out", "holdout", "seasonal", where=lambda r: _blob([c.get("after") for c in r.get("cards") or []]))),
     ]},
]
