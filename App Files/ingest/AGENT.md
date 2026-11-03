# The ingest agent: exactly what it sees

This file is the contract for what the ingest agent receives. If the code and this file disagree, fix one of them. The design of the feature as a whole is in [DESIGN.md](DESIGN.md).

**What reaches the model on each request, in this order:**
1. **Tool definitions:** `read_page` and `propose_page`, nothing else ([§3](#3-tools)).
2. **System prompt:** two short lines Claude Code always adds, then [agent-prompt.md](agent-prompt.md) with your notes and each wiki's rules filled in ([§1](#1-system-prompt)).
3. **First user message:** a short context reminder from Claude Code, then date, indexes and notes ([§2](#2-first-user-message)).
4. **The conversation so far:** the agent's tool calls and our tool results.

## 1. System prompt

**Source:** always the shipped [agent-prompt.md](agent-prompt.md), so app updates reach every user. The app shows it read-only, on the *Agent prompt* tab of the Edit ingestion prompt window. Users add instructions through *Your notes* in the same window.

The text is sent as written, after three replacements:

| Placeholder | Replaced with |
|---|---|
| `{{user_notes}}` | Nothing if *Your notes* is empty. Otherwise `## Notes from the user`, then the notes inside `<user_notes>` tags. |
| `{{wikis}}` | One block per open wiki, in workspace order (below) |
| `{{date}}` | Today's date. The shipped prompt doesn't use it; the date is in the first message. |

Each wiki block:

```
### Wiki "team"

<rules>
...the full text of team/wiki_rules.md, frontmatter included...
</rules>
```

A wiki without a rules file gets `<rules>No rules file. Follow the existing pages' style.</rules>`.

`prompts.py` (`write_instructions`) builds the finished text; `agent.py` writes it to `system.md` in the run folder and passes it to the SDK as a file (`system_prompt={"type": "file", ...}`).

**Before our prompt, Claude Code always adds two short lines.** There's no switch for these:
- an internal billing line (`x-anthropic-billing-header: cc_version=…; cc_entrypoint=sdk-py`)
- `You are a Claude agent, built on Anthropic's Claude Agent SDK.`

## 2. First user message

Built by `write_first_message` in `prompts.py` and saved to `first-message.md` in the run folder. Each wiki's index ends with its page templates, if it has any: name, id and description only ([DESIGN.md](DESIGN.md#page-templates)). The order puts what changes least first, which helps prompt caching:
- the indexes, which only change when pages change
- then the notes, which change every run

````
Today is 2026-11-01. Ingest the notes below into the wikis.

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

<note id="personal:Notes/2026-10-28 Club meetup.md" type="meeting" started="2026-10-28" ended="2026-10-28">
...the note's full text, frontmatter included...
</note>
````

- Notes are sent in full; nothing is cut.
- If the system prompt and first message together come to more than about 150,000 tokens (characters ÷ 4), the run stops before calling Claude and asks you to select fewer notes.

**After our text, Claude Code adds an environment block.** It's a system-role message, about 440 tokens, listing the working folder, platform, shell and OS. It can't be switched off.

**Before our text, Claude Code adds a context reminder.** It's a `<system-reminder>` block holding the signed-in account's email address and today's date, with a note that it isn't part of the user's message. It comes from the Claude Code login and can only be turned off in "bare" mode, which would also drop that login. The agent prompt's line about system reminders tells Claude to treat it as context, not instructions.

## 3. Tools

Each tool is a plain function in `tools.py`, next to a spec with its name, description and inputs (`READ_PAGE`, `PROPOSE_PAGE`). `tools_for_claude` serves them in-process (`create_sdk_mcp_server(name="wiki")`), so the model sees them as `mcp__wiki__read_page` and `mcp__wiki__propose_page`. A function signals a problem by raising `ToolError`; its message goes back to the agent with `is_error`. The descriptions and schemas below are sent word for word.

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
| No match | `No page matches "Titans". Closest: team:Moons/Titan.md, …` |
| A note, quick-note template or rules file | `<id> is not a wiki page (it is a note file).` |

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
- `summary` isn't empty.
- `from_notes` lists only notes in this run.
- Exactly one of `page` (with `edits`) or `new_path` (with `content`) is given.

**Edits**
- The page was read in this run, belongs to `wiki`, and is a wiki page (not a script, note or template).
- Each `find` occurs exactly once, applied in order.
- The edits must actually change the page.

**New pages**
- The path ends in `.md` and has no `..`, dot-folders or characters Windows forbids.
- It isn't in the notes folder, `Templates/`, `.wiki/` or `wiki_rules.md`, and doesn't exist yet.
- `content` isn't empty.
- A `template`, if given, is a page template of the same wiki (an id or its name), and was read in this run. The card then carries `template` and `templateName`, and the app shows it.

**Both**
- If the result starts with frontmatter, it must parse as YAML.

On success the result is `Proposed: team:Planets/Saturn.md (card c3).`, and the card goes to the app as a progress line.

## 4. SDK options

`agent.py` first describes the agent in plain words (`make_agent`):

```python
Agent(
    model="claude-haiku-5-5",         # the Ingest view's model menu (the job's settings.model)
    effort="low",
    instructions_file="<run folder>/system.md",
    tools=<read_page + propose_page, from tools.py>,
    max_turns=40,
    max_cost_usd=1.00,                # at API prices
    work_folder="<run folder>",
    save_raw_requests=False,          # the "Also save each run's raw requests" box
    continues_session=None,           # a feedback round: the run's conversation id
)
```

Then `claude_code_options(agent)` turns it into what Claude Code takes, switching off everything else:

```python
ClaudeAgentOptions(
    model="claude-haiku-5-5",                       # job setting "model" (the Ingest view's menu) overrides
    effort="low",                                   # job setting "effort" overrides
    system_prompt={"type": "file", "path": "<run folder>/system.md"},
    tools=[],                                       # no built-in tools
    mcp_servers={"wiki": <read_page + propose_page>},
    strict_mcp_config=True,
    allowed_tools=["mcp__wiki__read_page", "mcp__wiki__propose_page"],
    disallowed_tools=["Agent", "Task", "Bash", "Read", "Write", "Edit", "Glob", "Grep",
                      "WebSearch", "WebFetch", "TodoWrite", "NotebookEdit", "Skill"],
    permission_mode="dontAsk",
    setting_sources=[],                             # no CLAUDE.md, settings, hooks
    settings=<only "apiKeyHelper" from ~/.claude/settings.json, if present>,
    agents=None, skills=[], plugins=[],
    cwd="<run folder>",
    env={<the "env" block of ~/.claude/settings.json, if present: gateway URL, token, model names>,
         "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
         "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},   # no session-naming side request
    max_turns=40,
    max_budget_usd=1.00,
    resume=None,                                    # the conversation id, in a feedback round
    include_partial_messages=True,                  # each request's final output tokens, for the transcript
)
```

**What Claude Code then sends** (seen in a raw request log):
- thinking `{type: "adaptive", display: "updates"}`
- `output_config.effort: "low"`
- `max_tokens` 128000
- context editing that clears old thinking

**Sign-in**
- There's no `cli_path`, so the SDK uses the Claude Code engine bundled with it (2.1.316 at setup).
- That engine signs in with the computer's Claude Code login in `~/.claude`.
- The installed `claude` (2.1.160 here) wasn't used, because its "sonnet" meant Sonnet 4.6.

**Side requests.** Claude Code would otherwise make one extra request per run just to name the session. That request re-sends the whole first message, uncached: about 4,800 tokens, or 10–15% of a Haiku run. `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` stops it; tested on 2026-11-01, no naming request appears in the raw log.

## 5. What is stripped, and how

| Normally included | Here | How |
|---|---|---|
| Claude Code's system prompt (coding rules, tool guidance) | Replaced by ours | `system_prompt` as a file |
| CLAUDE.md, user and project | Not loaded | `setting_sources=[]` and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` |
| Settings: permissions, hooks, output styles, model choices | Not loaded | `setting_sources=[]`. Only the sign-in parts are passed. |
| Built-in tools (Read, Write, Edit, Bash, Glob, Grep, web, todo) | None | `tools=[]` and `disallowed_tools` |
| Subagents (Agent/Task) | None | `agents=None`, and Agent/Task disallowed |
| Skills and the skill list | None | `skills=[]` and `CLAUDE_CODE_DISABLE_ATTACHMENTS=1` |
| Plugins and MCP servers from config files | None | `plugins=[]`, `strict_mcp_config=True` |
| File-changed notes, task-list nudges, `@file` expansion | None | `CLAUDE_CODE_DISABLE_ATTACHMENTS=1` |
| Project files near the working folder | None | `cwd` is the run's own folder |
| Asking a human to approve a tool | Never | Our two tools are pre-approved; everything else is denied (`dontAsk`) |

**Checked on 2026-11-01:**
- The init message's tool list is exactly `mcp__wiki__propose_page, mcp__wiki__read_page`. `log.jsonl` records it on every run.
- A raw request log shows only the two tools, the system prompt above and the reminder in §2.

## 6. Seeing what was sent

Every run has a folder in `~/.wikiapp/ingest-runs/<run id>/` (`%TEMP%\WikiApp\ingest-runs\<run id>\` under `WikiApp.exe`). **Open run folder** in the Ingest view opens it.

| File | Contents |
|---|---|
| `job.json` | What the app asked for: notes, wikis, settings, your notes |
| `system.md` | The system prompt, exactly as sent (without Claude Code's two lines) |
| `first-message.md` | The first user message, exactly as sent (without Claude Code's reminder) |
| `log.jsonl` | Progress events, the init message's tools and model, every tool call and its input, Claude's short remarks, cards, and the result with cost and tokens |
| `transcript.json` | The run summed up, written when it ends (also when it fails), and extended by each feedback round; see below |
| `session.json`, `feedback-<n>.json` | What a feedback round needs to continue the run, and each piece of feedback sent ([§6b](#6b-feedback-rounds)) |
| `raw\` | Only with *Also save each run's raw requests* on: every request and response body as Claude Code sent it (`OTEL_LOG_RAW_API_BODIES`). This is the only place the full request is visible. |

To try the prompts without calling Claude: `.venv\Scripts\python.exe ingest\run.py <job.json> --prepare-only`, from `App Files` (`.venv/bin/python` on macOS).

### transcript.json and Past runs

The Ingest view's **Past runs** list (the 30 newest run folders) opens any run's `transcript.json` in a window. The transcript holds:

| Part | Contents |
|---|---|
| `model`, `ok`, `message`, `started`, `finished`, `notes` | Which model actually ran (from Claude Code's init message), how the run ended, and which notes it covered |
| `context` | Approximate tokens (characters ÷ 4) of what was sent up front: the system prompt, each wiki's index, each note |
| `steps` | One per request to Claude, in order. Each has its exact tokens (input, cache written, cache read, output), its cost at list prices, the tools it called, and Claude's short remarks. |
| `steps[].tools` | For `read_page`: the name asked for, the page it resolved to, and about how many tokens came back. For `propose_page`: the page, summary and number of edits. Each also records any error sent back. |
| `cards` | The cards proposed |
| `totals` | Claude Code's cost, the plain-Claude-Code estimate, total tokens, requests, turns, page reads, cards, duration, stop reason |

**Where the per-request numbers come from**
- Input and cache tokens come from each answer's start (`message_start`).
- The final output count comes from its end (`message_delta`). That's why `include_partial_messages=True` is on.
- The steps add up exactly to the run's totals.
- A step's cost uses list prices. It can differ slightly from Claude Code's total, which prices each cache write by how long it's kept.

## 6b. Feedback rounds

Each card is answered ✓, ✗ or ↻ (feedback), and **Submit** sends them all at once. The ↻ cards go back to Claude together, as one round that continues the *same run*.

**What happens on Submit**
1. The ✓ cards are written and the ✗ cards dropped (by the app, not the agent).
2. The host writes `feedback-<n>.json` to the run folder: `{"cards": [{"card": "c3", "text": "..."}], "accepted": ["c1"], "rejected": ["c2"]}`. `accepted` and `rejected` list every card decided so far in the run, dismissed ones counted as rejected.
3. It starts `run.py <job.json> --feedback <file>`.
4. `revise_cards` in `agent.py` loads `session.json`, which the run saved when it ended. It holds the Claude Code session id, the pages the agent read (proposals must still be based on them), and the cards so far.
5. It **resumes that session** (`options.resume = <session id>`) with the same options as the run: same tools, system prompt file, model and effort.
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
- The round's cards need a new answer, revised or not.

**It's the same run, not a new one**
- The round's requests are added to the same `transcript.json`. They're tagged `"round": 1, 2, …`, and a `feedback` entry records each card's text and whether it changed, the accepted and rejected ids, Claude's reply, and the round's tokens and cost. (Rounds from before Submit had one card, as `card`, `page`, `text`; the run window shows both.)
- The run's totals (cost, tokens, requests, reads, duration) grow by the round's amounts. The plain-Claude-Code estimate is redone as if it were one longer session.
- Past runs still shows one row per run, marked "1 feedback round".
- While a round runs, the run shows as working: Ingest and Submit stay locked, and the round's cards show "Claude is revising this card…".

**Cost on a resumed session.** Claude Code's `total_cost_usd` covers the whole session so far, but its token counts cover only the round. So the round's cost is the reported total minus the run's previous cost. If that ever came out negative, the round would be priced from its tokens instead.

**Caching, measured on 2026-11-01**
- A resume sends exactly the same prefix: tools, system prompt and the conversation so far. Everything up to the new message is therefore read from the cache.

| Run | Cache read | Newly cached | What that covers |
|---|---|---|---|
| CLI test | 11,036 tokens | 665 | Cache read is the whole earlier conversation: the last request had ended at 10,044 + 992 + 2. Newly cached is the feedback message plus the last answer. |
| Second round, same run | 12,021 tokens | 265 | Round cost $0.0029 |
| In the app, two requests | 23,059 tokens | 950 | Round cost $0.0095 |

- **After five minutes:** we assume the 5-minute cache (a set assumption, not tested). Feedback sent more than five minutes after the last request re-caches the conversation once, which costs the conversation's size at $2.50 per million tokens (a few cents at most on runs this size).
- **Your notes and wiki rules:** a resumed session reuses the system prompt it recorded on its first request. Edits to your notes or a wiki's rules after a run only reach the next run, which also keeps the cache intact.

**Each run leaves a Claude Code session file** under `~/.claude/projects/` (a folder named after the run folder). Resuming needs it.

## 7. Cost and the plain-Claude-Code estimate

**Cost** is Claude Code's own figure for the run (`total_cost_usd`). If Claude Code doesn't report one, the token counts are priced at the run model's list prices instead (`PRICES` in `costs.py`, by model family). On a Claude subscription a run isn't billed per token, it counts toward the plan's usage; the cost is what the tokens would cost at API prices, for comparing runs and models. Per million tokens, in / cache write / cache read / out:

| Model | In | Cache write | Cache read | Out |
|---|---|---|---|---|
| Haiku 5.5 | $0.10 | $0.125 | $0.01 | $0.50 |
| Sonnet 5.5 | $2.00 | $2.50 | $0.20 | $10.00 |
| Opus 5.5 | $4.00 | $5.00 | $0.20 | $20.00 |
| Fable 5.1 | $10.00 | $12.50 | $0.25 | $50.00 |

The same prices are used for each step's cost in the transcript and for the plain-Claude-Code estimate.

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
| `prompts.py` | Fills the instructions template, builds the first message and the feedback message |
| `agent.py` | What the agent is given (model, effort, tools, limits), the options above, saving everything to the run folder |
| `tools.py` | What `read_page` can open and returns, and which proposals are accepted or sent back with an error |
| `<wiki>/Templates/Pages/*.md` | Page templates: their names and descriptions are in the index; their text only when read |
| `agent-prompt.md` | The instructions (shipped, read-only in the app) |
| *Your notes* (`~/.wikiapp/ingest/user-notes.md`) | The user's additions, inside the system prompt |
| `<wiki>/wiki_rules.md` | Per-wiki rules, inside the system prompt |

## 9. Notes

These come from the Claude API guidance and the Agent SDK docs.

**Model**
- **Model id:** `claude-haiku-5-5` by default, or the id picked in the model menu, exactly as Claude Code lists it (`ingest/models.py`). Never add a date suffix. Through a gateway, Claude Code's list follows the gateway setup.
- **Larger models cost more per run:** Sonnet 5.5 about 20x Haiku 5.5's token prices, Opus 5.5 about 40x, Fable 5.1 about 100x (§7). The prompt was tuned on Haiku and Sonnet (§10); Opus and Fable haven't been tested on it.
- **Thinking:** Haiku 5.5 and Sonnet 5.5 think adaptively by default. We leave thinking at the default. The prompt's planning step keeps some visible reasoning even at low effort.

**Effort**
- Haiku 5.5 defaults to `medium`; we set `low`. In the tests `medium` wasn't better (§10), and output is most of a Haiku run's cost.
- Judge by cost per useful card, not cost per run.

**Tool use**
- **Tool choice:** forcing a tool (`tool_choice` `any` or `tool`) returns an error on Sonnet 5.5, so we never rely on it. The prompt steers the agent to `propose_page` instead; the SDK uses `auto`.
- **Tool inputs:** parse them as JSON and check every field. Never match on the raw string, because escaping can differ. `tools.py` checks every field itself rather than trusting the model.

**Refusals and limits**
- A run can end with stop reason `refusal`, even on ordinary notes if a safety check misfires. `agent.py` (`how_it_ended`) treats it as a failed run: the cards it made can still be reviewed, and no notes are marked.
- `max_budget_usd` is a client-side estimate and can be slightly exceeded.

**Prompt caching**
- The cache matches requests by prefix, in the order tools → system → messages. Keep the tool list and the shipped prompt stable, and put the indexes before the notes.
- Within a run, every turn re-sends the conversation, and cache reads keep that cheap ($0.01 per million tokens on Haiku 5.5, $0.20 on Sonnet 5.5).

**Practical limits**
- **Windows command-line limit:** Windows caps a command line at about 32 KB, and long wiki rules could pass it. That's why the system prompt goes to the SDK as a file.
- **Custom prompt:** a custom system prompt replaces Claude Code's sentence about system reminders, so `agent-prompt.md` has its own.

**Prompt style**
- Current models follow instructions closely and literally.
- Explain why a rule exists, without capitals or "CRITICAL".
- Keep `agent-prompt.md` short, and put wiki-specific detail in `wiki_rules.md`.

**Auth and naming**
- **Auth:** the agent uses the computer's Claude Code sign-in.
- **Naming in the UI:** call it "Claude" or "Claude Agent" in the app, never "Claude Code". That's the SDK's branding rule for products built on it.

## 10. Model choice (tested 2026-11-01)

Each configuration was run once, on copies of the sample wikis, with two note sets:
- **Set A:** the three sample notes.
- **Set B:** one harder planning-call note with traps: "Tom said…", a colleague's surgery, a fact update, a new event, a task, club dues and a Webb image with no home in the wiki.

**First round, earlier prompt:**

| Model, effort | Set A | Set B |
|---|---|---|
| Sonnet 5.5, medium | $0.070, 3 cards | $0.061, 5 cards |
| Sonnet 5.5, low | $0.023, 1 card | $0.049, 5 cards |
| Haiku 5.5, medium | $0.008, 6 cards | $0.0065, 6 cards |
| Haiku 5.5, low | $0.0065, 6 cards | $0.0041, 5 cards |

What the round showed:
- Haiku found as much or more of what the notes said.
- Haiku made no schema errors; Sonnet made several and had to retry.
- Haiku kept names out better.
- Every run left out the health detail and the "Tom said" attribution.
- Haiku 5.5 at low effort became the default.

**The current prompt (§1), Haiku 5.5 low:**

| Set | Cost | Cards | Result |
|---|---|---|---|
| A | $0.0057 | 5 | Every point placed on the page that's about it (the Titan sighting on Titan); no padded pages |
| B | $0.0039 | 3 | Both no-home items and the surgery left out; the volunteer handover left out because the task already had that owner; one minor gear note skipped |

**What the prompt does for a smaller model:**

| What it asks for | Why |
|---|---|
| A one-line-per-point plan before reading | Keeps visible reasoning at low effort. The plan appears in the transcript as Claude's notes. |
| An ordered placement test: rules first, then the page about the subject, then a new page only if all conditions hold, otherwise leave out | So points aren't forced onto loosely related pages |
| Explicit new-page conditions, with no padding to meet them | Keeps new pages conservative |
| "Write only what the notes say" | No outside facts |
| A check step before proposing | Catches errors before they become cards |
| Reply "Done." at the end | No closing summary in the output |

Haiku follows the wiki's rules for where things go. Rules with a "New pages" section (the starter template now has one) make it more predictable.

**Caveat:** one run per configuration on small notes. Runs vary, as the medium-effort runs showed. Check the results on a batch of real notes.
