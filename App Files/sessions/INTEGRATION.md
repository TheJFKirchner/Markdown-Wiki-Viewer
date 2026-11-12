# Hooking the wiki app up to the second brain

The second brain is a command-line tool. It does not depend on the wiki app, and the app needs no knowledge of how capture works: it runs commands and shows their results. Everything below is what the app needs in order to offer an ingestion page.

Every command is run as:

```
python <second-brain folder>/sb.py <command> --json
```

With `--json`, a command prints one JSON value to standard output and nothing else. The output is ASCII-escaped, so it decodes the same way under any console encoding.

Add `--personal <folder>` to name the personal wiki on the command line. With it, no `config.json` is needed, and every other setting takes its default. WikiApp calls the tool this way (`host/sessionruns.py`), with the folder picked in its Sessions tab. `--team <folder>` and `--config <path>` work the same way on every command.

| Exit code | Meaning | Output |
|---|---|---|
| 0 | Success | The result described below |
| 1 | The command failed | `{"error": "..."}` |
| 2 | Configuration problem (no config file, personal wiki not set, an unknown config key) | `{"error": "..."}` |

`review` is the one exception: when a review fails it still prints its normal result, with the failure under `errors`, and exits with 1.

## Every command

| Command | What it does | Calls a model |
|---|---|---|
| `init` | Create the personal wiki's skeleton | No |
| `status` | Whether the folder is set up, and what it holds | No |
| `list [--days N] [--all] [--min-turns N]` | Sessions waiting to be ingested, short ones hidden | No |
| `ingest <session_id or name> [--dry-run] [--force] [--only-new]` | Capture one session (by id, id prefix or readable name). `--only-new` (what WikiApp passes): a session already captured and unchanged since returns `status: "unchanged"` without a model call | Yes |
| `capture-note <path> [--dry-run] [--force]` | Capture one of your notes into the personal wiki (see "Notes" below) | Yes, unless the note is unchanged since its capture |
| `notes-status <path>...` | Whether each note is `new`, `changed` since its capture, or `captured` | No |
| `conflicts` | Conflicts between your notes and sessions, waiting to be settled | No |
| `resolve-conflict <id> keep_note\|accept_session\|dismiss` | Settle one | No |
| `ingest-file <path> [--date YYYY-MM-DD] [--dry-run]` | Capture a meeting summary or notes file | Yes |
| `skip <session_id> [--reason "..."]` | Mark a session as not worth ingesting | No |
| `review-list [--all]` | Topics due for review | No |
| `review <topic>` or `review --due` | Have the wiki reviewer rewrite a topic's current state | Yes |
| `folders-suggest` | Tags that enough topics share to become a folder | No |
| `folders-apply --tag <name> --topics <a,b,c> [--title "..."]` | Turn a tag into a folder and move topics into it | No |
| `merge-suggest` | Have the wiki reviewer suggest topics and tags to merge | Yes |
| `merge-apply --kind topic\|tag --keep <name> --merge <a,b>` | Merge topics, or tags, into one | No |
| `reindex [--wiki personal\|team]` | Regenerate `index.md` | No |
| `condense <session_id>` | Print the cut-down transcript the model would see (plain text, no JSON) | No |
| `install [--dest ~/.claude] [--force]` | Copy the agents' prompts, the helper skills and the lookup agent into a `.claude` folder | No |

## How the personal wiki is laid out

| Path | What it is |
|---|---|
| `WIKI.md` | Marks the folder as a personal wiki (`type: personal`) for the command line on its own. In WikiApp the wiki's role decides (see "Choosing the personal wiki") and this file isn't needed |
| `index.md` | One line per topic, grouped by folder, regenerated from the topic pages |
| `promotion-queue.md` | Data findings waiting to be promoted to the team wiki |
| `<topic>.md` | A topic: a page about one piece of work (`type: topic`), at the top level |
| `<tag>/` | A tag that became a folder: its topics, and a hub page `<tag>/<tag>.md` (`type: folder`) |
| `Sessions/` | One short record per captured session or note, in one flat folder (frontmatter `origin`: `session` or `note`) |

The tool's own progress (the ledger of what was captured or skipped, `spend.json`, `conflicts.json`, the write lock, the model's work folder) is kept in WikiApp's progress folder for the wiki (`pathlist.progress_dir`: `<.wiki folder>/progress/<alias>`). Without a WikiApp private folder (the command line on its own) it stays in `<personal wiki>/.sb`. The first time the progress folder is used, everything in `.sb` is copied across, and `.sb` is left as it was.

- A tag is only a label in a topic's frontmatter `tags:`. It connects related topics and has no page of its own.
- A topic lives at the top level, or in one folder at most. It keeps all its tags either way.
- Pages are found by name wherever they sit, and names are unique, so moving a page never breaks a `[[link]]` to it.
- A wiki made by the first version (a page per tag in `tags/`, notes in `session-notes/<year>/`) is upgraded automatically the first time `status` or a command that works on the pages runs: pages with `type: tag` become topics at the top level, notes move to `Sessions/`, and the ledger is repointed. Nothing is overwritten.

## Status

`python sb.py status --json --personal <folder>` says whether a folder is ready:

```json
{
 "wiki": "C:\\wikis\\personal",
 "exists": true,
 "type": "personal",
 "personal": true,
 "role": "personal",
 "set_up": true,
 "topics": 12,
 "tags": 5,
 "folders": 2,
 "sessions": 31,
 "review_due": 3,
 "queue_pending": 4
}
```

| Field | Meaning |
|---|---|
| `exists` | The folder is there |
| `type` | Whatever its `WIKI.md` says, or null without one |
| `role` | Its role in WikiApp (`personal`, `team`, `view`), or null when it isn't one of WikiApp's open wikis (or there is no WikiApp private folder) |
| `personal` | True when writes are allowed: its role is `personal`, or (with no role) its `WIKI.md` says `type: personal`. The counts below are 0 until then |
| `set_up` | `personal`, and `Sessions/` and `index.md` exist (`init` has run). Offer **Set up** while this is false |
| `topics` | Topic pages |
| `tags` | Different tags in use on the topics |
| `folders` | Tags that have become folders (hub pages) |
| `sessions` | Session notes |
| `review_due` | Topics due for review, as a number: a good badge for a review page |
| `queue_pending` | Unticked findings waiting for the team wiki |

## The ingestion page

### 1. List the sessions waiting

```
python sb.py list --json
```

Returns the Claude Code sessions touched in the last 14 days that still need a decision, newest first. `--days N` changes the window; `--all` also returns sessions already ingested or skipped.

Some sessions are never listed, whatever the options: sessions started through the Agent SDK (an `entrypoint` starting with `sdk`, WikiApp's own Notes and Promotion runs among them), this tool's own model calls, and sessions with no user message. A subagent's transcript is never listed: its work is part of the session that started it (see "Subagents" below).

**The minimum-turns filter.** A session with fewer of the user's own messages than `min_turns` is left out of `sessions` and only counted in `hidden_count`, so an "ingest all" that works through the list skips it. With WikiApp's private folder, `min_turns` is exactly what the app shows (`pathlist.get_sessions_filter`: 0 = off, 3, 5, 10 or 20; the stored filter, else 3), and `config.json` isn't consulted. On the command line on its own it is `config.json`'s `min_turns`, else its older `min_user_messages`, else 3. `--min-turns N` overrides all of them. A session named to `ingest` is captured however few turns it has (`--force` is no longer needed, and changes nothing).

```json
{
 "sessions": [
  {
   "session_id": "aaaaaaaa-1111-2222-3333-444444444444",
   "name": "2026-11-10-churn-dashboard-refresh",
   "title": "Churn dashboard refresh",
   "date": "2026-11-10",
   "last_active": "2026-11-10",
   "project": "C:\\work\\analytics\\renewals",
   "entrypoint": "claude-desktop",
   "user_messages": 7,
   "subagents": 2,
   "first_prompt": "The churn dashboard is showing last month twice...",
   "status": "new"
  }
 ],
 "hidden_count": 4,
 "min_turns": 3
}
```

| Field | Use |
|---|---|
| `session_id` | The hidden reference: pass this (or `name`) to `ingest` and `skip` |
| `name` | The session's readable name, `<date>-<a few words>`: show this instead of the id. See "Readable names" below |
| `title` | The session's name in Claude Code (the one the user gave it, else the one Claude Code generated), or the start of its first message |
| `date`, `last_active` | When the session started and was last used |
| `project` | The folder the session ran in |
| `user_messages` | How many messages the user typed: a quick sign of how substantial it is. Subagent reports, background-task notifications and messages from other sessions never count |
| `subagents` | How many subagents the session started (Agent or Task calls). Their work is folded into this session |
| `entrypoint` | How the session was started, for example `claude-desktop`. Never a value starting with `sdk`: those sessions are left out by the tool |
| `status` | See below |
| `note` | Present once ingested: the session note's path inside the personal wiki |
| `reason` | Present once skipped: why |

| Status | Meaning | Suggested button |
|---|---|---|
| `new` | Never ingested | Ingest, Skip |
| `updated` | Ingested, then the session was continued | Re-ingest |
| `ingested` | Done (only with `--all`) | none |
| `skipped` | Dismissed by the user, or the capture step found nothing durable (only with `--all`) | Ingest anyway |

Listing reads every recent transcript, so it takes a second or two on a machine with many sessions. Call it when the page opens and after each ingest, not on a timer.

**Readable names.** Each listed session is given a name, `<date>-<a few words>` (`2026-11-12-churn-dashboard-fix`): the session's start date and up to five words from Claude Code's title for it (a `custom-title` line, else the generated `ai-title` line; the last of each counts), else from the user's first message. No model is asked. A short piece of the session id (4 characters, then 8, then all) is added only when the name is already taken. The name is kept in the session's ledger entry the first time it is given, so it never changes, even if the session is renamed in Claude Code or captured. `ingest`, `skip` and `condense` accept it in place of the id. The session id stays in the ledger and in the record's frontmatter as the hidden reference.

**Subagents.** How Claude Code keeps them: the main assistant starts one with an `Agent` (formerly `Task`) tool call (`description`, `prompt`, `subagent_type`, `run_in_background`). A subagent that runs in the foreground answers that call with its report (the user line's `toolUseResult.status` is `completed`). One that runs in the background answers at once with `status: "async_launched"`, and its report arrives later as a user line the person never typed: `origin.kind` is `task-notification`, the text a `<task-notification>` block with `<tool-use-id>`, `<status>`, `<summary>` and `<result>`. Its own transcript is `<project>/<session id>/subagents/agent-<agent id>.jsonl`, with `agent-<agent id>.meta.json` naming the call (`toolUseId`). In the condensed transcript (`condense`, and what capture sends):

- each subagent's report appears where it reached the session, under `## ASSISTANT (subagent)`, as `SUBAGENT "<description>" reported: ...`, followed by up to 8 of its steps as one-liners from its own transcript (cut first when the transcript is too long); a report is cut at 6,000 characters, and numbers of six or more digits in it become `#`;
- a subagent whose report never arrived (still running, stopped) is shown with its own transcript's last message, marked as such;
- the assistant's instructions to a subagent (and its messages to a running one, `SendMessage`) appear inside the assistant's message, masked like a command, as `(the assistant's instructions to SUBAGENT "<description>": ...)`;
- none of it is ever labelled `USER`; a background shell command's notification keeps only its masked one-line summary (its output is tool output);
- the capture rule is unchanged: the executive assistant treats subagent material as the assistant's, so a subagent's finding is captured only when the user confirmed it in the conversation.

### 2. Ingest one

```
python sb.py ingest <session_id> --json
```

This is the slow call: one Haiku request, typically 20 to 40 seconds. Run it in the background and show the row as working until it returns. Several can run at once; file writes are locked so they cannot interleave. Capture never rewrites a topic's current state, so it makes no second request.

```json
{
 "session_id": "aaaaaaaa-1111-2222-3333-444444444444",
 "name": "2026-11-10-churn-dashboard-refresh",
 "title": "Fix the churn dashboard refresh",
 "warnings": [],
 "status": "ingested",
 "note": "Sessions/2026-11-10-fix-the-churn-dashboard-refresh.md",
 "topics": [{"slug": "churn-dashboard", "created": true, "path": "churn-dashboard.md", "tags": ["dashboard"], "review_due": false}],
 "tags": ["dashboard"],
 "queued_findings": 0
}
```

| Field | Meaning |
|---|---|
| `name` | The session's readable name (as in `list`) |
| `status` | `ingested` or `skipped`. A skip is a normal result, not an error: the session had no message from the user, or the capture step judged it had nothing durable. `reason` says why, and the result then has only `session_id`, `title`, `warnings`, `status` and `reason`. |
| `note` | The session note's path inside the personal wiki: `Sessions/<date>-<title words>.md` for a new capture, with a piece of the session's id added only when another record already has that name. Records from earlier versions keep their names (with the id suffix) |
| `topics` | One entry per topic the note was filed under, at most three |
| `topics[].slug` | The topic's name |
| `topics[].created` | True if this capture made the topic's page |
| `topics[].path` | The topic page's path inside the personal wiki: `<slug>.md`, or `<tag>/<slug>.md` once the topic is in a folder. Link with this, not with a path built from the slug. |
| `topics[].tags` | The topic's tags after this capture |
| `topics[].review_due` | True if the topic is now due for review |
| `tags` | The note's tags: the union of its topics' tags, as a list of names |
| `queued_findings` | How many data findings this capture added to the promotion queue |
| `warnings` | Always an empty list at present. Kept so callers written for earlier versions still work. |

- Re-ingesting a session overwrites its note in place and replaces its lines in the topics' logs. It never creates a duplicate. A `## Tasks` section that a record from an earlier version holds is kept word for word. A topic the session no longer belongs to loses its line and is flagged for review (`review_reason: removed`).
- **The AI never touches tasks.** Capture records no tasks and changes none: a to-do (a checkbox line, or "I need to send X by Friday") stays only where the person wrote it, and is not turned into a log line, a finding, an open question or anything else. As a guard, no checkbox line from the model is ever written into a record or onto a topic page. Task lines already in older records and pages are left as they are. Results no longer have `tasks` or `tasks_updated`.
- What the model is shown of a session is masked: in commands, a number of six or more digits becomes `#`, quoted values inside anything that looks like a SQL query become `'?'`, and a command is cut at 160 characters. File paths for Read, Edit and Write are not masked. `condense` prints the result.

Options: `--force` is accepted for older callers and changes nothing: a session named here is captured however short it is (the minimum-turns filter only hides sessions from `list`). `--dry-run` returns `session_id`, `title`, `warnings`, `status: "dry-run"` and what would be captured, under `extraction`, without writing anything.

### 3. Skip one

```
python sb.py skip <session_id> --reason "testing" --json
```

Removes the session from the waiting list. Nothing is written to the wiki.

### 4. Ingest a file

For a Teams meeting recap or any notes file (.md, .txt, .vtt, .docx):

```
python sb.py ingest-file "<path>" --date 2026-11-05 --json
```

The result has the same shape as `ingest`. Its `session_id` is `file-` plus a hash of the path. Without `--date`, the file's modified date is used, so the page should ask for the meeting date. Ingesting the same path again overwrites its note.

### 5. Capture a note

```
python sb.py capture-note "<full path of the note>" --json
```

A note (a Markdown file the person wrote) is captured exactly as a session is: a record in `Sessions/` with `origin: note`, filed under the same topics and tags, and a `[note]` line in each topic's log. Notes only ever go to the personal wiki. The executive assistant keeps everything of substance in a note, numbers included (from a session it keeps only the person's corrections, statements and confirmations).

The note itself gets two frontmatter properties, set line by line (nothing else in the note changes, line endings kept):

| Property | Meaning |
|---|---|
| `capture_id: n-<12 hex>` | The note's permanent id, written before its first capture. A renamed or moved note keeps it, so it is never captured twice; a copied note (two files with one id) gets an id of its own |
| `ingested: <YYYY-MM-DD>` | Captured (the same property the older Notes flow used). Not written if the note changed during the capture |

The ledger keeps a hash of the note's text under `note:<capture_id>`. A note unchanged since its capture is not sent again (`status: "unchanged"`, no model call; `--force` sends it anyway). An edited note is captured again in place of its earlier record: same record file, its log lines replaced, never added twice.

The result has the shape of `ingest`'s, plus `path` (the note), `capture_id` and `conflicts` (always empty here: conflicts are found by a review).

`notes-status <path>...` returns, for each note, `{path, status, capture_id, captured_at, record, ingested}`, where `status` is `new` (never captured), `changed` (edited since its capture) or `captured`, or `error` with `error`.

`notes-status` also gives `legacy: true` for a note the older Notes flow handled (`ingested:` but no `capture_id`): it counts as `captured`. Capturing it deliberately still works (it is then treated as new).

### 6. Log lines and where they came from

Every log line says where it came from: `- 2026-11-03 [note] — what it added ([[record]])` (the model is told not to repeat the date in what it added) or `[session]` (a Claude Code session or a meeting summary). The record's frontmatter `origin` says the same. Text typed in a topic page's Notes section counts as a note.

When the same record was filed under other topics too, the line ends `— also touches [[other-topic]], [[another]]`. Lines are rebuilt from the records, so older lines gain it the next time that topic's log is rebuilt.

### 7. Tags

Tags say what kind of thing a topic is (there is no `kind` any more) and what it belongs to. Two free-form Markdown files make up the tag list, both sent verbatim, labelled, with every capture, topic review and merge suggestion (never with Promotion):

| Path-list entry | Default | Written by the tool |
|---|---|---|
| `tag_list_reference` | unset | **Never.** Any existing tags file, typically the team's, in any format |
| `personal_tags` | `personal-tags.md` in the personal wiki | Only to append `tag — description` for a new tag (made from a starter the first time one is added), and to remove or rename a merged-away tag's line |

The model chooses a reference tag, else a personal tag, else a tag in use, else a new tag, which it must declare in `new_tags` with a description of 1 to 8 words; a longer one is refused (left off the topic, with a warning). Names are picked out of both files on a best-effort basis, only for warnings (a personal tag the reference list also has; a reference list no names could be found in) and for `personal_tags` on a topic: its tags the reference list isn't known to have (all of them when none is set). Nothing fails because of either file's format.

A capture result has `new_tags` (`[{tag, description}]` appended to the personal tags) and each topic's `personal_tags`; `review-list` rows have `personal_tags` too. `merge-apply --kind tag` refuses to merge away a reference tag, and its result has `personal_tags_changed`.

## The review page

Capture never rewrites a topic's current state. A topic becomes due for review once three new sessions are filed under it (`review_after_entries`), or when it is flagged. It then waits for a review, which is written directly with nothing to approve.

A flag's reason is kept in the page's frontmatter as `review_reason`:

| `review_reason` | Set when | Shown as `why` |
|---|---|---|
| `reversed` | A session reversed or replaced a decision made on the topic | "a decision was reversed" |
| `removed` | A re-ingest took a session off the topic | "a session was taken off it" |
| `merged` | Other topics were merged into it | "topics were merged into it" |

### 1. List the topics

```
python sb.py review-list --json
```

Returns the topics that are due. `--all` returns every topic, those due first, then by `updated`, newest first.

```json
[
 {
  "slug": "wiki-capture",
  "title": "Wiki capture",
  "folder": "wiki-tooling",
  "tags": ["dashboard"],
  "kind": "tool",
  "summary": "Capturing Claude Code sessions into the personal wiki; in daily use.",
  "updated": "2026-11-10",
  "state_as_of": "2026-11-06",
  "new_sessions": 3,
  "why": "3 new sessions",
  "due": true,
  "reviewed": false,
  "path": "wiki-tooling/wiki-capture.md"
 }
]
```

| Field | Use |
|---|---|
| `slug` | Pass this to `review` |
| `title`, `kind`, `summary` | From the topic page's frontmatter. `kind` is only on pages from before tags became the kind (empty otherwise) |
| `personal_tags` | The topic's tags the reference tag list isn't known to have |
| `folder` | The folder the topic is in (a tag's name), or an empty string |
| `tags` | The topic's tags |
| `updated` | The date of the newest session on the topic |
| `state_as_of` | When the current state was last written, or an empty string if never |
| `new_sessions` | Sessions added since the last review |
| `why` | A phrase to show: the flag's reason from the table above when the topic is flagged, otherwise "3 new sessions" (the count) or "nothing new" |
| `due` | True if the topic is flagged or `new_sessions` has reached the threshold |
| `reviewed` | True if the topic has been reviewed since it last changed: `state_as_of` is set, it is not flagged and `new_sessions` is 0. WikiApp's Promotion tab requires this of a topic |
| `path` | The topic page's path inside the personal wiki |

### 2. Review one topic, or every topic that is due

```
python sb.py review <topic> --json
python sb.py review --due --json
```

One request to the review model (Sonnet by default) for each topic. It rewrites the page's current state and its one-line summary from all the topic's session notes, clears the flag and its reason, and regenerates the index. The Notes section and the log are left exactly as they are. Any topic can be reviewed, due or not, as long as it has at least one session note.

```json
{
 "reviewed": [
  {"slug": "wiki-capture", "title": "Wiki capture", "sessions_used": 5, "state_as_of": "2026-11-10", "path": "wiki-tooling/wiki-capture.md"}
 ],
 "errors": [
  {"slug": "stop-loss-trend-report", "error": "The reviewer's reply had no state_markdown"}
 ]
}
```

- Each reviewed topic also has `notes_used`, `warnings`, `conflicts` (the conflicts this review found, objects as below), `related` (`[{topic, why}]`), `tags` (the topic's tags after the review), `personal_tags` and `new_tags`.
- **Related.** A review also writes the page's `## Related` section (added after Current state on a page that has none), from nothing every time: one `- [[topic]] — why` line per related topic. The reviewer is offered candidates worked out from the pages (topics filed together in a record, with a count; topics sharing a tag; topics linked in the page's Notes) and keeps those still supported; only existing topics are written.
- **Links in Current state** go only to existing topics: the reviewer is given the topic list, and any other `[[link]]` (in Current state, the summary or a Related line) is turned back into plain text, with a warning.
- **Tags.** A review adds tags and keeps the topic's own: the reviewer lists only tags to add (a new one is handled as in capture). It takes a tag off only by naming it under `remove_tags` with a reason, and every removal is listed in `warnings` with that reason; one without a reason is refused, with a warning. The topic's folder tag always stays. Additions stop at six tags.
- **No to-dos in Current state.** Its Open list is for unknowns and undecided questions only. Any checkbox line in the reviewer's reply is left out (with a warning), together with the lines under it.
- A topic whose review failed is listed under `errors` and stays due. The others are still reviewed. The exit code is 1 if `errors` has anything in it.

**Notes outrank sessions, and conflicts are shown.** The reviewer is told which records are notes and which are sessions. Where a session contradicts a note (a captured note, or the page's Notes section), Current state states the note's version, and a Conflict block under it shows both:

```
> **Conflict** (c-1a2b3c4d5e): your note and a session disagree. Current state follows your note.
> Your note ([[2026-11-04-pricing-call-n1a2b3c4]]): Reported quarterly.
> Session ([[2026-11-05-monthly-11111111]]): Reported monthly.
```

A conflict object is `{id, topic, note_text, session_text, session_ref, note_ref, found, status}` (`note_ref` is `notes-section` for the page's Notes). `conflicts` lists the open ones. `resolve-conflict <id> <resolution>` settles one:

| Resolution | Effect |
|---|---|
| `keep_note` | The block is removed; the note's version stands |
| `accept_session` | The block becomes a `**Settled**` line giving the session's version, the topic is flagged for review (`review_reason: conflict`), and the next review states the session's version. The note file is never edited |
| `dismiss` | The block is removed |

It returns `{conflict, topic, path, changed}`. A conflict's id comes from the two records and their text, so a settled conflict is not raised again by later reviews unless one of the two texts changes. Settled conflicts are listed to the reviewer too.
- `sessions_used` is at most 40: the newest 40 session notes are sent.
- `review` needs a topic name or `--due`.

### 3. Suggest folders

```
python sb.py folders-suggest --json
```

No model call. The suggestions are computed from the topic pages' `tags`. Nothing is moved.

```json
[
 {
  "tag": "stop-loss",
  "new": true,
  "title": "Stop loss",
  "topics": ["stop-loss-trend-report", "stop-loss-lasering", "stop-loss-renewals"]
 }
]
```

| Field | Meaning |
|---|---|
| `tag` | The tag that would become, or already is, a folder |
| `new` | True if the tag has no folder yet. A new folder is suggested only when at least three top-level topics share the tag (`folder_after_topics`). With `new` false, the topics are top-level topics that carry the tag of an existing folder |
| `title` | For a new folder's hub page: the tag with its dashes as spaces. For an existing folder, its hub page's title |
| `topics` | Topic names to move. A topic appears in at most one suggestion: an existing folder first, then the tag most topics share |

- Only top-level topics are offered. A topic already in a folder stays there.
- A tag is left out if it can't become a folder: a folder with that name already exists that the tool did not make, or some page in the wiki already has that name (the hub page would need it).
- Suggestions are not stored anywhere. The page shows each one with an accept and a dismiss button; dismissing needs no command.

### 4. Apply a folder

```
python sb.py folders-apply --tag stop-loss --title "Stop loss" --topics stop-loss-trend-report,stop-loss-lasering,stop-loss-renewals --json
```

No model call. It makes `<tag>/` and its hub page `<tag>/<tag>.md` (`type: folder`) if the tag is not a folder yet, moves each topic's page into that folder, sets the topic's `folder`, adds the tag to the topic if it lacks it, and regenerates the index, which also refreshes the hub's list of topics. `--title` is only used for a new folder. Links go by page name, so moving a page breaks none.

```json
{"tag": "stop-loss", "created": true, "moved": ["stop-loss-trend-report", "stop-loss-lasering", "stop-loss-renewals"], "hub": "stop-loss/stop-loss.md"}
```

- `created` is true if the hub page was made by this call.
- `moved` lists the topics whose pages actually moved; one already in the folder is left out.
- It fails if a named topic has no page, or if the tag can't become a folder (see above).
- A topic lives in one folder at most, and keeps all its tags.
- This command does not enforce the three-topic minimum. That rule belongs to the suggestions.

### 5. Suggest merges

```
python sb.py merge-suggest --json
```

One request to the review model: the wiki reviewer's second job. It is sent every topic (name, one-line summary, tags) and the tags in use, and suggests topics that are the same work under two names, and tags that mean the same thing. Nothing is changed. With fewer than two topics it returns `[]` without calling a model.

```json
[
 {"kind": "topic", "keep": "stop-loss-trend-report", "merge": ["stoploss-trend"], "reason": "Both record the same monthly trend report."},
 {"kind": "tag", "keep": "stop-loss", "merge": ["stoploss-reporting"], "reason": "Two names for the same subject."}
]
```

| Field | Meaning |
|---|---|
| `kind` | `topic` or `tag` |
| `keep` | The name that stays |
| `merge` | The names to fold into it |
| `reason` | One sentence to show the user |

The reply is checked before it is returned: only names that exist are kept, and within a kind each name appears in one suggestion at most. Suggestions are not stored anywhere.

### 6. Apply a merge

```
python sb.py merge-apply --kind topic --keep stop-loss-trend-report --merge stoploss-trend --json
python sb.py merge-apply --kind tag --keep stop-loss --merge stoploss-reporting --json
```

No model call.

**`--kind topic`** folds topics into one:

- the merged topics' log lines (their sessions) and tags move to the kept page;
- the person's own Notes text on a merged page is added to the end of the kept page's Notes, under "From <title>:";
- every `[[link]]` to a merged topic, anywhere in the wiki, is repointed to the kept one. That carries tasks linked to it over;
- session notes' `topics:` lists are updated;
- the merged pages are removed, and the index is regenerated;
- the kept topic is flagged for review (`review_reason: merged`).

```json
{"kind": "topic", "keep": "stop-loss-trend-report", "merged": ["stoploss-trend"], "path": "stop-loss/stop-loss-trend-report.md"}
```

It fails, changing nothing, if a named topic has no page.

**`--kind tag`** replaces tags with one:

- on every topic, folder page and session note that carries a merged tag;
- if a merged tag was a folder, the folder and its hub page are renamed to the kept tag, and links to the hub are repointed.

```json
{"kind": "tag", "keep": "stop-loss", "merged": ["stoploss-reporting"], "pages": 7}
```

`pages` is how many pages had the tag replaced. The merge is refused if more than one of the tags involved is a folder.

## Choosing the personal wiki

Sessions can only ever be written to the personal wiki, and this is enforced by the tool, not the app:

- **In WikiApp** (a private `.wiki` folder exists), each open wiki has a role kept in `.wiki/wiki-settings.json` (`pathlist.wiki_roles`; TECHNICAL.md §7.1): `personal` (one at most), `team` (one at most) or `view`. Every write command (`init`, `ingest`, `ingest-file`, `capture-note`, `skip`, `review`, `folders-apply`, `merge-apply`, `resolve-conflict`, `reindex`) checks the folder it is given first: the wiki whose role is `personal` is allowed, with or without a `WIKI.md` (an existing one is left alone); a team or view-only wiki is refused in plain words ("Northwind is view only; choose your personal wiki in Settings."), and so is a folder outside the open wikis while another wiki is personal. Nothing is written and no model is asked.
- **On the command line on its own** (no private folder, or a folder that isn't one of WikiApp's open wikis while none is personal), `config.json` (or `--personal`) names the folder, and it must contain a `WIKI.md` whose frontmatter says `type: personal`, as before.

So "designate a personal wiki" in the app is: give it the `personal` role, then run `python sb.py init --json` (Set up), which creates the `Sessions` folder, the promotion queue and the index if they are missing, and never `WIKI.md` (an existing one is left alone). Topic pages are added at the top level as sessions are ingested. It returns `{"wiki": "...", "created": ["Sessions/", "promotion-queue.md", "index.md"]}`: exactly what it made, in that order (`[]` when everything was there). WikiApp's `sessionsSetup` returns `status` plus that `created`. On the command line on its own, `init` also writes `WIKI.md` (from `templates/personal-WIKI.md`, listed first in `created`), because that is how `sb.py` alone knows the folder is personal; every write command there refuses a folder without it. `init` is safe to run on a wiki that already exists.

For several users, give each their own config file and pass it with `--config <path>` or the `SECOND_BRAIN_CONFIG` environment variable.

## Rules and prompts

**The personal wiki's rules** are the user's own "My capture rules" file (`.wiki/capture-rules.md` in WikiApp's private folder, path-list entry `personal_capture_rules`; Settings, Rules). Its text (below any comments) is sent with every capture and every topic review. A merge suggestion is not sent it. The personal wiki has no `wiki_rules.md`, and the body of `WIKI.md` is not used as rules; that file only marks the folder as personal for the command line on its own. Team wikis keep a `wiki_rules.md` (below).

**The prompts** are not in this folder. Capture uses the executive assistant's prompt and review uses the wiki reviewer's. Each has one prompt file, a slot in the app's path list (by default `<private .wiki folder>/prompts/<agent id>.md`, copied there from the shipped default in `../agents/<agent id>/SKILL.md`), read through `../agents/agentfiles.py`. `install` puts copies into `~/.claude/skills` only when you run it, for calling the agents by name in Claude Code. The tool sends the file's body, then a divider, then the sections it adds for the request (there is no shared task guide any more: the agents never write or change tasks). For a capture: the wiki's rules, the person's capture rules, the existing topics, the tag lists, the existing tags, the reply format, the source. The capture request does not name the folder a session ran in: a folder or file name is never evidence of what the work was about. For a review: the wiki's rules, the analyst's own notes on the topic, the session notes, the reply format. For a merge suggestion: the topics, the tags in use, the reply format. Set `WIKIAPP_SKILLS_DIR` to read the skills from another folder.

`install` copies the agents' skill files only where they are missing. `--force` replaces the helper skills and the lookup agent, never an agent's prompt. All three agent skills have `disable-model-invocation: true` in their frontmatter, so Claude Code only runs one when it is called by name.

## The team wiki

No command here writes to the team wiki's pages. It is changed only by the team wiki manager, because that step needs a person to review each change:

- In WikiApp, the Promotion tab sends the chosen topic pages, folder pages and the promotion queue to the team wiki manager, and each proposed change is a card to accept or reject. That runs through `ingest/run.py`, not this tool.
- In Claude Code, the `team-wiki-manager` skill does the same work by editing the team wiki's files, for review as a diff.

The team wiki's rules are its `wiki_rules.md`, the file every agent that works there is sent. `templates/team-wiki_rules.md` is a starting point to copy in under that name. The team wiki needs no `WIKI.md`. The team wiki manager never creates a table page: those come from the `data-dictionary` skill (a placeholder here), run in Claude Code, which reads the same `wiki_rules.md`. A finding about a table that has no page goes on its subject area's page.

What an app can usefully show:

- The promotion queue at `<personal wiki>/promotion-queue.md`. Lines starting `- [ ]` are findings waiting to be promoted, and `status` counts them as `queue_pending`. A line is ticked (`- [x]`) once it has been promoted; WikiApp ticks the lines a promotion run saw when all its cards are handled.
- Topic and folder pages that have not been promoted since they changed. WikiApp records a promotion as `promoted: <time>` in the page's frontmatter and compares it with `changed`, a UTC time this tool stamps on a topic page when a capture, a review, a merge or a move into a folder writes it, and on a folder's hub page when topics move into it or its tag is merged. This tool neither writes nor reads `promoted`, and it keeps the key when it rewrites a page.
- Whether a topic is ready to promote. WikiApp lets a topic be selected only once it has been reviewed since it last changed: `state_as_of` is set, `needs_review` is false and `entries_since_review` is 0. That is `reviewed` in `review-list`. Until then the row is disabled and says to review it first. A "Show already promoted" checkbox there lists promoted pages again.
- `python sb.py reindex --wiki team --json` regenerates the team wiki's `index.md` from page frontmatter and returns `{"wiki": "...", "pages": 42}`. It is safe to run at any time. It needs the team wiki's folder, from `--team` or `team_wiki` in `config.json`.

## Other commands the app may want

| Command | What it does |
|---|---|
| `reindex --json` | Regenerate the personal `index.md` from the topic pages, and each folder hub's list of topics, for example after deleting a topic by hand. Returns `{"wiki": "..."}` |
| `condense <session_id>` | Print exactly what the capture step would be shown for a session, masking included |
| `install --json` | Put the three agents' skill files, the helper skills (`wiki-capture`, `data-dictionary`) and the `wiki-lookup` agent into `~/.claude` (or `--dest`). Returns `{"written": [paths], "kept_existing": [paths]}`. Existing files are kept. `--force` replaces the helper skills and the lookup agent, never an agent's prompt |

## Committing

Nothing here runs git. Ingestion changes files in the personal wiki and stops. Reviewing and committing is a separate step, whether done by hand or by a separate button in the app.

## What the tool writes

All inside the personal wiki folder:

| Path | Written by | Safe to edit by hand |
|---|---|---|
| `Sessions/<date>-<title>.md` (`-<id piece>` only on a clash; older records keep `-<id>`) | `ingest`. `merge-apply` updates its `topics` or `tags` | Yes, but a re-ingest overwrites it, apart from a `## Tasks` section an earlier version wrote |
| `<slug>.md`, or `<tag>/<slug>.md` once in a folder | `ingest` (the log, the frontmatter), `review` (the current state, the summary), `folders-apply` (moves it), `merge-apply` (adds to the kept page, removes the merged ones) | Only the Notes section. Everything under the `## Current state`, `## Related` and `## Log` headings is managed (Related is written again by each review): the log is written again from the session notes on every capture, so anything typed there is replaced. Keep those three headings as they are; a page missing one is left alone with an error naming it. Use `###` for headings of your own inside Notes |
| `<tag>/<tag>.md` | `folders-apply` makes it; its list of topics is refreshed whenever the index is. `merge-apply --kind tag` renames it with its folder | Its Notes section. Everything under its `## Topics` heading is managed |
| `index.md` | regenerated on every ingest, review, `folders-apply`, `merge-apply` and `reindex` | No |
| `promotion-queue.md` | `ingest` adds lines; WikiApp's Promotion tab ticks them | Ticking or deleting lines is fine |
| Any other page of the wiki | `merge-apply` repoints `[[links]]` to a merged topic or a renamed folder | Yes |
| A captured note | `capture-note` sets `capture_id` and `ingested` in its frontmatter, and nothing else | Yes |

In the progress folder (see the layout above), not the wiki:

| File | Written by | Safe to edit by hand |
|---|---|---|
| `ledger.json` | `ingest`, `skip`, `capture-note`; `list` adds a new session's readable `name` | No. It records which sessions and notes are done, and each session's name (an entry with only `name` is a session not captured yet) |
| `conflicts.json` | `review`, `resolve-conflict` | No |
| `spend.json` | every command that calls the model | Yes |
| `lock` | present only during a write | Delete it if a crash leaves it behind; it expires on its own after 10 minutes |
| `llm/` | an empty working folder for the model calls | Yes |

The page frontmatter this tool keeps:

| Page | `type` | Other keys |
|---|---|---|
| Session note (a record) | `session` | `title`, `origin` (`session` or `note`), `date`, `session_id` (`note:<capture_id>` for a note), `source` (`claude-code`, `file` or `note`), `project`, `topics` (a list of topic names), `tags` (the union of those topics' tags), `entries`, `ingested`, and `capture_id` for a note |
| Topic page | `topic` | `title`, `tags` (a list; they are the kind: a page from before may still have `kind`), `folder` (the tag whose folder it is in, or empty), `summary`, `created`, `updated`, `state_as_of`, `entries_since_review` (sessions added since the last review), `needs_review` (true or false), `review_reason` (`reversed`, `removed`, `merged`, or empty), `changed` (a UTC time, stamped on each write) |
| Folder hub page | `folder` | `title`, `tags` (the folder's tag), `summary`, `created`, `updated`, `changed` |

Topic pages are found by `type` and by name, wherever they sit outside `Sessions/`. A hub page is a `type: folder` page named after the folder it is in. Names must be unique across the wiki, because links go by page name: a new topic is refused if another page already has its name. A page without one of these types is left alone, apart from the link repointing above. Folders called `Templates`, and folders whose name starts with a dot, are never read.

## If hooks are ever enabled

The original plan was to capture automatically when a session ends. That would be a `SessionEnd` hook running `python sb.py ingest <session_id>` in the background, with the session id taken from the hook's input. Nothing else would change, and the ingestion page would simply have less in it.

## Page sections and the log

Pages carry no marker comments. The parts the tool writes are found by their headings: `## Current state`, `## Related` and `## Log` on a topic page, `## Topics` on a folder's page, `## Findings` in `promotion-queue.md`. A section runs to the next `#` or `##` heading.

A session note's frontmatter has `entries`, one `"<topic>: <line>"` per topic. A topic's log is rebuilt from those on every capture and merge, newest first, so it always matches the notes. Notes written before `entries` existed keep the line they already had.

Pages written by earlier versions had `<!-- sb:... -->` comments around these parts. They are removed the next time the index is written.

## Cost

Every `ingest` and `review` result has `spend`: `{"cost", "tokens_in", "tokens_out", "calls", "model"}`. `cost` is the request's tokens priced from the app's own table of API list prices (`ingest/costs.py`) for the model that answered, in US dollars; `spend.model` is that model's exact id. Claude Code's own cost figure isn't used, because a version older than a model misprices it. On a subscription nothing is billed per token; the figure still shows how heavy the request was. A skipped session that reached the model has `spend` too.

`status` returns `spend`, the wiki's running totals by kind (`capture`, `review`, `merge`), each with `cost`, `tokens_in`, `tokens_out`, `calls` and `runs`. They are kept in `spend.json` in the progress folder, and each ledger entry records its session's `cost`. The tokens come from agentlib's reply (`Reply.usage`, `Reply.model`); a request whose reply had the wrong shape is still counted.

WikiApp's Sessions tab shows the cost on each result, and the total and average per ingest above the results.

## Choosing the model

`--model <exact id>` on `ingest`, `ingest-file`, `review` or `merge-suggest` sets the model for that command; without it the config's `extract_model` (default `claude-haiku-5-5`) and `review_model` (default `claude-sonnet-5-5`) are used. WikiApp passes the model picked in each tab's menu (`sessionsModel`, `reviewModel` in its settings; the Notes and Promotion tabs keep `ingestModel` and `promotionModel`). Every menu lists the models Claude Code offers on the computer, by name and exact id, with the tab's default marked.
