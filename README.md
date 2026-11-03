# WikiApp

A small, customizable, Obsidian-style viewer for folders of Markdown notes. It has a file explorer, a note viewer, and an interactive graph of how notes link together through `[[wikilinks]]`.

What makes it different: you can open **several folders at once**, for example a personal wiki and a team wiki, and see how they connect.

## Run it

| | Windows | Mac |
|---|---|---|
| **Start it** | Double-click **`WikiApp.cmd`** | Double-click **`WikiApp.command`** |
| **You need** | Windows 10 or 11 and [Python](https://www.python.org/downloads/) 3.10 or newer | A recent macOS and [Python](https://www.python.org/downloads/) 3.10 or newer |

**The first start sets everything up by itself.** It creates the app's Python environment in `App Files\.venv` and installs its packages, which takes a minute or two (about 200 MB). After that, it starts in a second or two. The packages are:
- `pywebview` for the window (and `pywin32` on Windows, for the taskbar);
- the Claude Agent SDK and PyYAML for Ingest.

**Pin it to the taskbar (Windows):** once it's open, right-click its taskbar button and choose **Pin to taskbar**.
- The pinned button has the WikiApp icon and starts the app directly, with no console flash.
- If an update changed the app's packages, the pinned button runs the setup first.
- On a Mac, the Dock shows the app as Python. To keep it handy, drag `WikiApp.command` to the right-hand end of the Dock.

**Python on Windows:** when installing it, tick **Add python.exe to PATH**. The Microsoft Store version also works. Macs don't come with a recent enough Python, so install it from python.org first.

**On a Mac, the first time:**
- If double-clicking `WikiApp.command` says it can't be opened, open Terminal in this folder and run this once:
  ```bash
  chmod +x WikiApp.command
  ```
- If macOS says it's from an unidentified developer, right-click it and choose **Open**.

**Windows only, with no Python at all:** `App Files\WikiApp.exe` is the older Windows host and still works.
- It keeps its own settings, separate from the Python version's.
- It needs the Python environment only for Ingest.
- The first time someone runs a downloaded copy of the exe, Windows SmartScreen may say "Windows protected your PC", because the exe isn't code-signed. Click **More info → Run anyway**.

The app itself is in **`App Files`**. Your notes stay in your own folders, wherever they are; the app only opens them.

Getting started:
- Click the add-folder icon at the top of the sidebar (or **Add folder**). Pick a folder of `.md` files (an existing Obsidian vault works) and give it an alias. Add as many folders as you like.
- A folder with no `Templates` folder gets one, with a sample note template and a sample page template (see [Notes](#notes) and [Ingest](#ingest)).
- The app remembers your folders, their aliases and colors, your signature and settings, the window's size and position, and where you left off (the view, the open page and the note you were writing in).
- Starting it while it's already open brings the open window to the front instead of opening a second one.
- You can also pass folders when starting it: `WikiApp.cmd "C:\notes\team" "C:\notes\personal"`. Each one gets an alias from its folder name.

### Sharing it

**With Git:** commit the folder. `.gitignore` already leaves out what each computer makes for itself (`.venv`, caches, `Share/` and shortcuts) and a `Sample Wikis/` folder, so wiki content kept next to the app isn't published with it. The others clone it and start it as above.

On Windows, mark the Mac launcher as runnable once, so Macs can double-click it after cloning:
```bash
git update-index --chmod=+x WikiApp.command
```

**As a zip, app only:** run `python make_share.py` in this folder. It builds `Share\WikiApp` and `Share\WikiApp.zip`:
- **Included:** `App Files`, the two launchers and the docs. On a Mac, the zip opens with `WikiApp.command` already runnable.
- **Left out:**
  - every wiki, including both sample wikis, so none of your notes go with it;
  - the `WikiApp` shortcut, which only works on this computer;
  - the Python environment (`App Files\.venv`) and caches.
- **Afterwards,** it checks that no copied file contains your user name.

Your folders, signature and other settings are stored in your user folder (`~/.wikiapp`), not in this folder, so they never go with a copy. Each person picks their own signature the first time they open the app.

**For Ingest,** each person also needs Claude Code signed in on their computer.

**Sending the zip:** email often blocks `.exe` files, even inside a zip, so use OneDrive, Teams or a shared drive. On a work computer, IT may also block programs that aren't code-signed.

## Features

- **View rail:** the strip of icons on the far left switches between **Graph**, **Page** (the note you have open), **Notes**, **Tasks** and **Ingest**. Ctrl+1 to Ctrl+5 do the same. The badges count open notes, unfinished tasks, and notes waiting to be ingested (or changes waiting for review). The button at the top of the rail (or `Ctrl+\`) hides or shows the sidebar.
- **File explorer:** folders first, collapsible, highlights the open note. Non-Markdown files are listed but dimmed, except scripts (below). The double-arrow button next to **Add folder** collapses one level of subfolders per press, deepest first; the workspace folders themselves stay open.
- **Scripts:** `.sql`, `.py` and other script files (`.ipynb`, `.r`, `.js`, `.ts`, `.ps1`, `.sh`, `.bat`, `.cmd`, `.vbs`, `.rb`, `.pl`, `.lua`, `.kql`, `.dax`) can be linked from notes by file name with the extension, like `[[load_orders.sql]]` or `[[etl/clean.py]]`. They appear in the graph as stars (**Show scripts** on the Graph card hides them), and clicking one shows its code and the notes that link to it. Links only go one way: scripts are never read for links of their own.
- **Graph view:** every note is a node, and every `[[link]]` is a line between two nodes.
  - Links to notes that don't exist yet appear as faint "ghost" nodes.
  - Hover a node to highlight it and its neighbors. Click a node to open it. Drag to move nodes, scroll to zoom.
  - Labels fade in as you zoom.
- **Note view:** rendered Markdown with clickable wikilinks, including `[[Note|alias]]` and `[[Note#Heading]]`, plus a list of linked mentions (backlinks).
- **Properties:** a note's YAML frontmatter appears under its title, one row per key (details below).
- **Graph card:** a settings card in the corner of the graph view.
  - **Color nodes by:** Folder, Tag, or None.
  - **Folders:** click a folder to hide or show it in the graph. Click its dot to change its color.
  - **Link duplicate names:** turns the dashed lines between same-named notes on or off (see below).
  - **Tags:** every tag with how many notes use it. Click tags to show only notes with any of them. Click a tag's dot to change its color.
  - Clicking a tag pill in a note jumps to the graph filtered by that tag.
  - Hovering a node shows its `description`.
- **Notes:** quick daily, weekly or meeting notes from templates, with a section per meeting or topic and a **Wrap note** button (details below).
- **Tasks:** every task from every open folder in one list (details below).
- **Editing:** double-click a note's tags or text to edit them in place, or open the full editor. Text editing has a formatting toolbar and `[[` autocomplete.
- **Search:** Ctrl+F searches words, tags, folders, properties and tasks.
- **Signature:** the corner at the bottom left holds your signature, a short alias like `alex`. It signs every task and note you add as `~alex`. The first time you open the app, it asks you for one.
- **Live updates:** add, edit, rename or delete files in another editor and the app updates on its own.

## Notes

Notes are for jotting things down before they belong anywhere in the wiki: a daily note, a weekly note, notes from a meeting. They're ordinary Markdown files in a notes folder, so they also show up in the file tree, search and the graph (as small squares; **Show notes** on the Graph card hides them).

**Where they're saved.** The **New notes are saved in** box on the Notes start page picks the workspace folder and the folder inside it (`personal` / `Notes` unless you change it), and shows the full path on disk. The folder is created with the first note. Notes are the files in that folder, in any of your workspace folders, so changing it changes what the Notes list shows; the files themselves stay where they are.

**Starting one.** Press **+** in the **Notes** section at the top of the sidebar, or pick a template on the Notes start page (the rail's Notes button, or Ctrl+3, always goes there; it also lists your open notes).
- The note is created as `Notes/2026-10-31 Daily.md` from its template, with the start date filled in:

  ```markdown
  ---
  type: daily
  started: 2026-10-31
  status: open
  tags: [daily-note]
  ---
  # Daily · Saturday, October 31

  ## Focus
  - 
  ```
- Each press makes a new note, so several daily or weekly notes can be open at once. A second one on the same day is named `2026-10-31 Daily 2.md`.

**Writing.** You type straight into the formatted note, like a word processor, and there's no Save button (it saves as you type). The Markdown is written for you.
- **Every line is editable as it looks.** Click anywhere and type.
  - Headings, bullets and numbers are drawn for you.
  - **Bold** stays bold, and links stay links.
  - Ctrl+B, Ctrl+I, Ctrl+Shift+X (strikethrough), Ctrl+` (code) and the toolbar format the selection.
- **Moving around:**
  - **Enter** starts the next line: the next bullet or number in a list.
  - **Enter** on an empty bullet ends the list; on a nested one, it moves the bullet out a level.
  - **Tab** / **Shift+Tab** nest and un-nest bullets and numbers. Numbered lists renumber themselves.
  - **Backspace** at the start of a line turns a bullet, number, quote or heading into plain text; at the start of plain text, it joins the line to the one above. **Delete** at the end joins the next line.
  - The arrow keys move between lines.
- **Shortcuts at the start of an empty line:** `- ` makes a bullet, `1. ` a numbered item, `# ` to `### ` a heading, `> ` a quote, and `[ ] ` a task.
- **Links:** typing `[[` opens a page picker under the caret. Pick a page and it goes in as a link. Backspace removes a whole link at once.
- **Write…** at the end of each section adds new text. After a list, a new line is a paragraph unless you start it with `- `.
- **Pasting** pastes plain text. Pasted Markdown (several lines, bullets, `**bold**`) shows formatted.
- **Code blocks** are still edited as Markdown, since that suits code. Click one to edit it; the toolbar's code block button adds one.
- **Lines kept as written:** a rare line whose Markdown the editor can't reproduce exactly (backslash escapes, for example) shows as its Markdown in a grey monospace font, so nothing is ever changed behind your back.
- **Tasks are edited as they look.** Click a task's circle to mark it complete (it gets a `done:` date), or click again to reopen it. Click anywhere else on a task to edit it in place:
  - the text is a plain text box (`[[` still suggests pages);
  - the circle steps through Incomplete → In progress → Complete;
  - **due** is a date picker, and × removes the date;
  - each dated note under the task is its own box, and × removes it;
  - **+ Add a note** adds one, dated now and signed with your signature.

  The app writes the Markdown for you.

  Keys while editing a task:
  - **Enter** in the task's text adds the next task below it; in a note, it adds the next note.
  - **Backspace** in an empty note removes it.
  - **Esc**, or clicking elsewhere, finishes. Notes and new tasks left empty are dropped.

  **Delete** removes the task and its notes, after asking. **Markdown** opens that list as plain Markdown for anything else, like reordering.
- **New tasks:**
  - **Ctrl+T** adds a task below the line you're on, signed and ready to type into the same way.
  - The **+ Task** button under the last line adds one at the end.
  - **Ctrl+Shift+9** turns the current line into a task.
- **Tables:** a table (the toolbar's table button, or Insert → Table) is a grid you type in directly. **+ Row**, **+ Column**, **− Row** and **− Column** appear under it and act on the cell you're in. Enter moves down a row, and adds one at the bottom.
- The full editor's formatting toolbar (bold, lists, links, table, Insert menu...) stays at the top while you can type; it works on the box you were last typing in. Wrapped notes don't show it.
- Each `## ` section is its own part. Type a name in **New section** at the bottom and press Enter to add `## 11:00 · Standup` with the current time. **Ctrl+Enter** jumps there from any box.
- **Ctrl+T while editing Markdown** (a code block, a list opened with a task's **Markdown** button, or the full editor's Markdown mode) adds a full task as text: `- [ ] New task due:<a week from today> ~you` with a timestamped subnote under it. "New task" is selected so you can type over it; **Tab** jumps to the due date, then the note, and Shift+Tab goes back.
- Tasks you write in a note appear in **Tasks** like any other.
- **On pages,** a line break in a note shows as a line break, the same as in the editor.
- **Limits:**
  - A selection can't span several lines.
  - Ctrl+Z undoes typing within a line, but not Enter or Backspace that joined or split lines.

**Wrapping up.** **Wrap note** adds `ended:` with today's date and sets `status: wrapped`. The note moves to the collapsed **Wrapped** list and turns read-only; **Reopen** undoes it.

**Templates** live in each folder's `Templates` folder, which has two parts:
- `Templates/Notes/`: templates for quick notes (this section);
- `Templates/Pages/`: templates for the pages Ingest creates (see Ingest).

When you link a folder that has no `Templates` folder, the app adds one with a sample of each: `Notes/Sample note.md` and `Pages/Sample page.md` (the app's own copies are in `App Files/app/templates/`). A folder that already has a `Templates` folder is left as it is, and note templates kept directly in `Templates/` (the older layout) still work.

Each template is one Markdown file, named after it. Daily and Weekly are built in; click the pencil next to one in the + menu to save it to `Templates/Notes` and edit it. **New template…** makes another (for example "Meeting"). In templates, `{{date}}`, `{{time}}`, `{{day}}` (Saturday, October 31), `{{week}}`, `{{year}}` and `{{signature}}` are filled in. Templates themselves don't appear in the graph, tags or tasks.

**Where notes open.** An open note opens in the Notes view, from anywhere (the file tree, the graph). A wrapped note opens as a page; **Open in Notes** on its header (or **View as page** in the Notes view) switches between the two.

If a note is changed outside the app while you're typing in it, nothing is overwritten: the status line says so and lets you pick **Keep mine** or **Load latest**.

## Ingest

Ingest gets what's in your wrapped notes into the wiki pages. Claude (Haiku 5.5 by default, chosen for cost) reads the notes, finds the pages they belong on, and proposes changes. It's told to be conservative: points with no clear home are left out rather than forced onto a page, and new pages are rare. Nothing is written until you accept a change.

1. Open **Ingest** on the rail. It lists every wrapped note that hasn't been ingested yet.
2. Tick the notes to send (notes written together are often related), pick the **Model** if you want another one, and press **Ingest**. A progress box shows what Claude is reading.
   - The model list comes from your Claude Code sign-in, so it shows the exact models you can use. Haiku 5.5 is the default and the cheapest; larger models cost more per run. Your choice is remembered.
3. Each proposed change arrives on the right as a card, one per page, in that wiki's color. A card shows the change as red and green lines, any new tags and links (a link to a page that doesn't exist yet is red), and, for a new page, a preview and the folder it will be saved in.
4. Answer every card. Nothing happens yet, and you can change an answer (press it again to clear it):
   - **✓** writes the change;
   - **✗** drops it;
   - **↻** opens a box for feedback to Claude: what should change on this card.
5. When every card has an answer, press **Submit** at the bottom right (or Ctrl+Enter in a feedback box).
   - The ✓ changes are written and the ✗ ones dropped.
   - All the feedback goes to Claude in one message, with which cards you accepted and rejected. Claude revises those cards in the same conversation, so it still knows what it read, or it says why it won't. The revised cards come back to be answered again.
   - Feedback is part of the same run: its cost is added to that run's.
   - A new run can't start until every card is handled.
6. When the last card is handled, the notes get `ingested: <date>` in their frontmatter and leave the list.

If a page changes after Claude proposed a change to it, its card turns grey with **Dismiss** as its only answer, and that card's notes stay in the list so they can be run again. After each run you see what its tokens would cost at Claude API prices, next to an estimate for the same work in a plain Claude Code session (which sends about 35k more tokens with every request). On a Claude subscription a run isn't billed per token: it counts toward your plan's usage, so the figure is for comparing runs and models.

**Past runs**, below the progress box, lists earlier runs. Click one to see:
- the model that ran;
- what it read, with approximate tokens per page;
- each request's tokens and cost;
- the totals.

- **?** explains how the agent works, with a diagram, in plain words.
- **Edit ingestion prompt** shows everything Claude is told, one tab each:
  - **Agent prompt**: the built-in instructions, read-only (they come with the app and update with it);
  - **Your notes**, which you add to them;
  - **Page templates** (below);
  - each wiki's **rules** (`wiki_rules.md` at the folder's top level: where things go and how to write them).

**Page templates** shape the new pages Claude proposes. Each one is a Markdown file in a wiki's `Templates/Pages` folder:
- its file name is the template's name (`Planet.md`, `Gear.md`);
- its frontmatter `description` says when to use it ("A piece of equipment I own. Use for a new page in Gear/.");
- the rest is the page's layout: frontmatter fields and headings, with placeholders like `{{title}}`.

Claude gets only each template's name and description with every run. It opens a template only when it's about to propose a new page that fits, then follows its layout, and the card shows which template it used. The **Page templates** tab lists every template (name, when to use it, a link to the file) and makes new ones. Like the quick-note templates, they're left out of the graph, tags and tasks, and they don't appear in the New note menu. A newly linked folder starts with `Templates/Pages/Sample page.md`, a general page template to copy or edit.

**Setup, once:**
- Ingest needs Claude Code signed in on this computer. It uses that sign-in; there's no API key.
- The app's own setup installs the Claude Agent SDK into `App Files/.venv` (see Run it). To reinstall or update the packages, press **Run setup** in the Ingest view, or run `python "App Files/setup.py" --upgrade`.

The details, including every word Claude is sent, are in [DESIGN.md](<App Files/ingest/DESIGN.md>) and [AGENT.md](<App Files/ingest/AGENT.md>).

## Tasks

Tasks are ordinary Markdown checkboxes, so they can live in any note and still work in other editors:

```markdown
- [ ] Email Sam about the budget due:2026-11-02 [[Budget 2027]] ~alex
- [/] Book the dark-sky site due:2026-11-03 ~maria
  - 2026-10-29 16:20 ~maria: The ranger office only answers on weekdays
  - 2026-10-30 09:05 ~alex: Hitting a roadblock: the online form is down
- [x] Pick a date done:2026-10-20 ~maria
```

| Part | Meaning |
|---|---|
| `[ ]` `[/]` `[x]` | Incomplete, in progress, complete |
| `due:YYYY-MM-DD` | Due date (optional) |
| `done:YYYY-MM-DD` | Added automatically when the task is completed |
| `~alex` | Who wrote it: your signature |
| Indented `- date time ~alex: text` lines | Subnotes: progress, roadblocks, updates |

The **Tasks** view has filters for Open, In progress, Complete or All, and a search box. **Group by** switches between:
- **Page:** tasks from the same note together, in the order they appear on the page. Each header shows the folder, the page and its counts.
- **Due date:** Overdue, Today, Next 7 days, Later, No due date, Complete.

On each task you can:
- change its status from the **status dropdown** (Incomplete / In progress / Complete),
- set, change or clear the **due date**,
- open **notes** to read the subnotes and add one (signed and timestamped),
- click the file name (in due-date grouping) to open the note the task lives in.

**All tasks for a page.** A task belongs to a page if it's written on that page, or if it links to it with `[[Page]]`. There are two ways to see all of a page's tasks, completed ones included:
- the **All tasks** button on a page header,
- **Show in Tasks** in the Tasks box at the bottom of every note that has tasks.

Tasks from other pages that link in are labeled "links to …". Click × on the "Tasks for …" chip to go back to every task.

**Link autocomplete.** Type `[[` in a task or subnote box and matching note names appear.
- Use the arrow keys, then Enter or Tab (or click) to insert one.
- `[[team:` limits the suggestions to one folder.
- The app writes `[[Name]]`, or `[[alias:Name]]` when a plain link would open a different note.

**New task** adds the task to the page you pick in **Add to page** (search by name; `team / ` limits it to one folder):
- If the page has a `Tasks` heading (any level), the task goes at the end of that section.
- If it doesn't, a `## Tasks` section is added at the end of the page.
- Each folder also offers a **Tasks** page, which is created the first time you use it.

The **+ Task** button on any note opens the form aimed at that note.

The app writes only to `.md` files inside your open folders. Before changing a line, it checks that the line still says what the app expects. If you edited the note somewhere else in the meantime, it refuses, reloads, and asks you to try again; it never overwrites your edit.

## Editing notes

### Double-click to edit tags or text

Two parts of a note can be edited right on the page:

- **Tags:** double-click the tags (or click **+ Add tags** on a note without any). They become chips:
  - Click × to remove a tag; Backspace in the empty box removes the last one.
  - Type to add one; Enter, a comma or a space adds it. Tags you already use elsewhere are suggested underneath.
  - Click away, press Enter in the empty box, or click ✓ to save. Esc cancels.
  - The tags are saved as `tags: [a, b]` in the note's properties, which are created if the note has none. Other properties are left alone.
- **Text:** double-click the title or anywhere in the text. Everything below the properties, title included, becomes one edit box in its place.
  - The word you double-clicked starts out selected.
  - The small toolbar has bold, italic, strikethrough, code, link (with `[[` suggestions), bulleted list, task and numbered list. The full editor's shortcuts and list behavior work too.
  - Click away, press **Ctrl+Enter** or click ✓ to save. **Esc** cancels, asking first if you changed anything.

A single click on a tag still shows that tag in the graph.

Only the tags line or the text is written back. If the note was changed somewhere else while you were editing, the app won't overwrite it; press Esc to see the latest version.

### The full editor

Click **✎ Edit** on any note (or press **Ctrl+E**) to edit the whole note. It works like the Notes view: you type straight into the formatted note, tasks open their form, and tables have row and column buttons. The **Normal text / Heading** menu sets the current line's style. The note's properties (YAML) are in the **Properties** box at the top. **Markdown** switches to the whole file as plain text (and **Formatted** switches back). **Save** (Ctrl+S) writes it back; **Cancel** (Esc) closes the editor, asking first if you have unsaved changes.

| Toolbar | Shortcut |
|---|---|
| Text style: normal, heading 1–4 | |
| Bold, italic, strikethrough, inline code | Ctrl+B, Ctrl+I, Ctrl+Shift+X, Ctrl+` |
| Bulleted, numbered and task lists, quote | Ctrl+Shift+8, Ctrl+Shift+7, Ctrl+Shift+9 |
| Link to a page (opens `[[` suggestions) | Ctrl+K |
| Full task with due date and a note (Tab moves through its parts) | Ctrl+T |
| Code block, table, divider line | |
| Outdent / indent | Shift+Tab / Tab |

- **Lists:** Enter in a list starts the next item, numbered lists keep counting, and Enter on an empty item ends the list.
- **Links:** typing `[[` suggests page names, the same as in task boxes.
- **Insert menu:** today's date, date and time, a signed note stamp, a task with a due date, a task with a note (Ctrl+T), a Tasks section, properties (frontmatter), and templates for meeting notes, a decision record, a table and a note callout.
- **Undo:** Ctrl+Z and Ctrl+Y work for typing and toolbar changes in the box you're editing (and everywhere in Markdown mode). Clicks on task circles and table buttons can't be undone; Cancel drops everything since the last save.

**If the file changes on disk while you're editing**, Save doesn't overwrite it. It says so and keeps your text. Pressing Save again replaces the version on disk with yours.

## Search

The search box in the top bar (**Ctrl+F**) searches every open folder as you type. With the box empty it shows these tips and your tags; click any of them to try it.

| Type | Finds |
|---|---|
| `jupiter moons` | Notes containing all the words (in the name, text, tags or property values) |
| `"red spot"` | An exact phrase |
| `-saturn` | Leaves out notes with the word |
| `#planet` or `tag:planet` | Notes with the tag (`#planet` also matches `#planet/giant`) |
| `folder:personal` (or `in:`) | One workspace folder |
| `path:Moons` | Notes whose path contains the text |
| `owner:maria`, `status:active` | Any frontmatter property |
| `links:Jupiter` (or `links:team:Jupiter`) | Notes that link to a page |
| `task:open` / `task:progress` / `task:done` / `is:task` | Tasks instead of pages |
| `due:overdue` / `due:today` / `due:week` / `due:2026-11-03` | Tasks by due date |
| `by:alex` or `~alex` | Tasks (and their subnotes) signed by someone |

Combine them, for example `#planet moon -saturn` or `task:open folder:team due:week`.

**Results.** Pages come first, with names matching your words ranked highest. Each shows its folder, tags and a highlighted snippet. Matching tasks are listed below the pages.

Use the arrow keys and Enter, or click, to open a result. A page opens with your words highlighted and scrolled into view; a task opens its page with the task flashing.

## Multiple folders

Each open folder has an **alias**, a short name you choose such as `team` or `personal`. It also has a color. Every note is identified by its alias plus its path, like `team:Planets/Jupiter.md`, so notes from different folders never get mixed up.

**Adding a folder.** The Add folder window scans the folder before anything is added. It lists every note whose name is also used in an open folder:

```
Jupiter (personal)  ↔  Jupiter (team)
Saturn (personal)   ↔  Saturn (team)
```

**Duplicates.** Same-named notes from different folders are labeled with their alias, like "Jupiter (team)". In the graph, a dashed line joins them, so you can see where a personal note and a team note cover the same thing.

**Links between folders.**

| You write | It opens |
|---|---|
| `[[Jupiter]]` | `Jupiter` in the same folder if there is one, otherwise the first match in the other folders (in the order they're listed) |
| `[[team:Jupiter]]` | `Jupiter` in the folder with alias `team`, and only there |
| `[[team:Jupiter#Moons\|the moons]]` | Same, at a heading, with custom link text |

Windows doesn't allow `:` in file names, so `alias:` can never be confused with part of a note's name.

**Changing a folder.** Click the gear next to a folder in the sidebar to change its alias or color, or to remove it from the workspace. Removing doesn't touch the files. Renaming an alias doesn't update `[[old-alias:Note]]` links written in notes.

## Frontmatter

Put YAML between `---` lines at the very top of a note:

```yaml
---
tags: [planet, rocky]
description: Our home, and the only planet known to have life.
order: 3
has_rings: false
aliases: [Terra, The Blue Marble]
orbits: "[[The Sun]]"
---
```

Each key becomes its own row:

| Value | Displayed as |
|---|---|
| `tags` (or `tag`) | Colored pills. Accepts `[a, b]`, a YAML list, or `a, b`. A leading `#` is optional, and tags are case-insensitive. |
| Text | Text with inline Markdown, so `[[links]]` are clickable. Multi-line text keeps its line breaks. |
| Number | The number |
| `true` / `false` | A checkbox |
| Lists | Chips |
| Dates (`2026-10-30`) | Text with a calendar icon |
| `description` | Text in italics, also shown when hovering the note's node in the graph |

Nested tags work for filtering: selecting `#planet` also matches `#planet/giant`. If the YAML can't be read, the note shows the error in place of its properties.

## How it's built

The full technical documentation is in [TECHNICAL.md](TECHNICAL.md). It covers the architecture, every module and dependency, what the app reads, writes and sends, and how to build and debug it.

```
WikiApp.cmd            Starts the app on Windows (sets it up the first time).
WikiApp.command        Starts the app on a Mac (sets it up the first time).
WikiApp.lnk            Shortcut to App Files\WikiApp.exe, if you made one (this computer only, not shared).
make_share.py          Builds a clean copy to share, in Share\ (see Sharing it).
README.md, CLAUDE.md   This file, and notes for Claude Code when working on the app.
TECHNICAL.md           Technical documentation (architecture, dependencies, data, build).
.gitignore, .gitattributes  What Git leaves out, and the launchers' line endings.

App Files/             Everything the app is made of.
setup.py             Makes .venv and installs requirements.txt (the launchers run it).
requirements.txt     The Python packages: pywebview, claude-agent-sdk, pyyaml.
.venv/               Made by setup.py on each computer; never shared.
WikiApp.exe          The older Windows-only host (C#). Hosts the app using WebView2.
bin/                 Microsoft's WebView2 connector DLLs, used by WikiApp.exe.
app/                 The app itself: plain HTML/CSS/JS, no build step.
  index.html
  css/styles.css     Theme: all colors (including the graph's) are variables at the top.
  js/main.js         Wiring: workspace folders -> scans -> explorer, graph, viewer; the view rail.
  js/workspace.js    The open folders, their aliases and colors (saved between runs).
  js/vault.js        Combines folders; frontmatter and tags; duplicates; resolving [[links]]; graph data.
  js/folderdialog.js The Add / Edit folder window and its duplicate check.
  js/explorer.js     The file tree, one section per folder.
  js/graph.js        The graph view (physics, sizes, hover, coloring and filtering).
  js/graphpanel.js   The Graph card: color mode, folders, duplicate links, tags.
  js/tags.js         Tag colors (palette and remembered choices).
  js/tasks.js        Task format: reading tasks and subnotes, building edited lines.
  js/taskspane.js    The Tasks view.
  js/notes.js        Notes: templates, filling them in, splitting a note into sections, wrapping.
  js/notespanel.js   The Notes section of the sidebar and its + menu.
  js/notesview.js    The Notes view: writing in a note, saving as you type, where notes are saved.
  js/livetext.js     Notes edited as they look: a row per line, the task form, table grids, code blocks.
  js/richtext.js     The rows' line kinds, and their formatted text back to Markdown.
  js/ingestview.js   The Ingest view: notes to ingest, the model menu, the run's progress, the change cards and Submit.
  js/ingestdialogs.js The Edit ingestion prompt and How Ingest works windows.
  js/autocomplete.js [[link]] suggestions and the page picker.
  js/editor.js       The full-note editor (toolbar, Insert menu, saving).
  js/inlineeditor.js Double-click editing of a note's tags or text, in place.
  js/textcommands.js Editing commands every editor shares (formatting, lists, Ctrl+T tasks, shortcuts).
  js/search.js       Search: the query language and ranking.
  js/searchbar.js    The search box and its results.
  js/signature.js    The signature corner.
  js/viewer.js       Notes: title, properties, Markdown body, backlinks.
  js/bridge.js       Messages between the page and the host (either one).
  js/persist.js      Keeps settings in a file as well as in the browser storage (see below).
  lib/               Third-party libraries (see below).
  templates/         The sample note and page templates a newly linked folder starts with.
host/                The hosts: wikiapp.py, notefiles.py, ingestruns.py (Python, Windows and Mac),
                     and WikiApp.cs with its build script (the older Windows-only exe); the icon.
ingest/              The ingest agent (Python, Claude Agent SDK). Start with agent.py (the agent, explained
                     for newcomers) and tools.py (its two tools). Also run.py (starts a run), prompts.py,
                     wikis.py (scan, links, index), transcript.py, costs.py, progress.py, models.py
                     (the model menu's list), the shipped agent-prompt.md, and its design docs.
```

Paths in the rest of this section are inside `App Files`.

The host (`host/wikiapp.py`, or `WikiApp.exe` on Windows) opens a window and shows `app/index.html` in it. The page can't read your disk directly. It asks the host through a few small messages: `pickFolder`, `scanVault`, `unwatchFolder`, `editLines`, `appendLines` and `createNote` (edits and new notes, `.md` files only), `readText` (showing a script, read-only), `saveSettings`, `openExternal` for web links, `closeWindow` (the page's answer when you close the window: it saves what you typed first, and asks before losing anything), and the Ingest messages (`ingestInfo`, `startIngest`, `cancelIngest`, `reviseIngestCards`, `saveIngestState`, `saveIngestNotes`, `runIngestSetup`, `listIngestRuns`, `openIngestRun`, `listIngestModels`). The host watches every open folder and tells the page which one changed. All of this lives in [host/wikiapp.py](<App Files/host/wikiapp.py>) (or [host/WikiApp.cs](<App Files/host/WikiApp.cs>)) and [app/js/bridge.js](<App Files/app/js/bridge.js>).

**Where your settings are kept.** Everything the app remembers is saved in `.wikiapp` in your user folder (`C:\Users\<you>\.wikiapp` on Windows, `/Users/<you>/.wikiapp` on a Mac):
- `settings.json`: folders, signature, colors, the last view, and so on.
- `window.txt`: the window's size and position.
- `ingest/`: Ingest cards waiting for review (`pending.json`) and your notes for the agent (`user-notes.md`).
- `ingest-runs/`: each run's prompts, log and transcript.

The first time the Python version starts on a PC that used `WikiApp.exe`, it copies the exe's settings over. The exe itself keeps its own copy in `%LOCALAPPDATA%\WikiApp\`, with its runs in `%TEMP%\WikiApp\ingest-runs\`.

To start fresh, close the app and delete that folder. Your notes are never stored there; they stay in your own folders.

## Customizing

Everything you're likely to change is in `App Files\app`. Edit a file, then press **F5** in the app to reload. You don't need to rebuild anything.

- **Colors and fonts:** the variables at the top of [app/css/styles.css](<App Files/app/css/styles.css>).
- **Default tag colors:** the `PALETTE` list in [app/js/tags.js](<App Files/app/js/tags.js>).
- **Graph look and physics:** [app/js/graph.js](<App Files/app/js/graph.js>). Node size is in `radius()`, forces are in the `d3Force` lines.
- **Developer tools:** press **F12** in the app to inspect the page and see errors.

Only changes to the C# host (`App Files\host\WikiApp.cs`) need a rebuild. Run `App Files\host\build.cmd`, which uses the C# compiler that comes with Windows. To change the icon, edit and run `host\make-icon.ps1`, or replace `host\app.ico` with your own file. Then run `host\build.cmd`.

## Third-party components

- [force-graph](https://github.com/vasturiano/force-graph) 1.52.0, MIT license: graph rendering and physics.
- [markdown-it](https://github.com/markdown-it/markdown-it) 15.0.2, MIT license: Markdown rendering.
- [js-yaml](https://github.com/nodeca/js-yaml) 4.3.2, MIT license: reading frontmatter.
- [Microsoft WebView2 SDK](https://www.nuget.org/packages/Microsoft.Web.WebView2) 1.0.4314.35, license in `bin/WebView2-LICENSE.txt`: the browser engine connection.
