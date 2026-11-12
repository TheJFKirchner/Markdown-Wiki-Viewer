---
name: data-dictionary
description: Create or update the team wiki page for a database table, including its column dictionary and PHI flags. Use when the user asks to document a table, or when a table's team wiki page needs its column dictionary and PHI section filled in.
---

# data-dictionary (placeholder)

**This is a placeholder.** It creates a correctly shaped stub page and nothing more. Replace the "What to do" section with the real data dictionary process; keep the contract below unchanged so that the team wiki manager (the `team-wiki-manager` skill, and WikiApp's Promotion tab) and the lookup agent keep working.

- Team wiki: `{{TEAM_WIKI}}`

## Contract

**Input**: one table, named as `<database>.<table>` (for example `CLAIMSDB.claim_line`), plus anything already known about it.

**Output**: one page at the table location given in `{{TEAM_WIKI}}/wiki_rules.md` (by default `data/databases/<database>/<table>.md`), in this shape:

```
---
title: <database>.<table>
type: table
database: <database>
subject_areas: [<subject-area>, ...]
summary: one line saying what the table holds and when to use it
status: needs-dictionary | documented
last_verified: YYYY-MM-DD
---
# <database>.<table>

## Purpose
## Grain
## Keys
## Joins
## Gotchas
## PHI
## Columns
## Sources
```

- `status` is `needs-dictionary` until the Columns and PHI sections have been filled by the real process, then `documented`.
- This skill is the only writer of the `## Columns` and `## PHI` sections. Other skills may add to Purpose, Grain, Keys, Joins and Gotchas.
- The page links to each of its subject areas, and each of those subject-area pages links back to it.
- If the database has no overview page yet, create `<database>-overview.md` in the same folder with `type: database`, a one-line summary, and a link to the table.

## What to do

1. Read `{{TEAM_WIKI}}/wiki_rules.md` for the table folder and any table rules.
2. If the page already exists, leave it as it is and say so.
3. Otherwise create the stub in the shape above: `status: needs-dictionary`, today's date as `last_verified`, the Purpose section filled from what you were told, and under both `## PHI` and `## Columns` the single line `_Not yet documented._`
4. Add the table's link to each subject-area page it belongs to. If you were not told which subject areas apply and it is not obvious from the table's name, ask.
5. Report the path of the page.
