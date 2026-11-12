# WikiApp: technical documentation

This document is for anyone who has to understand, review, run or change WikiApp without help from AI tools.

It explains:
- what the program does;
- how its parts fit together;
- what it depends on;
- what it reads, writes and sends over the network;
- how to build, debug and change it.

The user guide (features, note and task formats) is in [README.md](README.md). The agent run behind the Ingest view's Promotion tab is specified in detail in [App Files/ingest/DESIGN.md](<App Files/ingest/DESIGN.md>) and [App Files/ingest/AGENT.md](<App Files/ingest/AGENT.md>). The Notes (capture), Sessions and Review tabs are covered by [App Files/sessions/README.md](<App Files/sessions/README.md>) and [App Files/sessions/INTEGRATION.md](<App Files/sessions/INTEGRATION.md>).

**How it was made.** The code was written with AI assistance (Claude Code) over a few sessions in October and November 2026. Every part is ordinary, readable source in mainstream languages: Python and JavaScript. There is no generated binary blob, no obfuscation and no build pipeline. Each source file starts with a comment saying what it does.

---

## 1. What it is

A desktop app for Windows and macOS that opens folders of Markdown (`.md`) notes, like a personal wiki and a team wiki, and lets you:
- browse them;
- see how the notes link to each other in a graph;
- search them;
- edit them;
- track tasks written inside them;
- write quick notes from templates.

An optional feature, **Ingest**, sends text to Claude (Anthropic's AI model) through **agentlib**, a separate engine-neutral library (§2). It has four tabs, each the work of one of three agents (§8, §8a):
- **Notes** (the executive assistant): wrapped quick notes are captured into the personal wiki as records filed under topics, exactly like sessions, and written straight away.
- **Sessions** (the executive assistant): a Claude Code session becomes a session note filed under topics, with tags, written straight into a folder marked as the personal wiki.
- **Review** (the wiki reviewer): rewrites a topic page's Current state and Related section in the personal wiki, raises conflicts where a session contradicts a note, and suggests merging duplicate topics and tags. The tab also turns a tag that several topics share into a folder.
- **Promotion** (the team wiki manager): personal pages become proposed edits to the team wiki, which a person accepts or rejects card by card. **It is the only route by which anything reaches a team wiki.**

Notes stay plain Markdown files in the user's own folders. The app keeps no database. Any other Markdown editor can open the same files. Everything private to the user (settings, prompts, progress) is in one folder named `.wiki`, at a place the user chooses (§7); the app never writes into a wiki except for what a feature exists to write there.

---

## 2. Requirements

The app is a web page inside a window opened by its host, `host/wikiapp.py`: Python with pywebview, for Windows and macOS (§4). `WikiApp.cmd` or `WikiApp.command` starts it.

### To run the app

| Requirement | Detail |
|---|---|
| Windows 10 or 11, or a recent macOS | Tested on Windows 11. macOS support is written but not yet tested on a Mac (§11). |
| Python 3.11 or newer | agentlib needs 3.11 (`setup.py` refuses older). Tested with Python 3.13 from the Microsoft Store. On a Mac, use python.org or Homebrew; the system's `python3` is too old. |
| Python packages | Listed in `App Files/requirements.txt`, with the tested versions: `pywebview` 6.2.1 and `pyyaml` 6.0.3 (`pywin32` on Windows). They're installed into `App Files/.venv` by `App Files/setup.py`, which the launchers run before every start. It returns at once unless `requirements.txt`, or which agentlib folder is used, changed. pywebview pulls in `pythonnet` (to use WebView2 through .NET) on Windows, and `pyobjc` (WebKit) on macOS. |
| The system web view | Windows: Microsoft Edge WebView2 Runtime (ships with Windows 11 and current Windows 10) and .NET Framework 4.x (built in). macOS: WebKit (built in). |

No installer, no admin rights, no registry entries. Node.js isn't needed.

### To use Ingest (optional)

| Requirement | Detail |
|---|---|
| agentlib, beside the app | A separate library (`..\General-Purpose-Productivity\agentlib` today) that maps the Claude Agent SDK to engine-neutral functions; a Cursor engine is planned. It is never copied into the app. `setup.py` looks in the folders next to the project folder, and one level inside each, for a folder named `agentlib` holding `pyproject.toml` and an `agentlib` package; exactly one found is installed into `.venv` editable (`pip install -e`), which also brings the Claude Agent SDK at the version agentlib pins. None or several: the app starts with the AI features off and says why; the user sets the folder in Settings (the `agentlib` path entry), which installs it. |
| agentlib set up for the user's sign-in | Done once per computer, in agentlib, never in this app: its guide `setup/claude-setup.md` and its own `setup/local.toml` (login, a company settings file, or gateway variables). Check with `python -m agentlib.check` (one tiny request; `--status` sends nothing). The app's Settings screen shows the same status (`connectionStatus`, free) and has a Test connection button (`testConnection`, one tiny request). |
| Internet access | For the one-time package install, and for calls to Claude during a run. |

The app itself never imports `claude_agent_sdk` and never runs `claude -p`: every request goes through agentlib (the Promotion run in `ingest/agent.py`, capture and review in `sessions/secondbrain/llm.py`).

---

## 3. Folder layout

```
Custom Local Obsidian\
├─ WikiApp.cmd                 Starts the app on Windows (runs setup.py, then the host)
├─ WikiApp.command             Starts the app on macOS (the same; LF line endings, executable)
├─ App Files\                  The whole app
│  ├─ setup.py                 Makes .venv, installs requirements.txt, finds and installs agentlib
│  ├─ requirements.txt         Python packages, with the tested versions as minimums
│  ├─ .venv\                   Made by setup.py on each computer; not part of the source
│  ├─ app\                     The user interface: HTML, CSS, JavaScript (ES modules)
│  │  ├─ index.html
│  │  ├─ css\styles.css
│  │  ├─ js\*.js               First-party modules (§5)
│  │  ├─ lib\                  Third-party libraries, vendored (§6)
│  │  └─ templates\            Shipped Daily and Weekly (copied into .wiki), built-in samples and starters
│  ├─ agents\                  The three agents' default prompts (<agent id>\SKILL.md), the other
│  │                           shipped wording (messages\) and agentfiles.py (§8)
│  ├─ sessions\                Capture (sessions and notes), reviews, conflicts, tags, folders, merges: the
│  │                           sb.py command line, its helper skills, lookup agent, tests and docs (§8a)
│  ├─ host\                    wikiapp.py, notefiles.py, ingestruns.py, sessionruns.py (the host);
│  │                           pathlist.py (every path), appfolder.py (the private folder); tests\;
│  │                           app.ico (the icon), make-icon.ps1 (draws it)
│  └─ ingest\                  The Promotion run, its tests and its design docs
├─ .wiki\                      The user's private folder, if kept here (the suggested place). Git-ignored; never shared.
├─ Sample Wikis\               Example data, if present (team\, personal\). Not part of the app; never committed or shared.
├─ make_share.py               Builds a clean copy to share (§9)
├─ Share\                      Output of make_share.py; not part of the source
├─ .gitignore, .gitattributes  What Git leaves out; the launchers' line endings
├─ README.md                   User guide
├─ TECHNICAL.md                This file
└─ CLAUDE.md                   Working notes for AI coding tools (also a useful summary for people)
```

**Size.** About 16,200 lines of first-party code and styles (counted 2026-11-10, without the tests and the agents' prompt files):

| Part | Lines |
|---|---|
| JavaScript | ≈9,950 |
| CSS | ≈1,550 |
| Python | ≈4,800 (the host ≈1,200, `ingest` ≈1,370, `sessions` ≈2,030 without its tests, `agents` ≈115, setup ≈75) |
| HTML, launchers and other scripts | ≈400 |

---

## 4. Architecture

```
WikiApp.cmd / WikiApp.command ──► setup.py (checks .venv) ──► .venv python host/wikiapp.py
┌──────────────────────── host/wikiapp.py (Python, pywebview) ───────────────────────┐
│  pywebview window (WebView2 on Windows, WebKit on macOS)                           │
│   ├─ shows ──► http://127.0.0.1:<random port>/<random token>/index.html            │
│   │      ▲  AppServer: answers only that path, from App Files/app/ (loopback only) │
│   │      └─ window.pywebview.api.call({id, cmd, args}) ◄──► Host.dispatch          │
│   ├─ notefiles.py  the only code that writes notes (.md inside an open folder),    │
│   │                folder scans, read-only file reads, polling Watcher             │
│   │                → "vaultChanged" event                                          │
│   ├─ pathlist.py   every path (the .wiki folder, prompts, each wiki's rules...)    │
│   ├─ appfolder.py  first run, move/adopt, older data, agentlib, connection check   │
│   ├─ ingestruns.py starts ingest/run.py and relays its output as events            │
│   └─ sessionruns.py runs sessions/sb.py and returns the JSON it prints             │
└────────────────────────────────────────────────────────────────────────────────────┘
          │ starts (no window)
          ▼
  .venv python -X utf8 ingest/run.py job.json                     (Promotion runs)
          │ agentlib → its Claude engine (the Claude Agent SDK) → Anthropic API (or the gateway in agentlib's setup)

  .venv python -X utf8 sessions/sb.py <command> --json --personal <folder>   (Notes capture, Sessions, Review)
          │ agentlib, one request per capture or review, no tools → the same API or gateway
```

Every process finds the private folder the same way (`pathlist.app_folder()`: `WIKIAPP_DATA_DIR`, else the pointer file), so the runs read the same prompts and write the same progress as the host.

### 4.1 The host (`App Files/host/*.py`)

| Module / class | Role |
|---|---|
| `wikiapp.py` `main` | Entry point. If another copy answers (through `instance.json` in the private folder, or, during the first start, the guard port below), it asks that copy to come to the front and exits. Otherwise it runs `appfolder.startup()` (with a place chosen: brings the prompt and template copies up to date), sets the taskbar identity or Dock icon, and starts the `Host`. Command-line arguments are folders to open. |
| `wikiapp.py` guard | Before a place for the private folder is chosen there is no `instance.json`. The host then listens on a fixed loopback port worked out from the app's own path (`guard_port()`, 20000 to 39999), answering only `GET /wikiapp-focus`, so a second start finds the first. It writes nothing; if the port is taken there is simply no guard. |
| `pathlist.py` | The single path list (standard library only; the runs and `setup.py` import it too). Every file and folder the app uses: the private folder and its contents, the prompt and template slots, each wiki's rules, templates, index and progress, the transcripts folder, agentlib, the reference tag list. Overrides are kept in `.wiki/paths.json`. Also the prompt slots' status and reset, `read_prompt(name, **values)`, engine settings and each agent's model (`agent_model`, `set_agent_model`), and agentlib discovery. |
| `appfolder.py` | The private folder's life: `first_run_state` (validation, preview, known wiki folders, leftovers), `choose_location`, `relocate` (move or adopt, never merge), `migrate` (copies only), `startup`, `agentlib_status` / `install_agentlib`, `connection_status` / `test_connection` (agentlib's check), `open_path`. |
| `wikiapp.py` `Host` | The window and the commands. It creates the pywebview window (icon, dark title bar and taskbar identity on Windows), saves and restores its position (`window.txt`), answers every command in `dispatch`, and pushes events with `window.run_js`. |
| `wikiapp.py` `AppServer` | A `ThreadingHTTPServer` on `127.0.0.1`, random port. It serves `App Files/app/` only under a random secret path, plus a generated `settings.js` and a `__focus` endpoint (used for the single window). No-store caching, so edits show after F5. |
| `wikiapp.py` `Api` | The one method pywebview exposes to the page, `call(msg)`. It returns `{id, ok, result | error}`. |
| `notefiles.py` | Scans and note writes. It resolves every path inside the given folder root (no `..` escapes), only writes `.md` or `.markdown` files, and keeps each file's line endings and BOM. A scan skips dot-folders and hidden files and returns each file's path, size and modified time, plus the text of notes up to 5 MB; `read_text` is read-only, stays inside the folder, and stops at 2 MB. Its `Watcher` polls each watched folder once a second (paths, sizes, modified times) and reports a change once things are quiet. That needs no extra package and behaves the same on both systems. |
| `ingestruns.py` | The Promotion tab: info (including whether agentlib is installed, and why not), its saved cards (`pending_promotion`), run folders (`run_history`), starting and stopping `run.py` (one run at a time), feedback rounds, the model list, opening setup in a terminal. Also the three agents' prompt files, through `agents/agentfiles.py`, for the Agents and rules window. |
| `sessionruns.py` | The Notes (capture), Sessions and Review tabs: runs `sessions/sb.py <command> --json --personal <folder>` with no window and returns its JSON. Several may run at once; all are stopped when the window closes. |

**How the UI is served.** The page loads from `http://127.0.0.1:<port>/<token>/`:
- The port and the 128-bit token are new on every start.
- Any request without the token gets a 404. So another program, or a web page in a browser, can't read the app's files or its `settings.js`.
- The page's writes never go through this server. They use pywebview's bridge, which only the window's own page can call.
- Links open in the default browser (`openExternal`, `http`/`https`/`mailto` only). New-window requests also go to the browser (pywebview's `OPEN_EXTERNAL_LINKS_IN_BROWSER`).

**Browser storage is per run.**
- The window uses a private profile in a new temporary folder for each run (pywebview's private mode with no `storage_path`), so nothing of the web view goes in `.wiki`.
  - The browser engine of a window that just closed can hold its folder for a few seconds, and WebView2 can't open a new window on a folder in use; a new folder each run avoids that.
- The origin's port also changes on each start. So the page starts every run with empty storage, and `settings.json` is what carries settings between runs (`persist.js`).

**Taskbar (Windows).** A Python program's window would normally group under Python and couldn't be pinned, because Windows doesn't know how to relaunch it. So the host does three things:
- it sets the process's AppUserModelID (`WikiApp.WikiApp`);
- it passes `app.ico` to pywebview, so the window has the icon from the start;
- it writes the window's AppUserModel properties (`SHGetPropertyStoreForWindow`, through pywin32): ID, relaunch command (`.venv` `pythonw.exe host\wikiapp.py`), display name and icon.

**Pin to taskbar** then pins WikiApp with its own icon. A pinned button starts the host without the launcher. So `main` first asks `setup.is_current()`; if `requirements.txt` changed, it opens the launcher, which shows the install and then starts the app.

### 4.2 Page ↔ host protocol

The two sides talk in JSON:
- **JavaScript side:** `app/js/bridge.js`.
- **Python side:** `Api.call` → `Host.dispatch`, using pywebview's bridge for requests and `window.run_js` → `window.__wikiappReceive` for events.

`bridge.js` knows it's inside the app, and not a plain browser, from `window.__wikiappHost`, which the host's `settings.js` sets to `'python'`. `persist.js` makes the same check.

```
page → host   { id, cmd, args }
host → page   { id, ok: true, result }  or  { id, ok: false, error }
host → page   { event, data }            (pushed, no id)
```

**Commands:**

| Command | What it does |
|---|---|
| `getStartupFolders` | Folders passed on the command line |
| `pickFolder` | Shows the folder dialog; the chosen path or `null` |
| `pickFile` | `{start?}` (a folder, or a file in it, to open at). Shows the file dialog; the chosen path or `null` |
| `scanVault` | Scans a folder (and starts watching it) |
| `unwatchFolder` | Stops watching a folder |
| `editLines` | Replaces lines in a note, **only if** the expected lines are still there (see 4.3) |
| `appendLines` | Appends lines to a note, creating it if needed |
| `createNote` | Creates a note; fails if it exists |
| `readText` | Reads a file's text, read-only (used to show scripts) |
| `saveSettings` | Writes `settings.json` (refused, with nothing written, until a place for the private folder is chosen) |
| `openExternal` | Opens a URL in the default browser |
| `setTitle` | Sets the window title to the page's |
| `closeWindow` | The page's answer to `closeRequested`: `answer` is `asking` (it's asking the user), `no` (stay open) or `yes` (close now) |
| `firstRunState` | `{candidate?}` (typed or picked text; omitted = the chosen folder, or the suggested one). Returns `{chosen, location, location_exists, from_env, pointer_file, suggested, valid, error, preview, wiki_roots, leftovers, agentlib}`. `valid`/`error`: the candidate is empty, not a full path, or its parent folder doesn't exist. `preview`: `{folder, folder_exists, items: [{name, label, path, action: "create"\|"copy"\|"found", source}], old_wiki_index, inside_wiki}` (`old_wiki_index`: the place is an older version's `<wiki>/.wiki` index folder; `inside_wiki`: the wiki folder it's inside, or `""`). `wiki_roots`: the wiki folders the app knows (the workspace's, and an older version's settings). `leftovers`: `[{path, kind, note}]`, shown once. `agentlib`: as `agentlibStatus`. Writes nothing |
| `chooseFolder` | `{path}` (the `.wiki` folder or the folder to put it in). The first start: makes the folder, copies older data in, copies shipped prompts and templates where missing, writes the pointer. Overwrites nothing. Returns `firstRunState` plus `copied`, `created` |
| `relocateFolder` | `{path, mode: "move"\|"adopt"}`. Move: to an empty place, then the old folder is removed. Adopt: use the `.wiki` folder already there; the old one is left alone. Never merges. Refused while a Promotion run is going. Returns `firstRunState` plus `left_behind` |
| `dismissLeftovers` | The leftovers list has been seen |
| `listPaths` | Every visible path-list row, in order (the rules first: `personal_capture_rules`, then the team wiki's `wiki.<alias>.rules`; then the note templates; then everything else; the advanced agent prompts last): `{name, label, path, exists, kind, group, tier, status, default, state, can_reset, can_customise, can_change, can_clear, overridden}` (§7). `tier`: `main` or `advanced` (internal slots aren't listed). `state`: `ok`, `missing` (should exist and doesn't: a configured path that has gone, or a note template deleted at its place), `not_created` (made on first use), `unset` (an optional entry with no value, or nothing chosen yet). `status`: note templates `default`, `customised`, `customised_newer_default`; agent prompts `built_in`, `customised`, `customised_newer_default`; `null` otherwise. `can_customise`: an agent prompt still read from the app's own file. `can_clear`: an optional entry with no default (`tag_list_reference`) that has a value; for those, clearing replaces "back to default location". A wiki's rows (`wiki.<alias>.*`) also carry `role` (`personal`, `team`, `view`). Only the team wiki has a `rules` row (no other wiki's rules file is read by anything); a view-only wiki has no `progress` row either (its `templates` and `index` rows stay) |
| `getWikiRoles` | `{}` → `{roles: {<alias>: "personal"\|"team"\|"view"}, needs_team, needs_personal}` (§7.1, Wiki roles). A wiki not seen before (just opened, or not yet in the saved folder list) is `view`. `needs_personal`: no open wiki is personal; `needs_team`: some open wiki isn't personal and none is the team wiki. Never infers roles from aliases or older settings: that happens only when an existing installation is upgraded (§7.1) |
| `setWikiRole` | `{alias, role}` → the same shape plus `demoted`: making a wiki `personal` or `team` turns the wiki that had that role `view`, and `demoted` names it (or `null`). Refused for an alias that isn't open or a role that isn't one of the three |
| `getSessionsFilter`, `setSessionsFilter` | `{}` / `{min_turns}` → `{min_turns, options: [0, 3, 5, 10, 20]}`: "hide sessions with fewer than N turns" (0 = off, default 3), counting only the user's own messages. Kept in `wiki-settings.json`. Any other value is refused |
| `customisePrompt` | `{name}` (an agent prompt): makes the editable copy `.wiki/prompts/<id>.md` from the app's own file, if there isn't one. Returns the row (`status: "customised"`) |
| `setPath` | `{name, path}`; `path: ""` = back to the default, or clear. Returns the row. Setting `agentlib` installs it in the background and fires `agentlibInstalled` `{ok, message}` |
| `resetPrompt` | `{name}`: a note template back to the shipped text; an agent prompt's copy deleted (or its override forgotten), back to `built_in`. Returns the row. Refused for the capture rules and internal slots |
| `readPathFile`, `writePathFile` | `{name}` → `{name, path, exists, text, default_text?, starter_text?, status?}`; `{name, text, expect?}` writes a text entry (refused if the file changed since `expect`). Returns the row |
| `openPath` | `{name}`: opens the entry, a file in its default app and a folder in the file manager. Returns `{ok: true}` or `{ok: false, error}` |
| `getEngineSettings`, `setEngineSettings` | `{engine, engines: {<id>: {...}}, available: [{id, label}]}`; set takes `{settings: {engine?, engines?: {<id>: {fields}}}}` and merges. Claude's fields: `models` = `{"executive-assistant", "wiki-reviewer", "team-wiki-manager"}`, each agent's model: the one stored default that the tabs' model menus show and save |
| `setAgentModel` | `{agent, model}` (`model: ""` = the default): the same as `setEngineSettings` for one agent's model. Returns the engine settings |
| `connectionStatus` | agentlib's `connection_status(engine)`, free, sends nothing: `{engine, ok, method, summary, setup_file, setup_doc, problems, notes}`. Never secret values |
| `testConnection` | agentlib's `check_connection_sync(engine)`: **one tiny real request** on the engine's cheapest model. `{engine, ok, model, cost_usd, error, fix, report}` |
| `agentlibStatus`, `installAgentlib` | `{path, found, installed, message}` (why the AI features are off); install runs in the background, then `agentlibInstalled` |
| `ingestInfo`, `saveIngestState` | The Promotion tab (§8). `name` defaults to `"promotion"`, the only one left. `ingestInfo` returns `ready` (agentlib installed), `message` (why not), `running`, `runId`, `state` and `dataDir`; `saveIngestState` takes the cards as `state` (text). |
| `startIngest`, `reviseIngestCards`, `cancelIngest`, `runIngestSetup`, `answerIngestQuestions`, `listIngestRuns`, `openIngestRun`, `listIngestModels` | Promotion runs (§8). `startIngest` takes the `job` (`agent: "team-wiki-manager"`, `targets`). A target that isn't the team wiki stops the run before anything is sent, with a `done` event whose `message` names the role ("Northwind is view only; choose a team wiki in Settings."). |
| `agentsInfo`, `saveAgentPrompt` | The Agents and rules window (§8). `agentsInfo` returns the three agents: `id`, `name`, `tab`, `job`, `slot`, `path`, `text`, `default`, `changed`, `exists`, `status`, `can_reset`, `error`. `saveAgentPrompt` takes `id` and `text`; a file that starts with frontmatter must keep it. |
| `captureNotes`, `notesStatus` | The Notes tab (§8a): capture notes into the personal wiki (`notesCapture` events as each finishes); each note's `new`, `changed` or `captured` |
| `listConflicts`, `resolveConflict` | The Review tab's conflicts (§8a): `resolution` is `keep_note`, `accept_session` or `dismiss` |
| `sessionsStatus`, `sessionsSetup`, `sessionsList`, `sessionsIngest`, `sessionsSkip` | The Sessions tab (§8a). Each takes `root`, the personal wiki's folder; `sessionsIngest` and `sessionsSkip` take the session `id` (its readable name works too). `sessionsList` returns `{sessions: [rows], hidden_count, min_turns}`: each row has `session_id` (the hidden reference), `name` (the readable name, `<date>-<a few words>`), `title`, `user_messages` (the user's own messages only), `subagents` (subagents folded into the session) and the rest as in INTEGRATION.md; sessions under the filter's `min_turns` are left out and counted in `hidden_count`. `sessionsStatus` adds `role` and `set_up`. `sessionsSetup` returns that status plus `created`: exactly what Set up made in the wiki, in order, from `"Sessions/"`, `"promotion-queue.md"`, `"index.md"` (`[]` when all were there; never `WIKI.md`). They answer when `sb.py` finishes, which for `sessionsIngest` is 20 seconds to a couple of minutes. A folder that isn't the personal wiki is refused in plain words ("Northwind is view only; choose your personal wiki in Settings."). |
| `reviewList`, `reviewTopic`, `suggestFolders`, `applyFolder`, `suggestMerges`, `applyMerge` | The Review tab (§8a). Each takes `root`. `reviewList` returns every topic, those due first. `reviewTopic` takes `topic` and is one request to Claude. `suggestFolders` works from the pages, with no request to Claude, and moves nothing. `applyFolder` takes `folder` (`tag`, `title`, `topics`) and moves the topic pages into the tag's folder. `suggestMerges` is one request to Claude and changes nothing. `applyMerge` takes `merge` (`kind`: `topic` or `tag`, `keep`, `merge`) and folds the topics, or the tags, into one. |

**Events:** `vaultChanged` (a watched folder changed), `ingest` (one progress line from the agent), `ingestExit` (the agent process ended), `notesCapture` (one note captured), `agentlibInstalled` (`{ok, message}`), `closeRequested` (the window's close button was clicked; the window stays open until the page answers `closeWindow`).

**Closing.** The close button doesn't close at once. The host cancels it and sends `closeRequested`. The page then:
- saves the Notes view's last typing;
- saves an open in-place edit;
- asks before throwing away anything it couldn't save, or unsaved changes in the full editor.

If the page never answers (it's broken or still loading), a click after 4 seconds closes anyway. F5 asks the same way (`setBeforeReload` in `bridge.js`). Anything else that unloads the page gets the browser's own "Leave?" question (`beforeunload`).

### 4.3 How a change reaches a file

The app never holds a lock on notes and never overwrites blindly:

1. The page reads a note's text from the latest scan.
2. To save, it sends `editLines` with the line number, the lines it expects to find there, and the replacement lines.
3. The host re-reads the file. If those lines no longer match, because the file changed on disk (another editor, a sync tool), it **refuses** with "The note changed on disk".
4. The page rescans and tells the user, and the user's text is kept so nothing typed is lost:
   - In the full editor, it stays in the editor.
   - In an in-place edit, the page doesn't change until it's saved or dropped (Esc).
   - In the Notes view, the note comes back with **Keep mine / Load latest**, even if the user had already moved to another note.
5. The host writes the whole file to a hidden temp file next to it, then swaps it in, so a failed write leaves the old note whole. It refuses to edit a note that isn't UTF-8 rather than corrupt it.
6. After every successful write, the folder is rescanned and the whole model is rebuilt.

### 4.4 The page (`App Files\app\`)

- `index.html` loads, in order:
  1. `settings.js` (generated by the host from `settings.json`);
  2. `js/persist.js`;
  3. `lib/force-graph.min.js` (a global script);
  4. `js/main.js` (an ES module).
- `main.js` owns the application state and wires the modules together.

**Data model** (`vault.js` `buildVault`): workspace folders → host scans → one combined model. It holds:
- notes keyed by `alias:path`;
- names, for resolving `[[links]]`;
- scripts (`.sql`, `.py`… are link targets only);
- tags;
- tasks;
- duplicate names across folders;
- backlinks.

Graph data is derived from the model. Every view (file tree, graph, page viewer, Notes, Tasks, Ingest, search) reads it, and `main.js` calls `rebuild()` after any scan.

**Settings** live in the WebView's `localStorage`. `persist.js` wraps `localStorage.setItem/removeItem/clear` and mirrors every change, debounced by 150 ms, to `settings.json` in the private folder through the host. Until a place for that folder is chosen, `settings.js` sets `window.__wikiappFolderChosen = false` and the page shows the first-run screen (`setup.js`) instead of the app.
- Each save increments `__rev`.
- At start-up, whichever copy (file or browser storage) has the higher `__rev` wins.
- Keys in use:
  - workspace: `workspace` (open folders: root, alias, color, hidden), `notesFolder`, `notesDir`, `signature`;
  - restoring where the user left off: `lastView`, `lastPage`, `lastNote`;
  - graph: `tagColors`, `colorBy`, `showDuplicates`, `showNotes`, `showScripts`, `showSessions` (session notes, frontmatter `type: session`), `graphPanelOpen`;
  - layout: `notesPanelOpen`, `sidebarWidth`, `sidebarHidden`;
  - Tasks: `taskGroupBy`, `newTaskPage`;
  - Ingest: `ingestTab` (the tab last shown), `ingestLogRaw`, `ingestModels` (the last model list), `sessionsWiki` (the personal wiki's alias before wiki roles: read only once, by the roles upgrade, §7.1). Each agent's chosen model is **not** a page setting: it's in the engine settings (`engine.json`, §7.1), the one source of truth. Older `ingestModel` / `promotionModel` keys are no longer the source;
  - unused: `lastVault` (legacy).

---

## 5. First-party module reference

### JavaScript (`App Files\app\js\`)

All are ES modules except `persist.js`, which is a plain script so it runs before any module.

| Module | Purpose | Imports |
|---|---|---|
| `main.js` | Wiring and state: views, rail, saving, session restore, and the Ingest view's four tabs (`showIngestTab`) with the tab bar's **?** and **Agents and rules** buttons | bridge, vault, workspace, explorer, graph, viewer, tags, graphpanel, folderdialog, taskspane, signature, autocomplete, tasks, editor, inlineeditor, searchbar, notespanel, notesview, ingestview, ingestdialogs, sessionsview, reviewview, notes |
| `bridge.js` | `call(cmd, args)` → Promise, and `on(event, fn)` for host events | – |
| `persist.js` | Mirrors `localStorage` to `settings.json` (`__rev` rule) | – |
| `workspace.js` | The open folders: aliases, colors, hidden flag | – |
| `vault.js` | Data model: frontmatter (YAML), tags, `[[link]]` resolution, duplicates, graph data | lib/js-yaml, tasks, notes |
| `tasks.js` | Task line format: parsing, and building edited lines (text changes keep every `due:`/`done:`/`~` token, moved to the line's end) | – |
| `notes.js` | Quick notes: templates, placeholders, sections, wrapping | tasks |
| `explorer.js` | Sidebar file tree | vault |
| `graph.js` | Force-directed graph on a canvas (uses the global `ForceGraph`) | tags |
| `graphpanel.js` | Graph settings card: coloring, folders, tags, and the switches (duplicate links, Show notes, Show scripts, Show sessions) | – |
| `tags.js` | Tag color palette and remembered colors | – |
| `viewer.js` | Page view: properties, Markdown body (`html: false`; `breaks: true`, so a line break shows as one), and `renderEditable` for rows being edited, backlinks, script pages | lib/markdown-it, vault, taskspane, tags |
| `editor.js` | Full-note editor: properties box, formatted body, Markdown mode, toolbar | textcommands, livetext |
| `inlineeditor.js` | Double-click editing of tags or body in place | textcommands, vault, tags |
| `livetext.js` | Notes edited as they look: one row per line (a `contenteditable` box showing the line's inline Markdown formatted; its heading/bullet/number/quote prefix kept aside), the task form, the table grid, and code blocks edited as Markdown. Enter/Backspace/Tab/arrows, Markdown shortcuts, `[[` page picker, paste, renumbering, and the toolbar's commands for rows | lib/markdown-it, tasks, viewer (task icons), textcommands (shortcut keys, inserts), richtext |
| `richtext.js` | Rows: line kinds (`classify`), formatted text back to Markdown (`serialize`, keeping how each mark was written via `data-md` / `data-src`), caret helpers | – |
| `textcommands.js` | Shared editing commands (bold, lists, Ctrl+T tasks, …) | autocomplete, tasks |
| `autocomplete.js` | `[[` link suggestions and the page picker | vault |
| `search.js` | Query language and ranking | vault, tasks |
| `searchbar.js` | Search box and results | search, vault, tasks, tags |
| `taskspane.js` | Tasks view | tasks, vault |
| `notespanel.js` | Notes section of the sidebar | notes, tasks |
| `notesview.js` | Notes view: writing, autosave, conflicts | textcommands, editor, livetext, notes, tasks |
| `signature.js` | The user's signature (`~alias`) | tasks |
| `folderdialog.js` | Add or Edit folder window, duplicate check | vault |
| `capturenotes.js` | The Ingest view's Notes tab: wrapped notes (new, changed or captured), Capture into the personal wiki, results as `notesCapture` events arrive | notes, modelmenu |
| `ingestview.js` | The Ingest view's Promotion tab: the personal wiki's topic and folder pages (a topic only selectable once reviewed) and its promotion queue, model menu, run progress, cards, line diff, answers and Submit, feedback rounds, questions, past runs, marking pages promoted | vault, notes, tasks, modelmenu |
| `modelmenu.js` | The tabs' model menus: each agent's model read from and saved to the engine settings (`getEngineSettings`, `setEngineSettings`) | bridge |
| `ingestdialogs.js` | Ingest windows: Agents and rules (the three agents and their prompts, page templates, each wiki's rules), help (with diagram), run transcript | vault |
| `sessionsview.js` | The Ingest view's Sessions tab: personal wiki picker and setup, sessions waiting, Ingest, Skip, Ingest all, result cards | – |
| `reviewview.js` | The Ingest view's Review tab: topics due for a review and why, Review, Review all, conflicts (Keep note, Accept session, Dismiss), folder suggestions, Suggest merges, result cards | – |
| `settingsview.js` | The Settings screen: every `listPaths` row grouped, its state, Open (`openPath` or the app's editor), Change (`setPath`, with `pickFolder`/`pickFile`), Reset, Back to default / Clear, move or adopt for the app folder; the AI engine, models, `connectionStatus` and `testConnection` | bridge, setup, ai, modelmenu |
| `setup.js` | The first-run screen: where to keep the private folder (`firstRunState`, `chooseFolder`), with the warning for a place inside a wiki | bridge |
| `ai.js` | Whether the AI features can run (`agentlibStatus`); disables every `data-ai` button with the reason while they can't | bridge |

### Python: setup and the host (`App Files\`, `App Files\host\`)

| File | Purpose | Imports |
|---|---|---|
| `setup.py` | Makes `.venv` if needed, then `pip install -r requirements.txt` and `pip install -e <agentlib>` unless the hash recorded in `.venv/wikiapp-setup.txt` (requirements, the agentlib folder and its `pyproject.toml`) still matches; `--upgrade` updates everything. Never fails over agentlib: it writes why to `.venv/wikiapp-agentlib.txt` and the app starts with AI off | stdlib, local `host/pathlist` |
| `host/wikiapp.py` | Entry point, window, app server, command dispatch, settings, window position, single window (instance.json, or the first-start guard port) | stdlib, `webview` (pywebview), local `notefiles`, `ingestruns`, `sessionruns`, `pathlist`, `appfolder`; on Windows pythonnet and pywin32 for the window; on macOS `AppKit` (pyobjc) |
| `host/pathlist.py` | The single path list (§7): entries, overrides, row state, prompt slots and their status, `read_prompt`, engine settings and agent models, agentlib discovery | stdlib only (Python 3.10+, so `setup.py` can run it before the venv exists) |
| `host/appfolder.py` | The private folder: first run, preview and validation, move or adopt, migration (copies only), leftovers, agentlib status and install, the connection check, `open_path` | stdlib, local `pathlist`, `setup`; `agentlib` (only for the connection check) |
| `host/notefiles.py` | Folder scans, `readText`, the note writes and their checks, the polling watcher | stdlib (`os`, `stat`, `threading`, `time`) |
| `host/ingestruns.py` | Promotion runs: info, saved cards, run folders, start, feedback, stop, setup window, the model list; the agents' prompt files for the Agents and rules window | stdlib, local `pathlist`, `appfolder`, `agents/agentfiles` |
| `host/sessionruns.py` | Notes capture, Sessions and Review tabs: runs `sessions/sb.py` and returns its JSON | stdlib, local `ingestruns` |
| `host/tests/test_appfolder.py` | The private folder and the path list, zero tokens (fake engine for the connection check) | unittest |
| `agents/agentfiles.py` | The three agents (`AGENTS`: id, name, tab, job) and their prompt slots (`prompt.<agent id>`): `read`, `body` (the text without any frontmatter, which is what an agent is sent), `system` (the same text: what an agent is sent), `save`, `info`; `seed`/`skill_file` with a `base` folder for `sb.py install` only | stdlib, local `host/pathlist` |
| `agents/<agent id>/SKILL.md`, `agents/messages/*.md` | The shipped defaults: each agent's prompt (`executive-assistant`, `wiki-reviewer`, `team-wiki-manager`) and the other wording (Promotion's first, feedback and answers messages and Wikis section; the capture, notes-capture, review and merge requests; the personal tags starter; the personal capture rules starter) | – |
| `sessions/sb.py`, `sessions/secondbrain/` | Capture (sessions and notes), reviews, conflicts, tags, folders and merges, a command line that also runs without the app: `transcripts.py` (find, cut down and mask Claude Code transcripts), `llm.py` (one-shot structured calls through agentlib), `wiki.py` (every file write), `ingest.py` (capture), `review.py` (Current state, Related, conflicts, merge suggestions), `conflicts.py`, `tags.py` (reference and personal tags), `prompts.py`, `cli.py`, `config.py`. See [sessions/INTEGRATION.md](<App Files/sessions/INTEGRATION.md>) | stdlib, `agentlib`, `agents/agentfiles`, `host/pathlist` |

### Python: Ingest (`App Files\ingest\`)

This code runs the Promotion tab's agent, the team wiki manager, through agentlib. It is written for someone who has never seen agent code: `agent.py` explains what an agent is and sets it up as plain values; the tools are plain functions in their own file. The details, and every word the agent sees, are in [ingest/DESIGN.md](<App Files/ingest/DESIGN.md>) and [ingest/AGENT.md](<App Files/ingest/AGENT.md>).

| File | Purpose |
|---|---|
| `agent.py` | **Start here.** The agent: one run, a feedback round, the reviewer's answers, following the loop, and the engine settings it runs with |
| `tools.py` | The agent's tools as plain functions (`read_page`, `propose_page`, and for a promotion asking the reviewer), every proposal check, and what they remember during a run |
| `prompts.py` | The text the agent is given, from the prompt slots: its prompt, then a "Wikis" section naming each wiki's role, with the team wiki's rules; the first, feedback and answers messages |
| `wikis.py` | Wiki scan, `[[link]]` resolution (same rules as `vault.js`), each wiki's rules file and templates from the path list, and the per-wiki index (a copy kept in `.wiki/indexes/`, never in the wiki) |
| `transcript.py`, `costs.py`, `progress.py` | The run's record (`transcript.json`), token prices, progress lines and `log.jsonl` |
| `run.py` | The command line the host starts: one run, `--prepare-only`, `--feedback`, `--answers` |
| `models.py` | Prints the models the engine offers, through agentlib, for the model menus. Makes no request |
| `tests/` | The run on agentlib's fake engine, zero tokens |

---

## 6. Third-party components

The page's libraries are vendored (copied into the folder). The Python packages are installed by `setup.py` from PyPI, once per computer. Nothing loads from the internet at run time, and the page has no build step.

| Component | Version | License | Where | Used for |
|---|---|---|---|---|
| pywebview (Python) | 6.2.1 tested | BSD-3-Clause | `.venv` (installed by setup) | The app's window. It brings `pythonnet` and `clr_loader` (MIT) on Windows, and `pyobjc` (MIT) on macOS. |
| pywin32 (Python, Windows only) | 312 tested | PSF | `.venv` | The window's taskbar properties (pinning) |
| force-graph | 1.52.0 | MIT | `app\lib\force-graph.min.js` (global script) | Graph drawing and physics |
| markdown-it | 15.0.2 | MIT | `app\lib\markdown-it.min.js` (ES module) | Rendering Markdown; raw HTML in notes is disabled (`html: false`) |
| js-yaml | 4.x (README records 4.3.2) | MIT | `app\lib\js-yaml.js` (ES module build) | Reading frontmatter (`CORE_SCHEMA`, so dates stay text) |
| agentlib (Python) | the sibling folder's version | The user's own library (separate repo) | Its own folder, installed editable into `.venv` | Every request to Claude. It brings `claude-agent-sdk` (Anthropic Commercial Terms) at the version it pins, which pulls in `mcp`, `anyio`, `pydantic`, `jsonschema`, `httpx2` and others |
| PyYAML | 6.0.3 tested | MIT | `.venv` | YAML in the agent's checks and index |

**To update a vendored library,** replace its file and reload with F5. markdown-it and js-yaml must stay ES module builds, with a default export; force-graph must stay a global (UMD) build.

---

## 7. Data: what is read, written and sent

### 7.1 The private folder (`.wiki`) and the path list

Everything private to the user is in one folder named `.wiki`. Wikis are shared (often through git); this folder is not.

- **Where it is.** Chosen on the first start (`firstRunState`, `chooseFolder`). The suggested place is the project folder (the one holding `WikiApp.cmd`); `.gitignore` has `.wiki/`, so it is never committed and a `git pull` never touches it. The user may pick the `.wiki` folder itself or the folder to put it in.
- **The pointer.** The only thing in a fixed place: `~/.wikiapp-location`, one line naming the folder. `WIKIAPP_POINTER_FILE` moves the pointer (tests); `WIKIAPP_DATA_DIR` names the `.wiki` folder directly and the pointer isn't read (developer runs; the folder is made if missing).
- **Nothing is created until a place is chosen.** With no pointer the app writes nothing at all: `saveSettings` is refused, no `instance.json`, no indexes.
- **Never made again.** A configured path that has gone is reported (`state: "missing"`) and the feature needing it fails with a clear message; it is not recreated. Files are only ever created inside `.wiki`, or where the user saves one. A whole `.wiki` folder that has gone is reported on the next start, not remade.
- **Moving it** (`relocateFolder`): `move` copies the contents to an empty (or new) place, switches the pointer and removes the old folder (anything locked is reported as `left_behind`); `adopt` switches to a `.wiki` folder already there and leaves the old one alone. Never merged.
- **Updating by re-extracting a zip** deletes a `.wiki` kept in the old copy unless the zip is extracted over the top; README says so.

**The path list** (`host/pathlist.py`) is the one place every path comes from. Each row (`listPaths`) is `{name, label, path, exists, kind, group, status, default, state, can_reset, can_change, can_clear, overridden}`. Overrides are kept in `.wiki/paths.json`, with each prompt slot's record (the hash of the default its copy was made from).

| Group | Entries (name: default) |
|---|---|
| App folder | `app_folder`, `pointer_file`, `path_list` (`paths.json`). The folder moves only through `relocateFolder` |
| Rules (listed first) | `personal_capture_rules` (`capture-rules.md`, at the top of `.wiki`), the team wiki's `wiki.<alias>.rules` (`<wiki>/wiki_rules.md`; listed for the team wiki only) |
| Note templates (main) | `template.daily`, `template.weekly` (`note-templates/Daily.md`, `Weekly.md`; the folder name is `NOTE_TEMPLATES_DIR` in `pathlist.py`) |
| App data | `settings` (`settings.json`), `window_placement` (`window.txt`), `instance` (`instance.json`, deleted on close), `engine_settings` (`engine.json`), `pending_promotion` (`ingest/pending-promotion.json`), `run_history` (`ingest-runs/`), `indexes` (`indexes/`), `progress` (`progress/`), `note_templates` (`note-templates/`), `prompts` (`prompts/`, customised agent prompts only), `wiki_settings` (`wiki-settings.json`: each wiki's role and the Sessions filter); `personal_tags` (`personal-tags.md` in the personal wiki) |
| Each wiki | `wiki.<alias>.templates` (`<wiki>/Templates` if the wiki has one, else unset), `wiki.<alias>.index` (`indexes/<alias>.md`), `wiki.<alias>.progress` (`progress/<alias>/`). Each row has the wiki's `role`; a view-only wiki has no `rules` or `progress` row |
| Agent prompts (advanced, listed last) | `prompt.executive-assistant`, `prompt.wiki-reviewer`, `prompt.team-wiki-manager`: the app's own `agents/<id>/SKILL.md` until customised, then `prompts/<id>.md` |
| Internal (not listed) | `prompt.promotion-first-message`, `prompt.ingest-feedback`, `prompt.ingest-answers`, `prompt.wikis-section`, `prompt.sessions-capture`, `prompt.sessions-notes-capture`, `prompt.sessions-review`, `prompt.sessions-merges`, `template.sample-note`, `template.sample-page`, `template.page-starter`, `template.rules-starter`, `template.team-rules` (and the personal tags starter): always the shipped file in `App Files` |
| Outside the app | `notes_folder` (the folder inside each wiki that holds quick notes, `Notes`), `transcripts` (`~/.claude/projects`, read only), `agentlib` (the one found beside the project folder), `sessions_config` (`sessions/config.json`, the command line's), `tag_list_reference` (unset; any tags file, read only) |

**Row state:** `ok`; `missing` (should exist and doesn't: a configured path that has gone, or a prompt deleted at its place); `not_created` (made on first use: settings, window placement, engine settings, Promotion cards, run history, indexes, progress, personal tags, a wiki's rules, index and progress, the notes folder); `unset` (an optional entry with no value, or nothing chosen yet). `can_clear` is set for an optional entry with no default (`tag_list_reference`) that has a value; for it, clearing replaces "back to default location".

**File slots come in three tiers**, so the private folder holds only what a person actually edits. Every row from `listPaths` has `tier`: `main` or `advanced`; internal slots aren't listed.
- **Main** (copied into `.wiki` on setup): `template.daily`, `template.weekly`. Setup copies each shipped default only where its file doesn't exist. `status`: `default` (unedited; follows a newer shipped default by itself on the next start, `sync_slots`), `customised` (left alone), `customised_newer_default` (edited, and the app now ships a different default). `resetPrompt` writes the shipped text back. A file deleted at its place is not made again.
- **`personal_capture_rules`** (main, listed first) is the user's own and the single place for personal-wiki rules: a starter (comments only) is copied once if missing, then never updated, overwritten or reset; no status; `read_prompt` returns it without its `<!-- -->` comments. Capture, review and merge suggestions send it; they read no other personal rules file.
- **Advanced** (not copied): the three agents' prompts. Read straight from the shipped `agents/<id>/SKILL.md` (`status: "built_in"`, `can_customise: true`) until `customisePrompt` makes the editable copy `prompts/<id>.md` (`customised`, or `customised_newer_default` once edited and the app ships a different prompt). Saving a built-in prompt (`writePathFile`, `saveAgentPrompt`) makes the copy first, so the app's own file is never written. `resetPrompt` deletes the copy (or, for a slot pointed at the user's own file such as a Claude Code skill, forgets the override and leaves the file) and goes back to the shipped file.
- **Internal** (never copied, never listed): the wording wrapped around each request, the samples and the one-time starters. `read_prompt(name)` and `readPathFile` read the shipped file; `setPath`, `writePathFile`, `resetPrompt` refuse.
- The tool descriptions and the JSON reply formats stay in code, because code parses the replies.

**A `.wiki` from the previous layout** (which copied every slot in) is tidied on the next start (`upgrade_layout`, once; `paths.json` gets `"layout": 2`). A copy of a now-internal or retired file (including the old task guide) that is byte-identical to a default the app recorded for it, or to today's shipped file, is removed. An agent prompt's copy is removed if unedited, kept as the customised copy if edited. An edited copy of an internal file is left on disk untouched, no longer read, and added to the leftovers list once; an override that pointed an internal slot at the user's own file is dropped and reported the same way. `prompts/personal-capture-rules.md` moves to `capture-rules.md`, and `templates/Notes/Daily.md` and `Weekly.md` to `note-templates/`, unless the user had pointed them elsewhere (that override stays; a `templates` folder override becomes per-template overrides). Empty old folders (`templates/`, `starters/`, an empty `prompts/`) are removed. Nothing the user edited is ever deleted. Until that first start, a run still finds the capture rules at the old place.

**Wiki roles** (`wiki-settings.json`, `getWikiRoles`/`setWikiRole`; `pathlist.wiki_roles`, `set_wiki_role`, `wiki_role_for_root`, `wiki_with_role`). Each open wiki has a role, kept here and never in a file inside the wiki, keyed by the wiki's folder (so an alias change keeps it): `{"version": 1, "roles": {<folder key>: {role, root, alias}}, "sessions": {"min_turns": N}}`.
- `personal` (one at most): where notes and sessions are captured and Review and Suggest merges write. It replaces the old `sessionsWiki` setting and alias-`personal` lookup, and `WIKI.md` is no longer needed: Set up (`sessionsSetup`) makes `Sessions/`, `promotion-queue.md` and `index.md` and returns them as `created`, never `WIKI.md`, and an existing one is left alone. (The retired internal slot `template.personal-wiki` is gone; `sb.py` on its own still reads `sessions/templates/personal-WIKI.md` in place.)
- `team` (one at most): the only wiki Promotion proposes changes to.
- `view` (any number; every newly opened wiki starts here): no agent writes to it or proposes pages for it. Promotion may still read it (`read_page`) for context. The user's own edits in the editor are unaffected.
- Enforced in code: `sb.py` refuses a root that isn't the personal wiki (`wiki.require_personal`), and Promotion refuses a target that isn't the team wiki, both when a run starts (`agent.target_refusal`) and in `propose_page`. The refusal names the role in plain words (`pathlist.role_refusal`).
- **Upgrade.** Only when an existing installation with no saved roles is opened by this version (the host's start-up, `chooseFolder` and `relocateFolder` adopt, all `wiki_roles(persist=True, upgrade=True)`): the wiki that was personal (the `sessionsWiki` setting, else the alias `personal`, else the one wiki whose `WIKI.md` says `type: personal`) is personal; if exactly one other wiki is open it is the team wiki; with several, they are all view and `needs_team` is true. The result is saved at once. A fresh private folder is settled with no roles (`"roles_settled": true` in `paths.json`, so a fresh `.wiki` still holds only what the user edits). Nothing else infers roles: a wiki opened afterwards is view, whatever its alias.

**Engine settings** (`engine.json`, `getEngineSettings`/`setEngineSettings`/`setAgentModel`): `{"engine": "claude", "engines": {"claude": {"models": {"executive-assistant": "claude-haiku-5-5", "wiki-reviewer": "claude-sonnet-5-5", "team-wiki-manager": "claude-sonnet-5-5"}}}}`. Each engine keeps its own fields under its id, so a new engine adds its block without touching the others. The per-agent model is the one source of truth: the tabs' model menus show it and save a change to it, and the runs read it (`pathlist.agent_model`).

**First start of this version: copies only.** On `chooseFolder`, `appfolder.migrate` copies into the new folder, only where it has no such file yet: `~/.wikiapp`'s `settings.json`, `window.txt`, `ingest/pending-promotion.json` and `ingest-runs/` (or, when there is no `~/.wikiapp`, what the retired Windows-only version left in `%LOCALAPPDATA%\WikiApp` and `%TEMP%\WikiApp\ingest-runs`), and the three agents' prompts from `~/.claude/skills/<agent id>/SKILL.md` when the user edited them (they become customised copies in `prompts/`; an unedited one isn't copied, the agent reads the app's own file). The retired Notes flow's files (`ingest/pending.json`, the note taker's prompt, `ingest/user-notes.md`) are not carried forward. Nothing is deleted. A one-time list of leftovers (`leftovers.json`, shown by the page until `dismissLeftovers`): the old `~/.wikiapp`, the old skill copies (the note taker's included), each wiki's old `.wiki/index.md`, and sample templates an older version copied into a wiki and that are unchanged since.

### 7.2 Everything read and written

| What | Where | Written by |
|---|---|---|
| Notes, templates, a wiki's rules file | The user's wiki folders | The host only (`notefiles.py`, or `writePathFile` for a path-list file), with the change check in §4.3 |
| The Python environment | `App Files/.venv` (with `wikiapp-setup.txt` and `wikiapp-agentlib.txt`) | `setup.py` (pip) |
| The pointer | `~/.wikiapp-location` | `chooseFolder`, `relocateFolder` |
| Everything in §7.1's Rules (the capture rules), Note templates, App data and customised agent prompts | The private `.wiki` folder | The host, `run.py` (run folders, indexes) and `sb.py` (progress) |
| Ingest index, one per wiki | `.wiki/indexes/<alias>.md` (a copy to look at; the run uses the text) | `ingest/wikis.py`, at the start of each run. Nothing is written into the wiki |
| Web view profile | A new temporary folder each run (private mode) | The web view |
| Agent conversation files, one per Promotion run (needed for feedback rounds) | Where the engine keeps them (Claude: `~/.claude/projects/<run folder name>/`) | The engine, through agentlib |
| Captured sessions and notes: records, topic pages (Current state, Related, Notes, Log), folder hub pages, the index, the promotion queue, `personal-tags.md`; `capture_id` and `ingested` in a captured note's frontmatter | In the personal wiki: `Sessions/` (flat), `<topic>.md`, `<tag>/<topic>.md` and `<tag>/<tag>.md`, `index.md`, `promotion-queue.md`, `WIKI.md` (only `sb.py init` on the command line on its own makes it, and only it reads it), `personal-tags.md` | `sessions/sb.py` directly. **The exception to "only the host writes"**: it writes only inside the wiki whose role is `personal` (§7.1; on the command line on its own, a folder whose `WIKI.md` says `type: personal`). Details: [sessions/INTEGRATION.md](<App Files/sessions/INTEGRATION.md>) |
| What capture has done (ledger, spend, conflicts, the write lock, the model's work folder) | `.wiki/progress/<alias>/` (`pathlist.progress_dir`). An older `<personal wiki>/.sb` is copied across once and left as it was | `sessions/sb.py` |
| `promoted: <date>` on promoted pages; ticks in `promotion-queue.md`; accepted changes to the team wiki | The personal wiki; the team wiki | The host (`editLines`, `createNote`), when a promotion's cards are answered and submitted |
| The reference tag list | Wherever `tag_list_reference` points | **Never written.** Read with every capture, review and merge suggestion |
| agentlib's sign-in setup | agentlib's own `setup/local.toml` | The user, following agentlib's guide. The app only reads its status |

The app never writes to `~/.claude/skills`, never into `<wiki>/.wiki/`, and never seeds a `Templates` folder into a wiki.

To reset the app completely, close it, delete the `.wiki` folder and `~/.wikiapp-location`. Notes are never stored there.

**Network traffic**
- **The app itself makes no network requests.** Links the user clicks open in the default browser. The host's page server listens on `127.0.0.1` only, never on the network; so does the first-start guard (§4.1), which answers one request.
- **Setup** downloads the Python packages from PyPI (pypi.org) on the first start, and again only when `requirements.txt` or the agentlib folder changes (agentlib's install brings the Claude Agent SDK).
- **Ingest** makes HTTPS calls to Anthropic's API, or to the gateway named in agentlib's own setup, always through agentlib. Nothing else in the app talks to a model.
  - **A Promotion run** sends: the team wiki manager's prompt, each open wiki's alias and role, and the team wiki's rules file (no other wiki's); an index of page names, descriptions, tags, headings and links, for every open wiki; the full text of the selected topic pages, folder pages and promotion queue; the text of each page the agent chooses to read. The engine may add a short environment block. Runs switch off Claude Code's optional background traffic (`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`).
  - **A capture, review or merge suggestion** (`sessions/secondbrain/llm.py`) is one structured request with no tools. It sends the agent's prompt, plus: for a capture, the personal capture rules (the personal wiki's only rules), the tag lists (the reference list and personal tags), its index lines and the cut-down session transcript, meeting file or note; for a review, the capture rules, the tag lists, the topic's Notes section and its records (the 40 newest, 2,500 characters each at most) and the candidate related topics; for a merge suggestion, the topics' names, summaries and tags, the tags in use and the tag lists.
  - **The connection check** (`testConnection`, Settings) sends one tiny message on the cheapest model, only when the button is pressed. `connectionStatus` sends nothing.
- **What a cut-down transcript holds** (`condense` and `_mask` in `sessions/secondbrain/transcripts.py`): the user's messages, the assistant's text, and each tool call as one line. Tool output and thinking are dropped. Subagents are folded into the session that started them: each subagent's report (from its `Agent` call's result, or the `<task-notification>` that delivers a background subagent's report, or failing both its own transcript's last message) appears under `## ASSISTANT (subagent)` as `SUBAGENT "<description>" reported: ...`, followed by up to 8 of its steps as one-liners; the assistant's instructions to a subagent are shown, masked, inside the assistant's message. None of it is ever labelled USER, and only the user's own messages count as turns. A background shell command's notification keeps only its masked one-line summary. In subagent reports a number of six or more digits becomes `#`; a report is cut at 6,000 characters before anything else is. Commands (Bash, PowerShell), search patterns, web search queries and other tools' inputs are masked: a number of six or more digits becomes `#`, quoted values inside anything that looks like a SQL query become `'?'`, and the line is cut (a command at 160 characters). File paths for Read, Edit and Write are not masked.
- The system web view (Edge WebView2 Runtime on Windows) and the operating system may update themselves as usual. That's outside the app.

**Security notes**
- The page can only reach the disk through the host's commands. Note writes are limited to `.md` files inside folders the user opened; other writes go to the private folder or to a path-list file the user saves. Reads outside a scan are read-only, stay inside the folder and stop at 2 MB.
- Notes are rendered with raw HTML switched off, so a note can't inject markup or script into the app.
- The Promotion agent runs with **no built-in tools**: no shell, no file write, no web, no subagents. Its only tools read wiki pages, propose a card, or ask the reviewer. A person must press ✓ before the host writes anything, and `propose_page` refuses any wiki that isn't the team wiki (its role) and one of the job's `targets`, so nothing can be proposed in the personal wiki or a view-only wiki.
- Capture and review have no tools at all: each replies with JSON, and `sb.py` writes the files. `sb.py` refuses to write to a folder that isn't the personal wiki (its role; on the command line alone, `WIKI.md` with `type: personal`). Notes and sessions never reach a team wiki except through Promotion, and never reach a view-only wiki.
- The reference tag list is never opened for writing.
- An agent's prompt is a file the user can edit. The parts a run depends on (the material, the wiki rules, the reply format) are added by the code and are not in that file.
- Sign-in lives in agentlib's own setup; the app never sees a key, and `connectionStatus` returns names only, never secret values.
- The host's page server answers only requests carrying its per-run secret token, and only ever serves `App Files/app/` (paths are resolved and must stay inside it). It accepts no writes.
- Nothing in the folder is a compiled program. The launchers are plain scripts, and the Python they run is the user's own installation.
- Developer tools are enabled (F12 on Windows; right-click → Inspect on macOS). Remote debugging is off unless switched on before launch with `WIKIAPP_DEBUG_PORT=<port>`.

---

## 8a. Notes capture, Sessions and Review (the personal wiki)

Full detail is in `App Files\sessions\README.md` (what it does, the command line, settings) and `App Files\sessions\INTEGRATION.md` (every command and its JSON, the page layout, conflicts, tags). This is the overview.

- **What it is.** `sessions/sb.py` is a command-line tool that also runs without the app. Its ties to the rest of the folder are `agents/agentfiles.py` (the agents' prompts), `host/pathlist.py` (every path) and agentlib (every model request). Each request is one structured call with no tools; the model replies with JSON and `sb.py` writes the files. It never runs `claude -p`.
- **The personal wiki** is the open wiki whose role is `personal` (Settings; §7.1, Wiki roles). Every write command first checks the role and refuses a team or view-only wiki; `WIKI.md` is not needed. The Notes, Sessions, Review and Promotion tabs all use that folder.
- **Capture: sessions** (the Sessions tab, the executive assistant). It reads Claude Code's transcripts (the path list's `transcripts`, `~/.claude/projects` by default), cuts one down (§7), and sends it. From the reply it writes a record in `Sessions/` (`<date>-<title words>.md`; a piece of the id is added only on a clash), a `[session]` line in the log of each of its topics' pages (a new topic's page is made), the index, and any data findings on the promotion queue. Sessions started through the Agent SDK (the app's own runs among them) are never listed, and neither are subagents' transcripts: a subagent's work is part of the session that started it.
- **Readable names.** Each listed session has a name, `<date>-<a few words>` (`2026-11-12-churn-dashboard-fix`), from Claude Code's title for it (`custom-title`, else the generated `ai-title`) or else the user's first message, with no model request; a short piece of the id is added only on a clash. It is kept in the session's ledger entry, so it never changes. The session id stays the hidden reference (frontmatter, ledger).
- **The minimum-turns filter** (`getSessionsFilter`/`setSessionsFilter`; 0, 3, 5, 10 or 20, default 3): sessions with fewer of the user's own messages (subagent reports and notifications never count) are left out of the list, so "ingest all" skips them; one chosen explicitly is still captured. It replaces the old `min_user_messages` skip. With a private folder, `sb.py` uses exactly what the app shows (the stored filter, else 3); `config.json`'s `min_turns`, then `min_user_messages`, are read only by `sb.py` on its own.
- **Capture: notes** (the Notes tab, the executive assistant). A wrapped quick note is captured exactly like a session: a record with `origin: note`, a `[note]` log line. The note gets `capture_id` (its permanent id) and `ingested` in its frontmatter, nothing else; an edited note is captured again in place of its earlier record. Notes only ever go to the personal wiki.
- **Topics.** A topic is one piece of work: `<slug>.md` (`type: topic`) with Current state, Related, Notes (the user's; never edited) and Log. Log lines say where they came from (`[note]` or `[session]`) and end `— also touches [[other]]` when the record was filed under other topics too.
- **Tags** say what kind of thing a topic is and what it belongs to (there is no `kind` field any more). Two free-form files make up the tag list, both sent with every capture, review and merge suggestion: `tag_list_reference` (unset by default; any existing tags file, typically the team's; never written) and `personal_tags` (`personal-tags.md` in the personal wiki; made the first time a new tag is added, with its description; updated by a tag merge).
- **The personal capture rules** (`personal_capture_rules`, `.wiki/capture-rules.md`): the user's own free-text rules for what capture picks out and what gets its own page, and the personal wiki's only rules (a `wiki_rules.md` in the personal wiki is not read). Sent with captures, reviews and merge suggestions; never written by the app after its starter.
- **Review** (the Review tab, the wiki reviewer). A topic becomes due after three new records, or when flagged (a decision reversed, a record taken off it, a merge, a settled conflict). `reviewTopic` rewrites the Current state zone, the Related section and the one-line summary, directly. Notes outrank sessions: where a session contradicts a note, Current state follows the note and a Conflict block shows both; `listConflicts` and `resolveConflict` (`keep_note`, `accept_session`, `dismiss`) settle them, and a settled conflict isn't raised again unless a text changes.
- **Folders and merges.** A tag three or more top-level topics share can become a folder with a hub page (no model request). Topics or tags that duplicate each other can be merged (one request to suggest; nothing changes until a suggestion is accepted).
- **Progress** (the ledger, spend, conflicts, the lock, the model's work folder) is in `.wiki/progress/<alias>/`. Without a private folder (the command line alone) it stays in `<personal wiki>/.sb`; an older `.sb` is copied across once and left as it was.
- **No approval for captures and reviews, by design.** They write pages `sb.py` itself manages in the personal wiki, so they write directly. Folders, merges and conflicts are suggestions to accept. The team wiki is never written by `sb.py`, apart from `reindex --wiki team`; data findings wait in `promotion-queue.md` for Promotion (§8).
- **`python sessions/sb.py install`** copies the agents' prompts, the helper skills and the `wiki-lookup` agent into a `.claude` folder, only when the person runs it. The app itself never writes there.
- **Tests:** `python -m unittest discover tests` in `App Files\sessions` (no calls to Claude; agentlib's fake engine).

## 8. The Ingest view and Promotion

Full detail, including every word sent to the model, is in `App Files\ingest\DESIGN.md` and `App Files\ingest\AGENT.md`.

**Four tabs, three agents.** `main.js` owns the tabs (`showIngestTab`); the tab last shown is the `ingestTab` setting. The **?** and **✎ Agents and rules** buttons sit in the tab bar and belong to all four.

| Tab | Agent (id) | Module | Runs through | Writes |
|---|---|---|---|---|
| Notes | Executive assistant (`executive-assistant`) | `capturenotes.js` | `sessions/sb.py capture-note` (§8a) | Directly, into the personal wiki |
| Sessions | Executive assistant (`executive-assistant`) | `sessionsview.js` | `sessions/sb.py` (§8a) | Directly, into the personal wiki |
| Review | Wiki reviewer (`wiki-reviewer`) | `reviewview.js` | `sessions/sb.py` (§8a) | Directly, into the personal wiki; a folder, a merge or a conflict's resolution only when accepted |
| Promotion | Team wiki manager (`team-wiki-manager`) | `ingestview.js` | `ingest/run.py`, agentlib | Cards, in every wiki but the personal one: **the only route to a team wiki** |

**Models.** Each agent's model is kept in the engine settings (`engines.<engine>.models.<agent id>`, §7.1): Haiku 5.5 for the executive assistant, Sonnet 5.5 for the wiki reviewer and the team wiki manager. The tabs' model menus (`modelmenu.js`) read their default from `getEngineSettings` and save a changed choice with `setEngineSettings` (or `setAgentModel`); Settings shows the same values. The menu's list comes from `listIngestModels` (`ingest/models.py`, through agentlib; no request is made).

**The agents' prompts** (`agents/agentfiles.py`, §7.1). Each agent has one advanced prompt slot, `prompt.<agent id>`: the app's own `agents/<agent id>/SKILL.md` until the user customises it (`.wiki/prompts/<agent id>.md`). An agent is sent the file's text without any frontmatter, then what the code adds for that request. The rules files (the capture rules, each team wiki's rules) are the main way to change what agents do; prompts are the advanced way. (The shared task guide, `prompt.tasks`, is gone: no agent writes or changes tasks. An old copy in `.wiki/prompts/TASKS.md` is left where it is, unused.)

**The Agents and rules window** (`ingestdialogs.js`): the three agents (`agentsInfo`, `saveAgentPrompt`), every wiki's page templates, and one tab per wiki for its rules file (the path list's `wiki.<alias>.rules`; only the team wiki's is ever sent to an agent). A checkbox turns on raw request logging for Promotion runs (`ingestLogRaw`).

**A Promotion run**
1. **The list** (`promotable` in `ingestview.js`), from the personal wiki: its topic and folder pages that have no `promoted` time or changed since, and `promotion-queue.md` while it has unticked lines. A topic can be selected only once it has been reviewed since it last changed. **Show already promoted** lists the rest.
2. The page sends `startIngest`. The job has `agent: "team-wiki-manager"`, `targets` (every workspace folder except the personal wiki) and the selected pages as `notes`. The host writes `job.json` to a new run folder (`run_history`) and starts `.venv` Python on `-X utf8 ingest/run.py <job.json>`, with no window.
3. `agent.py` rebuilds the index (each wiki's page templates at the end; a copy in `.wiki/indexes/`), builds the instructions (the agent's prompt, then the "Wikis" section: each wiki's role, and the team wiki's rules only) and the first message (from `prompt.promotion-first-message`), and starts the agent through agentlib with no built-in tools, limits on turns and cost, and the model from the engine settings.
4. The agent reads pages and calls `propose_page`; `tools.py` checks each proposal (each edit's text occurs exactly once, valid paths and YAML, a template it has read, a wiki in `targets`). A valid proposal becomes a card. When it can't tell where a point belongs it may first ask up to five questions; `answerIngestQuestions` continues the run with the answers.
5. The user answers each card (✓, ✗, ↻). Answers are kept in `pending_promotion`; nothing happens until **Submit**. ✓ sends `editLines` (only if the page still equals the card's "before" text) or `createNote`; a card whose page changed becomes stale; the ↻ cards go back to the agent together (`reviseIngestCards`, the same conversation, `run.py --feedback`).
6. When every card is handled, each promoted page gets `promoted: <time>`, and the queue lines the run saw are ticked.

**Costs.** Each run's `transcript.json` records every request's tokens and cost, shown under **Past runs**, at API list prices (on a subscription a run counts toward the plan's usage instead).

**Page templates.** A wiki's `Templates/Pages/*.md` files are templates for new pages (the file name is the template's name; frontmatter `description` says when to use it). A wiki without a `Templates` folder has none (its `wiki.<alias>.templates` is unset); a new page template starts from the built-in starter. The agent reads a template only when it's about to propose a new page, follows it, and names it in `propose_page`'s `template`. Everything under `Templates/` is left out of the graph, tags and tasks. The app never adds a `Templates` folder to a wiki.

---

## 9. Build, run, debug

**Run:** double-click `WikiApp.cmd` (Windows) or `WikiApp.command` (macOS).
- Each runs `App Files/setup.py` with the `.venv` Python. On the first start there's no `.venv` yet, so it uses the Python it finds instead (`setup.py` refuses one older than 3.11). Setup also finds and installs agentlib (§2).
- The first start then asks where to keep the private `.wiki` folder (§7.1).
- Then it starts `host/wikiapp.py`: with `pythonw.exe` on Windows (no console), and detached with `nohup` on macOS.
- On macOS the file must be executable: run `chmod +x WikiApp.command` once, or use `git update-index --chmod=+x WikiApp.command` before committing.
**Change the interface:** edit files in `App Files\app\`, then press **F5** (Cmd+R on macOS) in the app. There's nothing to build.

**Change the host:** edit `App Files/host/*.py` and start the app again.

**Change the icon:** edit and run `App Files\host\make-icon.ps1` (PowerShell; it draws `host\app.ico`), or replace `app.ico` with any `.ico` file. Then start the app again.

**Set up or update the packages:**
- Edit `requirements.txt`. The next start installs the change.
- To update everything, run `python "App Files/setup.py" --upgrade`, or press **Run setup** in the Ingest view.

**Share a copy:**
- **With Git,** commit the folder. `.gitignore` leaves out `.venv`, caches, `Share/`, shortcuts, `Sample Wikis/` and `.wiki/` (the private folder, when kept in the project folder). `WikiApp.command` is committed executable (`git update-index --chmod=+x`). `.gitattributes` keeps `WikiApp.command` at LF and `WikiApp.cmd` at CRLF.
- **As a zip,** run `python make_share.py [output folder]`. The default output folder is `Share\`.

`make_share.py` writes `WikiApp\` and `WikiApp.zip` there, containing the app only:
- `App Files` (code, `agents/` and `agents/messages/`, `app/templates/` and `app/templates/starters/`, the tests), without `.venv`, `__pycache__`, `.pytest_cache`, `*.pyc`, any `.wiki` folder, or the retired `agents/note-taker/`;
- the launchers, the three docs, `.gitignore` and `.gitattributes`.

It never copies `Sample Wikis\` (any wiki content), the private `.wiki` folder or `.venv`, which hold the user's own notes, settings and this PC's paths. agentlib is not included: each person needs their own copy beside the app.

In the zip, every entry carries Unix permissions, and `WikiApp.command` is executable (755), so it can be double-clicked after unzipping on a Mac.

Then it scans every copied file for the current user name, as UTF-8 and UTF-16 text in any case, and exits with code 1 if it finds one.

It only replaces an existing `WikiApp\` that it built itself, which it tracks with a `.made-by-make_share` marker.

Per-user state (the `.wiki` folder, including the signature) never goes with a copy. A new user chooses a place for their own folder, starts with no folders and is asked for a signature on first launch (`signature.js`). Someone who updates by unzipping a newer copy must extract it over the top, or keep `.wiki` elsewhere, or a `.wiki` inside the old copy is lost with it (README says so).

**Debugging**

| Need | How |
|---|---|
| Page errors, state, network | F12 in the app (Edge DevTools); right-click → Inspect on macOS |
| See the host's Python errors | Start it with the console Python: `App Files\.venv\Scripts\python.exe "App Files\host\wikiapp.py"` (macOS: `App Files/.venv/bin/python ...`) |
| Drive the app from scripts | Set `WIKIAPP_DEBUG_PORT=9334` (Windows only), start it, and connect with the Chrome DevTools Protocol (`http://127.0.0.1:9334/json`). |
| Test without touching real settings | Set `WIKIAPP_DATA_DIR` to a scratch folder before starting the app (it is the `.wiki` folder; made if missing). A scratch `settings.json` there can point the workspace at copies of the wikis. To try the first-run screen instead, set `WIKIAPP_POINTER_FILE` to a scratch file that doesn't exist. |
| Run the tests (zero tokens) | From `App Files`: `.venv\Scripts\python.exe -m unittest discover -s host/tests`, `-s ingest/tests`, and `discover tests` inside `sessions`. They use temporary folders and agentlib's fake engine |
| Check agentlib and the sign-in | **Settings** (free status, Test connection), or `python -m agentlib.check` in the agentlib folder |
| See a Promotion run's exact input | Open the run folder (**Open run folder** in the app): `system.md`, `first-message.md`, `log.jsonl`, `transcript.json`. To capture full request bodies, tick the raw requests box in Agents and rules. |
| See what a capture would send | `python sessions/sb.py condense <session id>` prints the cut-down transcript; `ingest <session id> --dry-run` shows what would be captured without writing. |
| Build an Ingest prompt without calling Claude | `App Files\.venv\Scripts\python.exe App Files\ingest\run.py <job.json> --prepare-only` |
| Rebuild one wiki's index by hand | `python wikis.py team="C:\path\team" personal="C:\path\personal"` (the copy goes to `.wiki/indexes/`) |
| Start fresh | Close the app, delete the `.wiki` folder and `~/.wikiapp-location` |

**Quirks worth knowing**
- **Only one instance runs.** A second launch focuses the first. The host keeps one per private folder (`instance.json`), so a debug copy with its own `WIKIAPP_DATA_DIR` can run beside the real one. During a first start (no folder yet) the guard port does the same job, one per copy of the app.
- **On Windows, the venv's `python.exe` and `pythonw.exe` are small launchers** that start the real interpreter as a child process. The window belongs to that child.
- **The Microsoft Store build of Python can't see other programs' folders in `%LOCALAPPDATA%`.** That's Windows app virtualization; the private folder and the pointer are in places that aren't virtualized (the project folder or the user's choice, and the home folder).
- **Moving a wiki folder** breaks the path saved in `settings.json`. To fix it, close the app, edit the `workspace` roots in that file, and raise `__rev` above the browser copy's so the file wins.
- **Sync tools** such as OneDrive can fire change events without real changes. The page compares a scan signature (paths, sizes, modified times) and skips rebuilds when nothing changed.

---

## 10. Common changes

| Change | Where |
|---|---|
| Colors and fonts | CSS variables at the top of `app\css\styles.css` |
| Default tag colors | `PALETTE` in `app\js\tags.js` |
| Graph look and physics | `app\js\graph.js` (`radius()`, the `d3Force` calls) |
| Task or note formats | `app\js\tasks.js`, `app\js\notes.js` (and the README, which documents them for users) |
| Link resolution rules | `resolveLink` / `resolveScript` in `app\js\vault.js`, **and** `Wikis.find_page` in `ingest\wikis.py`. Keep the two in step. |
| A new host command | Add it to `Host.dispatch` in `host/wikiapp.py`. Call it with `call('name', args)` from the page, and list it in §4.2. |
| A new Python package | Add it to `App Files/requirements.txt`. Every computer installs it on its next start. A package agentlib needs belongs in agentlib's `pyproject.toml` instead. |
| A new file or folder the app uses | Add an entry to `host/pathlist.py` (`APP_DATA`, `SLOTS`, `USER_FILES`, `OUTSIDE` or `WIKI_PARTS`) and read the path from there; never hard-code a path elsewhere. Add it to `CREATED_ON_USE` or `OPTIONAL` if that's what it is. Settings shows it with no change to the page. |
| New wording sent to an agent | A shipped default in `agents/messages/`, a slot in `SLOTS`, and `pathlist.read_prompt(name, **values)` where it's used. Keep tool descriptions and reply formats in code. |
| A new view | A `<section id="x-view">` and a rail button in `index.html`, a module in `app\js\`, and `showView` / `railTo` / `restoreSession` in `main.js` |
| An agent's shipped instructions | `agents\<agent id>\SKILL.md` (or `agents\messages\*.md` for the other wording). Users' unedited copies pick up the change on their next start; edited copies are left alone and flagged "newer default available" in Settings. Users add wiki-specific rules in each wiki's rules file and page templates, and capture rules in their personal capture rules file. |
| What the code adds to an agent's prompt | Promotion: `write_instructions`, `write_first_message` and the feedback and answers messages in `ingest\prompts.py` (wording from the prompt slots). Capture and review: the section lists in `sessions\secondbrain\ingest.py` and `review.py`, and the reply formats in `sessions\secondbrain\prompts.py`. |
| A new agent | Add it to `AGENTS` in `agents\agentfiles.py` with a default `agents\<id>\SKILL.md`, a `prompt.<id>` slot (and `AGENT_SLOTS`) in `host\pathlist.py`, and its model in `ENGINES` / `MODEL_AGENTS`. |
| A new tool for the agent | In `ingest\tools.py`: a spec (name, description, inputs) and a plain function. Explain it in the team wiki manager's prompt and in `AGENT.md`. |
| The model, effort or limits | Each agent's default model: `ENGINES` in `host\pathlist.py` (the user's choice is in `engine.json`). Effort and limits (Promotion): `ingest\agent.py`. |
| Thresholds of capture and review | `DEFAULTS` in `sessions\secondbrain\config.py`: `review_after_entries`, `folder_after_topics` and others. |
| Prices used for cost figures | `PRICES` in `ingest\costs.py`, by model family. Update them when a new model version changes prices. |
| Upgrading the Python packages | `python "App Files/setup.py" --upgrade`, then run the tests. The Agent SDK's version is agentlib's to pin. Raise the minimums in `requirements.txt` to the versions you tested. |

Whenever the agent's inputs or tools change, update `ingest\AGENT.md` to match: it's the record of exactly what the model sees.

---

## 11. Known gaps and risks

- **No automated tests for the page.** The Python side has tests (`host/tests`, `ingest/tests`, `sessions/tests`; zero tokens). The page was checked by hand in the running app, on copies of the sample wikis, through the DevTools protocol. Those helper scripts aren't part of the folder. The riskiest code to change without tests:
  - `edit_lines` (`notefiles.py`), the change check in §4.3;
  - link resolution in `vault.js` and `wikis.py`;
  - `persist.js`;
  - the card answer, Submit and stale logic in `ingestview.js`.
- **macOS is untested.** The host was built and tested on Windows 11. Its macOS paths have not yet run on a Mac:
  - `WikiApp.command`;
  - pywebview's WebKit window;
  - the Dock icon;
  - `open` for folders;
  - process groups for **Cancel**;
  - the Terminal window for **Run setup**.
- **No version control yet.** The folder isn't a Git repository, though `.gitignore` and `.gitattributes` are ready for one.
- **Python packages have minimum versions, not exact pins.** `requirements.txt` asks for at least the tested versions, so a new computer may get newer ones. For fully repeatable installs, change `>=` to `==`.
- **Scale.** Each scan reads every note's text into memory (up to 5 MB per note), and the Ingest index lists every page in every request. That's fine for hundreds of pages. A design for very large wikis (a folder map plus per-folder indexes on demand) is described but not built.
- **Ingest depends on agentlib** being beside the app and set up, and through it on Claude Code and Anthropic's Agent SDK. agentlib needs Python 3.11+. AGENT.md records what was verified, and when.
- **"Move" in Settings removes the old private folder** after copying it. Files locked at that moment (a sync tool) are left and reported.
- **Polling, not change notifications.** The host's watcher re-lists each open folder once a second. That's fine for hundreds or a few thousand files. Very large folders would want `watchdog` instead.
- **Single user.** Two people editing the same file at the same moment are protected only by the change check in §4.3. A later save is refused, not merged.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| Workspace folder | A folder of notes the user opened, with an alias (`team`, `personal`) and a color |
| Note id | `alias:path`, for example `personal:Notes/2026-10-31 Daily.md` |
| Wiki link | `[[Page]]`, or `[[alias:Page]]` for a page in another folder |
| Quick note | A note in the notes folder (default `Notes`), written from a template; open until wrapped |
| Wrapped / captured | Frontmatter states: `status: wrapped`; `capture_id` and `ingested: <date>` once the Notes tab has captured the note |
| Private folder | `.wiki`: everything private to the user (settings, prompts, progress), at a place they choose; found through `~/.wikiapp-location` |
| Path list | `host/pathlist.py`: every file and folder the app uses, each with a state, shown in Settings |
| File slot | A path-list file the app ships a default for. Main (note templates: copied, status default/customised), advanced (agent prompts: built in until customised), internal (never copied or listed) |
| agentlib | The separate, engine-neutral library every model request goes through |
| Page template | A file in a wiki's `Templates/Pages` that Promotion's new pages can follow; its `description` says when |
| Card | One proposed change to one page, waiting for an answer (✓, ✗ or ↻ feedback) and Submit |
| Run | One Promotion session: an agent conversation, plus any feedback rounds on its cards |
| Agent | One of the three that do the Ingest view's work: executive assistant, wiki reviewer, team wiki manager. Each has one prompt file in the private folder |
| Personal wiki | The open wiki whose role is `personal` (Settings). Notes and sessions are only ever captured into it |
| Wiki role | `personal`, `team` or `view` for each open wiki, kept in `.wiki/wiki-settings.json`. Only the team wiki gets Promotion cards; no agent writes to a view-only wiki |
| Record (session note) | What a captured session or note becomes, in the personal wiki's `Sessions/` (frontmatter `type: session`, `origin: session` or `note`, with `topics` and `tags`) |
| Topic | A page about one piece of work, `<slug>.md` at the top level of the personal wiki or in a tag's folder (`type: topic`): Current state, Related, Notes, Log |
| Tag | A label in a topic's frontmatter `tags:` saying what kind of thing it is and what it belongs to (there is no `kind` field). Chosen from the reference tag list and personal tags. It has no page of its own |
| Conflict | A session that contradicts a note: Current state follows the note, and the conflict waits in the Review tab |
| Folder | A tag that three or more topics shared and that was made a folder, `<tag>/`, with a hub page `<tag>/<tag>.md` (`type: folder`) that lists its topics |
| Promoted | Frontmatter `promoted: <date>` on a topic or folder page once a promotion's cards are all handled |
| Host | The native program around the web-based interface: `host/wikiapp.py` (Python, Windows and macOS) |
| `.venv` | The app's own Python environment in `App Files`, made by `setup.py` on each computer |
