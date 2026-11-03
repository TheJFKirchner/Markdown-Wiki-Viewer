"""The ingest agent. Start reading here.

An "agent" is a Claude model that is given four things and then left to work on its own:
  - instructions: what its job is (also called the "system prompt");
  - a first message: here, the notes to ingest and an index of every wiki page;
  - tools: functions it may ask us to run (here: read a page, propose a change; see tools.py);
  - limits: how long it may go on.
It works in a loop: it thinks, asks for a tool, reads what the tool sent back, and repeats until
it says it's done. The Claude Agent SDK runs that loop for us; this file sets it up and follows it.

  ingest_notes()   one run: get everything ready, start the agent, follow it until it stops.
  revise_cards()   a feedback round: the same conversation, continued with the reviewer's feedback.

The agent never writes to the wikis. Its proposals become cards, and the app writes a change only
when the person accepts it.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from costs import add_totals, plain_claude_code_cost, priced, prices_for, run_totals
from progress import log, tell_app
from prompts import page_name, write_feedback_message, write_first_message, write_instructions
from tools import TOOL_NAMES, RunMemory, tools_for_claude
from transcript import Transcript
from wikis import Wikis

# Haiku 5.5 at low effort: in side-by-side tests it proposed as many good changes as Sonnet 5.5
# for about a tenth of the cost (see AGENT.md). The Ingest view's model menu can pick another.
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "low"
MAX_TURNS = 40          # trips round the loop
MAX_COST_USD = 1.00     # at API prices
MAX_PROMPT_TOKENS = 150_000


@dataclass
class Agent:
    """Everything the agent is given, in plain words."""
    model: str                    # which Claude: "claude-haiku-5-5", "claude-sonnet-5-5"...
    effort: str                   # how much it thinks before answering: "low", "medium", "high"...
    instructions_file: Path       # its instructions, saved in the run folder (system.md)
    tools: object                 # the two tools from tools.py
    max_turns: int                # limits, so a run can't go on for ever
    max_cost_usd: float
    work_folder: Path             # the run folder
    save_raw_requests: bool = False      # also keep every request exactly as sent (for checking)
    continues_session: str | None = None  # a feedback round continues this earlier conversation


def make_agent(job: dict, run_folder: Path, memory: RunMemory, continues_session: str | None = None) -> Agent:
    settings = job.get("settings") or {}
    return Agent(
        model=settings.get("model") or DEFAULT_MODEL,
        effort=settings.get("effort") or DEFAULT_EFFORT,
        instructions_file=run_folder / "system.md",
        tools=tools_for_claude(memory),
        max_turns=int(settings.get("maxTurns") or MAX_TURNS),
        max_cost_usd=float(settings.get("maxBudgetUsd") or MAX_COST_USD),
        work_folder=run_folder,
        save_raw_requests=bool(settings.get("logRaw")),
        continues_session=continues_session,
    )


# ---- One run --------------------------------------------------------------------------------

async def ingest_notes(job: dict, run_folder: Path, prepare_only: bool = False) -> int:
    today = job.get("date") or ""
    note_ids = list(job.get("notes") or [])

    tell_app({"type": "stage", "stage": "index", "text": "Building index"})
    wikis = Wikis(job["wikis"], job.get("notesDir") or "Notes")
    indexes = wikis.write_indexes(today)

    tell_app({"type": "stage", "stage": "notes", "text": "Reading notes"})
    model = (job.get("settings") or {}).get("model") or DEFAULT_MODEL
    transcript = Transcript(job, run_folder, prices_for(model))

    def stop(why: str) -> int:
        tell_app({"type": "done", "ok": False, "message": why})
        transcript.finish(False, why, None, [])
        return 1

    missing = [n for n in note_ids if n not in wikis.pages]
    if missing:
        return stop("These notes weren't found: " + ", ".join(missing))

    # What the agent is given. Both texts are saved in the run folder, to see exactly what was sent.
    instructions = write_instructions(wikis, job.get("userNotes") or "", today)
    first_message = write_first_message(wikis, indexes, note_ids, today)
    (run_folder / "system.md").write_text(instructions, encoding="utf-8", newline="\n")
    (run_folder / "first-message.md").write_text(first_message, encoding="utf-8", newline="\n")
    transcript.context(instructions, indexes, {n: wikis.pages[n].text for n in note_ids})

    size = (len(instructions) + len(first_message)) // 4
    if size > MAX_PROMPT_TOKENS:
        return stop(f"The selected notes and the index come to about {size:,} tokens. Select fewer notes.")
    if prepare_only:
        tell_app({"type": "done", "ok": True, "prepared": True, "message": f"Prompts saved in {run_folder}"})
        return 0

    memory = RunMemory(wikis, job["runId"], note_ids, tell_app)
    agent = make_agent(job, run_folder, memory)

    tell_app({"type": "stage", "stage": "agent", "text": "Claude is reading the notes"})
    result, requests, error, session = await talk_to_claude(agent, first_message, transcript)

    ok, error = how_it_ended(result, error)
    totals = run_totals(result, requests, memory.read_count, len(memory.cards), transcript.prices)
    save_session(run_folder, session, memory)
    transcript.finish(ok, error, totals, list(memory.cards.values()))
    tell_app({"type": "done", "ok": ok, "message": error, **totals})
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
    memory = RunMemory(wikis, job["runId"], list(job.get("notes") or []), tell_app)
    memory.pages_read = session["read"]
    memory.cards = session["cards"]
    by_id = {c["id"]: c for c in memory.cards.values()}
    items = feedback.get("cards") or ([{"card": feedback["card"], "text": feedback["text"]}] if feedback.get("card") else [])
    unknown = [i.get("card") for i in items if i.get("card") not in by_id]
    if not items or unknown:
        tell_app({"type": "done", "ok": False, "feedback": True, "message": f"Card {', '.join(map(str, unknown)) or '(none)'} isn't part of this run."})
        return 1
    asked = [(by_id[i["card"]], str(i.get("text") or "")) for i in items]
    memory.decided = {c: how for how in ("accepted", "rejected") for c in feedback.get(how) or [] if c in by_id}

    agent = make_agent(job, run_folder, memory, continues_session=session["sessionId"])
    transcript = Transcript.load(job, run_folder, prices_for(agent.model))
    entry = transcript.begin_feedback(asked, memory.decided, page_name)
    before = {card["id"]: dict(card) for card, _ in asked}
    tell_app({"type": "stage", "stage": "feedback",
              "text": f"Claude is revising {asked[0][0]['title']}" if len(asked) == 1 else f"Claude is revising {len(asked)} cards"})

    message = write_feedback_message(asked, memory.decided)
    result, requests, error, session_id = await talk_to_claude(agent, message, transcript)

    ok, error = how_it_ended(result, error)
    prices = transcript.prices
    round_totals = run_totals(result, requests, memory.read_count, len(memory.cards), prices)
    # On a continued conversation Claude Code reports the whole conversation's cost so far, not
    # just this round's (its token counts are this round's only). The round costs the difference.
    previous_cost = (transcript.data.get("totals") or {}).get("cost") or 0
    if result and result.total_cost_usd is not None and result.total_cost_usd >= previous_cost:
        round_totals["cost"] = round(result.total_cost_usd - previous_cost, 4)
    else:
        round_totals["cost"] = round(priced(round_totals["tokens"], prices), 4)
    round_totals["plainClaudeCode"] = plain_claude_code_cost(round_totals["cost"], round_totals["requests"], prices)

    now = {c["id"]: c for c in memory.cards.values()}
    revised = [i for i, card in before.items() if now.get(i) and now[i] != card]
    for item in entry["cards"]:
        item["revised"] = item["card"] in revised
    entry.update(reply=(result.result or "").strip()[:1500] if result else "", revised=bool(revised),
                 tokens=round_totals["tokens"], cost=round_totals["cost"], requests=round_totals["requests"])
    totals = add_totals(transcript.data.get("totals"), round_totals, prices)
    totals["cards"] = len(memory.cards)
    save_session(run_folder, session_id or session["sessionId"], memory)
    transcript.data["finished"] = datetime.now().isoformat(timespec="seconds")
    transcript.data["totals"] = totals
    transcript.set_cards(list(memory.cards.values()))
    transcript.save()
    tell_app({"type": "reply", "cards": list(before), "text": entry["reply"], "revised": revised})
    tell_app({"type": "done", "ok": ok, "feedback": True, "cards": list(before), "message": error, **totals, "round": round_totals})
    return 0 if ok else 1


# ---- Talking to Claude ------------------------------------------------------------------------

async def talk_to_claude(agent: Agent, message: str, transcript: Transcript) -> tuple:
    """Sends one message to the agent and follows it round its loop until it stops.
    -> (Claude Code's final result or None, the request ids, an error text, the conversation id)"""
    from claude_agent_sdk import (AssistantMessage, CLINotFoundError, ClaudeSDKError, ResultMessage,
                                  StreamEvent, SystemMessage, TextBlock, ToolResultBlock, ToolUseBlock,
                                  UserMessage, query)

    result = None
    requests = set()
    error = ""
    session = None
    try:
        async for event in query(prompt=message, options=claude_code_options(agent)):
            if isinstance(event, SystemMessage) and event.subtype == "init":
                # The start: which model is running and which tools the agent really has.
                transcript.data["model"] = event.data.get("model")
                session = event.data.get("session_id") or session
                log({"type": "init", "model": event.data.get("model"), "tools": event.data.get("tools"),
                     "mcp_servers": event.data.get("mcp_servers"), "session_id": session})
            elif isinstance(event, StreamEvent):
                transcript.stream_event(event.event)          # token counts as an answer streams in
            elif isinstance(event, AssistantMessage):
                # Claude's turn: some text, and the tools it wants us to run.
                if event.message_id:
                    requests.add(event.message_id)
                transcript.claude_said(event, TextBlock, ToolUseBlock)
                for block in event.content:
                    if isinstance(block, ToolUseBlock):
                        log({"type": "tool_use", "name": block.name, "input": block.input})
                        if block.name.endswith("read_page"):
                            tell_app({"type": "stage", "stage": "reading", "text": f"Reading {block.input.get('page', '')}"})
                    elif isinstance(block, TextBlock) and block.text.strip():
                        log({"type": "text", "text": block.text})
                if event.error:
                    log({"type": "assistant_error", "error": str(event.error)})
            elif isinstance(event, UserMessage):
                transcript.tools_answered(event, ToolResultBlock)   # what our tools sent back
            elif isinstance(event, ResultMessage):
                result = event                                      # the end: totals and how it stopped
                session = event.session_id or session
    except CLINotFoundError:
        error = "Claude Code wasn't found. Install it and sign in, then try again."
    except ClaudeSDKError as err:
        error = str(err).strip().splitlines()[0] if str(err).strip() else type(err).__name__
    return result, requests, error, session


def how_it_ended(result, error: str) -> tuple[bool, str]:
    """-> (whether the agent finished normally, and if not, why in plain words)"""
    stop = result.stop_reason if result else None
    ok = bool(result) and not result.is_error and stop != "refusal" and not error
    # When Claude Code ends with an error result, the SDK first hands us that result and then
    # raises an error saying only "returned an error result", so the result says more.
    if not ok:
        if stop == "refusal":
            error = "Claude declined to continue (a safety check stopped the run)."
        elif result and result.subtype == "error_max_turns":
            error = "The run hit its turn limit before finishing."
        elif result and result.subtype == "error_max_budget_usd":
            error = "The run hit its cost limit before finishing."
        elif result and result.is_error and result.result:
            error = result.result
        elif not error:
            error = "The run stopped with an error."
    if any(sign in error.lower() for sign in ("authenticate", "oauth", "not logged in", "/login", "api key")):
        error = ("Claude Code isn't signed in on this computer (or its sign-in expired). Run  claude auth login  "
                 "in a terminal (install Claude Code first if there's no claude command), then try again.")
    return ok, error


def save_session(run_folder: Path, session: str | None, memory: RunMemory) -> None:
    """What a feedback round needs to carry on: the conversation id, the pages the agent has read
    (proposals must be based on them), and the cards so far."""
    (run_folder / "session.json").write_text(json.dumps({
        "sessionId": session, "read": memory.pages_read, "cards": memory.cards,
    }, ensure_ascii=False), encoding="utf-8")


# ---- Plumbing: the Agent, in the form Claude Code takes ----------------------------------------
# Claude Code normally brings a lot of its own: built-in tools (shell, file editing, web), the
# user's settings, CLAUDE.md files, skills and plugins. All of that is switched off here, so the
# agent gets only our instructions and our two tools, and nothing else from this computer.

BUILT_IN_TOOLS = ["Agent", "Task", "Bash", "Read", "Write", "Edit", "Glob", "Grep",
                  "WebSearch", "WebFetch", "TodoWrite", "NotebookEdit", "Skill"]


def claude_code_options(agent: Agent):
    from claude_agent_sdk import ClaudeAgentOptions

    env = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
           # Stops Claude Code's side request that names the session: it re-sends the whole first
           # message, uncached, on every run (about 10-15% of a Haiku run's cost).
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    if agent.save_raw_requests:
        (agent.work_folder / "raw").mkdir(exist_ok=True)
        env["OTEL_LOG_RAW_API_BODIES"] = f"file:{agent.work_folder / 'raw'}"
    sign_in_env, sign_in = sign_in_settings()
    env = {**sign_in_env, **env}
    return ClaudeAgentOptions(
        model=agent.model,
        effort=agent.effort,
        system_prompt={"type": "file", "path": str(agent.instructions_file)},
        mcp_servers={"wiki": agent.tools},
        allowed_tools=TOOL_NAMES,
        max_turns=agent.max_turns,
        max_budget_usd=agent.max_cost_usd,
        resume=agent.continues_session,
        cwd=str(agent.work_folder),
        # Nothing else: no built-in tools, other tool servers, settings, subagents, skills or plugins.
        tools=[],
        disallowed_tools=BUILT_IN_TOOLS,
        strict_mcp_config=True,
        permission_mode="dontAsk",
        setting_sources=[],
        settings=sign_in,
        agents=None,
        skills=[],
        plugins=[],
        env=env,
        # Stream events carry each request's final output-token count, for the transcript.
        include_partial_messages=True,
    )


def sign_in_settings() -> tuple[dict, str | None]:
    """Only the sign-in parts of ~/.claude/settings.json (a gateway URL, token helper, model
    names). The rest of the user's settings, hooks and CLAUDE.md stay out of the run.
    It signs in with the computer's existing Claude Code login (~/.claude): no API key.
    -> (its `env` block, for Claude Code's environment: settings travel on the command line,
    where other programs could see a token in it; its `apiKeyHelper` as settings, or None)"""
    try:
        settings = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    helper = settings.get("apiKeyHelper")
    return {str(k): str(v) for k, v in env.items()}, (json.dumps({"apiKeyHelper": helper}) if helper else None)
