// Wires the pieces together: workspace folders -> scans -> one combined model ->
// file tree, graph and notes.

import { call, on, isHosted, setBeforeReload } from './bridge.js';
import { buildVault, graphData, noteLabel, tagMatches, tagsEdit, RULES_FILE } from './vault.js';
import { createWorkspace } from './workspace.js';
import { createExplorer } from './explorer.js';
import { createGraph } from './graph.js';
import { createViewer } from './viewer.js';
import { createTagColors } from './tags.js';
import { createGraphPanel } from './graphpanel.js';
import { createFolderDialog } from './folderdialog.js';
import { createTasksPane } from './taskspane.js';
import { createSignature } from './signature.js';
import { createLinkAutocomplete } from './autocomplete.js';
import { withStatus, withDue, newTaskLine, newSubnoteLine, isoDate, tasksSectionEnd } from './tasks.js';
import { createEditor } from './editor.js';
import { createInlineEditor } from './inlineeditor.js';
import { createSearchBar, plain } from './searchbar.js';
import { createNotesPanel } from './notespanel.js';
import { createNotesView } from './notesview.js';
import { createIngestView } from './ingestview.js';
import { createIngestDialogs } from './ingestdialogs.js';
import { createSessionsView } from './sessionsview.js';
import { createReviewView } from './reviewview.js';
import { createCaptureView } from './capturenotes.js';
import { createSettingsView } from './settingsview.js';
import { showSetup, showLeftovers } from './setup.js';
import { refreshAi } from './ai.js';
import { loadEngineModels } from './modelmenu.js';
import { loadRoles, aliasWithRole, onRolesChange, roleOf, ROLE_LABEL } from './roles.js';
import { NOTE_TEMPLATES_DIR, PAGE_TEMPLATES_DIR, DEFAULT_NOTES_DIR, cleanNotesDir, setDefaultTemplates, templatesIn, fillTemplate, newNotePath, noteInfo } from './notes.js';

const $ = (id) => document.getElementById(id);

const state = {
  vault: null,
  view: 'graph',          // graph | note (a page) | notes | tasks | ingest
  openId: null,           // "alias:path" of the file open in the page view
  editingId: null,        // the open file, while it's in the editor
  scans: new Map(),       // alias -> host scan of that folder
  errors: new Map(),      // alias -> why it couldn't be read
  signatures: new Map(),  // alias -> summary of the last scan, to skip no-op refreshes
  linkCount: 0,
};

const workspace = createWorkspace();
const tagColors = createTagColors();
const explorer = createExplorer($('explorer'), {
  onOpen: openFile,
  onEditFolder: (alias) => dialog.open({ alias }),
});
const graph = createGraph($('graph'), { onOpen: openFile });
const panel = createGraphPanel($('graph-panel'), {
  tagColors,
  onChange: ({ fit, colorsChanged }) => {
    applyStyle({ fit });
    if (colorsChanged && state.openId) rerenderOpenNote();
  },
  onFolderChange: (alias, changes, { quiet = false } = {}) => {
    workspace.update(alias, changes);
    const folder = state.vault?.folders.find((f) => f.alias === alias);
    if (folder) Object.assign(folder, changes);
    if (!quiet) refreshPanel();         // quiet: a color picker is still open; don't redraw it
    if (changes.color) explorer.setVault(state.vault);
    applyStyle({ fit: 'hidden' in changes });
  },
});
const viewer = createViewer($('note'), {
  onOpen: openFile,
  onOpenExternal: (url) => call('openExternal', { url }),
  // Clicking a tag in a note's properties shows that tag in the graph.
  onTag: (tag) => {
    panel.select([tag]);
    showView('graph');
    applyStyle({ fit: true });
  },
  // "Show in Tasks" on a note: every task on it or linking to it.
  onShowTasks: (id) => {
    tasksPane.focusPage(id);
    showView('tasks');
  },
  onAddTask: (id) => {
    tasksPane.newTaskOn(id);
    showView('tasks');
  },
  onEdit: (id) => startEditing(id),
  onOpenInNotes: (id) => openJot(id),
  loadText: (id) => {
    const colon = id.indexOf(':');
    const folder = workspace.find(id.slice(0, colon));
    return call('readText', { root: folder.root, path: id.slice(colon + 1) });
  },
  onEditTags: ({ id, hide }) => {
    const note = state.vault.notes.get(id);
    if (note && !state.editingId) inlineEditor.openTags({ note, hide });
  },
  onEditBody: ({ id, ...options }) => {
    const note = state.vault.notes.get(id);
    if (note && !state.editingId) inlineEditor.openBody({ note, ...options });
  },
  tagColors,
});
const inlineEditor = createInlineEditor({
  getSignature: () => signature.get(),
  getVault: () => state.vault,
  tagColors,
  onSaveBody: ({ note, start, original, lines }) =>
    saveLines(note, () => call('editLines', { ...target(note), start, expect: original, replace: lines })),
  onSaveTags: ({ note, tags }) => {
    const edit = tagsEdit(note.content, tags);
    return edit ? saveLines(note, () => call('editLines', { ...target(note), ...edit })) : true;
  },
  onClose: () => state.openId && rerenderOpenNote(),
});
const editor = createEditor($('editor'), {
  getSignature: () => signature.get(),
  onCancel: () => {
    if (editor.isDirty() && !confirm('Discard your unsaved changes to this note?')) return;
    stopEditing();
  },
  onSave: saveEditedNote,
  render: (text, folder) => viewer.renderMarkdown(text, folder),
  renderEditable: (text, folder) => viewer.renderEditable(text, folder),
  onOpenLink: (id) => openFile(id),
  onOpenExternal: (url) => call('openExternal', { url }),
});
createLinkAutocomplete({ getVault: () => state.vault });
const searchBar = createSearchBar($('search'), {
  getVault: () => state.vault,
  tagColors,
  onOpenNote: (id, terms) => {
    openFile(id, undefined, { page: true });
    if (state.openId === id && !state.editingId) viewer.highlight(terms);
  },
  // A task result opens its page, scrolled to the task.
  onOpenTask: (task, terms) => {
    openFile(task.note.id, undefined, { page: true });
    if (state.openId === task.note.id && !state.editingId) viewer.highlight(terms, plain(task.text).slice(0, 30));
  },
});
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.code === 'KeyF') {
    e.preventDefault();
    searchBar.focus();
  }
});
const dialog = createFolderDialog($('folder-dialog'), {
  workspace,
  call,
  getVault: () => state.vault,
  onSave: saveFolder,
  onRemove: removeFolder,
});
const signature = createSignature($('signature'), { onChange: () => tasksPane.refreshHint() });
const tasksPane = createTasksPane($('tasks-view'), {
  renderInline: (text, folder) => viewer.renderInline(text, folder),
  onOpen: openFile,
  getSignature: () => signature.get(),
  requireSignature: () => signature.require(),
  getFolders: () => workspace.list(),
  actions: {
    setStatus: (task, status) => editTask(task, task.line, [task.raw], [withStatus(task.raw, status, isoDate())]),
    setDue: (task, due) => editTask(task, task.line, [task.raw], [withDue(task.raw, due)]),
    // The subnote goes right after the last line that belongs to the task.
    addSubnote: (task, text) => {
      const last = task.note.content.split(/\r?\n/)[task.blockEnd];
      return editTask(task, task.blockEnd, [last], [last, newSubnoteLine(task, text, signature.get())]);
    },
    // Adds the task at the end of the page's Tasks section. A page without one gets a
    // "## Tasks" section at the end; a page that doesn't exist yet is created.
    addTask: async ({ pageId, text, due }) => {
      const colon = pageId.indexOf(':');
      const folder = workspace.find(pageId.slice(0, colon));
      const path = pageId.slice(colon + 1);
      const note = state.vault.notes.get(pageId);
      const line = newTaskLine(text, due, signature.get());
      const root = folder.root;
      if (!note) {
        return writeAndReload(folder, () =>
          call('appendLines', { root, path, lines: [line], header: [`# ${path.replace(/\.md$/i, '').split('/').pop()}`, ''] }),
        );
      }
      const after = tasksSectionEnd(note.content);
      if (after < 0) {
        return writeAndReload(folder, () => call('appendLines', { root, path, lines: ['', '## Tasks', line] }));
      }
      const anchor = note.content.split(/\r?\n/)[after];
      return writeAndReload(folder, () =>
        call('editLines', { root, path, start: after, expect: [anchor], replace: [anchor, line] }),
      );
    },
  },
});

const notesPanel = createNotesPanel($('notes-panel'), {
  getTemplates: () => templatesIn(state.vault, notesFolder()),
  getFolders: () => workspace.list(),
  getNotesFolder: () => notesFolder(),
  setNotesFolder: (alias) => setNotesLocation({ alias }),
  onOpen: (id) => openJot(id),
  onNew: (template) => newNote(template),
  onEditTemplate: (template) => editTemplate(template),
  onNewTemplate: () => newTemplate(),
});
const notesView = createNotesView($('notes-view'), {
  getVault: () => state.vault,
  getSignature: () => signature.get(),
  getTemplates: () => templatesIn(state.vault, notesFolder()),
  getLocation: () => ({ alias: notesFolder(), dir: notesDir(), folders: workspace.list() }),
  setLocation: (changes) => setNotesLocation(changes),
  render: (text, folder) => viewer.renderMarkdown(text, folder),
  renderEditable: (text, folder) => viewer.renderEditable(text, folder),
  onOpenLink: (id) => openFile(id),
  onOpenExternal: (url) => call('openExternal', { url }),
  onWrite: writeJot,
  onNew: (template) => newNote(template),
  onOpen: (id) => openJot(id),
  onOpenPage: (id) => openFile(id, undefined, { page: true }),
  onChange: () => {
    notesPanel.setActive(notesView.shownId());
    updateTitle();
  },
  onSaveFailed: (note) => toast(`Your last edits to ${note.name} couldn't be saved. They're kept in the Notes view: open it to keep them or load the latest version.`),
});

// The Ingest view has four tabs (three agents; Notes and Sessions share one):
//   Notes      the executive assistant: wrapped quick notes -> records filed under topics in the personal wiki, written directly
//   Sessions   the executive assistant: Claude Code sessions -> session notes filed under topics, written directly
//   Review     the wiki reviewer: rewrites a topic page's summary, suggests merges; folders from shared tags
//   Promotion  the team wiki manager: personal pages -> changes to the Team wiki, answered card by card
const INGEST_TABS = ['notes', 'sessions', 'review', 'promotion'];
function updateIngestCounts() {
  $('ingest-badge').textContent = ingestView.badge() || '';
  $('ingest-notes-count').textContent = ingestView.badge() || '';
  $('ingest-sessions-count').textContent = sessionsView.count() || '';
  $('ingest-review-count').textContent = reviewView.count() || '';
  $('ingest-promotion-count').textContent = promotionView.badge() || '';
}

function showIngestTab(tab) {
  tab = INGEST_TABS.includes(tab) ? tab : 'notes';
  store('ingestTab', tab);
  for (const name of INGEST_TABS) $(`ingest-${name}`).hidden = name !== tab;
  for (const button of document.querySelectorAll('.ingest-tab')) {
    button.classList.toggle('active', button.dataset.tab === tab);
    button.setAttribute('aria-selected', String(button.dataset.tab === tab));
  }
  if (state.view !== 'ingest') return;
  if (tab === 'sessions') sessionsView.shown();
  if (tab === 'review') reviewView.shown();
}
$('ingest-help').addEventListener('click', () => ingestDialogs.openHelp());
$('ingest-agents').addEventListener('click', () => ingestDialogs.openPrompt());
document.querySelector('.ingest-tabs').addEventListener('click', (e) => {
  const button = e.target.closest('.ingest-tab');
  if (button) showIngestTab(button.dataset.tab);
});

const sessionsView = createSessionsView($('ingest-sessions'), {
  call,
  getPersonalWiki: () => workspace.find(aliasWithRole('personal')) || null,
  getFolders: () => workspace.list(),
  findFolder: (alias) => workspace.find(alias),
  reload: async (alias) => {
    const folder = workspace.find(alias);
    if (folder && (await scanFolder(folder))) rebuild();
  },
  openPage: (id) => openFile(id, undefined, { page: true }),
  toast: (message) => toast(message),
  onChange: () => updateIngestCounts(),
  onCaptured: () => reviewView.refresh(),
});

const reviewView = createReviewView($('ingest-review'), {
  call,
  getWiki: () => sessionsView.wiki(),
  reload: async (alias) => {
    const folder = workspace.find(alias);
    if (folder && (await scanFolder(folder))) rebuild();
  },
  openPage: (id) => openFile(id, undefined, { page: true }),
  toast: (message) => toast(message),
  onChange: () => updateIngestCounts(),
});

// What the two card tabs share. Promotion is the same screen (ingestview.js) with another list.
const cardViewDeps = {
  call,
  on,
  getVault: () => state.vault,
  getFolders: () => workspace.list(),
  findFolder: (alias) => workspace.find(alias),
  getNotesDir: () => notesDir(),
  reload: async (alias) => {
    const folder = workspace.find(alias);
    if (folder && (await scanFolder(folder))) rebuild();
  },
  render: (text, folder) => viewer.renderMarkdown(text, folder),
  openPage: (id) => openFile(id, undefined, { page: true }),
  toast: (message) => toast(message),
  onChange: () => updateIngestCounts(),
  onHelp: () => ingestDialogs.openHelp(),
  onEditPrompt: () => ingestDialogs.openPrompt(),
  onShowRun: (transcript, when) => ingestDialogs.openRun(transcript, when),
};
const promotionView = createIngestView($('ingest-promotion'), {
  ...cardViewDeps,
  mode: 'promotion',
  getSourceWiki: () => sessionsView.wiki(),
  getTeamWiki: () => workspace.find(aliasWithRole('team')) || null,
});

// The Notes tab: capture wrapped notes into the personal wiki (capturenotes.js).
const ingestView = createCaptureView($('ingest-notes'), {
  call,
  on,
  findFolder: (alias) => workspace.find(alias),
  getPersonal: () => sessionsView.wiki(),
  reload: async (alias) => {
    const folder = workspace.find(alias);
    if (folder && (await scanFolder(folder))) rebuild();
  },
  openPage: (id) => openFile(id, undefined, { page: true }),
  toast: (message) => toast(message),
  onChange: () => updateIngestCounts(),
  onCaptured: () => reviewView.refresh(),
});
const ingestDialogs = createIngestDialogs($('ingest-dialog'), {
  // The three agents and their prompts (built in until customised; see agents/agentfiles.py).
  getAgents: () => call('agentsInfo'),
  saveAgent: async (id, text) => {
    try {
      await call('saveAgentPrompt', { id, text });
      return true;
    } catch (err) {
      return err.message;
    }
  },
  // The connected wikis, for the page-template list.
  getWikis: async () => workspace.list().map((f) => ({ alias: f.alias, color: f.color })),
  // The rules files the Agents window edits, read through the path list: "My capture rules" (steers capture and
  // Review in the Personal wiki) and the Team wiki's rules (steer Promotion). A View only wiki's rules aren't used.
  getRulesTabs: async () => {
    const tabs = [];
    const read = async (name) => {
      try {
        return await call('readPathFile', { name });
      } catch {
        return { path: '', text: null };
      }
    };
    const capture = await read('personal_capture_rules');
    tabs.push({
      key: 'capture', label: 'My capture rules', name: 'personal_capture_rules', path: capture.path, color: null,
      text: capture.text, starter: capture.starter_text || '',
      about: 'Your own rules for what gets captured into your Personal wiki (notes and sessions) and how topics are reviewed: what to pick out, and what earns its own page.',
    });
    const team = aliasWithRole('team');
    const folder = team && workspace.find(team);
    if (folder) {
      const file = await read(`wiki.${team}.rules`);
      const starter = await readSlot('template.rules-starter');
      tabs.push({
        key: `team:${team}`, label: `${team} rules (Team)`, name: `wiki.${team}.rules`, path: file.path, color: folder.color,
        text: file.text, starter: fillAlias(starter, team),
        about: 'Promotion follows these when it proposes pages in the Team wiki.',
      });
    }
    return tabs;
  },
  // Writes a rules file through the path list; refused if it changed since the window opened it.
  saveRules: async (name, text, opened) => {
    try {
      await call('writePathFile', { name, text, ...(opened != null ? { expect: opened } : {}) });
    } catch (err) {
      return /changed on disk/.test(err.message) ? 'the file changed outside the app. Close and reopen this window to see it.' : err.message;
    }
    const alias = /^wiki\.(.+)\.rules$/.exec(name)?.[1];
    const folder = alias && workspace.find(alias);
    if (folder && (await scanFolder(folder))) rebuild();
    return true;
  },
  // Page templates for Ingest's new pages, in every wiki: [{ id, alias, name, path, description }].
  getPageTemplates: () =>
    [...(state.vault?.notes.values() || [])]
      .filter((n) => n.path.startsWith(`${PAGE_TEMPLATES_DIR}/`))
      .map((n) => ({ id: n.id, alias: n.folder, name: n.name, path: n.path, description: n.description.trim() }))
      .sort((a, b) => a.alias.localeCompare(b.alias) || a.name.localeCompare(b.name)),
  openPageTemplate: (id) => startEditing(id),
  // Creates <wiki>/Templates/Pages/<name>.md from a starter and opens it in the editor.
  newPageTemplate: async (alias, name) => {
    const folder = workspace.find(alias);
    const clean = name.replace(/[\\/:*?"<>|#^[\]]/g, '').trim();
    if (!folder || !clean) return;
    const path = `${PAGE_TEMPLATES_DIR}/${clean}.md`;
    const id = `${alias}:${path}`;
    if (!state.vault.notes.has(id)) {
      const starter = await readSlot('template.page-starter');
      const ok = await writeAndReload(folder, () => call('createNote', { root: folder.root, path, lines: starter.split('\n') }));
      if (!ok) return;
      toast(`Made the ${clean} page template in ${alias} / ${path}. Describe when to use it, then lay out the page.`);
    }
    startEditing(id);
  },
  getLogRaw: () => load('ingestLogRaw') === 'true',
  setLogRaw: (on) => store('ingestLogRaw', on),
  openRunFolder: (runId) => call('openIngestRun', { runId }).catch((err) => toast(err.message)),
});

// The Settings screen: every path WikiApp uses, and the AI engine. Reached from the gear at the bottom of the rail.
const settingsView = createSettingsView($('settings-view'), {
  getFolders: () => workspace.list(),
  toast: (message) => toast(message),
  // A file inside a connected wiki opens in the app's own editor; anything else is the caller's to show.
  openInEditor: async (path) => {
    const norm = (p) => p.replace(/\\/g, '/').replace(/\/+$/, '');
    const full = norm(path).toLowerCase();
    for (const f of workspace.list()) {
      const root = norm(f.root).toLowerCase();
      if (!full.startsWith(`${root}/`)) continue;
      const id = `${f.alias}:${norm(path).slice(root.length + 1)}`;
      if (state.vault?.notes.has(id)) {
        startEditing(id);
        return true;
      }
    }
    return false;
  },
  onChanged: async (names) => {
    await loadPaths();
    if (state.vault) rebuild();
    if (names.some((n) => /^wiki\./.test(n))) for (const f of workspace.list()) if (await scanFolder(f)) rebuild();
  },
});

// Roles (Personal, Team, View only) live in the host; the page's copy is refreshed after the workspace changes
// (a moment later, so the host has the saved folder list) and the views that depend on it redraw.
async function refreshRoles() {
  await new Promise((resolve) => setTimeout(resolve, 600));
  await loadRoles();
}
onRolesChange(() => {
  if (state.vault) explorer.setVault(state.vault);
  refreshPanel();
  sessionsView.rolesChanged();
  reviewView.refresh();
  ingestView.redraw();
  if (state.vault) promotionView.setVault(state.vault);
  updateIngestCounts();
  if (state.view === 'ingest') showIngestTab(load('ingestTab'));
});

$('add-folder').addEventListener('click', () => dialog.open());
$('collapse-folders').addEventListener('click', () => {
  if (!explorer.collapseLevel()) toast('Nothing more to collapse: only the workspace folders are open.');
});
$('welcome-open').addEventListener('click', () => dialog.open());
for (const button of document.querySelectorAll('.rail-button[data-view]')) {
  button.addEventListener('click', () => railTo(button.dataset.view));
}
// Ctrl+1..5 switch views, in rail order.
document.addEventListener('keydown', (e) => {
  const n = /^Digit([1-5])$/.exec(e.code);
  if (!n || !(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || !state.vault) return;
  e.preventDefault();
  railTo(document.querySelectorAll('.rail-button[data-view]')[n[1] - 1].dataset.view);
});

// The rail's Notes button always goes to the Notes start page (templates and open notes);
// the other buttons go back to their view as it was.
function railTo(view) {
  if (view === 'notes') {
    notesView.show(null);
    notesPanel.setActive(null);
    store('lastNote', '');
  }
  showView(view);
}

// ---- Writing tasks back to notes ----------------------------------------------------

// Replaces lines in the task's note, then reloads that folder.
function editTask(task, start, expect, replace) {
  const folder = workspace.find(task.note.folder);
  return writeAndReload(folder, () =>
    call('editLines', { root: folder.root, path: task.note.path, start, expect, replace }),
  );
}

// Runs a write, then rescans the folder so every view shows the result right away.
// If the note changed on disk in the meantime, the host refuses; we reload and say so.
async function writeAndReload(folder, write) {
  let ok = true;
  try {
    await write();
  } catch (err) {
    ok = false;
    toast(err.message);
  }
  if (await scanFolder(folder)) rebuild();
  return ok;
}

// ---- Editing a note ---------------------------------------------------------------------

function startEditing(id) {
  const note = state.vault?.notes.get(id);
  if (!note) return;
  // The full editor replaces an in-place edit; unsaved changes are saved first.
  if (inlineEditor.isDirty()) {
    inlineEditor.save();
    toast('Saving your edit first. Press Edit again to open the full editor.');
    return;
  }
  inlineEditor.cancel({ force: true });
  if (state.openId !== id) openFile(id);
  if (state.openId !== id) return; // the user kept unsaved edits to another note
  state.editingId = id;
  editor.open(note, workspace.find(note.folder)?.color || 'transparent');
  $('note').hidden = true;
  $('editor').hidden = false;
  $('note-view').classList.add('editing');
  showView('note');
}

function stopEditing() {
  state.editingId = null;
  editor.close();
  $('editor').hidden = true;
  $('note').hidden = false;
  $('note-view').classList.remove('editing');
  if (state.openId) rerenderOpenNote();
  updateTitle();
}

// Closing an in-place edit before showing something else. Clicking elsewhere means "save", so
// changes are saved rather than dropped. -> true at once when there's nothing to save, else a
// Promise of whether it saved: if not, the page stays, with the edit and the reason showing.
function leaveInlineEditor() {
  if (!inlineEditor.isOpen()) return true;
  if (!inlineEditor.isDirty()) {
    inlineEditor.cancel({ force: true });
    return true;
  }
  return inlineEditor.save().then((saved) => {
    if (!saved) toast("Your edit to this page couldn't be saved, so the page stays open with your text. Copy what you need, then press Esc to see the latest version.");
    return saved;
  });
}

// Before the window closes or reloads: saves what can be saved and asks about what can't.
// -> whether to go ahead.
async function readyToLeave(action) {
  await notesView.flush();
  const failedNote = notesView.unsavedNote();
  if (failedNote && !confirm(`Your last edits to ${failedNote} couldn't be saved. ${action} anyway and lose them?`)) return false;
  if (inlineEditor.isOpen() && inlineEditor.isDirty() && !(await inlineEditor.save())
      && !confirm(`Your edit to this page couldn't be saved. ${action} anyway and lose it?`)) return false;
  if (state.editingId && editor.isDirty() && !confirm(`You have unsaved changes to ${pageTitle(state.editingId)}. ${action} anyway and lose them?`)) return false;
  return true;
}

// Leaving the editor for another note: fine if nothing changed, else ask first.
function leaveEditor() {
  if (!state.editingId) return true;
  if (editor.isDirty() && !confirm('Discard your unsaved changes to this note?')) return false;
  stopEditing();
  return true;
}

// Saves the whole note, but only if the file still holds the text the editor started from.
// Returns true when saved, 'conflict' when the file changed on disk meanwhile.
async function saveEditedNote(note, text, original) {
  const folder = workspace.find(note.folder);
  if (!folder) {
    toast("This note's folder was renamed or removed from the workspace, so it can't be saved here. Copy your text, then reopen the note.");
    return false;
  }
  try {
    await call('editLines', {
      root: folder.root,
      path: note.path,
      start: 0,
      expect: original.split('\n'),
      replace: text.split('\n'),
    });
  } catch (err) {
    if (await scanFolder(folder)) rebuild();
    const latest = state.vault.notes.get(note.id);
    if (!latest) {
      toast("This note was moved or deleted outside the app, so it can't be saved here.");
      return false;
    }
    // Keep the user's text; the next Save will replace the version on disk.
    editor.setOriginal(latest.content);
    toast('This note changed on disk while you were editing. Your text is kept; press Save again to replace the version on disk.');
    return 'conflict';
  }
  if (await scanFolder(folder)) rebuild();
  stopEditing();
  toast('Saved.');
  return true;
}

const target = (note) => ({ root: workspace.find(note.folder).root, path: note.path });

// Runs an in-place save (tags or body), then reloads the folder. The host only replaces the
// lines if they still say what they said when editing started.
// Returns true, or a message saying why it wasn't saved.
async function saveLines(note, write) {
  const folder = workspace.find(note.folder);
  try {
    await write();
  } catch (err) {
    if (await scanFolder(folder)) rebuild();
    return /changed on disk/.test(err.message)
      ? 'Not saved: this note was changed somewhere else while you were editing.'
      : `Not saved: ${err.message}`;
  }
  if (await scanFolder(folder)) rebuild();
  return true;
}

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.code === 'KeyE' && !state.editingId && !inlineEditor.isOpen() && !$('note-view').hidden && state.openId) {
    e.preventDefault();
    startEditing(state.openId);
  }
});

let toastTimer = 0;
function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), 5000);
}

// The host watches every open folder and says which one changed.
on('vaultChanged', async ({ root }) => {
  const folder = workspace.list().find((f) => samePath(f.root, root));
  if (folder && (await scanFolder(folder))) rebuild();
});

// ---- Closing and reloading ------------------------------------------------------------
// The window's close button: the host asks the page first, and closes once it says so.
// F5 asks too. Anything else that unloads the page gets the browser's own "Leave?" question.

on('closeRequested', async () => {
  const answer = (value) => call('closeWindow', { answer: value }).catch(() => {});
  await answer('asking');
  answer((await readyToLeave('Close WikiApp')) ? 'yes' : 'no');
});
let reloading = false;
setBeforeReload(async () => (reloading = await readyToLeave('Reload')));
window.addEventListener('beforeunload', (e) => {
  if (reloading) return;
  if ((state.editingId && editor.isDirty()) || inlineEditor.isDirty() || notesView.unsavedNote()) {
    e.preventDefault();
    e.returnValue = '';
  }
});
window.addEventListener('pagehide', () => notesView.flush()); // the last moment of typing, if it can

// ---- Loading folders ----------------------------------------------------------------

// Scans one workspace folder. Returns true if anything changed since the last scan.
async function scanFolder(folder) {
  try {
    const scan = await call('scanVault', { path: folder.root });
    state.errors.delete(folder.alias);
    // Sync tools (OneDrive, Dropbox) can trigger change events without changing anything.
    const signature = scanSignature(scan);
    if (state.signatures.get(folder.alias) === signature) return false;
    state.signatures.set(folder.alias, signature);
    state.scans.set(folder.alias, scan);
  } catch (err) {
    state.errors.set(folder.alias, err.message);
    state.scans.set(folder.alias, { root: folder.root, folders: [], files: [] });
    state.signatures.delete(folder.alias);
  }
  return true;
}

// Rebuilds the combined model from the latest scans and updates every view.
// fit: re-center the graph (after folders are added or removed, not for live edits).
function rebuild({ fit = false } = {}) {
  const folders = workspace.list().map((f) => ({
    ...f,
    scan: state.scans.get(f.alias) || { folders: [], files: [] },
    error: state.errors.get(f.alias) || '',
  }));
  if (!folders.length) {
    state.vault = null;
    closeNote();
    explorer.setVault(null);
    notesPanel.setVault(null);
    document.title = 'WikiApp';
    $('stats').textContent = '';
    showWelcome();
    return;
  }

  const vault = buildVault(folders, { notesDir: notesDir() });
  const data = graphData(vault);
  state.vault = vault;
  state.linkCount = data.links.filter((l) => l.kind === 'link').length;
  document.title = `${folders.map((f) => f.alias).join(' + ')} - WikiApp`;
  $('welcome').hidden = true;

  tagColors.assign(vault.tags.keys());
  refreshPanel({ keepSelection: !fit });
  explorer.setVault(vault);
  viewer.setVault(vault);
  tasksPane.setVault(vault);
  notesPanel.setVault(vault);
  notesView.setVault(vault);
  ingestView.setVault(vault);
  promotionView.setVault(vault);
  updateIngestCounts();
  $('tasks-badge').textContent = vault.tasks.filter((t) => t.status !== 'done').length || '';
  $('notes-badge').textContent = [...vault.notes.values()].filter((n) => n.inbox && !noteInfo(n).wrapped).length || '';
  graph.setData(data, { fit });
  applyStyle();
  updateTitle();

  if (state.openId && fileExists(state.openId)) {
    rerenderOpenNote();
  } else if (state.openId && !state.editingId) {
    closeNote(); // (a note being edited stays open so its text isn't lost)
  }
  explorer.setActive(state.view === 'notes' ? notesView.shownId() : state.openId);
}

async function loadWorkspace() {
  await Promise.all(workspace.list().map(scanFolder));
  rebuild({ fit: true });
}

// From the Add/Edit folder window.
async function saveFolder({ mode, root, scan, alias, color, oldAlias }) {
  if (mode === 'add') {
    workspace.add(root, alias, color);
    state.scans.set(alias, scan);
    await scanFolder(workspace.find(alias)); // starts watching it too
    rebuild({ fit: true });
    await refreshRoles();
    if (roleOf(alias) === 'view') toast(`${alias} is View only. To give it a role (Personal or Team), open Settings, Wikis and their roles.`);
    return;
  }
  workspace.update(oldAlias, { alias, color });
  if (alias !== oldAlias) {
    for (const map of [state.scans, state.errors, state.signatures]) {
      if (map.has(oldAlias)) map.set(alias, map.get(oldAlias));
      map.delete(oldAlias);
    }
    if (state.openId?.startsWith(oldAlias + ':')) state.openId = alias + state.openId.slice(oldAlias.length);
  }
  rebuild();
  if (alias !== oldAlias) refreshRoles();
}

function removeFolder(alias) {
  const folder = workspace.find(alias);
  workspace.remove(alias);
  for (const map of [state.scans, state.errors, state.signatures]) map.delete(alias);
  call('unwatchFolder', { path: folder.root });
  rebuild({ fit: true });
  refreshRoles();
}

function fileExists(id) {
  const colon = id.indexOf(':');
  const scan = state.scans.get(id.slice(0, colon));
  return Boolean(scan && scan.files.some((f) => f.path === id.slice(colon + 1)));
}

function scanSignature(scan) {
  return scan.folders.join('|') + '\n' + scan.files.map((f) => `${f.path}:${f.size}:${f.mtime}`).join('|');
}

// ---- Graph styling --------------------------------------------------------------------

function refreshPanel(options) {
  const vault = state.vault;
  if (!vault) return;
  const counts = new Map();
  for (const note of vault.notes.values()) counts.set(note.folder, (counts.get(note.folder) || 0) + 1);
  panel.setData(
    {
      folders: workspace.list().map((f) => ({ ...f, count: counts.get(f.alias) || 0 })),
      tags: vault.tags,
      duplicateCount: vault.duplicates.size,
    },
    options,
  );
}

// Applies the panel's folder visibility, tag filter and coloring to the graph, and
// updates the stats line.
function applyStyle({ fit = false } = {}) {
  const { selected, colorBy, showDuplicates, showNotes, showScripts, showSessions } = panel.state();
  const filters = [...selected];
  const folders = new Map(workspace.list().map((f) => [f.alias, f]));
  const matchedTag = (node) => filters.find((f) => node.tags.some((t) => tagMatches(t, f)));
  const folderShown = (alias) => folders.has(alias) && !folders.get(alias).hidden;

  const isVisible = (node) => {
    if (!node || typeof node !== 'object') return true;
    if ((node.inbox && !showNotes) || (node.script && !showScripts) || (node.session && !showSessions)) return false;
    // Ghost notes belong to no folder; show them if a visible folder links to them.
    const inShownFolder = node.ghost ? node.linkedFrom.some(folderShown) : folderShown(node.folder);
    return inShownFolder && (!filters.length || Boolean(matchedTag(node)));
  };

  graph.setStyle(
    {
      isVisible,
      showDuplicates,
      colorFor: (node) => {
        if (colorBy === 'folder') return folders.get(node.folder)?.color || null;
        if (colorBy !== 'tag' || !node.tags.length) return null;
        // While filtering, color by the selected tag the note matched; otherwise by its first tag.
        const filter = filters.length && matchedTag(node);
        return tagColors.get(filter ? node.tags.find((t) => tagMatches(t, filter)) : node.tags[0]);
      },
    },
    { fit },
  );

  const vault = state.vault;
  if (!vault) return;
  const notes = [...vault.notes.values()];
  const shown = notes.filter((n) => folderShown(n.folder) && (!filters.length || matchedTag(n))).length;
  const parts =
    shown < notes.length
      ? [`${shown} of ${notes.length} notes`]
      : [`${notes.length} notes`, `${state.linkCount} links`];
  if (vault.duplicates.size) parts.push(`${vault.duplicates.size} shared names`);
  $('stats').textContent = parts.join(' · ');
}

// ---- Notes and views ------------------------------------------------------------------

// A note from the Notes folder that isn't wrapped yet opens in the Notes view, ready to type
// in; everything else (and anything with page: true) opens as a page.
function openFile(id, heading, { page = false } = {}) {
  const note = state.vault?.notes.get(id);
  if (!page && note?.inbox && !noteInfo(note).wrapped) {
    openJot(id);
    return;
  }
  if (id !== state.editingId && !leaveEditor()) return;
  if (id === state.editingId) {
    showView('note'); // already open in the editor
    return;
  }
  // An in-place edit has normally saved itself already (clicking elsewhere saves). One still
  // open with changes is saved first, and the page only changes once it has been.
  const left = leaveInlineEditor();
  if (left !== true) {
    left.then((saved) => saved && openFile(id, heading, { page }));
    return;
  }
  state.openId = id;
  store('lastPage', id);
  explorer.setActive(id);
  graph.setActive(id);
  viewer.show(id, heading);
  showView('note');
}

function pageTitle(id) {
  const note = state.vault.notes.get(id);
  if (note) return noteLabel(note);
  const path = id.slice(id.indexOf(':') + 1);
  return path.slice(path.lastIndexOf('/') + 1);
}

function closeNote() {
  state.openId = null;
  graph.setActive(null);
  explorer.setActive(null);
  if (state.view === 'note') showView('graph');
}

// Re-render the open note in place, keeping the scroll position. While a part of it is being
// edited in place, wait: closing that editor re-renders.
function rerenderOpenNote() {
  if (inlineEditor.isOpen()) return;
  const scroll = $('note-view').scrollTop;
  viewer.show(state.openId);
  $('note-view').scrollTop = scroll;
}

function showView(view) {
  if (state.view === 'notes' && view !== 'notes') notesView.flush();
  state.view = view;
  if (state.vault) store('lastView', view);
  for (const name of ['graph', 'tasks', 'note', 'notes', 'ingest', 'settings']) {
    $(`${name}-view`).hidden = view !== name;
    $(`rail-${name}`).classList.toggle('active', view === name);
  }
  graph.setVisible(view === 'graph');
  if (view === 'note' && !state.openId) {
    $('note').innerHTML = '<p class="empty-page">Open a page from the files, the graph or search.</p>';
  }
  if (view === 'notes') notesView.shown();
  if (view === 'settings') settingsView.shown();
  if (view === 'ingest') showIngestTab(load('ingestTab'));
  // The file tree marks what's in front: the note in the Notes view, else the open page.
  explorer.setActive(view === 'notes' ? notesView.shownId() : state.openId);
  updateTitle();
}

// The name of what's shown, at the left of the top bar.
function updateTitle() {
  const titles = { graph: 'Graph', tasks: 'Tasks', ingest: 'Ingest', settings: 'Settings', notes: `Notes${notesView.shownId() ? ` / ${notesView.title()}` : ''}` };
  let title = titles[state.view];
  if (state.view === 'note') {
    title = state.openId ? `${state.editingId ? '✎ ' : ''}${pageTitle(state.openId)}` : 'Page';
  }
  $('view-title').textContent = title;
  $('view-title').title = state.view === 'note' && state.openId ? state.openId.replace(':', ' / ') : '';
}

// ---- Notes (quick notes from templates) ---------------------------------------------

// The workspace folder new notes go in: the one picked in the + menu, else "personal", else the first.
function notesFolder() {
  const folders = workspace.list();
  const saved = load('notesFolder');
  return (folders.find((f) => f.alias === saved) || folders.find((f) => f.alias.toLowerCase() === 'personal') || folders[0])?.alias;
}

// The folder inside it that holds notes ("Notes" unless changed on the Notes start page).
// The path list's notes_folder is the one source of truth; the page keeps a copy (loadPaths).
let notesFolderName = DEFAULT_NOTES_DIR;
function notesDir() {
  return notesFolderName;
}

// The notes folder and the Daily/Weekly templates, from the path list (listPaths, readPathFile).
async function loadPaths() {
  try {
    const entry = (await call('listPaths')).find((r) => r.name === 'notes_folder');
    notesFolderName = cleanNotesDir(entry?.path) || DEFAULT_NOTES_DIR;
  } catch { /* keep the last one */ }
  const defaults = {};
  for (const [name, slot] of [['Daily', 'template.daily'], ['Weekly', 'template.weekly']]) {
    const text = await readSlot(slot);
    if (text) defaults[name] = text;
  }
  setDefaultTemplates(defaults);
}

// The text of a prompt/template slot ('' when it can't be read).
async function readSlot(name) {
  try {
    return ((await call('readPathFile', { name })).text || '').replace(/\r\n/g, '\n');
  } catch {
    return '';
  }
}
const fillAlias = (text, alias) => text.replace(/\{\{\s*alias\s*\}\}/g, alias);

// From the "Where new notes are saved" box: { alias } and/or { dir }. Notes are found by their
// folder, so the lists are rebuilt.
function setNotesLocation({ alias, dir }) {
  if (alias) store('notesFolder', alias);
  if (dir !== undefined) {
    call('setPath', { name: 'notes_folder', path: cleanNotesDir(dir) || '' })
      .then(loadPaths)
      .then(() => state.vault && rebuild())
      .catch((err) => toast(err.message));
    return;
  }
  if (state.vault) rebuild();
}

function openJot(id) {
  notesView.show(id);
  notesPanel.setActive(id);
  store('lastNote', id);
  showView('notes');
}

// Saves the Notes view's text: replaces the whole file, if it still holds `expect`.
// Returns true, or why it wasn't saved.
async function writeJot(note, expect, replace) {
  const folder = workspace.find(note.folder);
  if (!folder) return 'its folder was removed from the workspace.';
  try {
    await call('editLines', { root: folder.root, path: note.path, start: 0, expect, replace });
  } catch (err) {
    if (await scanFolder(folder)) rebuild();
    return /changed on disk/.test(err.message) ? 'the file was changed outside the app.' : err.message;
  }
  if (await scanFolder(folder)) rebuild();
  return true;
}

// A new note from a template. There can be several open notes of the same kind (two daily
// notes, say); each new one gets its own file.
async function newNote(template) {
  const alias = notesFolder();
  const folder = workspace.find(alias);
  if (!folder || !template) return;
  const path = newNotePath(state.vault, alias, notesDir(), template.name);
  const lines = fillTemplate(template.text, { signature: signature.get() }).split('\n');
  if (lines[lines.length - 1] !== '') lines.push('');
  if (!(await writeAndReload(folder, () => call('createNote', { root: folder.root, path, lines })))) return;
  openJot(`${alias}:${path}`);
  // Start typing at the end of the note.
  const boxes = $('notes-view').querySelectorAll('textarea');
  const last = boxes[boxes.length - 1];
  if (last) {
    last.focus();
    last.setSelectionRange(last.value.length, last.value.length);
  }
}

// Opens a template in the full editor. A built-in one is saved to Templates/Notes first.
async function editTemplate(template) {
  if (!template) return;
  let id = template.id;
  if (!id) {
    const alias = notesFolder();
    const folder = workspace.find(alias);
    const path = `${NOTE_TEMPLATES_DIR}/${template.name}.md`;
    const lines = template.text.split('\n');
    if (!(await writeAndReload(folder, () => call('createNote', { root: folder.root, path, lines })))) return;
    id = `${alias}:${path}`;
    toast(`Saved the ${template.name} template to ${alias} / ${path}. Edit it here; new notes will use it.`);
  }
  startEditing(id);
}

async function newTemplate() {
  const name = (prompt('Name of the new template (for example "Meeting"):') || '').replace(/[\\/:*?"<>|#^[\]]/g, '').trim();
  if (!name) return;
  const existing = templatesIn(state.vault, notesFolder()).find((t) => t.name.toLowerCase() === name.toLowerCase());
  if (existing) {
    editTemplate(existing);
    return;
  }
  editTemplate({
    name,
    id: null,
    text: ['---', `type: ${name.toLowerCase()}`, 'started: {{date}}', 'status: open', 'tags: []', '---', `# ${name} · {{day}}`, '', '## {{time}} · Notes', '- ', ''].join('\n'),
  });
}

function showWelcome(error) {
  const welcome = $('welcome');
  welcome.querySelector('.error')?.remove();
  if (error) {
    const p = document.createElement('p');
    p.className = 'error';
    p.textContent = error;
    welcome.insertBefore(p, $('welcome-open'));
  }
  welcome.hidden = false;
}

function samePath(a, b) {
  const norm = (p) => p.replace(/[\\/]+$/, '').toLowerCase();
  return norm(a) === norm(b);
}

// ---- Resizable sidebar ----------------------------------------------------------

const sidebar = $('sidebar');
const resizer = $('resizer');
const savedWidth = load('sidebarWidth');
if (savedWidth) sidebar.style.width = savedWidth;

// The button at the top of the rail (or Ctrl+\) hides and shows the sidebar.
function setSidebarHidden(hidden) {
  sidebar.hidden = hidden;
  resizer.hidden = hidden;
  const button = $('toggle-sidebar');
  const label = hidden ? 'Show the sidebar' : 'Hide the sidebar';
  button.title = `${label} (Ctrl+\\)`;
  button.setAttribute('aria-label', label);
  button.setAttribute('aria-expanded', String(!hidden));
  button.classList.toggle('collapsed', hidden);
  store('sidebarHidden', hidden);
}
setSidebarHidden(load('sidebarHidden') === 'true');
$('toggle-sidebar').addEventListener('click', () => setSidebarHidden(!sidebar.hidden));
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.code === 'Backslash') {
    e.preventDefault();
    setSidebarHidden(!sidebar.hidden);
  }
});

resizer.addEventListener('pointerdown', (e) => {
  resizer.setPointerCapture(e.pointerId);
  resizer.classList.add('dragging');
  const startX = e.clientX;
  const startWidth = sidebar.offsetWidth;
  const move = (ev) => (sidebar.style.width = `${startWidth + ev.clientX - startX}px`);
  const up = () => {
    resizer.classList.remove('dragging');
    resizer.removeEventListener('pointermove', move);
    store('sidebarWidth', sidebar.style.width);
  };
  resizer.addEventListener('pointermove', move);
  resizer.addEventListener('pointerup', up, { once: true });
});

// ---- Small settings that survive restarts ---------------------------------------

function store(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

function load(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

// ---- Start ----------------------------------------------------------------------

async function start() {
  if (!isHosted) {
    showWelcome('This page runs inside WikiApp. Open it with WikiApp.cmd (Windows) or WikiApp.command (Mac).');
    $('welcome-open').hidden = true;
    return;
  }
  // Until a place has been chosen for WikiApp's private folder, the app is just the setup screen.
  let first = null;
  try {
    first = await call('firstRunState');
  } catch (err) {
    showWelcome(err.message);
    return;
  }
  if (!first.chosen || (!first.location_exists && !first.from_env)) {
    const known = [...(await call('getStartupFolders').catch(() => [])), ...workspace.list().map((f) => f.root)];
    showSetup($('setup-screen'), first, () => known);
    return;
  }
  refreshAi();
  await loadEngineModels();
  await loadRoles();
  await loadPaths();
  if (first.leftovers?.length) showLeftovers($('settings-dialog'), first.leftovers);
  // Folders passed on the command line join the workspace (alias from the folder name).
  for (const root of await call('getStartupFolders')) {
    if (!workspace.hasRoot(root)) workspace.add(root, workspace.suggestAlias(root));
  }
  if (workspace.list().length) {
    await loadWorkspace();
    restoreSession();
  } else {
    showWelcome();
  }
  ingestView.load();
  await promotionView.load();
}

// Back to where the last run left off: the open page, the note in the Notes view, the view.
function restoreSession() {
  const notes = state.vault?.notes;
  if (!notes) return;
  const page = load('lastPage');
  const note = load('lastNote');
  const view = load('lastView');
  if (page && notes.has(page)) openFile(page, undefined, { page: true });
  if (note && notes.has(note)) {
    notesView.show(note);
    notesPanel.setActive(note);
  }
  showView(['graph', 'note', 'notes', 'tasks', 'ingest', 'settings'].includes(view) ? view : 'graph');
}

start();

// The AI banner (Ingest view) links to Settings.
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-goto="settings"]')) showView('settings');
});
