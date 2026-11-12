"""The ingest agent. Start reading here.

An "agent" is a Claude model that is given four things and then left to work on its own:
  - instructions: what its job is (also called the "system prompt");
  - a first message: here, the personal pages to promote and an index of every wiki page;
  - tools: functions it may ask us to run (here: read a page, propose a change; see tools.py);
  - limits: how long it may go on, and how much it may spend.
It works in a loop: it thinks, asks for a tool, reads what the tool sent back, and repeats until
it says it's done. The agentlib library runs that loop for us (on Claude today; it is written so
another engine can run the same agent later); this file sets it up and follows it.

This code runs one agent, the team wiki manager, behind the Promotion tab: it reads chosen pages
of the personal wiki and proposes changes to the team wikis. (Notes reach the personal wiki
through the Sessions tab, not through here.)

  promote()           one run: get everything ready, start the agent, follow it until it stops.
  answer_questions()  a promotion's questions answered: the same conversation, continued.
  revise_cards()      a feedback round: the same conversation, continued with the reviewer's feedback.

The agent never writes to the wikis. Its proposals become cards, and the app writes a change only
when the person accepts it.
"""

import json
from datetime import datetime
from pathlib import Path

from agentlib import (Agent, AgentError, ConversationMissing, Done, RateLimit, Text, ToolCall, ToolResult)

from costs import add_totals, plain_claude_code_cost, prices_for, run_totals
from progress import log, tell_app
from prompts import (agent_prompt, page_name, write_answers_message, write_feedback_message, write_first_message,
                     write_instructions)
from tools import RunMemory, tools_for_agent
from transcript import Transcript
from wikis import Wikis
import pathlist  # noqa: E402  (on the path through wikis.py: every setting comes from the path list)

AGENT_ID = "team-wiki-manager"   # this code runs one agent: the team wiki manager, for a promotion
DEFAULT_EFFORT = "low"
MAX_TURNS = 40          # trips round the loop
MAX_COST_USD = 1.00     # at API prices: the run stops at this spend
MAX_PROMPT_TOKENS = 150_000
TURN_TIMEOUT_S = 1800   # one message's work, at most (the Stop button ends a run sooner)
TOOL_SERVER = "wiki"    # the model sees mcp__wiki__read_page...; also what runs saved before agentlib used


# ---- The agent, described ------------------------------------------------------------------------

def model_for(job: dict, fields: dict | None = None) -> str | None:
    """The model a run uses: one the job names (settings.model) wins; otherwise the engine
    settings' model for this agent (engines.<engine>.models["team-wiki-manager"], the one place
    the default is kept, which the app reads and writes); otherwise the engine's own default (None)."""
    chosen = (job.get("settings") or {}).get("model")
    if chosen:
        return str(chosen)
    if fields is None:
        fields = engine_choice()[1]
    models = fields.get("models") if isinstance(fields.get("models"), dict) else {}
    return models.get(AGENT_ID) or None


def make_agent(job: dict, run_folder: Path, memory: RunMemory) -> Agent:
    """Everything the agent is given, in plain words."""
    settings = job.get("settings") or {}
    engine, fields = engine_choice()
    return Agent(
        name=AGENT_ID,
        engine=engine,                                   # "claude" unless the engine settings say otherwise
        model=model_for(job, fields),
        effort=settings.get("effort") or DEFAULT_EFFORT,  # how much it thinks before answering
        instructions=(run_folder / "system.md").read_text(encoding="utf-8"),
        tools=tools_for_agent(memory),                   # exactly these tools; nothing built in
        tool_server=TOOL_SERVER,
        permission_mode="never_ask",                     # our tools are pre-approved; anything else is denied
        max_turns=int(settings.get("maxTurns") or MAX_TURNS),
        max_budget_usd=float(settings.get("maxBudgetUsd") or MAX_COST_USD),
        cwd=str(run_folder),                             # the run's own folder: no project files near it
        env=engine_env(engine, fields, run_folder, bool(settings.get("logRaw"))),
        timeout_s=TURN_TIMEOUT_S,
    )


# ---- One run --------------------------------------------------------------------------------

async def promote(job: dict, run_folder: Path, prepare_only: bool = False) -> int:
    """One promotion: the personal pages in job["notes"] are read, and the team wiki manager
    proposes changes to the wikis in job["targets"] (every open wiki but the personal one)."""
    today = job.get("date") or ""
    note_ids = list(job.get("notes") or [])

    tell_app({"type": "stage", "stage": "index", "text": "Building index"})
    wikis = Wikis(job["wikis"], job.get("notesDir") or "Notes")
    indexes = wikis.write_indexes(today)

    tell_app({"type": "stage", "stage": "notes", "text": "Reading pages"})
    transcript = Transcript(job, run_folder, prices_for(model_for(job) or ""))

    def stop(why: str) -> int:
        tell_app({"type": "done", "ok": False, "message": why})
        transcript.finish(False, why, None, [])
        return 1

    if job.get("agent") not in (None, "", AGENT_ID):
        return stop(f'This run is for the team wiki manager only, not "{job["agent"]}".')
    if not job.get("targets"):
        return stop("Choose a wiki to promote into: the job names no target wiki.")
    refused = target_refusal(wikis, job["targets"])
    if refused:
        return stop(refused)
    missing = [n for n in note_ids if n not in wikis.pages]
    if missing:
        return stop("These pages weren't found: " + ", ".join(missing))

    # What the agent is given. Both texts are saved in the run folder, to see exactly what was sent.
    # The instructions come from the team wiki manager's prompt file (see agents/agentfiles.py).
    instructions = write_instructions(wikis, agent_prompt(AGENT_ID), today)
    first_message = write_first_message(wikis, indexes, note_ids, today)
    (run_folder / "system.md").write_text(instructions, encoding="utf-8", newline="\n")
    (run_folder / "first-message.md").write_text(first_message, encoding="utf-8", newline="\n")
    transcript.context(instructions, indexes, {n: wikis.pages[n].text for n in note_ids})

    size = (len(instructions) + len(first_message)) // 4
    if size > MAX_PROMPT_TOKENS:
        return stop(f"The selected pages and the index come to about {size:,} tokens. Select fewer pages.")
    if prepare_only:
        tell_app({"type": "done", "ok": True, "prepared": True, "message": f"Prompts saved in {run_folder}"})
        return 0

    memory = RunMemory(wikis, job["runId"], note_ids, tell_app, job.get("targets"))
    agent = make_agent(job, run_folder, memory)

    tell_app({"type": "stage", "stage": "agent", "text": "Claude is reading the pages"})
    reply, error, session = await talk_to_agent(agent, first_message, transcript)

    ok, error = how_it_ended(reply, error)
    totals = run_totals(reply, memory.read_count, len(memory.cards), transcript.prices)
    save_session(run_folder, session, memory, reply.total_cost_usd if reply else 0)
    transcript.finish(ok, error, totals, list(memory.cards.values()))
    # questions: how many the agent asked the reviewer (a promotion). The app shows them, and the
    # answers continue this conversation (answer_questions, below).
    tell_app({"type": "done", "ok": ok, "message": error, "questions": len(memory.questions), **totals})
    return 0 if ok else 1


# ---- The reviewer's answers ---------------------------------------------------------------------

async def answer_questions(job: dict, run_folder: Path, answers: dict) -> int:
    """Continues a promotion with the reviewer's answers to the agent's questions
    ({"q1": "...", "q2": ""}; an empty answer means the question was skipped). The same
    conversation, so the agent still has the pages it read; it now proposes its cards."""
    session = json.loads((run_folder / "session.json").read_text(encoding="utf-8"))
    questions = session.get("questions") or []
    if not session.get("sessionId") or not questions:
        tell_app({"type": "done", "ok": False, "answers": True, "message": "This run has no questions to answer."})
        return 1
    wikis = Wikis(job["wikis"], job.get("notesDir") or "Notes")
    memory = RunMemory(wikis, job["runId"], list(job.get("notes") or []), tell_app, job.get("targets"))
    memory.pages_read = session["read"]
    memory.cards = session["cards"]
    memory.questions, memory.asked = questions, True  # one round of questions per run

    agent = make_agent(job, run_folder, memory)
    transcript = Transcript.load(job, run_folder, prices_for(agent.model or ""))
    tell_app({"type": "stage", "stage": "answers", "text": "Claude is using your answers"})
    message = write_answers_message(questions, {str(k): str(v or "") for k, v in (answers or {}).items()})
    (run_folder / "answers-message.md").write_text(message, encoding="utf-8", newline="\n")
    reply, error, session_id = await talk_to_agent(agent, message, transcript, resume=session["sessionId"],
                                                   cost_base=conversation_cost(session, transcript))

    ok, error = how_it_ended(reply, error)
    totals = add_round(transcript, reply, memory)
    save_session(run_folder, session_id or session["sessionId"], memory, reply.total_cost_usd if reply else None, session)
    transcript.data["finished"] = datetime.now().isoformat(timespec="seconds")
    transcript.data["totals"] = totals
    transcript.data["questions"] = [{**q, "answer": str((answers or {}).get(q["id"]) or "")} for q in questions]
    transcript.set_cards(list(memory.cards.values()))
    transcript.save()
    tell_app({"type": "done", "ok": ok, "answers": True, "message": error, **totals})
    return 0 if ok else 1


# ---- A feedback round -------------------------------------------------------------------------

async def revise_cards(job: dict, run_folder: Path, feedback: dict) -> int:
    """Continues the run's own conversation with the reviewer's feedback on some cards
    ({"cards": [{"card": "c3", "text": "..."}], "accepted": [ids], "rejected": [ids]}).
    Same conversation, tools and instructions, so everything said so far is read from the
    prompt cache; the round's requests and cost are added to the run's transcript and totals."""
    session = json.loads((run_folder / "session.json").read_text(encoding="utf-8"))
    if not session.get("sessionId"):
        tell_app({"type": "done", "ok": False, "feedback": True, "message": "This run has no Claude session to continue."})
        return 1

    # The tools pick up where the run left off: the pages read and the cards so far.
    wikis = Wikis(job["wikis"], job.get("notesDir") or "Notes")
    memory = RunMemory(wikis, job["runId"], list(job.get("notes") or []), tell_app, job.get("targets"))
    memory.pages_read = session["read"]
    memory.cards = session["cards"]
    memory.questions, memory.asked = session.get("questions") or [], bool(session.get("asked"))
    by_id = {c["id"]: c for c in memory.cards.values()}
    items = feedback.get("cards") or ([{"card": feedback["card"], "text": feedback["text"]}] if feedback.get("card") else [])
    unknown = [i.get("card") for i in items if i.get("card") not in by_id]
    if not items or unknown:
        tell_app({"type": "done", "ok": False, "feedback": True, "message": f"Card {', '.join(map(str, unknown)) or '(none)'} isn't part of this run."})
        return 1
    asked = [(by_id[i["card"]], str(i.get("text") or "")) for i in items]
    memory.decided = {c: how for how in ("accepted", "rejected") for c in feedback.get(how) or [] if c in by_id}

    agent = make_agent(job, run_folder, memory)
    transcript = Transcript.load(job, run_folder, prices_for(agent.model or ""))
    entry = transcript.begin_feedback(asked, memory.decided, page_name)
    before = {card["id"]: dict(card) for card, _ in asked}
    tell_app({"type": "stage", "stage": "feedback",
              "text": f"Claude is revising {asked[0][0]['title']}" if len(asked) == 1 else f"Claude is revising {len(asked)} cards"})

    message = write_feedback_message(asked, memory.decided)
    reply, error, session_id = await talk_to_agent(agent, message, transcript, resume=session["sessionId"],
                                                   cost_base=conversation_cost(session, transcript))

    ok, error = how_it_ended(reply, error)
    round_totals = run_totals(reply, memory.read_count, len(memory.cards), transcript.prices)
    now = {c["id"]: c for c in memory.cards.values()}
    revised = [i for i, card in before.items() if now.get(i) and now[i] != card]
    for item in entry["cards"]:
        item["revised"] = item["card"] in revised
    entry.update(reply=(reply.text or "").strip()[:1500] if reply else "", revised=bool(revised),
                 tokens=round_totals["tokens"], cost=round_totals["cost"], requests=round_totals["requests"])
    totals = add_totals(transcript.data.get("totals"), round_totals, transcript.prices)
    totals["cards"] = len(memory.cards)
    save_session(run_folder, session_id or session["sessionId"], memory, reply.total_cost_usd if reply else None, session)
    transcript.data["finished"] = datetime.now().isoformat(timespec="seconds")
    transcript.data["totals"] = totals
    transcript.set_cards(list(memory.cards.values()))
    transcript.save()
    tell_app({"type": "reply", "cards": list(before), "text": entry["reply"], "revised": revised})
    # "cards" is the round's card ids; the run's card count is "cardCount" (the totals' own "cards"
    # number used to overwrite the ids here).
    tell_app({"type": "done", "ok": ok, "feedback": True, "message": error, **totals,
              "cards": list(before), "cardCount": totals["cards"], "round": round_totals})
    return 0 if ok else 1


def add_round(transcript: Transcript, reply, memory: RunMemory) -> dict:
    """The run's totals with one more round (answers or feedback) added."""
    round_totals = run_totals(reply, memory.read_count, len(memory.cards), transcript.prices)
    totals = add_totals(transcript.data.get("totals"), round_totals, transcript.prices)
    totals["cards"] = len(memory.cards)
    return totals


def conversation_cost(session: dict, transcript: Transcript) -> float:
    """What the conversation has cost so far, as the engine counted it. A continued conversation
    reports its running total; passing this in makes the reply's cost the new round's alone.
    (Runs saved before agentlib have no totalCostUsd: the transcript's total is the same figure.)"""
    saved = session.get("totalCostUsd")
    if isinstance(saved, (int, float)):
        return float(saved)
    return float((transcript.data.get("totals") or {}).get("cost") or 0)


# ---- Talking to the agent ---------------------------------------------------------------------

async def talk_to_agent(agent: Agent, message: str, transcript: Transcript, resume: str | None = None,
                        cost_base: float = 0.0) -> tuple:
    """Sends one message to the agent and follows it round its loop until it stops.
    resume: continue this earlier conversation (a feedback round, or a promotion's answers).
    -> (the finished turn's Reply or None, an error text, the conversation id)"""
    reply = None
    error = ""
    session_id = resume
    try:
        async with agent.session(resume=resume, cost_base=cost_base) as conversation:
            started = False
            async for event in conversation.stream(message):
                if not started:
                    # The start: which model is running and which tools the agent really has.
                    started = True
                    info = conversation.info
                    transcript.data["model"] = info.model or transcript.data.get("model")
                    log({"type": "init", "model": info.model, "tools": info.tools,
                         "mcp_servers": info.mcp_servers, "session_id": conversation.session_id})
                if isinstance(event, Text) and event.text.strip():
                    transcript.claude_said(event.text)               # Claude's short remarks
                    log({"type": "text", "text": event.text})
                elif isinstance(event, ToolCall):
                    transcript.tool_called(event.id, event.name, event.input)   # a tool it wants us to run
                    log({"type": "tool_use", "name": event.name, "input": event.input})
                    if event.name == "read_page":
                        tell_app({"type": "stage", "stage": "reading", "text": f"Reading {event.input.get('page', '')}"})
                elif isinstance(event, ToolResult):
                    transcript.tool_answered(event.id, event.text, event.is_error)  # what our tool sent back
                elif isinstance(event, RateLimit):
                    log({"type": "rate_limit", "status": event.status, "utilization": event.utilization})
                elif isinstance(event, Done):
                    reply = event.reply                              # the end: totals and how it stopped
            session_id = conversation.session_id or session_id
    except ConversationMissing:
        error = "This run's Claude conversation can't be found any more, so it can't be continued. Start a new run."
    except AgentError as err:
        error = err.short if getattr(err, "short", "") else (str(err).strip().splitlines() or [type(err).__name__])[0]
        reply = err.reply or reply                                   # a turn that failed midway: what it did so far
    if reply is not None:
        transcript.data["model"] = reply.model or transcript.data.get("model")
        if reply.model:
            transcript.prices = prices_for(reply.model)
        session_id = reply.session_id or session_id
    return reply, error, session_id


def target_refusal(wikis: Wikis, targets: list) -> str:
    """Why these targets can't be promoted into, in plain words, or "". Only the wiki whose role is
    "team" (Settings; pathlist.wiki_roles) can be: a view-only or personal wiki never gets cards."""
    for alias in targets:
        if alias not in wikis.roots:
            return f'"{alias}" isn\'t one of the wikis in this run.'
        role = pathlist.wiki_role_for_root(wikis.roots[alias])
        if role != "team":
            return pathlist.role_refusal(alias, role, "team")
    return ""


def how_it_ended(reply, error: str) -> tuple[bool, str]:
    """-> (whether the agent finished normally, and if not, why in plain words)"""
    stop = reply.stop_reason if reply else None
    ok = reply is not None and reply.status != "error" and stop != "refusal" and not error
    if not ok:
        kind = reply.error_kind if reply is not None and reply.status == "error" else None
        if stop == "refusal":
            error = "Claude declined to continue (a safety check stopped the run)."
        elif kind == "max_turns":
            error = "The run hit its turn limit before finishing."
        elif kind == "budget":
            error = "The run hit its cost limit before finishing."
        elif not error and reply is not None and reply.error:
            error = reply.error
        elif not error:
            error = "The run stopped with an error."
    if any(sign in error.lower() for sign in ("authenticate", "oauth", "not logged in", "/login", "api key")):
        error = ("Claude Code isn't signed in on this computer (or its sign-in expired). Run  claude auth login  "
                 "in a terminal (install Claude Code first if there's no claude command), then try again.")
    return ok, error


def save_session(run_folder: Path, session: str | None, memory: RunMemory, total_cost: float | None,
                 before: dict | None = None) -> None:
    """What a feedback round needs to carry on: the conversation id, what it has cost so far (so
    the next round's cost is its own), the pages the agent has read (proposals must be based on
    them), and the cards so far."""
    if total_cost is None and before is not None:
        total_cost = before.get("totalCostUsd")
    (run_folder / "session.json").write_text(json.dumps({
        "sessionId": session, "totalCostUsd": total_cost, "read": memory.pages_read, "cards": memory.cards,
        "questions": memory.questions, "asked": memory.asked,
    }, ensure_ascii=False), encoding="utf-8")


# ---- Plumbing: which engine, and its settings ------------------------------------------------------
# The engine (today "claude") and its own settings come from the engine settings in the path list
# (pathlist.get_engine_settings). agentlib's "lean" setup already leaves out everything an engine
# would otherwise bring from this computer (built-in tools, settings, CLAUDE.md files, skills,
# plugins). The environment below adds the few switches the app has always set for Claude.

ENGINE_ENV = {
    "claude": {
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",           # no file-changed notes, @file expansion, skill lists
        # Stops Claude Code's side request that names the session: it re-sends the whole first
        # message, uncached, on every run (about 10-15% of a Haiku run's cost).
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    },
}


def engine_choice() -> tuple[str, dict]:
    """-> (the engine's id, its settings: {"models": {agent id: model}, "env": {...}, ...})"""
    settings = pathlist.get_engine_settings()
    engine = settings.get("engine") or "claude"
    fields = (settings.get("engines") or {}).get(engine) or {}
    return engine, fields if isinstance(fields, dict) else {}


def engine_env(engine: str, fields: dict, run_folder: Path | None = None, save_raw_requests: bool = False) -> dict:
    """The environment for the engine's process: the app's switches, then any "env" block in the
    engine settings, then (Claude only) where to keep every raw request when that box is ticked."""
    env = dict(ENGINE_ENV.get(engine, {}))
    extra = fields.get("env")
    if isinstance(extra, dict):
        env.update({str(k): str(v) for k, v in extra.items()})
    if save_raw_requests and engine == "claude" and run_folder is not None:
        (run_folder / "raw").mkdir(exist_ok=True)
        env["OTEL_LOG_RAW_API_BODIES"] = f"file:{run_folder / 'raw'}"
    return env
