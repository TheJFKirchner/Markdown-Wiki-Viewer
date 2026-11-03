# Ingest: design (V1)

Status: **built, V1**, on 2026-11-01. Paths in this file are inside the `App Files` folder. The agent's exact inputs are in [AGENT.md](AGENT.md). The shipped instructions are in [agent-prompt.md](agent-prompt.md).

## Goal

Quick notes collect facts, decisions and status, but they only help later if that information reaches the wiki pages. Ingest sends wrapped notes to a Claude agent (Haiku 5.5 by default, through the Claude Agent SDK for Python). The agent proposes page changes, and nothing reaches a page until the user accepts the change with ✓.

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

The rail button **Ingest** (Ctrl+5) has a badge: the number of cards to review if there are any, otherwise the number of notes waiting.

```
┌ Ingest ──────────────────── [?] [✎ Edit ingestion prompt] ┬─ Proposed changes      3 to review ┐
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
- **Model**, next to Ingest: the models Claude Code offers on this computer, by their exact names, with Haiku 5.5 the default. The host fills it with `listIngestModels`, which runs `ingest/models.py`: it starts Claude Code through the Agent SDK, reads the list from its start-up handshake (`get_server_info()["models"]`, one entry per model, aliases like `default` and `opus` folded into the model they name) and stops it. No request is made, so it's free; it takes a few seconds, once per app start, and the last list is kept in the settings. The choice is remembered and sent as the job's `settings.model`.
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

Cards and their answers (and feedback being typed) survive closing the app: they're saved in `~/.wikiapp/ingest/pending.json` (`%LOCALAPPDATA%\WikiApp\ingest\` under `WikiApp.exe`). If the app closes during a run, the run counts as failed when it reopens.

### The ? button

**How Ingest works** explains, for someone who has never seen an agent:
- what happens when you press Ingest, in five steps;
- the words used: agent, agent loop, tool, Claude Agent SDK, prompt, index, card, tokens and cost;
- a diagram of Claude with its loop and its two tools, between your notes and your pages.

### Edit ingestion prompt

| Tab | What it is | Saved to |
|---|---|---|
| Agent prompt | The shipped [agent-prompt.md](agent-prompt.md), read-only (no Save): it updates with the app. `{{user_notes}}` and `{{wikis}}` show where the other tabs go. | – |
| Your notes | The user's own instructions, inserted under "Notes from the user" | `~/.wikiapp/ingest/user-notes.md` |
| Page templates | A list, not text: every wiki's page templates, and **New page template** ([Page templates](#page-templates)) | `<wiki>/Templates/Pages/<name>.md` |
| *alias* rules, one per wiki | That wiki's rules | `<wiki>/wiki_rules.md`, through the host like any note |

- A wiki without a rules file starts from a short template, and saving creates the file.
- `wiki_rules.md` is hidden from the graph, tags, tasks and link suggestions, like `Templates/`, but still shows in the file tree.
- A checkbox, *Also save each run's raw requests*, turns on raw request logging into the run folder.
- Saving applies to the next run.

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
| Collect the selected notes, the wikis and the user's notes into a job | App and host | No |
| Rebuild every wiki's index | `ingest/wikis.py`, at the start of each run | No |
| Fill the prompt template, write the first message, save both to the run folder | `ingest/prompts.py`, called from `ingest/agent.py` | No |
| Decide what's worth keeping, find pages, read them, follow links, pick a page template for a new page, draft changes | **The agent** | **Yes** |
| Check every proposal; send fixable errors back to the agent | `ingest/tools.py` | No |
| Report progress, cards, cost | `agent.py` → host → app | No |
| Work out new tags and links, flag missing link targets | App | No |
| Apply on ✓, detect stale cards, mark notes ingested | Host and app | No |

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
- **Edit ingestion prompt → Page templates** lists every template (wiki, name, when to use it, a link to the file that opens it in the editor) and makes a new one from a starter in the chosen wiki. A template without a description is flagged.
- **Kept out of the way:** everything under `Templates/` is left out of the graph, tags and tasks, and the New note menu lists only files directly in `Templates/`.
- **Why a folder and not a list in the prompt:** nothing to keep in step. A template's name and purpose live in the file itself.

## The agent

Everything it receives is in [AGENT.md](AGENT.md). In short:

| | |
|---|---|
| Library | `claude-agent-sdk` for Python. It runs the Claude Code engine that ships inside the package. |
| Sign-in | The computer's existing Claude Code login (`~/.claude`). No API key. From `~/.claude/settings.json`, only `env` and `apiKeyHelper` are passed through, so a gateway setup (for example LiteLLM) keeps working. |
| Model | The one picked in the Ingest view (the job's `settings.model`); by default `claude-haiku-5-5`. Effort `low`, adaptive thinking; a job's `settings.effort` can change the effort. Haiku is the default on cost; see [AGENT.md §10](AGENT.md#10-model-choice-tested-2026-11-01). |
| Tools | Exactly two: `read_page` and `propose_page`. Every built-in tool is off; the init message confirms this. |
| Context | Our system prompt only. No CLAUDE.md, settings, hooks, skills, subagents, plugins or other MCP servers. |
| Limits | 40 turns, $1.00 per run |

**Why two custom tools and not the built-in Read**
- `read_page("Titan")` resolves links the way the app does, so following a link just works.
- A miss returns the closest names, so the agent can try again without a search tool.
- It can only open pages and scripts in the open wikis.
- Its definition is much shorter than Read's.

## Files

| Path | What it is |
|---|---|
| `ingest/DESIGN.md`, `ingest/AGENT.md` | This design, and exactly what the agent sees |
| `ingest/agent-prompt.md` | The shipped system prompt, with `{{user_notes}}` and `{{wikis}}` |
| `ingest/agent.py` | **The agent, explained for newcomers:** what it's given (model, effort, instructions, tools, limits), one run, a feedback round, following its loop. Start reading here. |
| `ingest/tools.py` | Its two tools as plain functions, `read_page` and `propose_page`, with every proposal check |
| `ingest/prompts.py` | The text it's given: instructions, first message, feedback message |
| `ingest/run.py` | The command line the host starts. `--prepare-only` builds the prompts without calling Claude. |
| `ingest/wikis.py` | Wiki scanning, link resolution, the index and page templates |
| `ingest/transcript.py`, `ingest/costs.py`, `ingest/progress.py` | The run's record, its prices and totals, and its progress lines and log |
| `ingest/models.py` | Prints the models Claude Code offers, for the model menu (no request to Claude) |
| `setup.py`, `requirements.txt` (in `App Files`) | The app's setup: `App Files/.venv` with pywebview, `claude-agent-sdk` and `pyyaml` |
| `host/ingestruns.py` | The main host's side of Ingest (`WikiApp.cs` has its own) |
| `app/js/ingestview.js` | The Ingest view, model menu, cards, diff, answers and Submit, applying and marking |
| `app/js/ingestdialogs.js` | The Edit ingestion prompt and How Ingest works windows |
| `<wiki>/wiki_rules.md` | That wiki's rules for the agent |
| `~/.wikiapp/ingest/` | `pending.json` (cards and the last run), `user-notes.md` |
| `~/.wikiapp/ingest-runs/<id>/` | One folder per run: `job.json`, `system.md`, `first-message.md`, `log.jsonl`, `transcript.json`, `session.json`, any `feedback-<n>.json`, optionally `raw/` |

**Under `WikiApp.exe`:** the same files are in `%LOCALAPPDATA%\WikiApp\ingest\` and `%TEMP%\WikiApp\ingest-runs\<id>\`. The exe's run folders are in Temp because the Microsoft Store build of Python can't see other programs' folders in `%LOCALAPPDATA%`, but it can see Temp. The main host avoids the problem by keeping everything in `~/.wikiapp`.

**Host messages:** `ingestInfo`, `saveIngestState`, `saveIngestNotes`, `startIngest`, `reviseIngestCards`, `cancelIngest`, `runIngestSetup`, `listIngestRuns`, `openIngestRun`, `listIngestModels`.
- The host starts the `.venv` Python with `-X utf8 ingest/run.py <job.json>`, with no window.
- It passes each stdout line to the page as an `ingest` event, and sends `ingestExit` when the process ends.
- **Stop** kills the process tree: `taskkill /T` on Windows, the process group on macOS.

## Setup and requirements

- Python 3.10 or newer; the Store build works.
- Claude Code signed in on the computer.
- The app's own setup installs the packages, on the first start (about 200 MB; the SDK bundles the Claude Code engine). **Run setup** in the Ingest view reinstalls or updates them.

## Tested (2026-11-01, on copies of the samples)

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
  - Saving your notes and a rules file, the help window, settings restore.
- **Answers and Submit, the model menu, the Agent prompt tab (2026-11-02, Python host, on a fake finished run):**
  - The model menu listed Claude Code's four models by exact id (`models.py`, no request), with Haiku 5.5 as the default.
  - Answers were saved and nothing was written before Submit. Submit wrote the ✓ cards, dropped ✗, dismissed a stale card, and sent the ↻ card as one round with the accepted and rejected ids. The run then marked its note ingested.
  - A feedback round through `run.py` with a stand-in for Claude: the message, the revision of the ↻ card, the refusal to change an accepted card, the transcript and the events.
  - 30 simultaneous state saves (the Python host answers each call on its own thread).
  - Not tested: a real feedback round with Claude, and the exe's `listIngestModels` (built, not run).
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
