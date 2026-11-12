# Ingest: design (V1)

Status: **built, V1**, on 2026-11-01. Paths in this file are inside the `App Files` folder. The agent's exact inputs are in [AGENT.md](AGENT.md). The shipped instructions are the team wiki manager's prompt: [team-wiki-manager](../agents/team-wiki-manager/SKILL.md).

> **The engine in `ingest/` now serves Promotion only.** It runs one agent, the team wiki manager, which reads chosen personal pages and proposes changes to the team wikis as cards. The Notes tab's old action (quick notes → the note taker → proposed page cards) is gone: notes now reach the personal wiki through the Sessions tab. Where this file still describes the Notes tab's screen, the cards and the run, read it as the Promotion tab's: the Promotion tab was built as the same screen and run, and the parts that applied only to the note taker no longer exist in the engine (a job naming another agent, or with no `targets`, stops before anything is sent).

**What this file covers.** The Ingest view's agents:

| Tab | Agent | Covered in |
|---|---|---|
| Sessions | Executive assistant | [sessions/README.md](../sessions/README.md) |
| Review | Wiki reviewer | [sessions/README.md](../sessions/README.md) |
| Promotion | Team wiki manager | This file ([Promotion](#promotion)) |

The **?** help button and the **✎ Agents and rules** button sit in the tab bar and belong to all four tabs.

## Goal

What is durable in the personal wiki (a finding, a decision, a method) only helps the team once it reaches the team wiki. The Promotion tab sends chosen personal pages to a Claude agent, the team wiki manager (its model is the engine settings' model for `team-wiki-manager` unless the tab sends one; it runs through agentlib, the shared agent library, on the Claude Agent SDK today). The agent proposes page changes, and nothing reaches a page until the user accepts the change with ✓. (Originally this design was for the Notes tab, which sent quick notes to a note taker; that flow is gone, see the status note above.)

## Note lifecycle

| State | Frontmatter | On the Ingest page |
|---|---|---|
| Open | `status: open` | No |
| Wrapped, not ingested | `status: wrapped`, no `ingested` | **Yes** |
| Wrapped and ingested | `status: wrapped`, `ingested: 2026-11-01` | No |

- A note becomes ingested when **every card from its run is resolved**, whether accepted or rejected. A run that proposes nothing for a note also counts as ingested.
- **Exception:** if any of the note's cards was dismissed because its page changed (see [Stale cards](#stale-cards)), the note is *not* marked. It returns to the list so it can be run again.
- A run that fails (error, refusal, turn or budget limit, stopped by the user) marks nothing. Any cards it did make can still be reviewed.

## The Ingest view

The rail button **Ingest** (Ctrl+5) has a badge: the number of the Notes tab's cards to review if there are any, otherwise the number of notes waiting. Each tab also shows its own count. The picture is the Notes tab, under the tab bar:

```
  Notes 2 │ Sessions 5 │ Review 1 │ Promotion 3                        [?] [✎ Agents and rules]
┌ Ingest ───────────────────────────────────────────────────┬─ Proposed changes      3 to review ┐
│ ☑ 2026-10-30 Daily     personal   daily · wrapped 10-30   │ ┃team┃ Saturn       EDIT  ✓ ✗ ↻   │
│ ☑ 2026-10-28 Club…     personal   meeting · wrapped 10-28 │ ┃    ┃ Adds the 10-28 sighting.    │
│ Select all     Model [Haiku 5.5 (default) ▾] [ Ingest 2 ] │ ┃    ┃ New links: Titan            │
│ ┌───────────────────────────────────────────────────────┐ │ ┃    ┃ − old line / + new line     │
│ │ ▓▓▓░░░ Reading team:Saturn                            │ │ ┃pers┃ 2026-10-30 …  NEW  ✓ ✗ ↻    │
│ │ 4 pages read · 2 changes proposed               Stop  │ │ ┃    ┃ Save as [Sessions/ ▾] …     │
│ └───────────────────────────────────────────────────────┘ │ 1 of 2 still needs an answer [Submit] │
└───────────────────────────────────────────────────────────┴───────────────────────────────────┘
```

**Left side**
- Every wrapped, un-ingested quick note from all wikis, newest first, with checkboxes. Clicking a title opens the note.
- **Model**, next to Ingest: the models Claude Code offers on this computer, by their exact names, with Haiku 5.5 the default. The host fills it with `listIngestModels`, which runs `ingest/models.py`: it asks agentlib for the engine's models (`list_models`; on Claude it starts Claude Code, reads the list from its start-up handshake, one entry per model with aliases like `default` and `opus` folded into the model they name, and stops it). No request is made, so it's free; it takes a few seconds, once per app start, and the last list is kept in the settings. The choice is remembered and sent as the job's `settings.model`.
- **Ingest** is disabled while a run is going, or while any card waits on the right, and says why. So only one run exists at a time, and a new run never mixes with old cards.
- **Progress box.** While running: the current step (*Building index*, *Reading notes*, *Reading team:Saturn*…), pages read, changes proposed, and **Stop**.
- **After a run:** the result, then **Cost $0.06 · plain Claude Code ≈ $0.22 ⓘ**, the token counts, and **Open run folder**. The plain-Claude-Code figure is explained in [AGENT.md](AGENT.md#7-cost-and-the-plain-claude-code-estimate).
- **Past runs:** a collapsed list of the 30 newest runs: when, notes, changes and cost. Clicking one opens its transcript. The window shows:
  - the totals: cost, tokens sent and written, requests, reads, duration;
  - the model that ran;
  - roughly how many tokens each part sent up front used;
  - a step-by-step table: each request's tool calls (pages read with their approximate tokens, proposals, errors sent back), its exact tokens and its cost;
  - the cards.

  It's built from each run's `transcript.json` ([AGENT.md §6](AGENT.md#6-seeing-what-was-sent)).

**Right side: one card per page.** The left border and the alias chip use the wiki's color, so it's clear which wiki a change lands in.

| Part | What it shows |
|---|---|
| Header | Wiki chip, page title (for an edit, the title opens the page), EDIT or NEW, then the answers ✓ ✗ ↻ |
| Feedback | When the answer is ↻, a box for what Claude should change. Earlier exchanges stay on the card ("You" / "Claude"). |
| Summary | The agent's one sentence |
| From | The notes the change came from |
| New tags | Tags added to the frontmatter. The app works these out by comparing before and after, so they don't depend on the agent's word. |
| New links | Links added. A link to a page that doesn't exist (and isn't created by another card) is red. |
| Edit | A red/green line diff with two lines of context |
| New page | **Save as** with a folder picker (any folder except the notes folder and `Templates`), plus a collapsed rendered preview |

**Answers, then Submit.** Pressing ✓, ✗ or ↻ only records the card's answer (pressing it again clears it); the card's border shows it. Nothing is written or sent until **Submit**, in a bar at the bottom right of the cards. The bar says how many cards still need an answer, or what Submit will do ("2 to write · 1 to drop · 1 card back to Claude"). Submit is enabled once every card has an answer: ↻ needs some feedback text, and a stale card's only answer is Dismiss. Ctrl+Enter in a feedback box also submits. Then:
1. ✓ cards are written, one by one (below). One that fails (its page changed meanwhile) stays open with no answer, and a message says why.
2. ✗ cards are dropped, and dismissed ones marked dismissed.
3. The ↻ cards go to Claude together, in **one feedback round**: one message with the feedback on each card and which cards were accepted and rejected. Claude revises those cards in the same conversation, and each is replaced under the same id, or Claude says in a sentence why it won't change it. The revised cards need a new answer. It counts toward the same run ([AGENT.md §6b](AGENT.md#6b-feedback-rounds)).

Cards and their answers (and feedback being typed) survive closing the app: they're saved in the path list's `pending_promotion` (`<.wiki folder>/ingest/pending-promotion.json` by default). If the app closes during a run, the run counts as failed when it reopens.

### The ? button

In the tab bar, for every tab. **How Ingest works** explains, for someone who has never seen an agent, using the Notes tab as the example:
- what happens when you press Ingest, in six steps;
- the words used: agent, agent loop, tool, model, Claude Agent SDK, prompt, feedback, index, card, tokens and cost;
- a diagram of Claude with its loop and its two tools, between your notes and your pages.

### Agents and rules

In the tab bar, for every tab (`openPrompt` in `ingestdialogs.js`).

| Tab | What it is | Saved to |
|---|---|---|
| Agents | A list of the four agents: name, tab, what it does, and **See the prompt**. That opens the agent's whole prompt for editing, with **Save** and **Reset to default** (the shipped text goes in the box; nothing changes until Save). | `~/.claude/skills/<agent id>/SKILL.md` |
| Page templates | A list, not text: every wiki's page templates, and **New page template** ([Page templates](#page-templates)) | `<wiki>/Templates/Pages/<name>.md` |
| *alias* rules, one per wiki | That wiki's rules | `<wiki>/wiki_rules.md`, through the host like any note |

**One prompt file per agent, and it is a Claude Code skill.**
- The ids are `executive-assistant`, `wiki-reviewer` and `team-wiki-manager`. The file is `~/.claude/skills/<agent id>/SKILL.md`, so the text the app sends is the text Claude Code uses when the skill is called there.
- The defaults ship in `agents/<agent id>/SKILL.md`. One is copied to the skills folder the first time it's needed, and never again, so a person's edits survive app updates. Until a file exists, a run uses the shipped default. Opening this window makes any file that's missing, and so does starting a Notes or Promotion run.
- Each shipped skill has `disable-model-invocation: true` in its frontmatter, so Claude Code runs it only when it is called by name.
- An agent is sent the body of its file: everything after the frontmatter (the lines between the two `---`). Save refuses text without that frontmatter, because Claude Code needs the skill's name and description.
- The code adds the rest for each request: the material, each wiki's rules, the reply format. Those parts aren't in the file, so editing a prompt can't break a run.
- `agents/agentfiles.py` does all of this. `WIKIAPP_SKILLS_DIR` overrides the skills folder, for tests.
- **The old "Your notes" file** (`~/.wikiapp/ingest/user-notes.md`) is not an input to this engine.

**Rules**
- A wiki's `wiki_rules.md` reaches every agent that works in that wiki. The team wiki manager gets the team wiki's rules only (each other wiki is named with its role, without rules); the executive assistant and the wiki reviewer get the personal capture rules instead of any `wiki_rules.md`.
- A wiki without a rules file starts from a short starter, and saving creates the file.
- `wiki_rules.md` is hidden from the graph, tags, tasks and link suggestions, like `Templates/`, but still shows in the file tree.

**Also in the window**
- A checkbox, *Also save each Promotion run's raw requests*, turns on raw request logging into the run folder.
- Saving applies to the next run.

## Promotion

The Promotion tab (`createIngestView` with `mode: 'promotion'` in `main.js`) is the only tab this engine serves. It was built as a second copy of the old Notes tab's screen; the run, the tools, the cards, the answers, Submit, feedback rounds and past runs work as described in this file.

| Part | Promotion |
|---|---|
| Agent | Team wiki manager (`team-wiki-manager`; the job's `agent` may say so or be left out) |
| The list | From the personal wiki (the wiki whose role is `personal`): topic and folder pages (frontmatter `type: topic` or `type: folder`) with no `promoted` time, or one earlier than `changed`; and `promotion-queue.md` while it has unticked (`- [ ]`) findings, listed first. **Show already promoted** lists promoted pages again |
| Where changes may go | The team wiki only: the wiki whose role is `team` (Settings; `pathlist.wiki_roles`), which must also be in the job's `targets`. A job without `targets`, or with a target that isn't the team wiki, doesn't start (`agent.target_refusal`, with the role in plain words); `tools.py` refuses a proposal anywhere else. View-only wikis can still be read. |
| First message opens | "Promote what is durable in the personal pages below into the team wiki." (the `prompt.promotion-first-message` slot) |
| Default model | The engine settings' model for `team-wiki-manager` (`engine.json`, `pathlist.get_engine_settings()`), the one place it is kept; a model the job names wins |
| Button | **Promote** |
| Cards saved in | The path list's `pending_promotion` (`<.wiki folder>/ingest/pending-promotion.json` by default) |
| When every card is handled | Each promoted page gets `promoted: <today>`. The queue lines the run saw when it started are ticked (`- [x]`). |

- The selected pages are sent in full, as the job's `notes`, so `from_notes` on a card names the personal pages a change came from.
- Promote is disabled, with the reason, until a personal wiki is chosen in the Sessions tab and at least one other folder is open.
- A topic can be selected only once it has been reviewed since it last changed: its `state_as_of` is set, `needs_review` is false and `entries_since_review` is 0 (`needsReview` in `ingestview.js`). Otherwise its checkbox is disabled and the row says to review it first, in the Review tab. Folder pages and the queue need no review.
- A promoted page returns to the list when its `changed` time becomes later than its `promoted` time (`promotedAlready`; a page with no `changed` is compared by `updated`). `sessions/sb.py` stamps `changed` on a topic page when a capture, a review, a merge or a move into a folder writes it. A folder's hub page gets a new `changed` when topics are moved into it or its tag is merged; a refresh of its list of topics alone doesn't change it.
- The **Show already promoted** checkbox also lists pages that haven't changed since they were promoted, so one can be sent again.
- The team wiki manager never creates a page for a table. Table pages come from the data dictionary skill, run in Claude Code. A finding about a table with no page goes on its subject area's page, and the card's summary says the table has no page. This rule is in the agent's prompt, and in the team wiki rules template (`sessions/templates/team-wiki_rules.md`); the code doesn't check it.
- The same exceptions apply as for notes: a failed run marks nothing, and a page with a dismissed (stale) card isn't marked.
- Host calls `ingestInfo` and `saveIngestState` take `name`: `"promotion"` (the default; any other name is refused). Only one run goes at a time.

## Cards and applying changes

The agent never writes files. Each card carries the page's text as the agent read it and the text after the change:

```json
{ "id": "c3", "run": "2026-11-01_193642", "wiki": "team", "kind": "edit",
  "page": "team:Planets/Saturn.md", "path": "Planets/Saturn.md", "title": "Saturn",
  "summary": "Adds the 10-28 sighting.", "fromNotes": ["personal:Notes/2026-10-28 Club meetup.md"],
  "before": "…the page as read…", "after": "…the page with the change…", "status": "open" }
```

A new page has `kind: "new"`, `page: null` and `before: ""`.

| Answer, on Submit | What happens |
|---|---|
| ✓ on an edit | The host's `editLines` replaces the whole file, but only if its lines still equal `before`. The host keeps the file's line endings and BOM. |
| ✓ on a new page | The host's `createNote` creates the file at the chosen path. It fails if the file exists. |
| ✗ | Drops the card. |
| ↻ | Sent to Claude with the round's other feedback; the card stays open until Claude answers. |

### Stale cards

Whenever the folders are rescanned, each open card is checked:
- **An edit is stale** if the page's text no longer equals `before`.
- **A new page is stale** if a page now exists at its path.

A stale card turns grey and offers only **Dismiss**. Dismissing it keeps the card's notes un-ingested, so they can be run again against the new text.

### End of a run

When the last card is resolved, the app adds `ingested: <today>` to each qualifying note (see [Note lifecycle](#note-lifecycle)). It then clears the run, keeping a one-line summary with its cost.

## What runs automatically, and what the agent does

| Step | Done by | AI? |
|---|---|---|
| Collect the selected notes (or the pages to promote), the wikis and the settings into a job | App and host | No |
| Rebuild every wiki's index | `ingest/wikis.py`, at the start of each run | No |
| Read the agent's skill file, add each wiki's rules, write the first message, save both texts to the run folder | `ingest/prompts.py`, called from `ingest/agent.py` | No |
| Decide what's worth keeping, find pages, read them, follow links, pick a page template for a new page, draft changes | **The agent** | **Yes** |
| Check every proposal; send fixable errors back to the agent | `ingest/tools.py` | No |
| Report progress, cards, cost | `agent.py` → host → app | No |
| Work out new tags and links, flag missing link targets | App | No |
| Apply on ✓, detect stale cards, mark notes ingested (or pages promoted) | Host and app | No |

## The index

At the start of each run, `wikis.py` writes `<wiki>/.wiki/index.md` for every wiki. The host skips dot-folders, so the index never shows in the app. One line per page:

```
- Saturn | team:Planets/Saturn.md | The ringed gas giant. | tags: planet, giant | links: Titan
```

Then, if the wiki has any, its page templates: only their name, id and description, never their text.

```
Page templates (for new pages; each line: template name | id | when to use it):
- Observing session | personal:Templates/Pages/Observing session.md | One night out observing. Use for every new page in Sessions/.
```

| Included | Left out |
|---|---|
| Pages: name, id, frontmatter `description`, tags, `##` sections, links | The notes folder, quick-note templates, `wiki_rules.md`, dot-folders and hidden files |
| Scripts, listed by file name | |
| Page templates (`Templates/Pages/`): name, id, `description` | The templates' text: the agent reads one with `read_page` only when it's about to propose a new page |

Link resolution in Python follows `vault.js`:
- `[[team:Name]]` looks only in that wiki.
- A plain name looks in its own wiki first, then the others in workspace order.
- A link with `/` matches by path, and the shortest path wins.

`wikis.py` also runs on its own: `python wikis.py team=C:\wikis\team personal=C:\wikis\personal`.

## Page templates

A wiki's `Templates/Pages` folder holds templates for the new pages Ingest proposes, so new pages of one kind look alike. (Its sibling, `Templates/Notes`, holds the quick-note templates.) A folder linked without a `Templates` folder starts with one sample of each, copied from `app/templates/`.

- **One Markdown file per template.** The file name is its name; its frontmatter `description` says when to use it; the rest is the layout (frontmatter fields and headings, with placeholders like `{{title}}`).
- **Claude sees only the list** (name, id, description) at the end of each wiki's index. It reads a template only when it's about to propose a new page that fits, follows its fields and headings (keeping a heading even when the notes have nothing for it yet), writes the page's own description, and names the template in `propose_page`'s `template`. `tools.py` checks that it's a page template of the same wiki and that it was read.
- **The card** for that new page shows **Template:** with a link to it. Templates can't be changed by a proposal.
- **Agents and rules → Page templates** lists every template (wiki, name, when to use it, a link to the file that opens it in the editor) and makes a new one from a starter in the chosen wiki. A template without a description is flagged.
- **Kept out of the way:** everything under `Templates/` is left out of the graph, tags and tasks, and the New note menu lists only files directly in `Templates/`.
- **Why a folder and not a list in the prompt:** nothing to keep in step. A template's name and purpose live in the file itself.

## The agent

Everything it receives is in [AGENT.md](AGENT.md). In short:

| | |
|---|---|
| Library | agentlib (`General-Purpose-Productivity/agentlib`), never an agent SDK directly. On the `claude` engine (the engine settings' default) it runs the Claude Agent SDK and the Claude Code engine that ships inside it. |
| Sign-in | The computer's existing Claude Code login (`~/.claude`), or a gateway set by environment variables. No API key. `~/.claude/settings.json` is no longer read; a gateway's variables can go in the engine settings' `env` block. |
| Instructions | The body of the team wiki manager's prompt (the `prompt.team-wiki-manager` slot), then each wiki's role, and the team wiki's rules. |
| Model | The one picked in the tab's model menu (the job's `settings.model`), else the engine settings' model for the agent. The Notes menu defaults to `claude-haiku-5-5`; the Promotion menu defaults to `claude-sonnet-5-5`. Effort `low`, adaptive thinking; a job's `settings.effort` can change the effort. Haiku is the Notes default on cost; see [AGENT.md §10](AGENT.md#10-model-choice-tested-2026-11-01). |
| Tools | `read_page` and `propose_page`, plus `ask_reviewer` in a promotion. Every built-in tool is off (agentlib's lean setup), and anything else is denied (`never_ask`); `log.jsonl` records the tools offered. |
| Context | Our system prompt only. No CLAUDE.md, settings, hooks, skills, subagents, plugins or other MCP servers. The skill file is read by our code and sent as the system prompt; Claude Code's own skill loading stays off. |
| Limits | 40 turns, $1.00 per run (a feedback round or the answers get their own $1.00) |

**Why two custom tools and not the built-in Read**
- `read_page("Titan")` resolves links the way the app does, so following a link just works.
- A miss returns the closest names, so the agent can try again without a search tool.
- It can only open pages and scripts in the open wikis.
- Its definition is much shorter than Read's.

## Files

| Path | What it is |
|---|---|
| `ingest/DESIGN.md`, `ingest/AGENT.md` | This design, and exactly what the agent sees |
| `agents/<agent id>/SKILL.md` | The shipped prompt of each agent; `team-wiki-manager` is the one this code runs |
| `agents/agentfiles.py` | Where each agent's prompt lives (`~/.claude/skills/<agent id>/SKILL.md`): seeding it from the default, reading it, its body without the frontmatter, saving it |
| `ingest/agent.py` | **The agent, explained for newcomers:** what it's given (model, effort, instructions, tools, limits), one run, a feedback round, following its loop. Start reading here. |
| `ingest/tools.py` | Its two tools as plain functions, `read_page` and `propose_page`, with every proposal check |
| `ingest/prompts.py` | The text it's given: instructions (the skill file's body, then a "Wikis" section with each wiki's rules), first message, feedback message |
| `ingest/run.py` | The command line the host starts. `--prepare-only` builds the prompts without calling Claude. |
| `ingest/wikis.py` | Wiki scanning, link resolution, the index and page templates |
| `ingest/transcript.py`, `ingest/costs.py`, `ingest/progress.py` | The run's record, its prices and totals, and its progress lines and log |
| `ingest/models.py` | Prints the models Claude Code offers, for the model menu (no request to Claude) |
| `setup.py`, `requirements.txt` (in `App Files`) | The app's setup: `App Files/.venv` with pywebview, `claude-agent-sdk` and `pyyaml` |
| `host/ingestruns.py` | The host's side of the Promotion tab, and of the agents' prompt files |
| `app/js/ingestview.js` | The Notes and Promotion tabs: the list, model menu, cards, diff, answers and Submit, applying and marking |
| `app/js/ingestdialogs.js` | The Agents and rules, How Ingest works and past run windows |
| `app/js/main.js` | The four tabs (`showIngestTab`) and the tab bar's two buttons |
| `<wiki>/wiki_rules.md` | That wiki's rules, for every agent that works in it |
| `<.wiki folder>/ingest/` | `pending-promotion.json` (the Promotion tab's cards and last run; the path list's `pending_promotion`) |
| `~/.wikiapp/ingest-runs/<id>/` | One folder per run: `job.json`, `system.md`, `first-message.md`, `log.jsonl`, `transcript.json`, `session.json`, any `feedback-<n>.json`, optionally `raw/` |

Everything is kept in `~/.wikiapp`, not `%LOCALAPPDATA%`, because the Microsoft Store build of Python can't see other programs' folders in `%LOCALAPPDATA%`.

**Host messages:** `ingestInfo` and `saveIngestState` (both take `name`: `"promotion"`), `agentsInfo`, `saveAgentPrompt`, `startIngest`, `reviseIngestCards`, `cancelIngest`, `runIngestSetup`, `listIngestRuns`, `openIngestRun`, `listIngestModels`.
- The host starts the `.venv` Python with `-X utf8 ingest/run.py <job.json>`, with no window.
- It passes each stdout line to the page as an `ingest` event, and sends `ingestExit` when the process ends.
- **Stop** kills the process tree: `taskkill /T` on Windows, the process group on macOS.

## Setup and requirements

- Python 3.10 or newer; the Store build works.
- Claude Code signed in on the computer.
- The app's own setup installs the packages, on the first start (about 200 MB; the SDK bundles the Claude Code engine). **Run setup** in the Ingest view reinstalls or updates them.

## Tested (2026-11-01, on copies of the samples)

These records are from before the prompts became skill files. Where they name the "Your notes" file or the "Agent prompt" tab, they mean the window that Agents and rules replaced. No test of the Agents tab, the skill files or the Promotion tab is recorded here yet.

- **From the command line:**
  - A prompt-only run, then real runs on Sonnet 4.6 (the installed Claude Code 2.1.160's "sonnet") and on `claude-sonnet-5-5` (the bundled engine).
  - Each run made 4 to 5 page reads and 3 to 6 cards, costing $0.07 to $0.12.
  - The init message lists only the two tools.
  - Raw request logging works.
- **In the app:**
  - The list, a full run with progress, the cost line and ✓ on an edit.
  - A stale card, Dismiss and ✗.
  - A new-page card with the folder changed and ✓.
  - Ingested marking, which skipped the note whose card was dismissed.
  - Saving the "Your notes" file and a rules file, the help window, settings restore.
- **Answers and Submit, the model menu, the Agent prompt tab (2026-11-02, on a fake finished run):**
  - The model menu listed Claude Code's four models by exact id (`models.py`, no request), with Haiku 5.5 as the default.
  - Answers were saved and nothing was written before Submit. Submit wrote the ✓ cards, dropped ✗, dismissed a stale card, and sent the ↻ card as one round with the accepted and rejected ids. The run then marked its note ingested.
  - A feedback round through `run.py` with a stand-in for Claude: the message, the revision of the ↻ card, the refusal to change an accepted card, the transcript and the events.
  - 30 simultaneous state saves (the host answers each call on its own thread).
  - Not tested: a real feedback round with Claude.
- **The code rewrite for newcomers, and page templates (2026-11-02, scratch copies):**
  - The prompts built without Claude: the index ends with the page templates' names and descriptions only.
  - The tools called through Claude Code's own wrapping, no Claude: a template must be read first and be from the same wiki, templates can't be edited, decided cards can't change, missing inputs come back as errors.
  - The feedback round with a stand-in for Claude, on the new code.
  - One real run on Haiku 5.5 (about $0.006 at API prices): 5 cards. It read only the template it needed (Observing session, not Gear), only for its new page, and followed its fields and headings with the page's own description.
  - The Page templates tab: the list, and New page template (makes the file and opens it in the editor).

## Ideas for later

- Edit a card's text before accepting it.
- Accept part of a card.
- Re-run one note.
- A per-run effort choice.
- Show the agent's reasoning notes in the run log view.

## Promotion: questions before proposals

A personal page says what happened on one piece of work. Where a point belongs in the team wiki, and whether it holds in general, is often something only the person knows. So in a promotion the agent has a third tool, `ask_reviewer`, and its prompt tells it to ask rather than guess, mainly about where something should go.

1. The agent plans and reads. If where a point goes is unclear, it calls `ask_reviewer` once, with up to five questions. Each has `about` (the point), `question`, and for a question of where something goes, `options`: the candidate destinations as page ids or new-page paths.
2. `tools.py` checks the call (at least one question, at most five, one call per run), sends the questions to the app as a `questions` event, and ends the agent's turn (agentlib's `ends_turn`). The run ends normally; its `done` event carries `questions`, the number asked.
3. The Promotion tab shows the questions as a form above the cards: the options as buttons, a text box, and **Skip: leave this point out**. Nothing else can start while questions are waiting, and the run is not closed.
4. **Continue** sends `answerIngestQuestions` with `{question id: answer}` (an empty answer for a skipped question). The host starts `run.py <job.json> --answers <answers.json>`, which resumes the same Claude session with one message (`write_answers_message` in `prompts.py`) and follows the agent as it proposes its cards. The round's cost is added to the run's.
5. The cards are answered and submitted as usual. The answered questions stay on the tab as a folded record, and are saved in the run's `transcript.json` under `questions`.

Tested 2026-11-10 on scratch copies, with Sonnet 5.5: a topic whose place was clear got a card with no questions; a topic that could go on an existing page or a new one, with a rule of uncertain status, got two questions with options; after one option was picked and the other question skipped, the agent proposed one edit to the chosen page and left the skipped point out.
