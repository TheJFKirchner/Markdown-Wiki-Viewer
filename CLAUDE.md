# WikiApp

A small, customizable, Obsidian-style app for folders of Markdown notes. It opens several folders at once (say a personal and a team wiki, each with an alias), shows how notes link in a graph, and has tasks, quick notes from templates, search and in-place editing. The user-facing docs are in [README.md](README.md).

## Goals and constraints

- **Anyone can clone the folder and run it on Windows or macOS.**
  - They double-click `WikiApp.cmd` or `WikiApp.command`.
  - The first start runs `App Files/setup.py`, which makes `App Files/.venv`, installs `requirements.txt`, and finds and installs agentlib (below). Every later start is quick.
  - Prerequisites: Python 3.11+, and for the AI features agentlib beside the project folder, set up once (its `setup/claude-setup.md`, checked with `python -m agentlib.check`). No console window stays open.
- **All agent code goes through agentlib** (`..\General-Purpose-Productivity\agentlib`, see the top-level CLAUDE.md). Never import `claude_agent_sdk`, never run `claude -p`. agentlib is never copied into the app: `setup.py` installs it editable. Test agents on agentlib's fake engine (zero tokens).
- **The app decides nothing about where the user's things go.** Everything private to the user is in one `.wiki` folder at a place they choose; every path comes from `host/pathlist.py`, and Settings shows them all. Never hard-code a path, never write into `~/.claude` or into a wiki's own folders beyond what a feature exists to write, and never create a folder the user didn't ask for.
- **No build step for the app.** `App Files/app/` is plain HTML, CSS and ES modules. Press F5 (Cmd+R on a Mac) in the app to reload after an edit.
- **One host, one page.** `host/wikiapp.py` (pywebview) is the host, for Windows and macOS: it opens the window and answers the page's commands.
- **Notes stay plain Markdown** that other editors can read. Tasks, quick notes and templates are all just text conventions (formats in README).
- **Never lose or overwrite the user's text.** Every write goes through the host and is refused if the lines on disk changed since the page read them.

## Layout

The project root has two folders, kept apart on purpose:

- **`App Files/`**: everything the app is made of. The host finds `app/`, `agents/`, `ingest/` and `sessions/` relative to itself, so the folder works wherever it's copied.
- **`Sample Wikis/`**: the example wikis, `team/` and `personal/`, where present. They're data, not part of the app, and `.gitignore` keeps them out of the repo. The user also uses them as real data, so treat them as theirs.

Also at the root:
- this file;
- `README.md` (user guide);
- `TECHNICAL.md` (technical documentation; keep it accurate when architecture, dependencies, data locations or host commands change);
- the launchers:
  - `WikiApp.cmd` must have CRLF line endings, and `WikiApp.command` LF. `.gitattributes` keeps them that way.
  - Keep both launchers tiny: the logic belongs in `setup.py`.
- `.gitignore`: leaves out `.venv`, caches, `Share/`, `Sample Wikis/`, `.wiki/` (the user's private folder, suggested in the project folder) and `*.lnk` (a shortcut holds this PC's absolute path);
- `make_share.py`, which builds a clean copy to send to others in `Share/`.
  - It ships the app only: no wiki content (`Sample Wikis/` is never copied), no `.wiki`, `.venv` or caches, and not agentlib.
  - Then it checks the copy for the user name.
  - Keep its include and exclude lists in step when adding top-level files.

Paths below, and in `ingest/DESIGN.md` and `ingest/AGENT.md`, are inside `App Files/`.

| Path | What it is |
|---|---|
| `setup.py`, `requirements.txt` | Make `.venv`, install the packages (pywebview, pyyaml, pywin32 on Windows) and agentlib (found beside the project folder, installed editable; it brings the Claude Agent SDK). Run before every start; returns at once when nothing changed. None or several agentlibs: the app starts with AI off and says why. |
| `host/wikiapp.py` | The host. It opens the window and serves `app/` on 127.0.0.1 under a secret path. It answers the page's messages, keeps settings and the window position, and allows one instance (`instance.json`, or a guard port during the first start). |
| `host/pathlist.py` | **Every path the app uses, in one list** (standard library only): the private `.wiki` folder and its contents, file slots in three tiers (main, advanced, internal; with status, customise and reset), each wiki's rules, templates, index and progress, the transcripts folder, agentlib, the reference tag list; overrides in `.wiki/paths.json`; row state; engine settings and each agent's model; `read_prompt(name, **values)`. Add new paths here, never elsewhere. |
| `host/appfolder.py` | The private folder's life: first run (preview, validation), choosing it, move or adopt, migration from older versions (copies only), leftovers, agentlib status and install, agentlib's connection check, opening an entry. |
| `host/notefiles.py`, `host/ingestruns.py`, `host/sessionruns.py` | The host's folder scans, note writes, folder watching (polling), Promotion runs, the agents' prompt files, and the Notes, Sessions and Review tabs' calls to `sessions/sb.py`. |
| `host/tests/`, `ingest/tests/`, `sessions/tests/` | Zero-token tests (temporary folders, agentlib's fake engine). Run all three before reporting work done. |
| `agents/` | The three agents behind the Ingest view: `executive-assistant` (Notes capture and Sessions), `wiki-reviewer` (Review), `team-wiki-manager` (Promotion). Each has one advanced prompt slot (`prompt.<agent id>`): the shipped `agents/<agent id>/SKILL.md` is read directly ("built_in") until the user customises it into `.wiki/prompts/<agent id>.md` (`customisePrompt`; `resetPrompt` deletes the copy). `agents/messages/` holds the other shipped wording (Promotion's messages, the capture and review requests, starters): internal, read in place, never copied or listed. `agentfiles.py` reads and saves the prompts. An agent is sent its file's text (frontmatter stripped), then what the code adds for that request. The agents never read, write or capture tasks; tasks live only in the notes where the user typed them. |
| `sessions/` | Capture of sessions and notes, topic reviews (Current state, Related, conflicts), tags, folders and merges, behind the Notes, Sessions and Review tabs: `sb.py` and the `secondbrain` package (it also runs from the command line without the app; model calls through agentlib), the helper skills and the `wiki-lookup` agent that `sb.py install` copies into a `.claude` folder only when run, the templates, and its tests. It writes straight into the personal wiki with no review step, and only into the wiki that has the Personal role (set in Settings, stored in the private `.wiki` folder); `WIKI.md` is no longer required. [sessions/README.md](<App Files/sessions/README.md>) explains it; [sessions/INTEGRATION.md](<App Files/sessions/INTEGRATION.md>) lists every command and its JSON. |
| `app/js/capturenotes.js`, `sessionsview.js`, `reviewview.js`, `ingestview.js` | The Notes (capture), Sessions, Review and Promotion tabs. `main.js` owns the four tabs (`showIngestTab`) and the tab bar's **?** and **Agents and rules** buttons. `modelmenu.js` is the tabs' model menus (the engine settings' per-agent model). |
| `app/js/settingsview.js`, `setup.js`, `ai.js` | The Settings screen (every path-list row, the AI engine), the first-run screen (where to keep `.wiki`), and whether the AI features can run. |
| `host/app.ico`, `host/make-icon.ps1` | The window, taskbar and Dock icon, and the script that draws it. |
| `app/index.html`, `app/css/styles.css` | The page shell and all styles. Every color is a CSS variable at the top of the stylesheet. |
| `app/js/main.js` | The wiring: workspace scans → combined model → views. It owns the view rail, saving, and the start-up session restore. |
| `app/js/vault.js` | The data model: notes, frontmatter, tags, `[[links]]`, duplicates and graph data. |
| `app/js/*.js` | One module per feature: the tasks pane, notes and templates, search, the editors, the graph and its panel. Each file starts with a comment saying what it does. |
| `app/lib/` | Third-party libraries (force-graph, markdown-it, js-yaml). |
| `app/templates/` | The shipped templates: `Notes/Daily.md` and `Weekly.md` (main tier, copied into `.wiki/note-templates/`), and the samples and `starters/` (internal, read in place). Nothing is ever seeded into a wiki. |
| `ingest/` | The agent run behind the Promotion tab (the team wiki manager), in Python through agentlib, written to be read by someone new to agent code: `agent.py` (start here), `tools.py` (its tools, as plain functions), `prompts.py` (the text it's given, from the prompt slots), `wikis.py` (wiki scan, link resolution, index, page templates; rules and templates from the path list), `transcript.py` and `costs.py`, `progress.py`, `run.py` (the command line), `models.py` (the model menu's list, free). Keep it that way: plain names, comments that explain agent ideas. [ingest/DESIGN.md](<App Files/ingest/DESIGN.md>) is the design; [ingest/AGENT.md](<App Files/ingest/AGENT.md>) is exactly what the agent sees and must stay in step with the code. |

## Conventions

- **Note ids** are `alias:path` (for example `personal:Notes/2026-10-31 Daily.md`). Links can name a folder: `[[team:Jupiter]]`.
- **Page ↔ host** talk through JSON messages in `app/js/bridge.js`.
  - The host gets them in `Host.dispatch` in `wikiapp.py` (through `window.pywebview.api.call`).
  - The host's `settings.js` sets `window.__wikiappHost = 'python'`, which tells the page it's in the app and not a plain browser.
  - The host only writes `.md` files inside an open folder, plus files in the private folder and path-list files the user saves.
- **Per-user data** is in one private folder named `.wiki`, at a place the user picks on the first start (suggested: the project folder, git-ignored). The only fixed thing is the pointer `~/.wikiapp-location`. `WIKIAPP_DATA_DIR` names the folder directly (dev runs); `WIKIAPP_POINTER_FILE` moves the pointer (tests). A fresh one holds only what a user edits: `capture-rules.md`, `note-templates/Daily.md` and `Weekly.md`, plus `paths.json` and `leftovers.json`; then, as needed, `settings.json`, `window.txt`, `instance.json`, `engine.json` (engine and each agent's model, the one source of truth the tabs read and write), `prompts/` (only customised agent prompts), `indexes/`, `progress/` (what capture has done, per wiki; was `<wiki>/.sb`), `ingest/pending-promotion.json`, `ingest-runs/`. File slots are main (copied), advanced (agent prompts, built in until customised) or internal (never copied or listed). TECHNICAL.md §7 has every entry, and how an older `.wiki` is tidied (`upgrade_layout`: unedited copies removed, nothing edited deleted).
  - Nothing is created until a place is chosen. A configured path that has gone is reported (`state: "missing"`), never recreated.
  - Changing the place later is move (to an empty place) or adopt (an existing `.wiki`), never merge.
  - The first start copies, never deletes: `~/.wikiapp` (or what the retired Windows-only version left in `%LOCALAPPDATA%\WikiApp` and `%TEMP%\WikiApp\ingest-runs`) and the agents' prompts from `~/.claude/skills` (`appfolder.migrate`). Keep that migration. The retired Notes flow's files are not carried forward. A one-time leftovers list is shown.
  - The user's own files: `personal_capture_rules` (free-text capture rules for the personal wiki; created once, never overwritten or reset), `personal_tags` (`personal-tags.md` in the personal wiki), and `tag_list_reference` (optional, any tags file; read only, never written).
- **Quick notes** are the files in the notes folder (setting `notesDir`, default `Notes`) of any workspace folder; `note.inbox` marks them. The Notes view and the full editor both edit through `livetext.js`, which keeps the text as Markdown lines and only formats the display.
- **Editing as it looks** (`livetext.js` + `richtext.js`): each line is a row with a `contenteditable` box.
  - The box holds the line's inline Markdown, rendered by `viewer.renderEditable` (no typographer; marks carry `data-md`, `[[links]]` carry `data-src` and are uneditable atoms).
  - `serialize` turns the box back into Markdown on every keystroke. The row's prefix (`##`, `- `, `1. `, indent) is kept aside in `row._kind`.
  - A line whose Markdown doesn't survive render → `serialize` unchanged is shown raw (class `raw`). Never relax that check: it's what keeps edits from rewriting text the user didn't touch.
  - Structural edits (Enter, Backspace joins, Tab, shortcuts) change `lines`, then `redrawAt` redraws and puts the caret back.
- **Rules are the main lever.** A team wiki's rules file (path-list `wiki.<alias>.rules`, default `<wiki>/wiki_rules.md`) reaches the team wiki manager in every Promotion run. The personal wiki's only rules are the user's capture rules (`personal_capture_rules`, `.wiki/capture-rules.md`), sent with every capture, review and merge suggestion; a `wiki_rules.md` in the personal wiki is not read. Agent prompts are the advanced lever. `WIKI.md` only marks a folder as personal; its body is not used as rules.
- **Only Promotion reaches a team wiki.** Notes and sessions are captured only into the personal wiki; Promotion proposes each team-wiki change as a card the user accepts.
- **Topics, tags and folders (personal wiki):**
  - A topic is a page about one piece of work (`type: topic`), kept at the top level as `<slug>.md`, with Current state, Related, Notes and Log.
  - Pages carry no marker comments. `sb.py` finds the parts it writes by their `##` headings (`get_zone` and `set_zone` in `wiki.py`), and leaves a page alone, with an error, if a heading is missing. A topic's log is written again from the records (`rebuild_log`) on every capture and merge, never edited in place; each line is marked `[note]` or `[session]`. Related is written again by each review.
  - Notes outrank sessions: a contradicting session raises a conflict (Current state follows the note) for the user to settle in the Review tab.
  - A tag is only a label in a topic's frontmatter `tags:` saying what kind of thing it is and what it belongs to (there is no `kind` field any more). Tags come from the reference tag list and the personal tags. A tag has no page of its own.
  - Records live in one flat `Sessions/` folder (`type: session`, `origin: session` or `note`). A record's frontmatter has `topics:` and `tags:` (the union of its topics' tags), so they are ordinary tags in the app.
  - When three or more top-level topics share a tag, the tag can become a folder `<tag>/` with a hub page `<tag>/<tag>.md` (`type: folder`). A topic lives in one folder at most and keeps all its tags.
  - Topics, and tags, that duplicate each other can be merged (`merge_topics`, `merge_tags` in `sessions/secondbrain/wiki.py`).
  - Links go by page name, so moving or merging a page breaks nothing.
  - A wiki from the first version (`tags/`, `session-notes/<year>/`) is upgraded the first time it's used (`upgrade_layout` in `wiki.py`). Keep that upgrade.
- **Templates:** a wiki's `Templates/` folder has `Notes/` (quick-note templates, for the New note menu; files directly in `Templates/` still count, the older layout) and `Pages/` (page templates for Promotion's new pages, `description` = when to use it). Everything under `Templates/` is left out of the graph, tags and tasks. Daily and Weekly are the user's, in `.wiki/note-templates/`; a wiki without `Templates/` has no page templates of its own. Nothing is ever seeded into a wiki.
- **Scripts** (`.sql`, `.py`... see `SCRIPT_EXT` in `vault.js`) live in `vault.scripts`, not `vault.notes`. They're link targets only (`resolveTarget` = notes, then scripts) and their text is read on demand, never scanned for links.
- **Settings** use `localStorage`. `app/js/persist.js` mirrors it into `settings.json`, so the app opens the same way however it's started. The page starts each run with empty storage, because its origin has a new random port, so the file is what counts.
- Match the existing style: small modules, a short header comment per file, plain DOM, no frameworks.
- **Write scripts in Python where possible** (tooling, the ingest agent, one-off helpers). Don't force it where it would complicate things: the page stays JavaScript, and a tiny launcher can stay a `.cmd` or `.command`.

## Working on it

- **Test in the real app on copies, never on the user's folders.**
  1. Copy `Sample Wikis/` (or any test wiki) to a scratch folder.
  2. Write a scratch `settings.json` whose `workspace` points at the copies.
  3. Start `App Files/.venv/Scripts/python.exe App Files/host/wikiapp.py` with `WIKIAPP_DATA_DIR=<scratch data folder>` and `WIKIAPP_DEBUG_PORT=9334`. (To try the first-run screen, set `WIKIAPP_POINTER_FILE` to a scratch file that doesn't exist instead, and choose a scratch place.)
  4. Drive it through the DevTools protocol (`http://127.0.0.1:9334/json`; the page URL contains `127.0.0.1`).
  5. Check afterwards that the real sample files are unchanged.

  With `WIKIAPP_DATA_DIR` set, the user's own `.wiki` folder and pointer are never touched, and no migration runs. Tests must set `WIKIAPP_POINTER_FILE` (or `WIKIAPP_DATA_DIR`) to scratch paths and replace `appfolder.old_locations`, or they read the user's real folder and older data. Never press Test connection, or call `testConnection`, in a test: it sends a real request; use agentlib's fake engine. The user's signature and folder list have been overwritten by tests before.

  **Things to know when testing on Windows:**
  - **The venv's `python.exe` is a launcher.** The real process is a child (`python3.13.exe`, or `pythonw3.13.exe`), and that child owns the window.
    - Find it by command line containing `wikiapp.py`. It may have forward slashes if a bash shell started it.
    - Start the user's real copy with PowerShell `Start-Process`, not as a bash background job, which the Bash tool ends with the command.
  - **Pinning depends on `set_taskbar_identity`** (pywin32, on the window's thread). If "Pin to taskbar" or the icon goes missing, check its four window properties (ID, relaunch command, name, icon) first.
- **Live agent runs cost money.** Test on agentlib's fake engine first (the three test suites do).
  - Try the Promotion prompts with `run.py <job.json> --prepare-only` (no request).
  - A job naming a note that doesn't exist stops before calling Claude. That's a free way to test the run plumbing.
- **Moving the sample wikis** breaks the folder paths saved in `settings.json`. To fix it, close the app, rewrite the `workspace` roots in that file, and raise `__rev` above the browser copy's so the file wins (see `persist.js`).
- **Only one instance runs.** A second launch just focuses the first (the host uses `instance.json` in the private folder, or the guard port during a first start), so use a separate `WIKIAPP_DATA_DIR` for a debug copy. A test that probes the guard must patch `guard_port`, or it reaches a real running copy.
- **macOS can't be tested here.** Mac-only code paths (`WikiApp.command`, Dock icon, `open`, process groups) are untested until someone runs them on a Mac.
- **Edit files with the editor tools, not shell scripts.**
  - Heredocs in the shell have eaten backslashes (`\n`, `\r\n`) in code.
  - PowerShell `Get-Content`/`Set-Content` has corrupted non-ASCII characters (`·`, `✎`).
