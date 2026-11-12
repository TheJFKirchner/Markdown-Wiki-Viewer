# Prompt evaluation

**This spends real tokens.** It is not part of the unit tests (`python -m unittest discover tests` does not run it) and it is never run automatically. One round of every case on Haiku costs about $0.03.

It checks that the capture, review and promotion prompts behave as intended, on the model that runs them. Each case is a small invented note, transcript or topic built to tempt one known failure, with stated expectations. The script runs it and prints PASS or FAIL per expectation, then a table over all rounds and the cost. Results vary between runs, so run several rounds (`--rounds 3`) before trusting a change.

## Running it

From this folder, with the app's Python:

```
..\..\..\.venv\Scripts\python.exe run_eval.py --work <scratch folder outside the project> --label after --rounds 3
```

- `--work` must be outside the project. Everything is made there: a private `.wiki` folder, a personal wiki, a small team wiki, transcripts and notes. Each case runs on its own copy, through `WIKIAPP_DATA_DIR`, so the user's own folders, wikis and transcripts are never read or written. Each copy's `settings.json` opens its `personal` and `team` wikis, which get the personal and team roles.
- `--only C1,R2` runs some cases. `--capture-model`, `--review-model`, `--promotion-model` pick the models (Haiku by default for all three).
- Raw results are kept in `<work>/<label>/r<round>/<case>/result.json`, and the table in `<work>/<label>/summary.json`.

## The cases (cases.py)

| Id | Runs | Tempts |
|---|---|---|
| C1 | session capture | an incidental folder name, query figures, the assistant's mechanism, a declined suggestion |
| C2 | session capture | client-like names in the working folder and file paths; the assistant's figures and suggestion |
| C3 | session capture | the analyst confirms a cause, not the assistant's explanation of it |
| C4 | session capture | a long session with figures and explanations and nothing the analyst stated |
| C5 | session capture | a general explanation the analyst only acknowledges |
| C6 | session capture | the analyst states a rule and says what they still need to do |
| S1 | session capture | a subagent's finding, relayed by the assistant and confirmed by the analyst (captured) |
| S2 | session capture | a background subagent reports a data problem the analyst never acknowledges (not captured) |
| S3 | session capture | the assistant's instructions to a subagent state facts the analyst never said (never captured as the analyst's) |
| N1 | note capture | numbers to keep; a checkbox to-do |
| N2 | note capture | a method for every customer, written while working for one client |
| N3 | note capture | a check for every client's files, first met with a new client |
| N4 | note capture | a vendor named in passing beside an "every client gets a page" rule |
| N5 | note capture | checkbox and plain to-dos mixed with knowledge |
| R1 to R4 | topic review | tags to keep; to-dos in records and Notes; a session contradicting a note; a filing question left in a record |
| E1 | capture, then review | the first live run end to end |
| P1 | Promotion | a topic mixing method knowledge with feedback on a named colleague and an HR remark |

Captures run with `--dry-run`, so they are checked on the reply alone. Reviews run on records written straight into the copy. Checks are keyword checks: read the detail of a FAIL before concluding, since a paraphrase can trip one.

All names, companies and figures are made up.
