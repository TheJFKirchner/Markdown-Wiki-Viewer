# WikiApp: technical documentation

This document is for anyone who has to understand, review, run or change WikiApp without help from AI tools.

It explains:
- what the program does;
- how its parts fit together;
- what it depends on;
- what it reads, writes and sends over the network;
- how to build, debug and change it.

The user guide (features, note and task formats) is in [README.md](README.md). The AI agent behind the Ingest feature is specified in detail in [App Files/ingest/DESIGN.md](<App Files/ingest/DESIGN.md>) and [App Files/ingest/AGENT.md](<App Files/ingest/AGENT.md>).

**How it was made.** The code was written with AI assistance (Claude Code) over a few sessions in October and November 2026. Every part is ordinary, readable source in mainstream languages: Python, JavaScript, C#. There is no generated binary blob, no obfuscation and no build pipeline. Each source file starts with a comment saying what it does.

---

## 1. What it is

A desktop app for Windows and macOS that opens folders of Markdown (`.md`) notes, like a personal wiki and a team wiki, and lets you:
- browse them;
- see how the notes link to each other in a graph;
- search them;
- edit them;
- track tasks written inside them;
- write quick notes from templates.

An optional feature, **Ingest**, sends finished notes to Claude (Anthropic's AI model). Claude proposes edits to wiki pages, and a person accepts or rejects each one before anything is written.

Notes stay plain Markdown files in the user's own folders. The app keeps no database. Any other Markdown editor can open the same files.

---

## 2. Requirements

There are two ways to run it:
- **The main host, `host/wikiapp.py`:** Python with pywebview, for Windows and macOS. Started by `WikiApp.cmd` or `WikiApp.command`.
- **The older host, `WikiApp.exe`:** C#, Windows only.

Both serve the same page and answer the same commands (§4).

### To run the app (main host)

| Requirement | Detail |
|---|---|
| Windows 10 or 11, or a recent macOS | Tested on Windows 11. macOS support is written but not yet tested on a Mac (§11). |
| Python 3.10 or newer | Tested with Python 3.13 from the Microsoft Store. On a Mac, use python.org or Homebrew; the system's `python3` is too old. |
| Python packages | Listed in `App Files/requirements.txt`, with the tested versions: `pywebview` 6.2.1, `claude-agent-sdk` 0.2.176 and `pyyaml` 6.0.3. They're installed into `App Files/.venv` by `App Files/setup.py`, which the launchers run before every start. It returns at once unless `requirements.txt` changed. The first install is about 200 MB, mostly the Claude Code engine bundled with the Agent SDK. pywebview pulls in `pythonnet` (to use WebView2 through .NET) on Windows, and `pyobjc` (WebKit) on macOS. |
| The system web view | Windows: Microsoft Edge WebView2 Runtime (ships with Windows 11 and current Windows 10) and .NET Framework 4.x (built in). macOS: WebKit (built in). |

No installer, no admin rights, no registry entries. Node.js isn't needed.

### To run `WikiApp.exe` (Windows only)

| Requirement | Detail |
|---|---|
| Windows 10 or 11, 64-bit | The exe is built for x64. |
| Microsoft Edge WebView2 Runtime | If it's missing, the exe says so and links to Microsoft's download page. |
| .NET Framework 4.x | Built into Windows 10 and 11. The exe uses Windows Forms and `System.Web.Extensions` (JSON). |

No Python is needed except for Ingest, which uses the same `App Files\.venv`.

### To rebuild `WikiApp.exe`

Nothing beyond Windows. `App Files\host\build.cmd` uses the C# compiler that ships inside Windows' .NET Framework, `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`. That compiler only understands **C# 5**, so the exe's source avoids newer syntax: no `$"..."` strings, no `?.`, no `=>` members.

### To use Ingest (optional)

| Requirement | Detail |
|---|---|
| The Python packages above | Installed by the same setup. |
| Claude Code signed in on the computer | Ingest uses the existing Claude Code login in `~/.claude`. It needs no API key of its own. A gateway configured in `~/.claude/settings.json` (`env`, `apiKeyHelper`) is passed through. |
| Internet access | For the one-time package install, and for calls to Claude during a run. |

---

## 3. Folder layout

```
Custom Local Obsidian\
├─ WikiApp.cmd                 Starts the app on Windows (runs setup.py, then the host)
├─ WikiApp.command             Starts the app on macOS (the same; LF line endings, executable)
├─ App Files\                  The whole app
│  ├─ setup.py                 Makes .venv and installs requirements.txt
│  ├─ requirements.txt         Python packages, with the tested versions as minimums
│  ├─ .venv\                   Made by setup.py on each computer; not part of the source
│  ├─ app\                     The user interface: HTML, CSS, JavaScript (ES modules)
│  │  ├─ index.html
│  │  ├─ css\styles.css
│  │  ├─ js\*.js               First-party modules (§5)
│  │  └─ lib\                  Third-party libraries, vendored (§6)
│  ├─ host\                    wikiapp.py, notefiles.py, ingestruns.py (main host);
│  │                           WikiApp.cs, build.cmd, make-icon.ps1 (the exe); app.ico
│  ├─ WikiApp.exe              The older Windows-only host (built from host\WikiApp.cs)
│  ├─ bin\                     Microsoft WebView2 SDK DLLs + their license (for the exe)
│  └─ ingest\                  Python agent for the Ingest feature, plus its design docs
├─ Sample Wikis\               Example data, if present (team\, personal\). Not part of the app; never committed or shared.
├─ WikiApp.lnk                 Shortcut to App Files\WikiApp.exe, if present (absolute path: this PC only)
├─ make_share.py               Builds a clean copy to share (§9)
├─ Share\                      Output of make_share.py; not part of the source
├─ .gitignore, .gitattributes  What Git leaves out; the launchers' line endings
├─ README.md                   User guide
├─ TECHNICAL.md                This file
└─ CLAUDE.md                   Working notes for AI coding tools (also a useful summary for people)
```

**Size.** About 12,100 lines of first-party code and styles:

| Part | Lines |
|---|---|
| JavaScript | ≈7,500 |
| CSS | ≈1,400 |
| Python | ≈1,980 (the main host ≈875, Ingest ≈1,050, setup ≈55) |
| C# | ≈960 |
| HTML and build/setup scripts | ≈300 |

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
│   ├─ settings.json / window.txt / instance.json in ~/.wikiapp                      │
│   └─ ingestruns.py starts ingest/run.py and relays its output as events            │
└────────────────────────────────────────────────────────────────────────────────────┘
          │ starts (no window)
          ▼
  .venv python -X utf8 ingest/run.py job.json
          │ Claude Agent SDK → bundled Claude Code engine → Anthropic API (or the user's gateway)
```

`WikiApp.exe` has the same shape, in C#:
- it serves the page from `https://wikiapp.example/` inside WebView2;
- messages go over WebView2's `postMessage`;
- it watches folders with `FileSystemWatcher`;
- its data is in `%LOCALAPPDATA%\WikiApp`.

### 4.1 The main host (`App Files/host/*.py`)

| Module / class | Role |
|---|---|
| `wikiapp.py` `main` | Entry point. If another copy answers on the port in `instance.json`, it asks that copy to come to the front and exits. Otherwise it copies the exe's settings over on the first start (Windows), sets the taskbar identity or Dock icon, and starts the `Host`. Command-line arguments are folders to open. |
| `wikiapp.py` `Host` | The window and the commands. It creates the pywebview window (icon, dark title bar and taskbar identity on Windows), saves and restores its position (`window.txt`), answers every command in `dispatch`, and pushes events with `window.run_js`. |
| `wikiapp.py` `AppServer` | A `ThreadingHTTPServer` on `127.0.0.1`, random port. It serves `App Files/app/` only under a random secret path, plus a generated `settings.js` and a `__focus` endpoint (used for the single window). No-store caching, so edits show after F5. |
| `wikiapp.py` `Api` | The one method pywebview exposes to the page, `call(msg)`. It returns `{id, ok, result | error}`. |
| `notefiles.py` | Scans and note writes, ported line for line from the exe's `Vault` and `NoteFiles` (same results, same refusals). Its `Watcher` polls each watched folder once a second (paths, sizes, modified times) and reports a change once things are quiet. That needs no extra package and behaves the same on both systems. |
| `ingestruns.py` | Ingest: info, saved state, run folders, starting and stopping `run.py`, feedback rounds, opening setup in a terminal. |

**How the UI is served.** The page loads from `http://127.0.0.1:<port>/<token>/`:
- The port and the 128-bit token are new on every start.
- Any request without the token gets a 404. So another program, or a web page in a browser, can't read the app's files or its `settings.js`.
- The page's writes never go through this server. They use pywebview's bridge, which only the window's own page can call.
- Links open in the default browser (`openExternal`, `http`/`https`/`mailto` only). New-window requests also go to the browser (pywebview's `OPEN_EXTERNAL_LINKS_IN_BROWSER`).

**Browser storage is per run.**
- The window uses a private profile, in a folder of its own for each run: `~/.wikiapp/webview/run-<pid>`.
  - The browser engine of a window that just closed can hold its folder for a few seconds, and WebView2 can't open a new window on a folder in use ("The requested resource is in use").
  - pywebview deletes the folder on close. Leftovers from crashed runs are removed on the next start.
- The origin's port also changes on each start. So the page starts every run with empty storage, and `settings.json` is what carries settings between runs (`persist.js`).

**Taskbar (Windows).** A Python program's window would normally group under Python and couldn't be pinned, because Windows doesn't know how to relaunch it. So the host does three things:
- it sets the process's AppUserModelID (`WikiApp.WikiApp`);
- it passes `app.ico` to pywebview, so the window has the icon from the start;
- it writes the window's AppUserModel properties (`SHGetPropertyStoreForWindow`, through pywin32): ID, relaunch command (`.venv` `pythonw.exe host\wikiapp.py`), display name and icon.

**Pin to taskbar** then pins WikiApp with its own icon. A pinned button starts the host without the launcher. So `main` first asks `setup.is_current()`; if `requirements.txt` changed, it opens the launcher, which shows the install and then starts the app.

### 4.1b The older host (`App Files\host\WikiApp.cs`)

| Class | Role |
|---|---|
| `Program` | Entry point. Loads the WebView2 DLLs from `bin\`, turns on per-monitor DPI awareness, and holds a named mutex (`WikiApp.SingleInstance.<user>`) so a second launch only brings the first window forward. Command-line arguments are folders to open. |
| `MainForm` | The window. Creates WebView2 with its user data in `%LOCALAPPDATA%\WikiApp\WebView2`, serves the UI, routes messages, watches folders, saves the window position and settings, and runs Ingest processes. |
| `NoteFiles` | Writes notes. Resolves every path inside the given folder root (no `..` escapes), only touches `.md` or `.markdown` files, and keeps each file's line endings and BOM. |
| `Vault` | Scans a folder, skipping dot-folders and hidden files. Returns each file's path, size and modified time, plus the text of notes up to 5 MB. `ReadText` is read-only, stays inside the folder, and stops at 2 MB. |
| `Ingest` | Paths and small file helpers for the Ingest feature (§8). |
| `FolderPicker` | The modern Windows "Select folder" dialog, through COM. |

**How the UI is served.** The page loads from `https://wikiapp.example/`. The host intercepts every request to that host (`WebResourceRequested`) and answers it from `App Files\app\`, with `Cache-Control: no-store` so edits show up after F5. `.example` is a reserved domain (RFC 2606), so nothing can resolve to the internet. Any navigation to another address is cancelled and opened in the default browser instead, for `http`, `https` and `mailto` only.

### 4.2 Page ↔ host protocol

The two sides talk in JSON:
- **JavaScript side:** `app/js/bridge.js`.
- **Python side:** `Api.call` → `Host.dispatch`, using pywebview's bridge for requests and `window.run_js` → `window.__wikiappReceive` for events.
- **C# side:** `MainForm.OnWebMessage` / `Dispatch`, over WebView2's `postMessage`.

`bridge.js` knows which host it's in from `window.__wikiappHost`, which the Python host's `settings.js` sets to `'python'`. `persist.js` makes the same check.

```
page → host   { id, cmd, args }
host → page   { id, ok: true, result }  or  { id, ok: false, error }
host → page   { event, data }            (pushed, no id)
```

**Commands:**

| Command | What it does |
|---|---|
| `getStartupFolders` | Folders passed on the command line |
| `pickFolder` | Shows the folder dialog |
| `scanVault` | Scans a folder (and starts watching it) |
| `unwatchFolder` | Stops watching a folder |
| `editLines` | Replaces lines in a note, **only if** the expected lines are still there (see 4.3) |
| `appendLines` | Appends lines to a note, creating it if needed |
| `createNote` | Creates a note; fails if it exists |
| `readText` | Reads a file's text, read-only (used to show scripts) |
| `saveSettings` | Writes `settings.json` |
| `openExternal` | Opens a URL in the default browser |
| `setTitle` | Python host only: sets the window title to the page's (the exe follows the title itself) |
| `closeWindow` | The page's answer to `closeRequested`: `answer` is `asking` (it's asking the user), `no` (stay open) or `yes` (close now) |
| `ingestInfo`, `saveIngestState`, `saveIngestNotes`, `startIngest`, `reviseIngestCards`, `cancelIngest`, `runIngestSetup`, `listIngestRuns`, `openIngestRun`, `listIngestModels` | Ingest (§8) |

**Events:** `vaultChanged` (a watched folder changed), `ingest` (one progress line from the agent), `ingestExit` (the agent process ended), `closeRequested` (the window's close button was clicked; the window stays open until the page answers `closeWindow`).

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

**Settings** live in the WebView's `localStorage`. `persist.js` wraps `localStorage.setItem/removeItem/clear` and mirrors every change, debounced by 150 ms, to `settings.json` through the host: `~/.wikiapp/settings.json` for the main host, `%LOCALAPPDATA%\WikiApp\settings.json` for the exe.
- Each save increments `__rev`.
- At start-up, whichever copy (file or browser storage) has the higher `__rev` wins.
- Keys in use:
  - workspace: `workspace` (open folders: root, alias, color, hidden), `notesFolder`, `notesDir`, `signature`;
  - restoring where the user left off: `lastView`, `lastPage`, `lastNote`;
  - graph: `tagColors`, `colorBy`, `showDuplicates`, `showNotes`, `showScripts`, `graphPanelOpen`;
  - layout: `notesPanelOpen`, `sidebarWidth`, `sidebarHidden`;
  - Tasks: `taskGroupBy`, `newTaskPage`;
  - Ingest: `ingestLogRaw`, `ingestModel` (the chosen model id), `ingestModels` (the last model list);
  - unused: `lastVault` (legacy).

---

## 5. First-party module reference

### JavaScript (`App Files\app\js\`)

All are ES modules except `persist.js`, which is a plain script so it runs before any module.

| Module | Purpose | Imports |
|---|---|---|
| `main.js` | Wiring and state: views, rail, saving, session restore | bridge, vault, workspace, explorer, graph, viewer, tags, graphpanel, folderdialog, taskspane, signature, autocomplete, tasks, editor, inlineeditor, searchbar, notespanel, notesview, ingestview, ingestdialogs, notes |
| `bridge.js` | `call(cmd, args)` → Promise, and `on(event, fn)` for host events | – |
| `persist.js` | Mirrors `localStorage` to `settings.json` (`__rev` rule) | – |
| `workspace.js` | The open folders: aliases, colors, hidden flag | – |
| `vault.js` | Data model: frontmatter (YAML), tags, `[[link]]` resolution, duplicates, graph data | lib/js-yaml, tasks, notes |
| `tasks.js` | Task line format: parsing, and building edited lines (text changes keep every `due:`/`done:`/`~` token, moved to the line's end) | – |
| `notes.js` | Quick notes: templates, placeholders, sections, wrapping | tasks |
| `explorer.js` | Sidebar file tree | vault |
| `graph.js` | Force-directed graph on a canvas (uses the global `ForceGraph`) | tags |
| `graphpanel.js` | Graph settings card: coloring, folders, tags, toggles | – |
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
| `ingestview.js` | Ingest view: note list, model menu, run progress, cards, line diff, answers and Submit, feedback rounds, past runs | vault, notes, tasks |
| `ingestdialogs.js` | Ingest windows: prompt editor (with the agent prompt, read-only), help (with diagram), run transcript | vault |

### Python: setup and the main host (`App Files\`, `App Files\host\`)

| File | Purpose | Imports |
|---|---|---|
| `setup.py` | Makes `.venv` if needed, then `pip install -r requirements.txt` unless the hash recorded in `.venv/wikiapp-setup.txt` still matches; `--upgrade` updates everything | stdlib (`hashlib`, `os`, `subprocess`, `sys`, `venv`, `pathlib`) |
| `host/wikiapp.py` | Entry point, window, app server, command dispatch, settings, window position, single window | stdlib (`ctypes`, `http.server`, `json`, `mimetypes`, `os`, `secrets`, `shutil`, `sys`, `threading`, `urllib`, `webbrowser`, `pathlib`), `webview` (pywebview), local `notefiles`, `ingestruns`; on Windows `System` / `System.Drawing` through pythonnet for the icon; on macOS `AppKit` (pyobjc) |
| `host/notefiles.py` | Folder scans, `readText`, the note writes and their checks, the polling watcher | stdlib (`os`, `stat`, `threading`, `time`) |
| `host/ingestruns.py` | Ingest runs: info, state, run folders, start, feedback, stop, setup window, the model list | stdlib (`importlib.util`, `json`, `os`, `signal`, `subprocess`, `sys`, `threading`, `datetime`, `pathlib`) |

### Python: Ingest (`App Files\ingest\`)

The code is written for someone who has never seen agent code: `agent.py` explains what an agent is, sets it up as plain variables (an `Agent` with `model`, `effort`, `instructions_file`, `tools`, `max_turns`, `max_cost_usd`…), and keeps Claude Code's plumbing in one function at the end (`claude_code_options`). The tools are plain functions in their own file.

| File | Purpose | Imports |
|---|---|---|
| `agent.py` | **Start here.** The agent: `ingest_notes` (one run), `revise_cards` (a feedback round), `talk_to_claude` (following the loop), `how_it_ended`, and the options Claude Code needs | stdlib (`json`, `dataclasses`, `datetime`, `pathlib`), `claude_agent_sdk`, local `costs`, `progress`, `prompts`, `tools`, `transcript`, `wikis` |
| `tools.py` | The agent's two tools as plain functions, `read_page` and `propose_page`, each with its description and inputs, every proposal check, `RunMemory` (what they remember during a run), and `tools_for_claude` (handing them to Claude Code) | `re`, `yaml`, `claude_agent_sdk` (`tool`, `create_sdk_mcp_server`), local `wikis` |
| `prompts.py` | The text the agent is given: `write_instructions`, `write_first_message`, `write_feedback_message` | stdlib (`pathlib`), local `wikis` |
| `wikis.py` | Wiki scan, `[[link]]` resolution (`find_page`, same rules as `vault.js`), the per-wiki index with its page templates | stdlib (`difflib`, `os`, `re`, `stat`, `sys`, `dataclasses`, `datetime`, `pathlib`), `yaml` |
| `transcript.py` | The run's record, `transcript.json` | stdlib (`json`, `datetime`, `pathlib`), local `costs` |
| `costs.py` | Token counts, list prices by model family, totals, the plain-Claude-Code estimate | – |
| `progress.py` | Progress lines for the app (`tell_app`) and the run's `log.jsonl` | stdlib (`json`, `pathlib`) |
| `run.py` | The command line the host starts: one run, `--prepare-only`, or `--feedback` | stdlib (`asyncio`, `json`, `os`, `sys`, `pathlib`), local `agent`, `progress` |
| `models.py` | Prints the models Claude Code offers (`id`, `name`, `description`) as JSON, for the model menu. Makes no request to Claude. | stdlib (`asyncio`, `json`, `sys`), `claude_agent_sdk` |
| `agent-prompt.md` | The agent's built-in instructions (template) | – |

---

## 6. Third-party components

The page's libraries and the exe's DLLs are vendored (copied into the folder). The Python packages are installed by `setup.py` from PyPI, once per computer. Nothing loads from the internet at run time, and the page has no build step.

| Component | Version | License | Where | Used for |
|---|---|---|---|---|
| pywebview (Python) | 6.2.1 tested | BSD-3-Clause | `.venv` (installed by setup) | The main host's window. It brings `pythonnet` and `clr_loader` (MIT) on Windows, and `pyobjc` (MIT) on macOS. |
| pywin32 (Python, Windows only) | 312 tested | PSF | `.venv` | The window's taskbar properties (pinning) |
| force-graph | 1.52.0 | MIT | `app\lib\force-graph.min.js` (global script) | Graph drawing and physics |
| markdown-it | 15.0.2 | MIT | `app\lib\markdown-it.min.js` (ES module) | Rendering Markdown; raw HTML in notes is disabled (`html: false`) |
| js-yaml | 4.x (README records 4.3.2) | MIT | `app\lib\js-yaml.js` (ES module build) | Reading frontmatter (`CORE_SCHEMA`, so dates stay text) |
| Microsoft WebView2 SDK | 1.0.4314.35 | Microsoft (see `bin\WebView2-LICENSE.txt`) | `bin\Microsoft.Web.WebView2.Core.dll`, `…WinForms.dll`, `WebView2Loader.dll` | Hosting the Edge engine |
| claude-agent-sdk (Python) | 0.2.176 tested | Anthropic Commercial Terms | `.venv` (installed by setup) | Running the Ingest agent through the Claude Code engine |
| PyYAML | 6.0.3 tested | MIT | `.venv` | YAML in the agent's checks and index |

`claude-agent-sdk` pulls in its own dependencies: `mcp`, `anyio`, `pydantic`, `jsonschema`, `httpx2`, and others. `pip` installs them.

**To update a vendored library,** replace its file and reload with F5. markdown-it and js-yaml must stay ES module builds, with a default export; force-graph must stay a global (UMD) build.

---

## 7. Data: what is read, written and sent

| What | Where | Written by |
|---|---|---|
| Notes, templates, `wiki_rules.md` | The user's wiki folders | The host only (`NoteFiles`), `.md` files only, with the change check in §4.3 |
| Ingest index | `<wiki>\.wiki\index.md` (a dot-folder, hidden from the app) | `ingest\wikis.py` directly, at the start of each run. **This is the one exception to "only the host writes"**, and it never touches notes. |
| The Python environment | `App Files/.venv` | `setup.py` (pip) |
| App settings | `~/.wikiapp/settings.json` (exe: `%LOCALAPPDATA%\WikiApp\settings.json`) | Host, at the page's request |
| Window position | `~/.wikiapp/window.txt` (exe: `%LOCALAPPDATA%\WikiApp\window.txt`) | Host |
| Running copy's port and token, for the single window | `~/.wikiapp/instance.json`, deleted on close | Main host |
| Web view profile | `~/.wikiapp/webview/run-<pid>/` for the main host (private mode, one folder per run, deleted on close); `%LOCALAPPDATA%\WikiApp\WebView2\` for the exe | The web view |
| Ingest cards waiting for review; the user's notes for the agent | `~/.wikiapp/ingest/pending.json`, `user-notes.md` (exe: `%LOCALAPPDATA%\WikiApp\ingest\`) | Host |
| Ingest run folders: job, prompts, log, transcript, session state | `~/.wikiapp/ingest-runs/<run id>/` (exe: `%TEMP%\WikiApp\ingest-runs\<run id>\`) | Host (`job.json`) and `run.py` |
| Claude Code session files, one per Ingest run (needed for feedback rounds) | `~/.claude/projects/<run folder name>/` | The Claude Code engine |

`~/.wikiapp` means the user's home folder: `C:\Users\<name>\.wikiapp`, or `/Users/<name>/.wikiapp`. `WIKIAPP_DATA_DIR` moves it.

On its first start on Windows, the main host copies the exe's data into it: settings, window position, Ingest data and past runs. To reset the app completely, close it and delete that folder. Notes are never stored there.

**Network traffic**
- **The app itself makes no network requests.** Links the user clicks open in the default browser. The main host's page server listens on `127.0.0.1` only, never on the network.
- **Setup** downloads the Python packages from PyPI (pypi.org) on the first start, and again only when `requirements.txt` changes.
- **Ingest** makes HTTPS calls to Anthropic's API, or to the user's configured gateway, through the Claude Code engine. A run sends:
  - the agent's instructions, the user's notes for the agent, and each wiki's rules;
  - an index of page names, descriptions, tags, headings and links;
  - the full text of the selected notes;
  - the text of each page the agent chooses to read.

  Claude Code also adds a short environment block (working folder, OS) and a reminder holding the signed-in account's email and today's date.
- Ingest switches off Claude Code's optional background traffic (`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`).
- WebView2 and Windows may update themselves as usual. That's outside the app.

**Security notes**
- The page can only reach the disk through the host's commands. Writes are limited to `.md` files inside folders the user opened. Reads outside a scan are read-only, stay inside the folder and stop at 2 MB.
- Notes are rendered with raw HTML switched off, so a note can't inject markup or script into the app.
- The Ingest agent runs with **no built-in tools**: no shell, no file write, no web, no subagents. Its only tools are `read_page`, which can only open wiki pages and scripts in the open folders, and `propose_page`, which only creates a card. A person must press ✓ before the host writes anything.
- The main host's page server answers only requests carrying its per-run secret token, and only ever serves `App Files/app/` (paths are resolved and must stay inside it). It accepts no writes.
- The exe isn't code-signed, so Windows SmartScreen warns on first run of a downloaded copy. The launchers are plain scripts, and the Python they run is the user's own installation.
- Developer tools are enabled (F12 on Windows; right-click → Inspect on macOS). Remote debugging is off unless switched on before launch: `WIKIAPP_DEBUG_PORT=<port>` for the main host, `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<port>` for the exe.

---

## 8. The Ingest feature

Full detail, including every word sent to the model, is in `App Files\ingest\DESIGN.md` and `App Files\ingest\AGENT.md`.

**What happens in a run**

1. The user ticks wrapped notes, picks a model (or keeps Haiku 5.5) and presses **Ingest**.
   - The model menu is filled by `listIngestModels`: the host runs `ingest/models.py`, which starts Claude Code through the Agent SDK, reads the model list from its start-up handshake (`get_server_info()`), and stops it. No request is made to Claude, so it costs nothing. It takes a few seconds, once per app start, and the last list is kept in the settings (`ingestModels`; the choice is `ingestModel`).
2. The page sends `startIngest`. The host writes `job.json` (notes, wiki folders, the user's notes, settings) to a new run folder. It then starts the `.venv` Python on `-X utf8 ingest/run.py <job.json>`, with no window. On macOS, the run gets its own process group, so **Cancel** also stops the Claude Code engine.
3. `run.py` hands the job to `ingest_notes` in `agent.py`, which:
   - rebuilds the index, which ends with each wiki's page templates (name, id, description only);
   - builds the instructions (system prompt), from `agent-prompt.md` plus the user's notes plus each `wiki_rules.md`;
   - builds the first message: the index, then the notes;
   - starts the agent through the Claude Agent SDK.

   What the agent is given (`make_agent`):
   - the chosen model (the job's `settings.model`; `claude-haiku-5-5` by default), effort `low`;
   - our instructions only: no CLAUDE.md or user settings loaded;
   - no built-in tools; the two in-process tools are served by `tools.py`;
   - a limit of 40 turns and $1.00 per run (at API prices).
4. The agent plans, reads pages, and calls `propose_page`. `tools.py` checks each proposal:
   - each edit's text must occur exactly once in the page as it was read;
   - paths must be valid;
   - frontmatter must be valid YAML;
   - a new page's `template`, if given, must be a page template of the same wiki that the agent has read;
   - and more.

   A valid proposal becomes a card. Each card carries the page's text before and after the change.
5. Every event is printed as one JSON line. The host relays each line to the page as an `ingest` event, and the page shows progress and cards.
6. The user answers each card: ✓, ✗ or ↻ (feedback). Answers are kept with the cards in `pending.json` and nothing happens until **Submit**, which needs every card answered. Then:
   - **✓** sends `editLines` (replacing the whole file, but only if it still equals the card's "before" text) or `createNote`;
   - **✗** drops the card;
   - a card whose page changed in the meantime becomes "stale" and can only be dismissed;
   - the **↻** cards go back to Claude together (below).
7. When every card is handled, the notes get `ingested: <date>` in their frontmatter.

**Feedback** resumes the same Claude Code session with one new message, using `run.py … --feedback <file>`. The page sends `reviseIngestCards` with `{cards: [{card, text}], accepted, rejected}`; the message tells Claude what was decided and gives the feedback on each card. `tools.py` refuses proposals for cards already accepted or rejected. The revised cards replace the old ones (same ids) and need a new answer. The round's cost is added to the same run.

**Costs.** Each run's transcript (`transcript.json`) records every request's tokens and cost, and the app shows it under **Past runs**. Costs are at Claude API list prices: on a Claude subscription a run isn't billed per token but counts toward the plan's usage, so the figures are for comparing runs and models. Typical cost on Haiku 5.5 is under one cent per run.

**Page templates.** A wiki's `Templates/Pages/*.md` files are templates for new pages: the file name is the template's name, and its frontmatter `description` says when to use it. The index lists only those two (and the id). The agent reads a template only when it's about to propose a new page, follows it, and names it in `propose_page`'s `template`; the card shows it. Like everything under `Templates/`, they're left out of the graph, tags and tasks (`isTemplatePath` in `notes.js`). Quick-note templates live beside them in `Templates/Notes/` (files directly in `Templates/` still count). When a folder without `Templates/` is linked, `seedTemplates` in `main.js` copies the app's seeds, `app/templates/Notes/Sample note.md` and `app/templates/Pages/Sample page.md`, into it through `createNote`.

---

## 9. Build, run, debug

**Run:** double-click `WikiApp.cmd` (Windows) or `WikiApp.command` (macOS).
- Each runs `App Files/setup.py` with the `.venv` Python. On the first start there's no `.venv` yet, so it uses the first Python 3.10+ it finds instead.
- Then it starts `host/wikiapp.py`: with `pythonw.exe` on Windows (no console), and detached with `nohup` on macOS.
- On macOS the file must be executable: run `chmod +x WikiApp.command` once, or use `git update-index --chmod=+x WikiApp.command` before committing.
- The exe still runs on its own: `App Files\WikiApp.exe`.

**Change the interface:** edit files in `App Files\app\`, then press **F5** (Cmd+R on macOS) in the app. There's nothing to build.

**Change the main host:** edit `App Files/host/*.py` and start the app again.

**Rebuild the exe:**
1. Close the exe; it's locked while it runs.
2. Run `App Files\host\build.cmd`.

It compiles `WikiApp.cs` against `bin\Microsoft.Web.WebView2.*.dll`, `System.Windows.Forms`, `System.Drawing` and `System.Web.Extensions`, and writes `App Files\WikiApp.exe`. If `host\app.ico` is missing, it first runs `make-icon.ps1` to draw one.

**Set up or update the packages:**
- Edit `requirements.txt`. The next start installs the change.
- To update everything, run `python "App Files/setup.py" --upgrade`, or press **Run setup** in the Ingest view.

**Share a copy:**
- **With Git,** commit the folder. `.gitignore` leaves out `.venv`, caches, `Share/`, shortcuts and `Sample Wikis/`. `WikiApp.command` is committed executable (`git update-index --chmod=+x`). `.gitattributes` keeps `WikiApp.command` at LF and `WikiApp.cmd` at CRLF.
- **As a zip,** run `python make_share.py [output folder]`. The default output folder is `Share\`.

`make_share.py` writes `WikiApp\` and `WikiApp.zip` there, containing the app only:
- `App Files`, without `.venv`, `__pycache__` or `*.pyc`;
- the launchers, the three docs, `.gitignore` and `.gitattributes`.

It never copies `Sample Wikis\` (any wiki content) or `WikiApp.lnk`. Those, and `.venv`, hold the user's own notes or this PC's paths.

In the zip, every entry carries Unix permissions, and `WikiApp.command` is executable (755), so it can be double-clicked after unzipping on a Mac.

Then it scans every copied file for the current user name, as UTF-8 and UTF-16 text in any case, and exits with code 1 if it finds one.

It only replaces an existing `WikiApp\` that it built itself, which it tracks with a `.made-by-make_share` marker.

Per-user state (`~/.wikiapp`, including the signature) is never in the project folder. A new user starts with no folders and is asked for a signature on first launch (`signature.js`).

**Debugging**

| Need | How |
|---|---|
| Page errors, state, network | F12 in the app (Edge DevTools); right-click → Inspect on macOS |
| See the main host's Python errors | Start it with the console Python: `App Files\.venv\Scripts\python.exe "App Files\host\wikiapp.py"` (macOS: `App Files/.venv/bin/python ...`) |
| Drive the app from scripts | Main host: set `WIKIAPP_DEBUG_PORT=9334` (WebView2 only), start it, and connect with the Chrome DevTools Protocol (`http://127.0.0.1:9334/json`). Exe: `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`. |
| Test without touching real settings | Set `WIKIAPP_DATA_DIR` to a scratch folder before starting the main host. A scratch `settings.json` there can point the workspace at copies of the wikis. |
| See an Ingest run's exact input | Open the run folder (**Open run folder** in the app): `system.md`, `first-message.md`, `log.jsonl`, `transcript.json`. To capture full request bodies, tick *Also save each run's raw requests* in Edit ingestion prompt. |
| Build an Ingest prompt without calling Claude | `App Files\.venv\Scripts\python.exe App Files\ingest\run.py <job.json> --prepare-only` |
| Rebuild one wiki's index by hand | `python wikis.py team="C:\path\team" personal="C:\path\personal"` |
| Start fresh | Close the app and delete `~/.wikiapp` (exe: `%LOCALAPPDATA%\WikiApp`) |

**Quirks worth knowing**
- **Only one instance runs.** A second launch focuses the first. The main host keeps one per data folder, so a debug copy with its own `WIKIAPP_DATA_DIR` can run beside the real one.
- **On Windows, the venv's `python.exe` and `pythonw.exe` are small launchers** that start the real interpreter as a child process. The window belongs to that child.
- **The Microsoft Store build of Python can't see other programs' folders in `%LOCALAPPDATA%`.** That's Windows app virtualization, and it's why:
  - the exe keeps Ingest run folders in `%TEMP%`;
  - the main host keeps all its data in `~/.wikiapp`, which isn't virtualized;
  - the host hands the user's notes for the agent to Python inside `job.json`, rather than as a file path.
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
| A new host command | Add it to `Host.dispatch` in `host/wikiapp.py` and a `case` in `Dispatch` in `WikiApp.cs` (then rebuild the exe). Call it with `call('name', args)` from the page, and list it in §4.2. |
| A new Python package | Add it to `App Files/requirements.txt`. Every computer installs it on its next start. |
| A new view | A `<section id="x-view">` and a rail button in `index.html`, a module in `app\js\`, and `showView` / `railTo` / `restoreSession` in `main.js` |
| The agent's instructions | `ingest\agent-prompt.md`. Users add their own through *Your notes*, each wiki's `wiki_rules.md` and its page templates (`Templates/Pages`). |
| A new tool for the agent | In `ingest\tools.py`: a spec (name, description, inputs) and a plain function, added to `TOOLS`. Explain it in `agent-prompt.md` and `AGENT.md`. |
| The model, effort or limits | `DEFAULT_MODEL`, `DEFAULT_EFFORT`, `MAX_TURNS` and `MAX_COST_USD` in `ingest\agent.py`. A job's `settings` can override the model (the Ingest view's menu sets it) and effort. The menu's default is `DEFAULT_MODEL` in `app\js\ingestview.js`; keep the two the same. |
| Prices used for cost figures | `PRICES` in `ingest\costs.py`, by model family (Haiku, Sonnet, Opus, Fable; cache writes assume the 5-minute rate). Update them when a new model version changes prices. |
| Upgrading the WebView2 SDK | Take the new `Microsoft.Web.WebView2` NuGet package, copy its `Core`, `WinForms` and x64 `WebView2Loader` DLLs into `bin\`, then rebuild |
| Upgrading the Python packages | `python "App Files/setup.py" --upgrade`, then run a test ingest. For the Agent SDK, check `ClaudeAgentOptions` field names against the SDK docs if anything fails. Raise the minimums in `requirements.txt` to the versions you tested. |

Whenever the agent's inputs or tools change, update `ingest\AGENT.md` to match: it's the record of exactly what the model sees.

---

## 11. Known gaps and risks

- **No automated tests.** Every change was checked by hand in the running app, on copies of the sample wikis, through the DevTools protocol. Those helper scripts aren't part of the folder. The riskiest code to change without tests:
  - `edit_lines` (`notefiles.py`) and `NoteFiles.EditLines` (C#), the change check in §4.3;
  - link resolution in `vault.js` and `wikis.py`;
  - `persist.js`;
  - the card answer, Submit and stale logic in `ingestview.js`.
- **macOS is untested.** The main host was built and tested on Windows 11. Its macOS paths have not yet run on a Mac:
  - `WikiApp.command`;
  - pywebview's WebKit window;
  - the Dock icon;
  - `open` for folders;
  - process groups for **Cancel**;
  - the Terminal window for **Run setup**.
- **Two hosts to keep in step.** Until `WikiApp.exe` is retired, every host command exists twice (Python and C#).
- **No version control yet.** The folder isn't a Git repository, though `.gitignore` and `.gitattributes` are ready for one.
- **Python packages have minimum versions, not exact pins.** `requirements.txt` asks for at least the tested versions, so a new computer may get newer ones. For fully repeatable installs, change `>=` to `==`.
- **Scale.** Each scan reads every note's text into memory (up to 5 MB per note), and the Ingest index lists every page in every request. That's fine for hundreds of pages. A design for very large wikis (a folder map plus per-folder indexes on demand) is described but not built.
- **Ingest depends on Claude Code and its login,** and on Anthropic's Agent SDK interface. Upgrades to either can change option names or behavior. AGENT.md records what was verified, and when.
- **Unsigned exe.** SmartScreen warns on first run. Signing needs a code-signing certificate.
- **Polling, not change notifications.** The main host's watcher re-lists each open folder once a second. That's fine for hundreds or a few thousand files. Very large folders would want `watchdog` instead.
- **Single user.** Two people editing the same file at the same moment are protected only by the change check in §4.3. A later save is refused, not merged.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| Workspace folder | A folder of notes the user opened, with an alias (`team`, `personal`) and a color |
| Note id | `alias:path`, for example `personal:Notes/2026-10-31 Daily.md` |
| Wiki link | `[[Page]]`, or `[[alias:Page]]` for a page in another folder |
| Quick note | A note in the notes folder (default `Notes`), written from a template; open until wrapped |
| Wrapped / ingested | Frontmatter states: `status: wrapped`; `ingested: <date>` once Ingest has processed the note |
| Page template | A file in a wiki's `Templates/Pages` that Ingest's new pages can follow; its `description` says when |
| Card | One proposed change to one page, waiting for an answer (✓, ✗ or ↻ feedback) and Submit |
| Run | One Ingest session: an agent conversation, plus any feedback rounds on its cards |
| Host | The native program around the web-based interface: `host/wikiapp.py` (Python, Windows and macOS) or `WikiApp.exe` (C#, Windows) |
| `.venv` | The app's own Python environment in `App Files`, made by `setup.py` on each computer |
