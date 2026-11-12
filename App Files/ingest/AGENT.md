# The ingest agent: exactly what it sees

This file is the contract for what the agent behind the Promotion tab receives. If the code and this file disagree, fix one of them. The design of the feature as a whole is in [DESIGN.md](DESIGN.md).

**The agent runs through agentlib**, the shared library that maps agent features to engine-neutral functions (`General-Purpose-Productivity/agentlib`, installed by `setup.py`). Nothing in the app imports an agent SDK itself. The engine is the one the engine settings name (`pathlist.get_engine_settings()`, `engine.json` in the private folder), `claude` by default, so the same code will run on another engine when agentlib has one.

**One agent runs through this code: the team wiki manager, for Promotion runs only.** It reads personal pages chosen in the Promotion tab and proposes changes to the team wiki (the one wiki whose role is `team` in Settings), as cards a person accepts or rejects. Its prompt is the `prompt.team-wiki-manager` slot. A job's `agent` is `"team-wiki-manager"` or absent; any other value, a job with no `targets`, or a target that isn't the team wiki (`agent.target_refusal`: "Northwind is view only; choose a team wiki in Settings."), stops before anything is sent.

The app used to run a second agent here, the note taker, which turned quick notes into proposed page cards (the Notes tab). That flow is gone: notes now reach the personal wiki through the Sessions tab (`sessions/`). The other agents, the executive assistant and the wiki reviewer, don't run through this code either.

**What reaches the model on each request, in this order:**
1. **Tool definitions:** `read_page`, `propose_page` and `ask_reviewer`; nothing else ([§3](#3-tools)).
2. **System prompt:** on Claude, two short lines Claude Code always adds, then the body of the agent's prompt file, then each wiki's role and the team wiki's rules ([§1](#1-system-prompt)).
3. **First user message:** on Claude, a short context reminder from Claude Code, then date, indexes and the personal pages ([§2](#2-first-user-message)).
4. **The conversation so far:** the agent's tool calls and our tool results.

## 1. System prompt

**Where the instructions come from.** The agent has exactly one prompt file, a prompt slot in the app's path list (`host/pathlist.py`), `prompt.team-wiki-manager`. `agents/agentfiles.py` reads it:
- By default it is `<private .wiki folder>/prompts/team-wiki-manager.md`, copied there from the shipped default ([agents/team-wiki-manager/SKILL.md](../agents/team-wiki-manager/SKILL.md)) when the folder is set up. The person may point the slot at any other file, such as a Claude Code skill they already have.
- An unedited copy follows the app's newer defaults by itself; an edited one is left alone.
- With no private folder chosen yet, the shipped default is read. `WIKIAPP_SKILLS_DIR` (tests) makes `<folder>/<agent id>/SKILL.md` win.
- The person edits the file in the app: Agents and rules, the Agents tab, **See the prompt**.

**How the system prompt is assembled** (`agent_prompt` and `write_instructions` in `prompts.py`). Three parts, in this order, joined by blank lines. The first is the agent's own prompt (`agentfiles.system`). There is no shared task guide any more: no agent writes or changes tasks.

1. **The body of the prompt file:** everything after the file's frontmatter, with leading and trailing blank lines removed (`agentfiles.body`). The frontmatter (the skill's `name`, `description` and `disable-model-invocation: true`, between the two `---` lines) is not sent. `{{date}}` in the body would be replaced with today's date; the shipped prompts don't use it, and the date is in the first message.
2. **The Wikis heading,** the `prompt.wikis-section` slot (shipped default, word for word):

   ```
   ## Wikis

   Each wiki has an alias, which comes first in its page ids and cross-wiki links. Follow each wiki's rules when writing in it. Where a wiki's rules differ from the guidance above, the wiki's rules win, except the rules on personal information, which always apply.
   ```
3. **One block per open wiki,** in workspace order:

   ```
   ### Wiki "team" (the team wiki: the only wiki you propose changes to)

   <rules>
   ...the full text of the wiki's rules file (where the path list's wiki.team.rules says; team/wiki_rules.md by default), frontmatter included...
   </rules>
   ```

   A wiki without a rules file gets `<rules>No rules file. Follow the existing pages' style.</rules>`.

   The heading names the wiki's role (Settings; `pathlist.wiki_roles`), from `ROLE_NOTES` in `prompts.py`: `(the team wiki: the only wiki you propose changes to)`, `(the personal wiki: where the pages come from; read only)` or `(view only: read it for context; never propose changes or new pages for it)`. A wiki whose role can't be found is shown as view only.

Nothing else goes in. There are no `{{user_notes}}` or `{{wikis}}` placeholders: the code appends the Wikis section itself, so an edited prompt can't lose it. The Wikis section has a heading for every open wiki, the personal wiki included, but only the team wiki's heading is followed by its `<rules>` block: the personal wiki's rules are the capture rules (never sent to Promotion), and a view-only wiki's rules file is not used. Every other wiki is the heading line alone, for example `### Wiki "Northwind" (view only: read it for context; never propose changes or new pages for it)`.

`agent.py` writes the finished text to `system.md` in the run folder and passes that file's text as the agent's `instructions`. In agentlib's lean setup the instructions are the whole system prompt; a long one (over about 30,000 characters) goes to Claude Code through a temporary file, so the Windows command-line limit doesn't apply.

**Before our prompt, Claude Code always adds two short lines.** There's no switch for these:
- an internal billing line (`x-anthropic-billing-header: cc_version=…; cc_entrypoint=sdk-py`)
- `You are a Claude agent, built on Anthropic's Claude Agent SDK.`

## 2. First user message

Built by `write_first_message` in `prompts.py` and saved to `first-message.md` in the run folder. Its opening line is the `prompt.promotion-first-message` slot, with `{{date}}` filled in. Each wiki's index ends with its page templates, if it has any: name, id and description only ([DESIGN.md](DESIGN.md#page-templates)). The order puts what changes least first, which helps prompt caching:
- the indexes (every open wiki, the personal one included), which only change when pages change
- then the personal pages, which change every run

````
Today is 2026-11-10. Promote what is durable in the personal pages below into the team wiki.

<index wiki="team">
<!-- Index of wiki "team", built by WikiApp's ingest on 2026-11-01.
     Each line: page name | page id | description | tags | sections | links. -->

- Saturn | team:Planets/Saturn.md | The ringed gas giant. | tags: planet, giant | links: Titan
...
Scripts (link targets only, written with their extension: [[name.sql]]):
- orbital_period.py | team:Scripts/orbital_period.py
</index>

<index wiki="personal">
...
</index>

<note id="personal:stop-loss-trend-report.md" type="topic">
...the topic page's full text, frontmatter included...
</note>

<note id="personal:promotion-queue.md">
...the queue's full text, ticked and unticked lines...
</note>
````

- The `<note>` blocks hold the personal pages chosen in the Promotion tab (the job's `notes`): topic pages, folder pages and the promotion queue, each in full; nothing is cut. Their ids are what `from_notes` must list. (The tag and field names are older than the Promotion-only engine; they are kept so the tools and prompts stay stable.)
- A `<note>` tag carries `type`, `started` and `ended` only where the page's frontmatter has them as text.
- If the system prompt and first message together come to more than about 150,000 tokens (characters ÷ 4), the run stops before calling Claude and asks you to select fewer pages.

**After our text, Claude Code adds an environment block.** It's a system-role message, about 440 tokens, listing the working folder, platform, shell and OS. It can't be switched off.

**Before our text, Claude Code adds a context reminder.** It's a `<system-reminder>` block holding the signed-in account's email address and today's date, with a note that it isn't part of the user's message. It comes from the Claude Code login and can only be turned off in "bare" mode, which would also drop that login. The team wiki manager's shipped prompt has no line about system reminders.

## 3. Tools

Each tool is a plain function in `tools.py`, next to a spec with its name, description and inputs (`READ_PAGE`, `PROPOSE_PAGE`, `ASK_REVIEWER`). `tools_for_agent` wraps each as an agentlib `Tool`; agentlib serves them to the model itself. `agent.py` names the tool server `wiki` (`TOOL_SERVER`), so on Claude the model sees `mcp__wiki__read_page`, `mcp__wiki__propose_page` and `mcp__wiki__ask_reviewer`, the same names runs had before agentlib (so their saved conversations can still be continued). Events, logs and the transcript use the short names. A function signals a problem by raising `ToolError`; its message goes back to the agent as an error result, written by agentlib as `error: ToolError: <message>`, and the turn goes on. The descriptions and schemas below are sent word for word.

### read_page

Description:

> Read a wiki page or script. `page` is a link as you would write it in the wiki: a title (Saturn), a path (Planets/Saturn), or either with a wiki alias (team:Saturn). Returns the page id, its outgoing links resolved to page ids, and its full text. If nothing matches, returns the closest page names; try one of those.

Input schema: `{ "page": string }`, required, nothing else allowed.

Result:

```
id: team:Planets/Saturn.md
links: Titan -> team:Moons/Titan.md
---
...the page's text, line endings as \n...
```

**Errors** (sent back with `is_error`):

| Case | Message |
|---|---|
| No match | `error: ToolError: No page matches "Titans". Closest: team:Moons/Titan.md, …` |
| A note, quick-note template or rules file | `error: ToolError: <id> is not a wiki page (it is a note file).` |

(Every error below has the same `error: ToolError: ` prefix; the tables leave it out.)

**Behavior**
- A script comes back with a line saying it can be linked but not changed.
- A page template comes back with: `This is a page template: follow it for a new page of this kind, and give its id as `template`. Don't propose changes to it.`
- Every successful read is remembered, so `propose_page` can check that edits are based on what was read.

### propose_page

Description:

> Propose every change to one page, for a person to accept or reject. Call once per page; calling again for the same page replaces the earlier proposal. For an existing page, read it first, then give `edits`: each `find` is text copied exactly from the page as read_page returned it, long enough to occur exactly once, and `replace` is what it becomes. To add text, find the lines it goes after and repeat them in `replace` followed by the addition. For a new page, give `new_path` (folders and file name ending in .md, relative to the wiki) and `content` (the whole page, frontmatter first), and `template` if it follows a page template. `summary` is one sentence shown to the reviewer; `from_notes` lists the ids of the notes the change came from.

**Input fields.** Required: `wiki`, `summary`, `from_notes`.

| Field | Type | Description sent to the model |
|---|---|---|
| `wiki` | string | "Alias of the wiki the page is in" |
| `page` | string | "Page id from read_page, for a change to an existing page" |
| `new_path` | string | "For a new page: path inside the wiki, ending in .md" |
| `template` | string | "For a new page: id of the page template it follows, if any" |
| `summary` | string | — |
| `from_notes` | list of strings | — |
| `edits` | list of `{find, replace}` | — |
| `content` | string | — |

The exact JSON is `PROPOSE_PAGE["inputs"]` in `tools.py`.

**Checks in `tools.py`.** Each failure goes back as an error the agent can fix:
- `wiki` is an open wiki.
- **`wiki` is the team wiki** (its role in Settings, read when the run's tools are made). Any other wiki, view-only or personal, comes back as the role refusal, for example `Northwind is view only; choose a team wiki in Settings. Changes may only be proposed in: team.` `read_page` is not limited: the agent may read pages in any open wiki, view-only ones included.
- **`wiki` is one of the job's `targets`.** The Promotion tab sets `targets` to the alias of every open wiki except the personal one (a job without `targets` doesn't start). A proposal anywhere else comes back as `Changes may only be proposed in: team. "personal" is where the pages came from.` `read_page` is not limited: the agent may read pages in any open wiki.
- `summary` isn't empty.
- `from_notes` isn't empty and lists only the personal pages sent in this run.
- Exactly one of `page` (with `edits`) or `new_path` (with `content`) is given.

**Edits**
- The page was read in this run, belongs to `wiki`, and is a wiki page (not a script, note or template).
- Each `find` occurs exactly once, applied in order.
- The edits must actually change the page.

**New pages**
- The path ends in `.md` and has no `..`, dot-folders or characters Windows forbids.
- It isn't the wiki's rules file or inside its templates folder (both where the path list says, `wikis.rules_files` and `wikis.templates_dirs`), and it isn't anywhere the wiki scan wouldn't count as a page (the notes folder, `Templates/`). It doesn't exist yet. (Dot-folders, such as the `.wiki/` folder older versions wrote, are refused by the path check above.)
- `content` isn't empty.
- A `template`, if given, is a page template of the same wiki (an id or its name), and was read in this run. The card then carries `template` and `templateName`, and the app shows it.

**Both**
- If the result starts with frontmatter, it must parse as YAML.

On success the result is `Proposed: team:Planets/Saturn.md (card c3).`, and the card goes to the app as a progress line.

## 4. Agent settings

`agent.py` describes the agent in plain words (`make_agent`), as an agentlib `Agent`:

```python
Agent(
    name="team-wiki-manager",          # the only agent this code runs (AGENT_ID)
    engine="claude",                   # the engine settings' choice (pathlist.get_engine_settings())
    model=model_for(job),              # see "The model" below
    effort="low",                      # job setting "effort" overrides
    instructions=<the text of <run folder>/system.md>,
    tools=<read_page + propose_page + ask_reviewer, from tools.py>,
    tool_server="wiki",                # the model sees mcp__wiki__<tool>
    permission_mode="never_ask",       # our tools are pre-approved; anything else is denied, nobody asked
    max_turns=40,                      # job setting "maxTurns" overrides
    max_budget_usd=1.00,               # at API prices; job setting "maxBudgetUsd" overrides
    cwd="<run folder>",
    env=<see below>,
    timeout_s=1800,                    # one message's work, at most
)
# setup is agentlib's default, "lean": only our instructions and our tools (§5).
```

**The model** (`model_for` in `agent.py`): a model the job names (`settings.model`) wins. Otherwise it is the engine settings' model for this agent, `engines.<engine>.models["team-wiki-manager"]` in `engine.json` (`pathlist.get_engine_settings()`). That is the one place the default is kept; the app reads and writes it there. With neither, the engine's own default is used.

A feedback round or the reviewer's answers open the same agent with `agent.session(resume=<conversation id>, cost_base=<what the conversation has cost so far>)` ([§6b](#6b-feedback-rounds)).

**The environment** (`engine_env` in `agent.py`): for Claude, the app's switches (`ENGINE_ENV`), then any `env` block in the engine settings (`engines.claude.env` in `engine.json`), then, with *Also save each run's raw requests* ticked, `OTEL_LOG_RAW_API_BODIES=file:<run folder>/raw`:

```python
{"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
 "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",              # no file-changed notes, @file expansion, skill lists
 "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}     # no session-naming side request
```

agentlib's lean setup adds its own on top of these (no auto-memory, no claude.ai MCP servers, all tools loaded up front). Another engine gets none of the Claude switches.

**What Claude Code then sends** (seen in a raw request log, before agentlib; the options it is given are the same in effect):
- thinking `{type: "adaptive", display: "updates"}`
- `output_config.effort: "low"`
- `max_tokens` 128000
- context editing that clears old thinking

**Sign-in**
- The agent signs in exactly like typing `claude`: the computer's Claude Code login in `~/.claude`, or a gateway set by environment variables.
- The app no longer reads `~/.claude/settings.json` for a gateway's `env` block or an `apiKeyHelper`. A gateway's variables can go in the engine settings' `env` block instead.

**Side requests.** Claude Code would otherwise make one extra request per run just to name the session. That request re-sends the whole first message, uncached: about 4,800 tokens, or 10–15% of a Haiku run. `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` stops it; tested on 2026-11-01, no naming request appears in the raw log.

## 5. What is stripped, and how

agentlib's lean setup does most of this; the table says what it means on Claude.

| Normally included | Here | How |
|---|---|---|
| Claude Code's system prompt (coding rules, tool guidance) | Replaced by ours | lean setup: `instructions` are the whole system prompt |
| CLAUDE.md, user and project | Not loaded | lean setup (no setting sources) and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` |
| Settings: permissions, hooks, output styles, model choices | Not loaded | lean setup |
| Built-in tools (Read, Write, Edit, Bash, Glob, Grep, web, todo) | None | lean setup offers only the listed tools; `never_ask` denies anything else |
| Subagents (Agent/Task) | None | not offered (agentlib doesn't support subagents) |
| Skills and the skill list | None | no `skills`, and `CLAUDE_CODE_DISABLE_ATTACHMENTS=1` |
| Plugins and MCP servers from config files | None | lean setup (strict MCP config) |
| File-changed notes, task-list nudges, `@file` expansion | None | `CLAUDE_CODE_DISABLE_ATTACHMENTS=1` |
| Project files near the working folder | None | `cwd` is the run's own folder |
| Asking a human to approve a tool | Never | Our tools are pre-approved; everything else is denied with an error result (`permission_mode="never_ask"`) |

**Checked on 2026-11-01** (before agentlib):
- The init message's tool list was exactly `mcp__wiki__propose_page, mcp__wiki__read_page`. `log.jsonl` records the offered tools on every run (the `init` entry, short names).
- A raw request log showed only the two tools, the system prompt above and the reminder in §2.

## 6. Seeing what was sent

Every run has a folder in the path list's `run_history` (`<.wiki folder>/ingest-runs/<run id>/` by default). **Open run folder** in the Ingest view opens it.

| File | Contents |
|---|---|
| `job.json` | What the app asked for: `date`, `notesDir`, `wikis`, `notes`, `settings`, `targets`, `agent: "team-wiki-manager"` (may be left out), and the `runId` the host adds. `notes` are the personal pages chosen. |
| `system.md` | The system prompt, exactly as sent (without Claude Code's two lines) |
| `first-message.md` | The first user message, exactly as sent (without Claude Code's reminder) |
| `log.jsonl` | Progress events, the offered tools and model (`init`, from agentlib's `s.info`), every tool call and its input, Claude's short remarks, rate-limit notices, cards, and the result with cost and tokens |
| `transcript.json` | The run summed up, written when it ends (also when it fails), and extended by each feedback round; see below |
| `session.json`, `feedback-<n>.json`, `answers.json`, `answers-message.md` | What a feedback round needs to continue the run (the conversation id, what it has cost so far, pages read, cards, questions), each piece of feedback sent ([§6b](#6b-feedback-rounds)), and the reviewer's answers |
| `raw\` | Only with *Also save each run's raw requests* on (in Agents and rules): every request and response body as Claude Code sent it (`OTEL_LOG_RAW_API_BODIES`, Claude only). This is the only place the full request is visible. |

To try the prompts without calling Claude: `.venv\Scripts\python.exe ingest\run.py <job.json> --prepare-only`, from `App Files` (`.venv/bin/python` on macOS).

### transcript.json and Past runs

The Ingest view's **Past runs** list (the 30 newest run folders) opens any run's `transcript.json` in a window. The transcript holds:

| Part | Contents |
|---|---|
| `model`, `ok`, `message`, `started`, `finished`, `notes` | Which model actually ran (as the engine reports it), how the run ended, and which personal pages it covered |
| `context` | Approximate tokens (characters ÷ 4) of what was sent up front: the system prompt, each wiki's index, each note |
| `steps` | One per request to Claude as far as it can be seen, in order: a step ends when our tools have answered, and Claude's next words or tool calls start the next one (a request with only thinking doesn't show). Each has the tools it called and Claude's short remarks. Its `tokens` and `cost` are `null` (the run window shows –): the engine reports tokens and cost once per message, so they are in `totals` and in each feedback round's entry. |
| `steps[].tools` | For `read_page`: the name asked for, the page it resolved to, and about how many tokens came back. For `propose_page`: the page, summary and number of edits. For `ask_reviewer`: the questions. For a tool the agent doesn't have: its name (and the denial). Each also records any error sent back. |
| `cards` | The cards proposed |
| `totals` | The engine's cost, the plain-Claude-Code estimate, total tokens, requests (model calls; `turns` is the same number), page reads, cards, duration, stop reason, `errorKind` (`budget`, `max_turns`, `other`, or null) |

**Where the numbers come from:** agentlib's `Reply` for each message (the run, a feedback round, the answers): `usage` (input, cache written, cache read, output tokens), `cost_usd` (that message's cost alone), `api_calls`, `duration_s`, `stop_reason`, `error_kind`. Live per-request token counts are no longer recorded.

## 6b. Feedback rounds

Each card is answered ✓, ✗ or ↻ (feedback), and **Submit** sends them all at once. The ↻ cards go back to Claude together, as one round that continues the *same run*.

**What happens on Submit**
1. The ✓ cards are written and the ✗ cards dropped (by the app, not the agent).
2. The host writes `feedback-<n>.json` to the run folder: `{"cards": [{"card": "c3", "text": "..."}], "accepted": ["c1"], "rejected": ["c2"]}`. `accepted` and `rejected` list every card decided so far in the run, dismissed ones counted as rejected.
3. It starts `run.py <job.json> --feedback <file>`.
4. `revise_cards` in `agent.py` loads `session.json`, which the run saved when it ended. It holds the conversation id, what the conversation has cost so far (`totalCostUsd`), the pages the agent read (proposals must still be based on them), and the cards so far.
5. It **continues that conversation** (`agent.session(resume=<conversation id>, cost_base=<totalCostUsd>)`) with the same agent as the run: same tools, instructions (the run's `system.md`), model and effort.
6. It sends one new user message, word for word (the decided line lists only what applies; with one card it says "Feedback on card c3:"):

```
The reviewer has gone through the cards. Accepted: c1, c4 (written to the wiki; leave them). Rejected: c2 (dropped).

Feedback on 2 cards:

<feedback card="c3" kind="edit" page="team:Planets/Saturn.md" summary="Adds the 10-28 sighting.">
Only keep the Titan observation, drop the ring tilt sentence.
</feedback>

<feedback card="c5" kind="new page" page="personal:Sessions/2026-10-30 Saturn.md" summary="A session page for 10-30.">
Name it after the date only.
</feedback>

Revise each of those proposals to follow its feedback: call propose_page again for the same page, which replaces that card. Read pages first if you need to. If feedback means a change shouldn't be made at all, don't call a tool for it; say so in one sentence that names the card. Don't propose anything else.
```

**What comes back**
- A new `propose_page` for the same page replaces the card under the **same id**. A proposal for another page would add a card.
- A proposal for a page whose card was already accepted or rejected is sent back as an error: "The reviewer already accepted card c1 for this page. Leave it as it is." (`RunMemory.decided` in `tools.py`). The app also ignores a revision of a card that isn't open.
- Claude's closing text is sent to the app as one `reply` event (`cards`, `text`, `revised`: the ids whose card changed). It's shown on each of the round's cards under its feedback ("You" / "Claude").
- The round ends with a `done` event (`feedback: true`) carrying the run's totals, `cards` (the round's card ids), `cardCount` (the run's number of cards) and `round` (the round's own totals).
- The round's cards need a new answer, revised or not.

**It's the same run, not a new one**
- The round's requests are added to the same `transcript.json`. They're tagged `"round": 1, 2, …`, and a `feedback` entry records each card's text and whether it changed, the accepted and rejected ids, Claude's reply, and the round's tokens and cost. (Rounds from before Submit had one card, as `card`, `page`, `text`; the run window shows both.)
- The run's totals (cost, tokens, requests, reads, duration) grow by the round's amounts. The plain-Claude-Code estimate is redone as if it were one longer session.
- Past runs still shows one row per run, marked "1 feedback round".
- While a round runs, the run shows as working: Ingest and Submit stay locked, and the round's cards show "Claude is revising this card…".

**Cost on a resumed session.** The engine's running total covers the whole conversation so far, but its token counts cover only the round. The conversation is opened with `cost_base` = what it had cost (`totalCostUsd` in `session.json`; for a run saved before agentlib, the transcript's total cost), so the reply's `cost_usd` is the round's alone. If the engine reports no cost, the round is priced from its tokens instead. The spending cap (`max_budget_usd`) starts again for each round.

**Caching, measured on 2026-11-01**
- A resume sends exactly the same prefix: tools, system prompt and the conversation so far. Everything up to the new message is therefore read from the cache.

| Run | Cache read | Newly cached | What that covers |
|---|---|---|---|
| CLI test | 11,036 tokens | 665 | Cache read is the whole earlier conversation: the last request had ended at 10,044 + 992 + 2. Newly cached is the feedback message plus the last answer. |
| Second round, same run | 12,021 tokens | 265 | Round cost $0.0029 |
| In the app, two requests | 23,059 tokens | 950 | Round cost $0.0095 |

- **After five minutes:** we assume the 5-minute cache (a set assumption, not tested). Feedback sent more than five minutes after the last request re-caches the conversation once, which costs the conversation's size at $2.50 per million tokens (a few cents at most on runs this size).
- **The agent's prompt and wiki rules:** a feedback round passes the run's own `system.md`, written when the run started, and doesn't rebuild it. Edits to an agent's prompt or a wiki's rules after a run only reach the next run, which also keeps the cache intact.
- **The `targets` and role checks** still apply to revised proposals: a feedback round reads the job's `targets` and the wikis' roles again.

**Each run leaves a Claude Code session file** under `~/.claude/projects/` (a folder named after the run folder). Resuming needs it; if it is gone, the round stops with "This run's Claude conversation can't be found any more" (agentlib's `ConversationMissing`).

## 7. Cost and the plain-Claude-Code estimate

**Cost** is the engine's own figure for the run (agentlib's `Reply.cost_usd`; on Claude, Claude Code's estimate). If the engine doesn't report one (a run that failed midway), the token counts are priced at the run model's list prices instead (`PRICES` in `costs.py`, by model family). On a Claude subscription a run isn't billed per token, it counts toward the plan's usage; the cost is what the tokens would cost at API prices, for comparing runs and models. Per million tokens, in / cache write / cache read / out:

| Model | In | Cache write | Cache read | Out |
|---|---|---|---|---|
| Haiku 5.5 | $0.10 | $0.125 | $0.01 | $0.50 |
| Sonnet 5.5 | $2.00 | $2.50 | $0.20 | $10.00 |
| Opus 5.5 | $4.00 | $5.00 | $0.20 | $20.00 |
| Fable 5.1 | $10.00 | $12.50 | $0.25 | $50.00 |

The same prices are used for the plain-Claude-Code estimate.

**Plain Claude Code ≈** estimates the same run in an ordinary Claude Code session, which sends more with every request. The estimate adds this assumed extra context, about 35k in all, which is what a normal session's starting context shows:

| Assumed extra per request | Tokens |
|---|---|
| Built-in tool definitions | 14,000 |
| System prompt | 12,000 |
| CLAUDE.md and memory | 5,000 |
| Skills and MCP lists | 4,000 |
| **Total** | **35,000** |

- The first request writes that extra to the prompt cache at $2.50 per million tokens: the 5-minute cache rate (1.25 × input). This is a set assumption, not measured.
- Each later request in the run reads it back at $0.20 per million.
- The figures are `PLAIN_CLAUDE_CODE_EXTRA` and `PRICES` in `costs.py`.

Example: a 5-request run adds 35,000 × $2.50/M + 4 × 35,000 × $0.20/M = $0.1155. A $0.056 run therefore shows as ≈ $0.172.

**What the estimate leaves out:** a plain session would also load CLAUDE.md files, and it often makes more requests. It shows the overhead, not a measured comparison.

## 8. Scripts that shape what the agent sees

| Script | Effect on the agent's view |
|---|---|
| `wikis.py` | Which pages and page templates exist and how they're described. A page or template with a weak `description` is easy for the agent to miss. |
| `prompts.py` | Reads the agent's prompt, appends the Wikis section, builds the first message, the feedback message and the answers message, from the prompt slots |
| `agent.py` | Which engine runs the team wiki manager, what it is given (model, effort, tools, limits, environment: §4), saving everything to the run folder |
| `tools.py` | What `read_page` can open and returns, which proposals are accepted or sent back with an error (the `targets` check included), and `ask_reviewer` |
| `<wiki>/Templates/Pages/*.md` | Page templates: their names and descriptions are in the index; their text only when read |
| The `prompt.team-wiki-manager` slot (`<.wiki folder>/prompts/team-wiki-manager.md` by default) | The instructions: the person's own copy of the agent's prompt, editable in the app. Its body is the first part of the system prompt. |
| `agents/team-wiki-manager/SKILL.md` | The shipped default of that file |
| The other prompt slots (`prompt.wikis-section`, `prompt.promotion-first-message`, `prompt.ingest-feedback`, `prompt.ingest-answers`) | The wording of each message; shipped defaults in `agents/messages/` |
| `engine.json` (the engine settings) | Which engine runs the agent, its default model (`models["team-wiki-manager"]`), and any extra `env` |
| `agents/agentfiles.py` | Which file is read, and stripping its frontmatter |
| `<wiki>/wiki_rules.md` (or where the path list points) | Per-wiki rules, inside the system prompt |

**Gone as inputs.** `ingest/agent-prompt.md`, the old *Your notes* file (`user-notes.md`), the note taker's prompt (`prompt.note-taker`) and the Notes run's first message (`prompt.ingest-first-message`) are not read by this code.

## 9. Notes

These come from the Claude API guidance and the Agent SDK docs (agentlib runs the agent on that SDK today).

**Model**
- **Model id:** the id picked in the model menu, exactly as the engine lists it (`ingest/models.py`: agentlib's `list_models`, which on Claude reads Claude Code's start-up handshake and makes no request; only ids starting `claude-` are offered). A model the job names wins; without one, the engine settings' model for `team-wiki-manager` is used, the one place that default is kept ([§4](#4-agent-settings)). Never add a date suffix. Through a gateway, Claude Code's list follows the gateway setup.
- **Larger models cost more per run:** Sonnet 5.5 about 20x Haiku 5.5's token prices, Opus 5.5 about 40x, Fable 5.1 about 100x (§7). No model has a recorded test on the team wiki manager's prompt (§10).
- **Thinking:** Haiku 5.5 and Sonnet 5.5 think adaptively by default. We leave thinking at the default. The prompt's planning step keeps some visible reasoning even at low effort.

**Effort**
- Haiku 5.5 defaults to `medium`; we set `low`, because output is most of a Haiku run's cost. (This was tested on the note taker's prompt; see §10.)
- Judge by cost per useful card, not cost per run.

**Tool use**
- **Tool choice:** forcing a tool (`tool_choice` `any` or `tool`) returns an error on Sonnet 5.5, so we never rely on it. The prompt steers the agent to `propose_page` instead; Claude Code uses `auto`.
- **Tool inputs:** parse them as JSON and check every field. Never match on the raw string, because escaping can differ. `tools.py` checks every field itself rather than trusting the model.

**Refusals and limits**
- A run can end with stop reason `refusal`, even on ordinary pages if a safety check misfires. `agent.py` (`how_it_ended`) treats it as a failed run: the cards it made can still be reviewed.
- `max_budget_usd` is a client-side estimate, checked between model calls, so it can be slightly exceeded. When it stops a run, agentlib's reply has `error_kind == "budget"`, and the app shows "The run hit its cost limit before finishing." (`error_kind == "max_turns"`: "The run hit its turn limit before finishing.")

**Prompt caching**
- The cache matches requests by prefix, in the order tools → system → messages. Keep the tool list and the agent's prompt stable, and put the indexes before the personal pages.
- Within a run, every turn re-sends the conversation, and cache reads keep that cheap ($0.01 per million tokens on Haiku 5.5, $0.20 on Sonnet 5.5).

**Practical limits**
- **Windows command-line limit:** Windows caps a command line at about 32 KB, and long wiki rules could pass it. agentlib sends a long system prompt to Claude Code as a temporary file for that reason.
- **Custom prompt:** a custom system prompt replaces Claude Code's sentence about system reminders; the team wiki manager's shipped prompt doesn't add one of its own.

**Prompt style**
- Current models follow instructions closely and literally.
- Explain why a rule exists, without capitals or "CRITICAL".
- Keep an agent's prompt short, and put wiki-specific detail in `wiki_rules.md`.
- An agent's prompt is also a Claude Code skill, so it has to read sensibly there too. The team wiki manager's says what to do in each place: propose with the tools in WikiApp, edit the team wiki's files directly when called as a skill.

**Auth and naming**
- **Auth:** the agent uses the computer's Claude Code sign-in (or a gateway set by environment variables).
- **Naming in the UI:** call it "Claude" or "Claude Agent" in the app, never "Claude Code". That's the SDK's branding rule for products built on it.

## 10. Model choice

No side-by-side test of models on the team wiki manager's prompt is recorded yet. (The tests recorded here before, on 2026-11-01, were of the note taker's prompt, which this code no longer runs.) The default is whatever the engine settings hold for `team-wiki-manager` ([§4](#4-agent-settings)); judge a model by cost per useful card on a batch of real personal pages, not by cost per run.

## The third tool: ask_reviewer

Offered on every run (the tools are built from the job's `targets`, which every run has).

**Description, as sent:** "Ask the reviewer up to 5 questions before proposing, when where a point belongs in the team wiki (or whether it holds in general) is unclear and the answer changes what you would write. Each question has `about` (the point it concerns, in a few words), `question` (one plain question), and for a question of where something goes, `options`: the candidate destinations as page ids or new-page paths. You can call this once per run. After calling it, stop and wait for the answers."

**Inputs:** `questions`, a list of `{about, question, options?}`.

**What it sends back:** on success, `N questions sent to the reviewer. Stop now: reply with just "Waiting." and call no more tools. The answers arrive as the next message.` The tool ends the agent's turn as soon as it succeeds (agentlib's `ends_turn`), so in practice no "Waiting." request is made: the run ends, and the app shows the questions (a `questions` event, and `questions: N` on `done`). As errors the agent can act on: no usable question, more than five, or a second call in the same run.

**The message that brings the answers back** (`write_answers_message`, from the `prompt.ingest-answers` slot), continuing the same conversation (`answer_questions` in `agent.py`, started by `run.py <job.json> --answers <answers.json>`):

```
The reviewer answered your questions.

<answer question="q1" about="...">
the answer, or: (Skipped. Leave this point out.)
</answer>

Now propose the changes, following these answers: read any page you still need first. A skipped question means that point is left out. Do not ask anything more.
```

The team wiki manager's own prompt (step 2, "Ask where it goes, when you can't tell") says when to ask and what about.
