// The Notes view: a quick note, ready to type in. The title is a text box; the text before the
// first section and each "## " section are shown formatted while you write (livetext.js:
// click a paragraph, list or table to edit it). Everything saves as you type (the whole file is
// rewritten, but only if it still says what it said when it was loaded).
// The formatting toolbar sits at the top while the note can be typed in, and acts on the box
// last typed in. Without a note open, it shows a start page: the templates, where new notes are
// saved, and the open notes.

import { createTextCommands } from './textcommands.js';
import { toolbarMarkup, bindToolbar } from './editor.js';
import { createLiveText } from './livetext.js';
import { parseNote, noteLines, withProperties, noteInfo, clock } from './notes.js';
import { isoDate, friendlyDate } from './tasks.js';

const SAVE_DELAY = 600;
const AUTOSIZE = typeof CSS !== 'undefined' && CSS.supports?.('field-sizing', 'content');

export function createNotesView(container, {
  getVault, getSignature, getTemplates, getLocation, setLocation, render: renderMarkdown, renderEditable,
  onOpenLink, onOpenExternal, onWrite, onNew, onOpen, onOpenPage, onChange,
}) {
  // The note being shown: { id, note, base: file lines as last read or written, front,
  // saving, queued: lines waiting to be written, error }
  let session = null;
  let timer = 0;
  const liveFor = new WeakMap(); // .live-text element -> its live text box

  // The formatting toolbar, made once and shown above an open (not wrapped) note.
  const commandsFor = new WeakMap(); // text box -> its editing commands
  let lastBox = null;                // the text box the toolbar acts on
  const toolbar = el('div', 'editor-toolbar jot-toolbar');
  toolbar.setAttribute('role', 'toolbar');
  toolbar.setAttribute('aria-label', 'Formatting');
  toolbar.innerHTML = toolbarMarkup({ topInserts: false, headings: false });
  const tools = bindToolbar(toolbar, () => {
    const ta = lastBox?.isConnected ? lastBox : container.querySelector('.rich-line.last .rich-text, .jot-text');
    return ta && commandsFor.has(ta) ? { ta, commands: commandsFor.get(ta) } : null;
  });

  // ---- Saving ---------------------------------------------------------------------

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => flush(), SAVE_DELAY);
    setStatus('Editing…');
  }

  // Writes the current text now (if it changed). Returns when it's written.
  function flush(s = session) {
    if (!s) return Promise.resolve();
    if (s === session) {
      clearTimeout(timer);
      timer = 0;
      if (!readOnly()) s.queued = noteLines(collect());
    }
    if (s.saving) return s.saving;
    return write(s);
  }

  async function write(s) {
    const lines = s.queued;
    s.queued = null;
    if (!lines || s.error) return;
    if (same(lines, s.base)) {
      if (s === session) setStatus('Saved');
      return;
    }
    if (s === session) setStatus('Saving…');
    let done;
    s.saving = new Promise((resolve) => (done = resolve));
    const result = await onWrite(s.note, s.base, lines);
    if (result === true) s.base = lines;
    else s.error = result;
    s.saving = null;
    if (s === session) {
      if (s.error) showError(s.error);
      else setStatus('Saved');
    }
    if (s.queued && !s.error) await write(s);
    done();
  }

  // ---- Reading the boxes ------------------------------------------------------------

  function collect() {
    return {
      front: session.front,
      title: container.querySelector('.jot-title')?.value || '',
      intro: textOf(container.querySelector('.jot-intro')),
      sections: [...container.querySelectorAll('.jot-section')].map((section) => ({
        heading: section.querySelector('.jot-heading').value,
        text: textOf(section.querySelector('.live-text')),
      })),
    };
  }

  const textOf = (box) => (box && liveFor.has(box) ? liveFor.get(box).value : '');

  const readOnly = () => Boolean(session && noteInfo(session.note).wrapped);

  // ---- Showing a note -----------------------------------------------------------------

  function open(id) {
    if (session && session.id === id) return; // already showing it (and maybe mid-edit)
    if (session) flush();
    const note = id && getVault()?.notes.get(id);
    if (!note) {
      session = null;
      renderStart();
      return;
    }
    session = { id, note, base: note.content.split(/\r?\n/), front: [], saving: null, queued: null, error: null };
    render();
  }

  function render({ keepFocus = false } = {}) {
    const focus = keepFocus ? focusState() : null;
    const { note } = session;
    const parts = parseNote(note.content);
    session.front = parts.front;
    const info = noteInfo(note);
    const locked = info.wrapped;
    const vault = getVault();

    const page = el('div', 'note jot' + (locked ? ' locked' : ''));

    // "● personal / Notes/2026-10-31 Daily.md        Saved   [View as page] [Wrap note]"
    const where = el('div', 'note-path');
    const dot = el('span', 'folder-dot');
    dot.style.background = vault.folders.find((f) => f.alias === note.folder)?.color || 'transparent';
    where.append(dot, el('span', 'note-folder', note.folder), ` / ${note.path}`, el('span', 'spacer'), el('span', 'jot-status'));
    const asPage = el('button', 'secondary-button note-action', 'View as page');
    asPage.title = 'Show this note as a page (rendered, with its backlinks)';
    asPage.addEventListener('click', async () => {
      await flush();
      onOpenPage(note.id);
    });
    const wrap = el('button', (locked ? 'secondary-button' : 'primary-button') + ' note-action jot-wrap', locked ? 'Reopen' : 'Wrap note');
    wrap.title = locked ? 'Reopen this note to keep writing in it' : `Finish this note: sets its end date to today (${isoDate()})`;
    wrap.addEventListener('click', () => (locked ? reopen() : wrapUp()));
    where.append(asPage, wrap);
    page.append(where);

    const title = el('input', 'jot-title');
    title.value = parts.title;
    title.placeholder = 'Title';
    title.readOnly = locked;
    page.append(title);

    // Type · started · ended / open
    const meta = el('div', 'jot-meta');
    if (info.type) meta.append(el('span', 'jot-chip type', info.type));
    if (info.started) meta.append(el('span', 'jot-chip', `Started ${when(info.started)}`));
    meta.append(
      locked
        ? el('span', 'jot-chip wrapped', info.ended ? `Wrapped ${when(info.ended)}` : 'Wrapped')
        : el('span', 'jot-chip open', 'Open'),
    );
    page.append(meta);
    if (locked) page.append(el('p', 'jot-locked-hint', 'This note is wrapped. Reopen it to keep writing.'));

    if (parts.intro || !parts.sections.length) {
      const intro = liveBox(parts.intro, note.folder, locked, 'Jot something…  (Ctrl+T adds a task)');
      intro.classList.add('jot-intro');
      page.append(intro);
    }
    for (const section of parts.sections) page.append(sectionBox(section, note.folder, locked));

    if (!locked) {
      const add = el('label', 'jot-new');
      add.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>';
      const input = el('input', 'jot-new-input');
      input.placeholder = 'New section: a meeting, a topic… then Enter';
      add.append(input);
      page.append(add);
      page.append(el('p', 'jot-hint', 'Ctrl+T adds a task · [[ links a page · start a line with "- ", "1. ", "# " or "[ ] " for a list, heading or task · Ctrl+Enter starts a new section · saved as you type'));
    }

    lastBox = null;
    tools.closeMenu();
    if (locked) container.replaceChildren(page);
    else container.replaceChildren(toolbar, page);
    autosizeAll();
    if (session.error) showError(session.error);
    else setStatus(session.saving ? 'Saving…' : 'Saved');
    if (focus) restoreFocus(focus);
  }

  // A part of the note, shown formatted (see livetext.js).
  function liveBox(value, folder, locked, placeholder) {
    const live = createLiveText({
      value,
      folder,
      readOnly: locked,
      placeholder,
      render: renderMarkdown,
      renderEditable,
      setupTextBox,
      onOpenLink,
      onOpenExternal,
      getSignature,
    });
    liveFor.set(live.root, live);
    return live.root;
  }

  // Each text box the live boxes make: editing commands (Ctrl+T, lists...), the toolbar, and
  // Ctrl+Enter to start a new section. Rows edited as they look bring their own commands.
  function setupTextBox(ta, own) {
    const commands = own || createTextCommands(ta, { getSignature });
    commandsFor.set(ta, commands);
    ta.addEventListener('focus', () => {
      lastBox = ta;
      tools.sync();
    });
    ta.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        container.querySelector('.jot-new-input')?.focus();
        return;
      }
      commands.handleKeydown(e);
    });
  }

  function sectionBox(section, folder, locked) {
    const box = el('section', 'jot-section');
    const head = el('div', 'jot-section-head');
    const heading = el('input', 'jot-heading');
    heading.value = section.heading;
    heading.placeholder = 'Section';
    heading.readOnly = locked;
    head.append(el('span', 'jot-hash', '##'), heading);
    if (!locked) {
      const remove = el('button', 'icon-button jot-remove', '×');
      remove.title = 'Remove this section';
      head.append(remove);
    }
    box.append(head, liveBox(section.text, folder, locked, 'Write…  (Ctrl+T adds a task)'));
    return box;
  }

  // ---- Start page -----------------------------------------------------------------------

  function renderStart() {
    const vault = getVault();
    const page = el('div', 'note jot-start');
    page.append(el('h1', '', 'Notes'));
    page.append(el('p', 'jot-start-intro', "Quick notes that aren't filed in the wiki yet: a daily or weekly note, meeting jottings, ideas. Start one from a template, then add a section for each meeting or topic."));
    const templates = el('div', 'jot-templates');
    for (const template of getTemplates()) {
      const button = el('button', 'jot-template');
      button.append(el('span', 'jot-template-name', template.name), el('span', 'jot-template-hint', template.id ? 'Your template' : 'Built-in template'));
      button.addEventListener('click', () => onNew(template));
      templates.append(button);
    }
    page.append(templates);
    page.append(locationBox());

    const current = [...(vault?.notes.values() || [])]
      .filter((n) => n.inbox && !noteInfo(n).wrapped)
      .sort((a, b) => noteInfo(b).started.localeCompare(noteInfo(a).started));
    if (current.length) {
      page.append(el('h3', '', 'Open notes'));
      const list = el('div', 'jot-open-list');
      for (const note of current) {
        const button = el('button', 'jot-open-row');
        button.append(el('span', 'label', note.name), el('span', 'notes-date', when(noteInfo(note).started)));
        button.addEventListener('click', () => onOpen(note.id));
        list.append(button);
      }
      page.append(list);
    }
    container.replaceChildren(page);
  }

  // "New notes are saved in [personal ▾] / [Notes]" and the full path on disk. Notes are the
  // files in that folder (in any workspace folder), so changing it changes the Notes list.
  function locationBox() {
    const { alias, dir, folders } = getLocation();
    const box = el('div', 'jot-location');
    box.append(el('div', 'jot-location-title', 'New notes are saved in'));
    const row = el('div', 'jot-location-row');
    const select = el('select', 'jot-location-folder');
    select.title = 'Workspace folder';
    for (const f of folders) select.append(new Option(f.alias, f.alias, false, f.alias === alias));
    const input = el('input', 'jot-location-dir');
    input.value = dir;
    input.title = 'Folder inside it (created when the first note is saved)';
    input.spellcheck = false;
    row.append(select, el('span', 'jot-location-sep', '/'), input);
    const folder = folders.find((f) => f.alias === alias);
    const sep = folder?.root.includes('\\') ? '\\' : '/'; // Windows or macOS paths
    const path = el('div', 'jot-location-path', folder ? `${folder.root.replace(/[\\/]+$/, '')}${sep}${dir.replace(/[\\/]/g, sep)}` : '');
    box.append(row, path, el('div', 'jot-location-hint', 'Templates are kept in the Templates folder of the same workspace folder.'));

    select.addEventListener('change', () => setLocation({ alias: select.value }));
    const saveDir = () => {
      if (input.value.trim() !== dir) setLocation({ dir: input.value });
    };
    input.addEventListener('change', saveDir);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') input.blur();
      if (e.key === 'Escape') {
        input.value = dir;
        input.blur();
      }
    });
    return box;
  }

  // ---- Actions --------------------------------------------------------------------------

  async function setFront(changes) {
    await flush();
    if (session.error) return;
    session.front = withProperties(session.front, changes);
    session.queued = noteLines(collect()); // (a wrapped note's boxes are read-only, but still readable)
    await write(session);
    // The rescan after the write updated session.note; show it with its new state.
    if (!session.error) render();
  }

  const wrapUp = () => setFront({ status: 'wrapped', ended: isoDate() });
  const reopen = () => setFront({ status: 'open', ended: null });

  function addSection(name) {
    const section = sectionBox({ heading: name.trim() ? `${clock()} · ${name.trim()}` : clock(), text: '' }, session.note.folder, false);
    container.querySelector('.jot-new').before(section);
    liveFor.get(section.querySelector('.live-text'))?.focusEnd();
    schedule();
  }

  // ---- Events ---------------------------------------------------------------------------

  container.addEventListener('input', (e) => {
    if (!session || readOnly()) return;
    if (e.target.matches('.jot-new-input')) return;
    if (e.target.matches('textarea')) autosize(e.target);
    if (session.error) return;
    schedule();
  });
  container.addEventListener('keydown', (e) => {
    if (!session || readOnly()) return;
    if (e.target.matches('.jot-new-input') && e.key === 'Enter') {
      e.preventDefault();
      addSection(e.target.value);
      e.target.value = '';
    } else if (e.target.matches('.jot-heading, .jot-title') && e.key === 'Enter') {
      e.preventDefault();
      const box = e.target.matches('.jot-title')
        ? container.querySelector('.live-text')
        : e.target.closest('.jot-section').querySelector('.live-text');
      liveFor.get(box)?.focusEnd();
    } else if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
      e.preventDefault();
      flush();
    }
  });
  container.addEventListener('click', (e) => {
    const remove = e.target.closest('.jot-remove');
    if (!remove) return;
    const section = remove.closest('.jot-section');
    if (textOf(section.querySelector('.live-text')).trim() && !confirm('Remove this section and its text?')) return;
    section.remove();
    schedule();
  });
  // Leaving a box saves right away rather than after the pause.
  container.addEventListener('focusout', () => {
    if (timer) flush();
  });

  // ---- Status line ----------------------------------------------------------------------

  function setStatus(text) {
    const status = container.querySelector('.jot-status');
    if (!status) return;
    status.className = 'jot-status';
    status.textContent = readOnly() ? '' : text;
  }

  // A failed save: the text stays in the boxes; the user picks which version wins.
  function showError(message) {
    const status = container.querySelector('.jot-status');
    if (!status) return;
    status.className = 'jot-status error';
    status.textContent = `Not saved: ${message} `;
    const keep = el('button', 'link-button', 'Keep mine');
    keep.title = 'Replace the file with what you see here';
    keep.addEventListener('click', () => {
      const latest = getVault().notes.get(session.id);
      if (!latest) return;
      session.note = latest;
      session.base = latest.content.split(/\r?\n/);
      session.error = null;
      flush();
    });
    const reload = el('button', 'link-button', 'Load latest');
    reload.title = 'Throw away your changes here and show the file as it is now';
    reload.addEventListener('click', () => {
      const latest = getVault().notes.get(session.id);
      if (!latest) return;
      session.note = latest;
      session.base = latest.content.split(/\r?\n/);
      session.error = null;
      render();
    });
    status.append(keep, ' · ', reload);
  }

  // ---- Focus and sizing -----------------------------------------------------------------

  function focusState() {
    const active = document.activeElement;
    if (!active || !container.contains(active)) return null;
    const boxes = [...container.querySelectorAll('input, textarea')];
    return { index: boxes.indexOf(active), start: active.selectionStart, end: active.selectionEnd };
  }

  function restoreFocus({ index, start, end }) {
    const box = container.querySelectorAll('input, textarea')[index];
    if (!box) return;
    box.focus();
    try { box.setSelectionRange(start, end); } catch { /* not a text box */ }
  }

  function autosize(ta) {
    if (AUTOSIZE) return;
    ta.style.height = 'auto';
    ta.style.height = `${ta.scrollHeight + 2}px`;
  }

  function autosizeAll() {
    for (const ta of container.querySelectorAll('textarea')) autosize(ta);
  }

  return {
    show(id) {
      open(id);
      onChange?.();
    },
    shownId: () => session?.id || null,
    title: () => (session ? session.note.name : 'Notes'),
    flush: () => flush(),
    // After a rescan: pick up the note's new text, unless the user is in the middle of an edit.
    setVault(vault) {
      if (!session) {
        if (!container.hidden) renderStart();
        return;
      }
      const latest = vault.notes.get(session.id);
      if (!latest) {
        session = null;
        renderStart();
        onChange?.();
        return;
      }
      session.note = latest;
      const lines = latest.content.split(/\r?\n/);
      if (same(lines, session.base)) return;
      if (timer || session.saving || session.queued || session.error) return;
      session.base = lines;
      render({ keepFocus: true });
    },
    // The view was hidden while it was drawn; text boxes need sizing once it's visible.
    shown() {
      if (session) autosizeAll();
      else renderStart();
    },
  };
}

function same(a, b) {
  return a.length === b.length && a.every((line, i) => line === b[i]);
}

function when(iso) {
  return /^\d{4}-\d{2}-\d{2}$/.test(iso) ? friendlyDate(iso) : iso;
}

function el(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
