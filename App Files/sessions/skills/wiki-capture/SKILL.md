---
name: wiki-capture
description: Capture finished Claude Code sessions or a meeting summary file into the personal wiki, review its topic pages, group topics into folders, or merge duplicate topics and tags. Use when the user asks to ingest sessions, capture a session, see what is waiting to be ingested, add a Teams meeting summary to their wiki, or review or tidy their topics and tags.
---

# wiki-capture

The personal wiki at `{{PERSONAL_WIKI}}` records the user's work. A script does all the writing; your job is to run it and report what it did. Do not write session notes, topic pages or folder pages by hand, and do not move, rename or delete them: the script keeps the links, the index and the ledger of ingested sessions consistent, and hand edits break that.

All commands are `python "{{SB_HOME}}/sb.py" <command>`. Add `--json` when you need to read the result.

## How the wiki is laid out

- **Topics.** A topic is one piece of work: a project, an analysis, a question or a tool. Each topic has a page, `<topic-name>.md`, at the top level of the wiki. The page has a "Current state" section, a "Notes" section that belongs to the user, and a dated "Log" with one line per session.
- **Tags.** A tag is only a label in a topic's frontmatter (`tags:`). It names the wider subject the work belongs to and connects related topics. A tag has no page of its own.
- **Session notes** are in one flat folder, `Sessions/`. Each is a short record of one session: summary, decisions, findings, open questions, tasks. Its frontmatter lists its `topics:` (one to three) and its `tags:` (the tags of those topics).
- **Folders.** When three or more top-level topics share a tag, the tag can become a folder: the topics' pages then sit in `<tag>/`, next to a hub page `<tag>/<tag>.md` that lists them. A topic is in one folder at most and keeps all its tags. Pages are linked by name, so a topic in a folder is still `[[topic-name]]`.
- **`index.md`** lists every topic in one line, grouped by folder.
- **`promotion-queue.md`** collects findings about data that are waiting to go to the team wiki.

## See what is waiting

`list` shows sessions from the last two weeks that have not been ingested, plus any that were ingested and then continued (status `updated`). `list --all` includes ingested and skipped ones. Sessions that a script started through the Agent SDK are never listed.

## Ingest sessions

`ingest <session_id>` reads the transcript, writes the session note, adds a line to the log of each of its topics' pages (making the page for a new topic), updates the index, and queues any data findings for promotion. It also records up to five tasks the user still has to do, and may update open tasks elsewhere in the wiki that the session finished or moved on. It takes up to a minute. Run sessions one at a time and tell the user, for each: the title, the topics it was filed under (and which were new), the tags, how many tasks were written or updated, and whether any topic is now due for review.

Ingesting does not rewrite a topic's "Current state". That is a separate step: see "Review topics" below.

If the user asks to ingest "everything", list first and show them what will be ingested before starting. Leave out the session you are currently in unless they ask for it; it is still changing.

A result of `skipped` means the capture step found nothing durable in the session; pass on its reason. `ingest <id> --dry-run` shows what would be captured without writing.

## Skip a session

`skip <session_id> --reason "..."` removes a session from the waiting list without ingesting it.

## A meeting summary

`ingest-file "<path>" --date YYYY-MM-DD` ingests a Teams recap or notes file (.md, .txt, .vtt or .docx) the same way. Ask for the meeting date if it is not clear from the file; without `--date` the file's modified date is used.

## Review topics

A topic's "Current state" is a briefing on where that work stands. It is rewritten only by a review, from all of the topic's session notes. A topic becomes due for review once three new sessions are filed under it, or when it is flagged: a session reversed one of its decisions, a session was taken off it, or other topics were merged into it.

- `review-list` shows the topics that are due, and why. `review-list --all` shows every topic.
- `review <topic>` reviews one topic. `review --due` reviews every topic that is due.

A review is written straight away; there is nothing to approve. It replaces the "Current state" section and the topic's one-line summary, and leaves the "Notes" section and the "Log" as they are. Each review is one model call and can take a minute. Review only when the user asks, or offer it when an ingest reports a topic as due. A topic has to be reviewed before it can be promoted to the team wiki.

## Group topics into folders

- `folders-suggest` lists the tags that could become folders, and the topics that would move. It is worked out from the pages, with no model call, and it moves nothing. A new folder is only suggested when three or more top-level topics share the tag. It can also suggest adding topics to a folder that already exists.
- `folders-apply --tag <tag> --topics <topic-a,topic-b,topic-c> --title "..."` moves those topics' pages into `<tag>/` and makes the folder's hub page if it is new. `--title` is only needed for a new folder.

A tag cannot become a folder if a folder or a page with that name already exists that the script did not make; the command says so.

Show the user each suggestion, and apply only the ones they accept.

## Merge duplicates

- `merge-suggest` asks the wiki reviewer which topics are the same work under two names, and which tags mean the same thing. It is one model call and it changes nothing.
- `merge-apply --kind topic --keep <topic> --merge <topic-a,topic-b>` folds topics into the one that stays. Their sessions, tags, tasks and the user's own notes move to the kept page, links across the wiki are repointed, and the merged pages are removed. The kept topic is then due for review.
- `merge-apply --kind tag --keep <tag> --merge <tag-a,tag-b>` replaces the tags on every topic and session note. If a merged tag was a folder, the folder is renamed to match.

A merge cannot be undone by a command. Show the user each suggestion and its reason, and apply only the ones they accept.

## The team wiki

This skill never writes to the team wiki. Findings wait in `promotion-queue.md`. They are promoted by the `team-wiki-manager` skill or in WikiApp's Promotion tab, and the user reviews every change.

## Afterwards

Do not commit the wiki. The user reviews and commits separately.
