---
description: How agents write in the team wiki.
---
# Team wiki rules

This is the team wiki: durable knowledge that is true for any analyst on the team. Pages are added and changed only through the team wiki manager, and every change is reviewed before it is kept: as a card to accept or reject in WikiApp's Promotion tab, or as a diff when the `team-wiki-manager` skill is used in Claude Code. Sessions are never written here directly.

Every agent that reads or writes in this wiki is sent this file. Edit it to match the wiki; the folder names are the part most likely to need correcting.

## Layout

| Page type | Folder | One page per |
|---|---|---|
| `subject-area` | `data/subject-areas/` | subject area, such as claims, membership, stop loss, authorizations |
| `database` | `data/databases/<database>/<database>-overview.md` | database, such as CCW, CLAIMSDB, Salesforce |
| `table` | `data/databases/<database>/` | table |
| `method` | `methodology/` | type of analysis or report and how it is done |
| `strategy` | `strategy/` | team-level project or initiative |
| `note` | `notes/` | anything durable that fits none of the above |
| source | `sources/` | original document that was ingested, kept unchanged |

A table page lives in exactly one database folder and links to at least one subject area.

## Every page

Frontmatter is required and is all that is required:

```
---
title: 
type: 
summary: one line saying what this page is and when to open it
last_verified: YYYY-MM-DD
---
```

The body is free-form unless the type is listed under "Page rules". A short page is a valid page.

End each page with a `## Sources` list naming where the content came from, with the date. Link a source document kept in this wiki. Name work from a personal wiki in plain text ("From analysis work, 2026-11-05"), because other analysts cannot follow links into it.

## Page rules

### subject-area

The routing guide for a subject. Its most important section is **Which source to use**: for each database that holds this subject, when to use it and when not to ("use CLAIMSDB claims for X; use CCW claims for Y"). Then a list of links to the table pages that belong to it.

### table

Tables are the one strict type, because agents rely on them. Sections, in this order: Purpose, Grain, Keys, Joins, Gotchas, PHI, Columns.

- Table pages are created by the data dictionary skill, run in Claude Code. The team wiki manager never creates one, and never writes or edits a table's `Columns` or `PHI` section.
- On an existing table page, the team wiki manager may add to Purpose, Grain, Keys, Joins and Gotchas.
- A finding about a table that has no page yet goes on its subject area's page, with a note that the table has no page.
- Table frontmatter adds: `database`, `subject_areas` (a list), `status`.

### strategy

A strategy page changes as the work moves. Keep a short **Status** section at the top with the date it was last true, and a dated **Decisions** list.

## Never

- No member-level or patient-level data anywhere: no names, IDs, dates of birth, or individual record values. Examples use made-up values.
- No pages about individual people.
