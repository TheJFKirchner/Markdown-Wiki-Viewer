# Second brain

Captures Claude Code sessions and meeting summaries into a personal wiki of plain markdown, and gives a reviewed path for promoting what proves durable into a team wiki. There is no database and no RAG: an agent finds things by reading a one-line-per-page index.

## How it fits together

**Personal wiki: what happened.** Each ingested session becomes a short session note (summary, decisions and why, findings and open questions), filed under one to three topics.

- **A topic** is one piece of work: a project, an analysis, a question, a tool. Its page is `<topic>.md` at the top level of the wiki (`type: topic`), with three parts:
  - **Current state**: a briefing on where the work stands, written by a review.
  - **Notes**: yours. Nothing automated touches it.
  - **Log**: one dated line per session, linking to its note.
- **A tag** is only a label in a topic's frontmatter `tags:`. It connects related topics: the wider subject the work belongs to. A tag has no page of its own. A new topic gets one to three tags, and capture reuses the tags already in use where one fits.
- **Session notes** live in one flat folder, `Sessions/`. A note's frontmatter has `topics:` (its topics' names) and `tags:` (the union of its topics' tags), so they are ordinary tags in WikiApp.
- **Tasks are never touched by the AI.** A to-do (a checkbox line, or "I need to send X by Friday") stays only where you wrote it: capture does not turn it into a log line, a finding, an open question or anything else, and no checkbox line from the model is ever written into a record or onto a topic page. A review keeps to-dos out of Current state. Task lines in records from earlier versions are left as they are.

**Notes are captured the same way.** A note you wrote (`capture-note`) becomes a record in `Sessions/` with `origin: note`, under the same topics and tags. Every log line is marked `[note]` or `[session]`. Notes outrank sessions: when a review finds a session contradicting a note, Current state follows the note and shows a Conflict block for you to settle (`conflicts`, `resolve-conflict`). Model calls go through agentlib (`llm.py`), never the raw SDK or the `claude` command. See INTEGRATION.md.

**Capture and review are separate steps.**

- **Capture** (the executive assistant, Haiku) reads the session and decides what is worth keeping. A script writes the files, so the links, index and log are always consistent. Capture adds the session's line to each topic's log. It never rewrites a current state.
- **Review** (the wiki reviewer, Sonnet) rewrites a topic's current state, and its one-line summary, from all of that topic's session notes. A topic becomes due for review once it has gained three sessions, or when it is flagged: a session reversed one of its decisions, a session was taken off it, or topics were merged into it. It then waits until you review it. A review is written directly, with nothing to approve.

**Folders.** When three or more top-level topics share a tag (`folder_after_topics`), that tag can become a folder: `<tag>/`, with a hub page `<tag>/<tag>.md` (`type: folder`) that lists its topics.
- `folders-suggest` works the suggestions out from the pages, with no model call. `folders-apply` moves the topics.
- A topic lives in one folder at most, and keeps all its tags.
- A tag can't become a folder if a folder or a page with that name already exists that the tool didn't make.
- Links go by page name, so moving a page breaks nothing. The index is grouped by folder.

**Merges.** The wiki reviewer's second job is suggesting merges (`merge-suggest`, one model call): topics that are the same work under two names, and tags that mean the same thing. `merge-apply` does one:
- **Topics:** the merged topics' sessions, tags, tasks and your own notes move to the kept page. Links across the wiki are repointed and the merged pages are removed. The kept topic becomes due for review.
- **Tags:** the tag is replaced on every topic and session note. If it was a folder, the folder is renamed to match.

**Team wiki: what is true.** Reference pages about subject areas, databases, tables and methods. Nothing here writes to it automatically. When a session turns up something about the data, it goes into a promotion queue in the personal wiki (`promotion-queue.md`). The team wiki manager works through that queue and your topic pages, and you review every change:

- in WikiApp's **Promotion** tab, each change is a card you accept or reject;
- called as the `team-wiki-manager` skill in Claude Code, it edits the team wiki's files and you review the diff before committing.

A topic can be promoted only once it has been reviewed since it last changed. The team wiki manager never creates a table page: those come from the `data-dictionary` skill, run in Claude Code. A finding about a table that has no page goes on its subject area's page.

**Lookup.** The `wiki-lookup` subagent takes a task, reads both indexes, and returns the few pages worth opening, so the main conversation never loads the index.

## The agents and their prompts

Three of WikiApp's four agents work on these wikis. Each has exactly one prompt file, and it is a Claude Code skill in `~/.claude/skills/<agent id>/SKILL.md`:

| Agent | Id | Does |
|---|---|---|
| Executive assistant | `executive-assistant` | Capture: `ingest`, `ingest-file` |
| Wiki reviewer | `wiki-reviewer` | `review`, `merge-suggest` |
| Team wiki manager | `team-wiki-manager` | Promotion, in WikiApp or as a skill |

- The defaults ship in `../agents/<agent id>/SKILL.md`. A default is copied to the skills folder the first time (by `sb.py install`, by WikiApp's Agents and rules window, or when a Notes or Promotion run starts) and never again, so your edits are kept. Until you have a copy, the shipped default is used.
- Each skill has `disable-model-invocation: true` in its frontmatter, so Claude Code only runs it when you call it by name.
- What a model is sent is the body of that file (without the frontmatter), then what the code adds for that one request: the material, the wiki's rules and the reply format.
- `WIKIAPP_SKILLS_DIR` names another skills folder, for tests.

**Rules.** The personal wiki's rules are the user's own "My capture rules" file (`.wiki/capture-rules.md` in WikiApp's private folder; Settings, Rules). They are sent with every capture and every topic review. A team wiki's rules go in a `wiki_rules.md` file at its top level. `WIKI.md` only marks the folder as personal for the command line on its own; its body is not sent to anyone.

**Which wiki is written to.** In WikiApp, each open wiki has a role (Settings): `personal`, `team` or `view` (see TECHNICAL.md §7.1). Every write command works only on the wiki whose role is `personal`, and refuses a team or view-only wiki in plain words; `WIKI.md` isn't needed there. On the command line without WikiApp's private folder, a folder whose `WIKI.md` says `type: personal` is the personal wiki, as before.

## In WikiApp

This folder ships inside WikiApp, and the app's **Ingest** view is the easy way to use it:

- **Sessions** tab: give one wiki the personal role in Settings, press Set up once, then Ingest or Ingest all. Sessions show a readable name (`<date>-<a few words>`), how many subagents they used, and short sessions are hidden by the minimum-turns filter.
- **Review** tab: the topics due for a review, Review or Review all, and folder and merge suggestions, each a card to accept or dismiss.
- **Promotion** tab: sends topic pages, folder pages and the promotion queue to the team wiki manager.

The app passes the wiki's folder itself, so that needs no config file. Steps 3 to 5 below are still worth doing once, so that Claude Code can read the wikis; for those, set `team_wiki` (and `personal_wiki`) in `config.json`.

## What it costs

A capture is one request to Haiku 5.5. Its cost is almost all the session's own text going in: a long working session is 25,000 to 35,000 tokens, under a cent at the app's price table. A review is one request to Sonnet 5.5 over a topic's session notes.

- **Models are named by exact id** (`extract_model: claude-haiku-5-5`, `review_model: claude-sonnet-5-5`), not by alias. An older Claude Code takes `haiku` to mean Haiku 4.5, which costs ten times as much per token. `--model <id>` on any command overrides both for that command, and WikiApp's tabs each have a model menu.
- **The cost shown is worked out from the app's own price table** (`ingest/costs.py`, API list prices by model family) for the model that answered. Claude Code's own figure isn't used: a version older than a model prices it at a fallback rate. Update the table when prices change. On a subscription nothing is billed per token; the figure shows how heavy a request was.
- **The prompt cache is off** for these calls: each is a single request that is never repeated, so caching it only added the cache-write surcharge.
- **`capture_thinking`** (default `false`) and **`review_thinking`** (default `true`) ask Claude Code not to use, or to use, extended thinking. Haiku 4.5 obeys it; Haiku 5.5 thought anyway when tested, which costs little at its prices.

Every result reports its cost and model, and `status` gives the running totals. To lower the cost further, lower `max_transcript_chars`: a session longer than that has its long messages cut before any are dropped.

## What you can edit on a topic page

A topic page has three headings: `## Current state`, `## Notes` and `## Log`. Notes is yours. The other two are written by the tool, with no marker comments in the page: the current state by a review, and the log again from the session notes on every capture. Keep the three headings as they are. If one is renamed or removed, the tool leaves that page alone and says which heading is missing. Inside Notes, use `###` for your own headings.

## Setup

Needs Python 3.9 or later and the Claude Code CLI. No packages to install.

1. Copy `config.example.json` to `config.json` and set `personal_wiki` and `team_wiki` to the two wiki folders.
2. Create the personal wiki's structure (on its own, `init` also writes `WIKI.md`, which marks the folder as personal for `sb.py`; inside WikiApp the wiki's role does that and no `WIKI.md` is made):
   ```
   python sb.py init
   ```
   A personal wiki made by the first version (`tags/` and `session-notes/<year>/`) needs no step: it is upgraded the first time `status`, or any command that works on the wiki's pages, runs. Its tag pages become topics at the top level, its notes move to `Sessions/`, and the ledger is repointed.
3. Copy `templates/team-wiki_rules.md` into the team wiki's root as `wiki_rules.md`, and correct its folder table to match how the team wiki is laid out. That is the file every agent that works in the team wiki is sent, and WikiApp edits it in Ingest, Agents and rules, the team wiki's rules tab. The team wiki needs no `WIKI.md`.
4. Install the agents' skills, the helper skills and the lookup agent into `~/.claude`, with the wiki paths filled in:
   ```
   python sb.py install
   ```
   - It installs the three agents' skills (`executive-assistant`, `wiki-reviewer`, `team-wiki-manager`), the helper skills `wiki-capture` and `data-dictionary`, and the `wiki-lookup` agent.
   - Existing files are left alone. `--force` replaces the helper skills and the lookup agent. It never replaces an agent's prompt.
   - The `data-dictionary` skill is a placeholder: replace its "What to do" section with the real process and keep its contract. It reads the team wiki's `wiki_rules.md` for where table pages go.
5. Add the contents of `CLAUDE-snippet.md` to your `CLAUDE.md`.

## Daily use

```
python sb.py list                      # sessions waiting to be ingested (--min-turns 0 shows short ones too)
python sb.py ingest <session-id>       # capture one (its readable name, or the first 8 characters of the id, are enough)
python sb.py skip <session-id>         # dismiss one
python sb.py ingest-file recap.docx --date 2026-11-05    # a Teams meeting summary

python sb.py review-list               # topics due for review (--all lists every topic)
python sb.py review <topic>            # rewrite one topic's current state
python sb.py review --due              # review every topic that is due

python sb.py folders-suggest           # tags enough topics share to become a folder; no model call, moves nothing
python sb.py folders-apply --tag stop-loss --title "Stop loss" --topics topic-a,topic-b,topic-c

python sb.py merge-suggest             # ask which topics and tags are duplicates; changes nothing
python sb.py merge-apply --kind topic --keep topic-a --merge topic-b,topic-c
python sb.py merge-apply --kind tag --keep stop-loss --merge stoploss-reporting
```

Or ask Claude to do it: the `wiki-capture` skill runs these for you. To move knowledge into the team wiki, use WikiApp's Promotion tab, or ask Claude to "use the team-wiki-manager skill to work through my promotion queue".

`INTEGRATION.md` describes the commands and their JSON output for an app that wants to offer this as a page with buttons.

## What gets sent to the model

A capture sends only a condensed transcript: your messages, Claude's replies, and each tool call as one line ("Read claims.sql", "Bash: python trend.py"). Tool output is removed before the model sees anything, so query results never reach the capture step, and the executive assistant's prompt forbids recording member-level data. `python sb.py condense <session-id>` prints exactly what would be sent.

Commands are masked before they are sent:
- a number of six or more digits becomes `#`;
- quoted values inside anything that looks like a SQL query become `'?'`;
- a command is cut at 160 characters.

The same masking applies to search patterns, web search queries and other tools' inputs. File paths for Read, Edit and Write are not masked, and neither is what you and Claude wrote in the conversation. A short ID, or a value outside a query, would still be included.

Which sessions are read: sessions started through the Agent SDK (an entrypoint starting with `sdk`, WikiApp's own Notes and Promotion runs among them) are never listed, and neither are this tool's own model calls.

**Subagents are part of the session that started them**, never listed on their own. Each subagent's report back to the main conversation is in the condensed transcript under `## ASSISTANT (subagent)`, as `SUBAGENT "<task>" reported: ...`, with a few of its steps as one-liners after it; the assistant's instructions to it are shown, masked like a command, inside the assistant's message. None of it is labelled as yours, and the executive assistant treats it as the assistant's word: a subagent's finding is captured only when you confirmed it. Only your own messages count as turns.

With the transcript go the agent's prompt, the personal wiki's rules, the index lines of the existing topics, and the tags in use, so the model can reuse a topic or a tag.

A review sends the topic's session notes (the newest 40, each cut at 2,500 characters) and your own Notes section from the topic's page. A merge suggestion sends only the names, one-line summaries and tags of the topics, and the tags in use. A folder suggestion sends nothing: it is worked out from the pages.

## Settings

In `config.json`:

| Setting | Default | Meaning |
|---|---|---|
| `personal_wiki`, `team_wiki` | | The two wiki folders |
| `transcripts_dir` | `~/.claude/projects` | Where Claude Code keeps session transcripts |
| `extract_model`, `review_model` | from the app's engine settings, else `claude-haiku-5-5`, `claude-sonnet-5-5` | Models for capture, and for reviews and merge suggestions |
| `engine` | the app's engine settings (`claude`) | The agentlib engine the requests run on; `fake` in tests |
| `lookback_days` | 14 | How far back `list` looks |
| `review_after_entries` | 3 | New sessions on a topic before it is due for review |
| `folder_after_topics` | 3 | Top-level topics that must share a tag before it is suggested as a folder |
| `min_turns` | unset (3) | `list` hides sessions with fewer of your own messages than this (0: hide none). Read only without WikiApp's private folder: with one, WikiApp's Sessions filter decides (default 3). A session you name to `ingest` is captured however short |
| `min_user_messages` | 2 | The older name for `min_turns`, read only when `min_turns` isn't set. Nothing is skipped by it any more |
| `max_transcript_chars` | 160000 | The longest condensed transcript, or meeting file, that is sent |
| `llm_timeout_seconds` | 300 | How long one model call may take |
| `exclude_project_patterns` | `[]` | Hide sessions whose project folder name contains any of these |
| `claude_cmd`, `claude_extra_args` | | No longer used (requests go through agentlib); still accepted so an older `config.json` loads |

An unknown key in `config.json` is an error.

## Layout

```
sb.py                 entry point
secondbrain/          transcripts.py (find, condense and mask), llm.py (model call, through agentlib),
                      wiki.py (all file writes: notes, topics, folders, merges, the index),
                      ingest.py (capture of sessions, files and notes), review.py (reviews and merge
                      suggestions), conflicts.py (notes against sessions, and how each is settled),
                      prompts.py (the agent's prompt plus what is added per request), cli.py, config.py
skills/               wiki-capture, data-dictionary (placeholder)
agents/               wiki-lookup
templates/            personal-WIKI.md (the WIKI.md that `init` writes on the command line on its own; WikiApp doesn't), team-wiki_rules.md (to copy
                      into a team wiki as wiki_rules.md)
tests/                python -m unittest discover tests
../agents/            the three agents' default prompts (one SKILL.md each) and agentfiles.py
```
