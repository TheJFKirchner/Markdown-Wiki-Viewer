# WikiApp

A small, customizable, Obsidian-style viewer for folders of Markdown notes. It has a file explorer, a note viewer, and an interactive graph of how notes link together through `[[wikilinks]]`.

What makes it different: you can open **several folders at once**, for example a personal wiki and a team wiki, and see how they connect.

## Run it

| | Windows | Mac |
|---|---|---|
| **Start it** | Double-click **`WikiApp.cmd`** | Double-click **`WikiApp.command`** |
| **You need** | Windows 10 or 11 and [Python](https://www.python.org/downloads/) 3.11 or newer | A recent macOS and [Python](https://www.python.org/downloads/) 3.11 or newer |

**The first start sets everything up by itself.** It creates the app's Python environment in `App Files\.venv` and installs its packages, which takes a minute or two (about 200 MB). After that, it starts in a second or two. The packages are:
- `pywebview` for the window (and `pywin32` on Windows, for the taskbar);
- PyYAML for reading frontmatter;
- **agentlib**, the separate library the AI features (the Ingest view) run on. It is not inside this folder: see [The AI library](#the-ai-library-agentlib) below.

Then the app asks one question: **where to keep its private folder** (see [Your private folder](#your-private-folder-wiki)). The suggested place is this folder. Nothing is written anywhere until you confirm.

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

The app itself is in **`App Files`**. Your notes stay in your own folders, wherever they are; the app only opens them.

### The AI library (agentlib)

The Ingest view's agents run through **agentlib**, a separate library kept in its own folder next to this one (today: `..\General-Purpose-Productivity\agentlib`). It is never copied into the app.

1. **Set agentlib up first, once per computer.** Follow its guide, `agentlib/setup/claude-setup.md`: it says how you sign in (your Claude Code login, a company settings file, or gateway variables) and keeps that in agentlib's own `setup/local.toml`, never in this app. Then check it from the agentlib folder with `python -m agentlib.check` (one tiny message on the cheapest model; `--status` checks without sending anything).
2. **The app finds and installs it.** Each start, `setup.py` looks in the folders next to this one, and one level inside each, for an `agentlib` folder. If it finds exactly one, it installs it into the app's Python "editable", so the library is used where it is.
3. **If it finds none, or more than one,** the app still starts, with the AI features off and a message saying why. Point it at the right folder in **Settings** (the "agentlib library" row); that installs it.

**Settings** also shows how you're signed in (free, sends nothing) and has a **Test connection** button, which sends one tiny request (a fraction of a cent).

The app never calls the Claude Agent SDK, or `claude -p`, itself: everything goes through agentlib.

Getting started:
- Click the add-folder icon at the top of the sidebar (or **Add folder**). Pick a folder of `.md` files (an existing Obsidian vault works) and give it an alias. Add as many folders as you like.
- The app never adds files or folders to a wiki you link (no `Templates` folder, no index). A wiki's own `Templates` folder is used if it has one; otherwise the templates in your private folder are (see [Notes](#notes)).
- The app remembers your folders, their aliases and colors, your signature and settings, the window's size and position, and where you left off (the view, the open page and the note you were writing in).
- Starting it while it's already open brings the open window to the front instead of opening a second one.
- You can also pass folders when starting it: `WikiApp.cmd "C:\notes\team" "C:\notes\personal"`. Each one gets an alias from its folder name.

### Sharing it

**With Git:** commit the folder. `.gitignore` already leaves out what each computer makes for itself (`.venv`, caches, `Share/` and shortcuts), a `Sample Wikis/` folder, so wiki content kept next to the app isn't published with it, and the private `.wiki` folder, so a `git pull` never touches it. The others clone it and start it as above.

On Windows, mark the Mac launcher as runnable once, so Macs can double-click it after cloning:
```bash
git update-index --chmod=+x WikiApp.command
```

**As a zip, app only:** run `python make_share.py` in this folder. It builds `Share\WikiApp` and `Share\WikiApp.zip`:
- **Included:** `App Files`, the two launchers and the docs. On a Mac, the zip opens with `WikiApp.command` already runnable.
- **Left out:**
  - every wiki, including both sample wikis, so none of your notes go with it;
  - your private `.wiki` folder (settings, prompts, progress);
  - the Python environment (`App Files\.venv`) and caches;
  - agentlib (each person keeps their own copy next to the app, set up as above).
- **Afterwards,** it checks that no copied file contains your user name.

Your folders, signature and other settings are in your private `.wiki` folder, which never goes with a copy. Each person picks their own place for it, and their own signature, the first time they open the app.

**For Ingest,** each person also needs agentlib next to the app and set up for their own sign-in (see [The AI library](#the-ai-library-agentlib)).

**Updating from a zip:** if you update by unzipping a newer copy, either **extract it over the top** of your existing folder (your `.wiki` folder there is kept), or keep your `.wiki` folder somewhere else (choose another place on the first start, or move it later in Settings). Unzipping into a fresh folder and deleting the old one deletes a `.wiki` folder kept inside it.

**Sending the zip:** email often blocks script files such as `.cmd`, even inside a zip, so use OneDrive, Teams or a shared drive.

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
  - **Show notes**, **Show scripts** and **Show sessions:** hide or show quick notes, scripts, and the session notes captured in Ingest's Sessions tab (notes whose frontmatter says `type: session`). Hiding session notes leaves their topic pages in the graph.
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

A wiki that has its own `Templates` folder uses it (note templates kept directly in `Templates/`, the older layout, still work). A wiki without one uses the templates in your private folder, `.wiki/templates/` (`Notes/Daily.md`, `Notes/Weekly.md`, `Notes/Sample note.md`, `Pages/Sample page.md`). The app never adds a `Templates` folder to a wiki. The shipped originals are in `App Files/app/templates/`; **Settings** shows where each template is, and **Reset to default** puts an edited one back.

Each template is one Markdown file, named after it. Daily and Weekly are always offered; click the pencil next to one in the + menu to edit it. **New template…** makes another (for example "Meeting"). In templates, `{{date}}`, `{{time}}`, `{{day}}` (Saturday, October 31), `{{week}}`, `{{year}}` and `{{signature}}` are filled in. Templates themselves don't appear in the graph, tags or tasks.

**Where notes open.** An open note opens in the Notes view, from anywhere (the file tree, the graph). A wrapped note opens as a page; **Open in Notes** on its header (or **View as page** in the Notes view) switches between the two.

If a note is changed outside the app while you're typing in it, nothing is overwritten: the status line says so and lets you pick **Keep mine** or **Load latest**.

## Ingest

The Ingest view gets what you write and do into your wikis. It has four tabs, and each tab's work is done by one agent: Claude with its own written instructions.

| Tab | Agent | What it does | What you approve |
|---|---|---|---|
| **Notes** | Executive assistant | Captures your wrapped quick notes into your **personal** wiki, filed under topics, like a session. | Nothing: it's written straight away |
| **Sessions** | Executive assistant | Reads a Claude Code session and writes its session note, topics and tags into your personal wiki. Your to-dos are never touched. | Nothing: it's written straight away |
| **Review** | Wiki reviewer | Rewrites a topic page's summary and its Related section once new records have landed on it, shows conflicts between your notes and sessions, and suggests merging duplicate topics and tags. The tab also suggests folders. | Each folder and merge suggestion, and each conflict. Summaries are written straight away |
| **Promotion** | Team wiki manager | Reads personal pages and queued findings about data, and proposes changes to the team wiki. | Every change |

**Promotion is the only way anything reaches a team wiki.** Notes and sessions only ever go to your personal wiki (a folder whose `WIKI.md` says `type: personal`), and Promotion proposes each change to the team wiki as a card you accept or reject.

Each tab shows how many things are waiting in it. Two buttons at the right of the tab bar belong to all four tabs:
- **?** explains how an agent works, with a diagram, in plain words.
- **✎ Agents and rules** opens the agents' prompts, the page templates and each wiki's rules ([Agents and rules](#agents-and-rules), below).

**Models and cost.** Each agent has one model, kept in your engine settings: Haiku 5.5 for the executive assistant (Notes and Sessions), Sonnet 5.5 for the wiki reviewer (Review) and for the team wiki manager (Promotion, because rewriting shared pages is worth a stronger model). Each tab's **Model** menu shows that agent's model and lists every model your sign-in offers; picking another saves it as the agent's model, and **Settings** shows the same choice. Sessions and Review show what every request cost, and Sessions shows the running total and the average per capture. The figures are API list prices from the app's own table; on a subscription a request isn't billed per token.

### The Notes tab: capture

The Notes tab captures your wrapped quick notes into your personal wiki, exactly as a Claude Code session is captured (see the Sessions tab, next): each note becomes a record in the `Sessions` folder (`origin: note`), filed under one to three topics, with a `[note]` line in each topic's log. The executive assistant keeps everything of substance in a note, numbers included. Nothing is proposed as cards: it's written straight away, and only to the personal wiki.

1. Open **Ingest** on the rail. The Notes tab lists your wrapped notes, each marked new, changed (edited since it was captured) or captured.
2. Tick the notes and press **Capture**. They're captured one after another, and the right side shows what each one added.
3. A captured note gets two lines in its frontmatter: `capture_id` (its permanent id, so a renamed or moved note is never captured twice) and `ingested: <date>`. Nothing else in the note changes.
4. Edit a note later and it shows as changed: capturing it again replaces its earlier record; it never adds a second one.

**Your capture rules.** Your private folder has `prompts/personal-capture-rules.md`, your own free-text rules for what capture should pick out and what gets its own page in your personal wiki ("give every client its own page", "always capture anything about X"). It starts as a short explanation inside comment marks, which are never sent; whatever you write below it goes with every capture and review for the personal wiki. It's yours: the app never changes or resets it. Open it from **Settings**.

**Where each line came from.** Every topic log line is marked `[note]` or `[session]`, and ends `— also touches [[other-topic]]` when the same record was filed under other topics too.

**Notes outrank sessions.** When the wiki reviewer finds a session that contradicts one of your notes (a captured note, or the topic page's own Notes section), the page's Current state follows your note, and a **Conflict** block under it shows both versions. The Review tab lists open conflicts: **Keep note**, **Accept session** (the next review then follows the session; your note file is never edited) or **Dismiss**.

The details are in [sessions/INTEGRATION.md](<App Files/sessions/INTEGRATION.md>).

### The Sessions tab

The **Sessions** tab lists your Claude Code sessions from the last two weeks that aren't in your personal wiki yet. Ingesting one sends it to the executive assistant, which writes a short session note (what was done, what was decided and why, what's still open) and files it under one to three topics.

- **A topic is one piece of work**: a project, an analysis, a question or a tool. Every topic has a page at the top level of the personal wiki, named after it (`<topic>.md`). The page has four parts:
  - **Current state**: a summary of where the work stands. The wiki reviewer writes it, in the Review tab.
  - **Related**: one line per related topic, with why. The wiki reviewer writes it again on each review.
  - **Notes**: yours. Nothing automated changes it.
  - **Log**: one dated line per record (a session or a note), marked `[session]` or `[note]`, linking to it.
- **A tag is a label on a topic** that says what kind of thing it is and what it belongs to, such as `stop-loss`. Tags replace the old `kind` field. A topic has `tags:` in its frontmatter; a tag has no page of its own. Tags come from two lists, both sent with every capture and review:
  - **a reference tag list** (optional, set in **Settings**): any existing tags file, typically your team's, in whatever format it uses. The app only reads it, never writes it.
  - **your personal tags**, `personal-tags.md` in your personal wiki: tags of your own beyond the reference list, one `tag — what it means` line each. It's made the first time capture adds a new tag (the assistant must say what a new tag means in a few words), and a tag merge updates it.
- **Session notes** go in one `Sessions` folder. A note's frontmatter lists its `topics:`, and carries its topics' tags as `tags:`, so they show on the Graph card, in search and as pills like any other tag.
- **Tasks.** The executive assistant records at most five tasks you still have to do after the session. They are written in the note as ordinary tasks, linked to the note's first topic, so they show in the Tasks view. It is also shown the open tasks anywhere in your personal wiki, and a session that finishes or moves one of them on updates it where it is written.

1. Choose your **Personal wiki** folder. The first time, press **Set up**: it adds a `WIKI.md` that marks the folder as personal, an `index.md`, a `promotion-queue.md` and a `Sessions` folder. Topic pages are added at the top of the folder as sessions are ingested. Nothing already there is changed.
2. Press **Ingest** on a session, or **Ingest all** to go through every session listed, one after another. **Stop after this one** ends the run early. **Skip** removes a session from the list without writing anything.
3. The right side shows what each session added: links to the note and its topics, the tags, and any data findings queued. A new topic is marked NEW, and a topic that is now due for a review says so.

- **There's no approval step.** What's captured is written straight away. That's safe because sessions are only ever written to a folder marked as a personal wiki; a team wiki can't be chosen by mistake.
- **A session you continue later** comes back to the list marked CONTINUED. Ingesting it again replaces its note; it never makes a second one.
- **Sessions a script started** through the Agent SDK (this app's own agent runs among them) are never listed. There is no option to include them. Subagents' own transcripts aren't read either.
- **What Claude is sent** is a cut-down transcript: what you and Claude said, and each tool call as one line. Tool output, such as query results, is removed first. Commands are masked too: a number of six or more digits becomes `#`, quoted values inside anything that looks like a SQL query become `'?'`, and a command is cut at 160 characters. The paths of files that were read or edited are kept as they are.
- **Findings about data** (which table to use for what, a known bad period) are added to `promotion-queue.md`. They reach the team wiki only through the Promotion tab, where you accept each change.
- **Capture never rewrites a topic's summary.** It adds the session's line to the topic's log, and the topic waits for the Review tab once it's due.
- **A personal wiki from the first version** (a `tags` folder of tag pages, and `session-notes` by year) is upgraded by itself the first time it's used: the tag pages become topics at the top level, the notes move to `Sessions`.
- Each capture is one request to the executive assistant's model (Haiku by default) through agentlib and takes 20 to 40 seconds.
- **What the tool remembers** (which sessions and notes were captured or skipped, spend, open conflicts) is kept in your private folder (`.wiki/progress/<wiki alias>/`), not in the wiki. A personal wiki from an earlier version had this in a hidden `.sb` folder; it's copied across the first time and the `.sb` folder is left as it was.

The capture tool also runs on its own from the command line, and comes with the skills and the lookup agent that let Claude Code read the wikis: see [sessions/README.md](<App Files/sessions/README.md>).

### The Review tab

The **Review** tab keeps the topic pages of your personal wiki (the one chosen in the Sessions tab) accurate and organised. The wiki reviewer does two jobs there: it rewrites a topic's summary, and it suggests merges.

**Reviews, on the left.** A topic becomes due for a review once three new sessions are filed under it, or when it is flagged. The row says why: a decision was reversed, a session was taken off it, or topics were merged into it.
- The list shows the topics that are due. Tick **Show all topics** to see the rest; any topic can be reviewed at any time.
- **Review** on a topic, or **Review all**, has the reviewer rewrite the page's **Current state** from all of that topic's records (sessions and notes), its **Related** section and its one-line summary. **Stop after this one** ends a Review all early.
- It's written straight away, with nothing to approve. Your own **Notes** section and the dated **Log** on the page are never changed.
- Current state holds no to-dos: its Open list is for questions not yet answered. A review adds tags and keeps the topic's own; it takes one off only when it's clearly wrong, and the result says which and why.
- Where a session contradicts your note, Current state follows the note and a **Conflict** block shows both; settle it in the list of conflicts (see [The Notes tab](#the-notes-tab-capture)).
- Each review is one request to the wiki reviewer's model (Sonnet by default).
- A topic has to be reviewed before it can be promoted (below).

**Organise, on the right.** Each suggestion is a card. **Accept** does it; **Dismiss** drops the suggestion.
- **Folders.** When three or more top-level topics share a tag, the tag can become a folder.
  - Accepting moves those topic pages into `<tag>/` and makes the folder's page `<tag>/<tag>.md`, which lists them.
  - Later topics with that tag are offered as an addition to the folder.
  - A topic lives in one folder at most, and keeps all its tags.
  - These suggestions are worked out from the pages themselves, with no request to Claude.
  - A tag can't become a folder if a folder or a page with that name already exists that the tool didn't make.
- **Merges.** **Suggest merges** asks the reviewer which topics are the same work under two names, and which tags mean the same thing. It's one request to Claude and it changes nothing.
  - Accepting a topic merge moves the merged topics' sessions, tags, tasks and your own notes to the topic that stays. Links across the wiki are repointed and the merged pages are removed. The kept topic is then due for a review.
  - Accepting a tag merge replaces the tag on every topic and session note. If the old tag was a folder, the folder is renamed to match.
- Links go by page name, so moving or merging a page never breaks one.
- The personal wiki's `index.md` lists the topics grouped by folder.

The right side also lists what was reviewed, grouped or merged since the app started.

### The Promotion tab

The **Promotion** tab moves what's durable in your personal wiki into the team wiki, and it's the only way anything gets there. The team wiki manager proposes each change as a card, and nothing is written until you accept it.

1. The left side lists, from your personal wiki (the one chosen in the Sessions tab):
   - the topic pages and folder pages that haven't been promoted yet, and those that changed since they were last promoted (a new session, a review, a merge, or a move into a folder);
   - the **Promotion queue** (`promotion-queue.md`), while it has findings that aren't ticked.

   A topic can only be ticked once it has been reviewed since it last changed. Until then its checkbox is disabled and the row says to review it first, in the Review tab. Tick **Show already promoted** to list promoted pages again, to send one a second time.
2. Tick what to send, pick the **Model** if you want another one (Sonnet 5.5 is the default here), and press **Promote**. A progress box shows what Claude is reading.
3. The team wiki manager proposes changes as cards, one per page, in every open folder except your personal wiki. A proposal for the personal wiki is refused before it becomes a card, so the tab needs your team wiki's folder in the workspace. A card shows the change as red and green lines, any new tags and links, and, for a new page, a preview and the folder it will be saved in.
4. Answer every card, then press **Submit** (or Ctrl+Enter in a feedback box). Nothing is written to the team wiki until then:
   - **✓** writes the change;
   - **✗** drops it;
   - **↻** opens a box for feedback. All the feedback goes to Claude in one message, in the same conversation; the revised cards come back to be answered again, and their cost is added to the run's.
5. When every card is handled, each promoted page gets `promoted:` with the time in its frontmatter and leaves the list until it changes again. The queue's findings that the run saw are ticked (`- [x]`).

If a page changes after Claude proposed a change to it, its card turns grey with **Dismiss** as its only answer. The team wiki manager never creates a page for a table: table pages come from the data dictionary skill, run in Claude Code. A finding about a table that has no page yet goes on its subject area's page, and the card says so.

**Past runs**, below the progress box, lists earlier runs: the model, what it read with approximate tokens per page, each request's tokens and cost, and the totals. The details, including every word Claude is sent, are in [DESIGN.md](<App Files/ingest/DESIGN.md>) and [AGENT.md](<App Files/ingest/AGENT.md>).

**Questions before proposals.** When the team wiki manager can't tell where a point belongs, it asks before it proposes anything: up to five questions, shown as a form above the cards. A question about where something goes lists the candidate pages as buttons. Answer in a few words, pick a button, or tick **Skip** to leave that point out, then press **Continue**. The same run carries on and the cards appear, following your answers. It asks once per run, and only when the answer changes what it would write; when where things go is clear it goes straight to the cards. Your answers stay on the tab as a short record until the run is finished.

### Agents and rules

**✎ Agents and rules**, in the tab bar, shows what the agents are told. It has these tabs:

- **Agents** lists the three agents: name, tab and what each does. **See the prompt** opens an agent's prompt for editing, with **Save** and **Reset to default** (which puts the shipped prompt back in the box; nothing changes until you save).
- **Page templates** lists every wiki's page templates and makes new ones (below).
- **One rules tab per wiki** edits that wiki's rules file (by default `wiki_rules.md` at the folder's top level; **Settings** can point it elsewhere), which says where things go and how to write them. Every agent that works in a wiki is sent that wiki's rules: the team wiki manager for each open wiki, the executive assistant and the wiki reviewer for the personal wiki. A wiki without the file starts from a short starter, and saving creates it.

**Each agent has exactly one prompt file**, in your private folder: `.wiki/prompts/<agent>.md`, where the agent is `executive-assistant`, `wiki-reviewer` or `team-wiki-manager`.
- The first time, each is copied from the default that ships with the app (`App Files/agents/<agent>/SKILL.md`). The other wording the agents get (first messages, feedback and answers messages, the capture and review requests) is in prompt files there too, shipped in `App Files/agents/messages/`.
- **Settings** shows each one's state: **Default** (an unedited copy, which follows a newer default when the app is updated), **Customised** (you've edited it, so updates leave it alone), or **Customised, newer default available**. **Reset to default** puts the shipped text back.
- A prompt can instead point at any existing file, such as a Claude Code skill you already have (**Change** in Settings). If that file starts with frontmatter (the lines between two `---`), keep them when you edit it.
- The app sends an agent its file's text (without any frontmatter), then the material to work on, the wiki rules and the reply format itself. Those added parts aren't in the file, so editing a prompt can't break a run.
- The app never writes to Claude Code's own folders (`~/.claude`). Earlier versions copied the prompts into `~/.claude/skills`; those copies are listed once as leftovers you can delete.

A checkbox in the window also saves each Promotion run's raw requests in its run folder, to check exactly what was sent.

**Page templates** shape the new pages the team wiki manager proposes. Each one is a Markdown file in a wiki's `Templates/Pages` folder (or, for a wiki without a `Templates` folder, in your private folder's `templates/Pages`):
- its file name is the template's name (`Planet.md`, `Gear.md`);
- its frontmatter `description` says when to use it ("A piece of equipment I own. Use for a new page in Gear/.");
- the rest is the page's layout: frontmatter fields and headings, with placeholders like `{{title}}`.

Claude gets only each template's name and description with every run. It opens a template only when it's about to propose a new page that fits, then follows its layout, and the card shows which template it used. The **Page templates** tab lists every template (name, when to use it, a link to the file) and makes new ones. Like the quick-note templates, they're left out of the graph, tags and tasks, and they don't appear in the New note menu. Your private folder starts with `templates/Pages/Sample page.md`, a general page template to copy or edit.

### Setup, once

- Ingest needs agentlib next to the app, set up for your sign-in (see [The AI library](#the-ai-library-agentlib)). Check it with **Test connection** in Settings.
- To reinstall or update the packages, press **Run setup** in the Ingest view, or run `python "App Files/setup.py" --upgrade`.

## Your private folder (.wiki)

Everything the app keeps for you alone is in one folder named `.wiki`. Your wikis are shared (often through git); this folder is private and never goes with them.

- **Where it is.** The first start asks. The suggested place is the app's own folder (the one with `WikiApp.cmd`), where `.gitignore` keeps it out of git, so a `git pull` never touches it. You can choose anywhere else; the app warns if the place is inside one of your wikis. You may pick the `.wiki` folder itself or the folder to put it in.
- **Nothing is written before you choose.** Until then the app creates no file or folder at all.
- **The pointer.** The only thing kept in a fixed place is one line saying where the folder is: `.wikiapp-location` in your user folder.
- **What's in it:** `settings.json` (your folders, signature, colors, the last view), `window.txt`, `engine.json` (the AI engine and each agent's model), `paths.json` (where you pointed things in Settings), `prompts/` (the agents' prompts and your capture rules), `templates/` and `starters/`, `indexes/` (one index of each wiki, rebuilt on each run), `progress/` (what capture has done, per wiki), `ingest/` (Promotion cards waiting for an answer) and `ingest-runs/` (each run's prompts, log and transcript).
- **From an earlier version.** The first time, the app copies what an earlier version kept in `~/.wikiapp` (settings, waiting cards, past runs) and the agents' prompts from `~/.claude/skills` (your edits count as customised). It only copies: nothing is deleted. Then it lists, once, what's left over (the old folder, the old skill copies, each wiki's old `.wiki/index.md`) for you to delete if you like.
- **Moving it later.** In Settings, change the app folder's place: either **move** its contents to a new, empty place, or **adopt** a `.wiki` folder that's already there. The two are never merged.
- **Updating from a zip:** extract over the top, or keep the folder elsewhere (see [Sharing it](#sharing-it)).

## Settings

The gear at the bottom of the rail opens **Settings**: every file and folder the app uses, in one list, grouped (the app folder, app data, prompts, templates, each wiki, and things outside the app such as Claude Code's transcripts and the agentlib library), plus the AI engine.

- Each row shows its path and its state: there, **missing** (a place you set that has gone; the app reports it and never makes it again), **not created yet** (the app makes it the first time it's needed), or **not set** (an optional entry, such as the reference tag list).
- **Open** opens the file (in the app's editor when it's in one of your wikis) or folder. **Change** points the entry somewhere else; **Back to default location** (or **Clear**, for an optional entry) undoes that. Prompts and templates also have **Reset to default**.
- **AI engine:** the engine (Claude, today), each agent's model, how you're signed in, and **Test connection**.

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
make_share.py          Builds a clean copy to share, in Share\ (see Sharing it).
README.md, CLAUDE.md   This file, and notes for Claude Code when working on the app.
TECHNICAL.md           Technical documentation (architecture, dependencies, data, build).
.gitignore, .gitattributes  What Git leaves out (including .wiki/), and the launchers' line endings.
.wiki/                 Your private folder, if you keep it here (never committed or shared).

App Files/             Everything the app is made of.
setup.py             Makes .venv, installs requirements.txt, finds agentlib and installs it (the launchers run it).
requirements.txt     The Python packages: pywebview, pyyaml (agentlib brings the Claude Agent SDK).
.venv/               Made by setup.py on each computer; never shared.
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
  js/capturenotes.js The Ingest view's Notes tab: wrapped notes to capture into the personal wiki.
  js/ingestview.js   The Ingest view's Promotion tab: what to send, the run's progress, the change cards and Submit.
  js/modelmenu.js    The tabs' model menus (each agent's model, kept in the engine settings).
  js/ingestdialogs.js The Agents and rules, How Ingest works and past run windows.
  js/settingsview.js The Settings screen: every path, its state, Open/Change/Reset; the AI engine.
  js/setup.js        The first-run screen: where to keep the private .wiki folder.
  js/ai.js           Whether the AI features can run (agentlib), for every AI button.
  js/sessionsview.js The Ingest view's Sessions tab: sessions to capture, Ingest all, what each one wrote.
  js/reviewview.js   The Ingest view's Review tab: topics due for a review, Review all, folder and merge suggestions.
  js/autocomplete.js [[link]] suggestions and the page picker.
  js/editor.js       The full-note editor (toolbar, Insert menu, saving).
  js/inlineeditor.js Double-click editing of a note's tags or text, in place.
  js/textcommands.js Editing commands every editor shares (formatting, lists, Ctrl+T tasks, shortcuts).
  js/search.js       Search: the query language and ranking.
  js/searchbar.js    The search box and its results.
  js/signature.js    The signature corner.
  js/viewer.js       Notes: title, properties, Markdown body, backlinks.
  js/bridge.js       Messages between the page and the host.
  js/persist.js      Keeps settings in a file as well as in the browser storage (see below).
  lib/               Third-party libraries (see below).
  templates/         The shipped templates (Notes/, Pages/) and starters (starters/) copied into .wiki.
host/                The host (Python, Windows and Mac): wikiapp.py, notefiles.py, ingestruns.py,
                     sessionruns.py; pathlist.py (every path the app uses, in one list) and appfolder.py
                     (the private folder: first run, moving it, older data, agentlib); tests/; the icon.
agents/              The three agents' default prompts (<agent>/SKILL.md),
                     the other wording the agents get (messages/), and agentfiles.py, which reads and saves them.
ingest/              The Promotion run (Python, through agentlib). Start with agent.py (the agent, explained
                     for newcomers) and tools.py (its tools). Also run.py (starts a run), prompts.py,
                     wikis.py (scan, links, index), transcript.py, costs.py, progress.py, models.py (the
                     model menu's list), tests/, and its design docs.
sessions/            Capture (sessions and notes), reviews, conflicts, tags, folders and merges (the Notes,
                     Sessions and Review tabs): the sb.py command line, which also runs without the app.
```

Paths in the rest of this section are inside `App Files`.

The host (`host/wikiapp.py`) opens a window and shows `app/index.html` in it. The page can't read your disk directly. It asks the host through a few small messages: `pickFolder`, `scanVault`, `unwatchFolder`, `editLines`, `appendLines` and `createNote` (edits and new notes, `.md` files only), `readText` (showing a script, read-only), `saveSettings`, `openExternal` for web links, `closeWindow` (the page's answer when you close the window: it saves what you typed first, and asks before losing anything), the private folder and Settings messages (`firstRunState`, `chooseFolder`, `relocateFolder`, `dismissLeftovers`, `listPaths`, `setPath`, `resetPrompt`, `readPathFile`, `writePathFile`, `openPath`, `pickFile`, `getEngineSettings`, `setEngineSettings`, `setAgentModel`, `connectionStatus`, `testConnection`, `agentlibStatus`, `installAgentlib`), and the Ingest messages: for the Promotion tab (`ingestInfo`, `startIngest`, `cancelIngest`, `reviseIngestCards`, `answerIngestQuestions`, `saveIngestState`, `runIngestSetup`, `listIngestRuns`, `openIngestRun`, `listIngestModels`), for the agents' prompts (`agentsInfo`, `saveAgentPrompt`), for the Notes tab (`captureNotes`, `notesStatus`), for the Sessions tab (`sessionsStatus`, `sessionsSetup`, `sessionsList`, `sessionsIngest`, `sessionsSkip`) and for the Review tab (`reviewList`, `reviewTopic`, `suggestFolders`, `applyFolder`, `suggestMerges`, `applyMerge`, `listConflicts`, `resolveConflict`). The host watches every open folder and tells the page which one changed. All of this lives in [host/wikiapp.py](<App Files/host/wikiapp.py>) and [app/js/bridge.js](<App Files/app/js/bridge.js>); TECHNICAL.md lists every message's payload.

**Where your settings are kept:** in your private `.wiki` folder (see [Your private folder](#your-private-folder-wiki)). What the Notes, Sessions and Review tabs write goes into your personal wiki itself; what the Promotion tab writes (once you accept it) goes into the team wiki.

WikiApp used to have a separate Windows-only version, now retired, that kept its data in `%LOCALAPPDATA%\WikiApp\`. If there is no `~/.wikiapp`, the first start copies that data instead, so nothing is lost.

To start fresh, close the app, delete the `.wiki` folder and the `.wikiapp-location` file in your user folder. Your notes are never stored there; they stay in your own folders. To put a prompt back to the shipped one, use **Reset to default** in Settings.

## Customizing

Everything you're likely to change is in `App Files\app`. Edit a file, then press **F5** in the app to reload. You don't need to rebuild anything.

- **Colors and fonts:** the variables at the top of [app/css/styles.css](<App Files/app/css/styles.css>).
- **Default tag colors:** the `PALETTE` list in [app/js/tags.js](<App Files/app/js/tags.js>).
- **Graph look and physics:** [app/js/graph.js](<App Files/app/js/graph.js>). Node size is in `radius()`, forces are in the `d3Force` lines.
- **Developer tools:** press **F12** in the app to inspect the page and see errors.

Changes to the host (`App Files\host\*.py`) take effect the next time the app starts. To change the icon, edit and run `host\make-icon.ps1`, or replace `host\app.ico` with your own file, then restart the app.

## Third-party components

- [force-graph](https://github.com/vasturiano/force-graph) 1.52.0, MIT license: graph rendering and physics.
- [markdown-it](https://github.com/markdown-it/markdown-it) 15.0.2, MIT license: Markdown rendering.
- [js-yaml](https://github.com/nodeca/js-yaml) 4.3.2, MIT license: reading frontmatter.