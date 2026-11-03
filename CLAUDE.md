# WikiApp

A small, customizable, Obsidian-style app for folders of Markdown notes. It opens several folders at once (say a personal and a team wiki, each with an alias), shows how notes link in a graph, and has tasks, quick notes from templates, search and in-place editing. The user-facing docs are in [README.md](README.md).

## Goals and constraints

- **Anyone can clone the folder and run it on Windows or macOS.**
  - They double-click `WikiApp.cmd` or `WikiApp.command`.
  - The first start runs `App Files/setup.py`, which makes `App Files/.venv` and installs `requirements.txt`. Every later start is quick.
  - The only prerequisite is Python 3.10+. No console window stays open.
- **No build step for the app.** `App Files/app/` is plain HTML, CSS and ES modules. Press F5 (Cmd+R on a Mac) in the app to reload after an edit.
- **Two hosts, one page.**
  - `host/wikiapp.py` (pywebview) is the main host, for Windows and macOS.
  - `WikiApp.exe` (C#) is the older Windows-only host, kept working. It needs no Python except for Ingest.
  - Both answer the same commands, so a host change goes in both until the exe is retired.
- **Notes stay plain Markdown** that other editors can read. Tasks, quick notes and templates are all just text conventions (formats in README).
- **Never lose or overwrite the user's text.** Every write goes through the host and is refused if the lines on disk changed since the page read them.

## Layout

The project root has two folders, kept apart on purpose:

- **`App Files/`**: everything the app is made of. Both hosts find `app/` and `ingest/` relative to themselves, so the folder works wherever it's copied.
- **`Sample Wikis/`**: the example wikis, `team/` and `personal/`, where present. They're data, not part of the app, and `.gitignore` keeps them out of the repo. The user also uses them as real data, so treat them as theirs.

Also at the root:
- this file;
- `README.md` (user guide);
- `TECHNICAL.md` (technical documentation; keep it accurate when architecture, dependencies, data locations or host commands change);
- the launchers:
  - `WikiApp.cmd` must have CRLF line endings, and `WikiApp.command` LF. `.gitattributes` keeps them that way.
  - Keep both launchers tiny: the logic belongs in `setup.py`.
- `.gitignore`: leaves out `.venv`, caches, `Share/` and `*.lnk`;
- a `WikiApp.lnk` shortcut to `App Files\WikiApp.exe`. It holds this PC's absolute path, so it's never shared;
- `make_share.py`, which builds a clean copy to send to others in `Share/`.
  - It ships the app only: no wiki content (`Sample Wikis/` is never copied), `.venv`, caches or the shortcut.
  - Then it checks the copy for the user name.
  - Keep its include and exclude lists in step when adding top-level files.

Paths below, and in `ingest/DESIGN.md` and `ingest/AGENT.md`, are inside `App Files/`.

| Path | What it is |
|---|---|
| `setup.py`, `requirements.txt` | Make `.venv` and install the packages (pywebview, claude-agent-sdk, pyyaml). Run before every start; returns at once when nothing changed. |
| `host/wikiapp.py` | The main host. It opens the window and serves `app/` on 127.0.0.1 under a secret path. It answers the page's messages, keeps settings and the window position, and allows one instance. |
| `host/notefiles.py`, `host/ingestruns.py` | The Python host's folder scans, note writes, folder watching (polling), and Ingest runs. |
| `WikiApp.exe`, `bin/`, `host/WikiApp.cs`, `host/build.cmd` | The older Windows-only host, the WebView2 DLLs it loads, its source and build script. |
| `app/index.html`, `app/css/styles.css` | The page shell and all styles. Every color is a CSS variable at the top of the stylesheet. |
| `app/js/main.js` | The wiring: workspace scans → combined model → views. It owns the view rail, saving, and the start-up session restore. |
| `app/js/vault.js` | The data model: notes, frontmatter, tags, `[[links]]`, duplicates and graph data. |
| `app/js/*.js` | One module per feature: the tasks pane, notes and templates, search, the editors, the graph and its panel. Each file starts with a comment saying what it does. |
| `app/lib/` | Third-party libraries (force-graph, markdown-it, js-yaml). |
| `app/templates/` | The seed templates (`Notes/Sample note.md`, `Pages/Sample page.md`) copied into a newly linked folder that has no `Templates` folder. |
| `ingest/` | The ingest agent, in Python with the Claude Agent SDK, written to be read by someone new to agent code: `agent.py` (the agent: what it's given, the loop, feedback rounds; start here), `tools.py` (its two tools, as plain functions), `prompts.py` (the text it's given), `wikis.py` (wiki scan, link resolution, index, page templates), `transcript.py` and `costs.py` (the run's record and prices), `progress.py` (lines for the app), `run.py` (the command line), `models.py` (the model menu's list, from Claude Code's start-up handshake, free), the shipped `agent-prompt.md`. Keep it that way: plain names, comments that explain agent ideas, plumbing kept apart from the agent's setup. [ingest/DESIGN.md](<App Files/ingest/DESIGN.md>) is the design; [ingest/AGENT.md](<App Files/ingest/AGENT.md>) is exactly what the agent sees and must stay in step with the code. |

## Conventions

- **Note ids** are `alias:path` (for example `personal:Notes/2026-10-31 Daily.md`). Links can name a folder: `[[team:Jupiter]]`.
- **Page ↔ host** talk through JSON messages in `app/js/bridge.js`.
  - The Python host gets them in `Host.dispatch` in `wikiapp.py` (through `window.pywebview.api.call`).
  - The exe gets them in `Dispatch` in `WikiApp.cs` (through WebView2 `postMessage`).
  - The Python host's `settings.js` sets `window.__wikiappHost = 'python'`, which tells the page which one it's in.
  - The hosts only write `.md` files inside an open folder, plus their own data.
- **Per-user data:**
  - The Python host keeps it in `~/.wikiapp` (`WIKIAPP_DATA_DIR` overrides): `settings.json`, `window.txt`, `ingest/`, `ingest-runs/`, `instance.json`. On first start it copies the exe's settings over.
  - The exe uses `%LOCALAPPDATA%\WikiApp` and `%TEMP%\WikiApp\ingest-runs`.
- **Quick notes** are the files in the notes folder (setting `notesDir`, default `Notes`) of any workspace folder; `note.inbox` marks them. The Notes view and the full editor both edit through `livetext.js`, which keeps the text as Markdown lines and only formats the display.
- **Editing as it looks** (`livetext.js` + `richtext.js`): each line is a row with a `contenteditable` box.
  - The box holds the line's inline Markdown, rendered by `viewer.renderEditable` (no typographer; marks carry `data-md`, `[[links]]` carry `data-src` and are uneditable atoms).
  - `serialize` turns the box back into Markdown on every keystroke. The row's prefix (`##`, `- `, `1. `, indent) is kept aside in `row._kind`.
  - A line whose Markdown doesn't survive render → `serialize` unchanged is shown raw (class `raw`). Never relax that check: it's what keeps edits from rewriting text the user didn't touch.
  - Structural edits (Enter, Backspace joins, Tab, shortcuts) change `lines`, then `redrawAt` redraws and puts the caret back.
- **Templates:** a wiki's `Templates/` folder has `Notes/` (quick-note templates, for the New note menu; files directly in `Templates/` still count, the older layout) and `Pages/` (page templates for Ingest's new pages, `description` = when to use it). Everything under `Templates/` is left out of the graph, tags and tasks. Linking a folder without `Templates/` copies the seeds in `app/templates/` into it (`seedTemplates` in `main.js`).
- **Scripts** (`.sql`, `.py`... see `SCRIPT_EXT` in `vault.js`) live in `vault.scripts`, not `vault.notes`. They're link targets only (`resolveTarget` = notes, then scripts) and their text is read on demand, never scanned for links.
- **Settings** use `localStorage`. `app/js/persist.js` mirrors it into `settings.json`, so the app opens the same way however it's started. The Python host's page starts each run with empty storage, because its origin has a new random port, so there the file is what counts.
- **The exe's host is C# 5:** the compiler built into Windows is used, so no `$"..."`, `?.` or `=>` members. Rebuild with `host\build.cmd /nopause`, after closing the exe (it's locked while it runs).
- Match the existing style: small modules, a short header comment per file, plain DOM, no frameworks.
- **Write scripts in Python where possible** (tooling, the ingest agent, one-off helpers). Don't force it where it would complicate things: the page stays JavaScript, and a tiny launcher can stay a `.cmd` or `.command`.

## Working on it

- **Test in the real app on copies, never on the user's folders.** The Python host makes this easy.
  1. Copy `Sample Wikis/` (or any test wiki) to a scratch folder.
  2. Write a scratch `settings.json` whose `workspace` points at the copies.
  3. Start `App Files/.venv/Scripts/python.exe App Files/host/wikiapp.py` with `WIKIAPP_DATA_DIR=<scratch data folder>` and `WIKIAPP_DEBUG_PORT=9334`.
  4. Drive it through the DevTools protocol (`http://127.0.0.1:9334/json`; the page URL contains `127.0.0.1`).
  5. Check afterwards that the real sample files are unchanged.

  With `WIKIAPP_DATA_DIR` set, the user's settings are never touched, and the migration from the exe is skipped. The user's signature and folder list have been overwritten by tests before.

  **Things to know when testing on Windows:**
  - **The venv's `python.exe` is a launcher.** The real process is a child (`python3.13.exe`, or `pythonw3.13.exe`), and that child owns the window.
    - Find it by command line containing `wikiapp.py`. It may have forward slashes if a bash shell started it.
    - Start the user's real copy with PowerShell `Start-Process`, not as a bash background job, which the Bash tool ends with the command.
  - **Pinning depends on `set_taskbar_identity`** (pywin32, on the window's thread). If "Pin to taskbar" or the icon goes missing, check its four window properties (ID, relaunch command, name, icon) first.
  - **Shells started by the Claude desktop app see a virtualized `%LOCALAPPDATA%`.** That matters for testing the exe.
    - What they create there lands in `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Local\`, and they see that copy merged over the real folder.
    - So an exe started from such a shell may use a different `WikiApp` data folder than the one the user's double-click uses.
    - Renaming that folder aside doesn't give a clean profile: it exposes the user's real one instead.
    - To test the exe, back up its `settings.json` and start it with `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`.
- **Ingest test runs call Claude** and cost a few cents each.
  - Try the prompts first with `run.py <job.json> --prepare-only`.
  - A job naming a note that doesn't exist stops before calling Claude. That's a free way to test the run plumbing.
- **Moving the sample wikis** breaks the folder paths saved in `settings.json`. To fix it, close the app, rewrite the `workspace` roots in that file, and raise `__rev` above the browser copy's so the file wins (see `persist.js`).
- **Only one instance runs.** A second launch just focuses the first (the Python host uses `instance.json` in its data folder), so use a separate `WIKIAPP_DATA_DIR` for a debug copy.
- **macOS can't be tested here.** Mac-only code paths (`WikiApp.command`, Dock icon, `open`, process groups) are untested until someone runs them on a Mac.
- **Edit files with the editor tools, not shell scripts.**
  - Heredocs in the shell have eaten backslashes (`\n`, `\r\n`) in code.
  - PowerShell `Get-Content`/`Set-Content` has corrupted non-ASCII characters (`·`, `✎`).
