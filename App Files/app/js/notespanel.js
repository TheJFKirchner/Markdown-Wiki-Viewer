// The Notes section at the top of the sidebar: open notes (newest first), then the wrapped
// ones (collapsed), and a + menu to start a note from a template, edit the templates, and
// pick the folder new notes go in.

import { noteInfo } from './notes.js';
import { friendlyDate } from './tasks.js';

const CHEVRON = '<svg class="chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>';
const PLUS = '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>';
const PENCIL = '<svg viewBox="0 0 24 24"><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
const WRAPPED_SHOWN = 30;

export function createNotesPanel(root, { getTemplates, getFolders, getNotesFolder, setNotesFolder, onOpen, onNew, onEditTemplate, onNewTemplate }) {
  let vault = null;
  let activeId = null;
  let open = load('notesPanelOpen') !== 'false';
  let wrappedOpen = false;

  root.innerHTML = `
    <div class="notes-head">
      <button class="notes-toggle">${CHEVRON}<span>Notes</span><span class="notes-count"></span></button>
      <button class="icon-button notes-new" title="New note">${PLUS}</button>
    </div>
    <div class="notes-menu" role="menu" hidden></div>
    <div class="notes-list"></div>`;
  const $ = (sel) => root.querySelector(sel);
  const menu = $('.notes-menu');

  $('.notes-toggle').addEventListener('click', () => {
    open = !open;
    store('notesPanelOpen', open);
    render();
  });
  $('.notes-new').addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.hidden) showMenu();
    else menu.hidden = true;
  });
  document.addEventListener('mousedown', (e) => {
    if (!menu.hidden && !root.contains(e.target)) menu.hidden = true;
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') menu.hidden = true;
  });

  menu.addEventListener('click', (e) => {
    const edit = e.target.closest('[data-edit]');
    const make = e.target.closest('[data-template]');
    if (edit) onEditTemplate(templateNamed(edit.dataset.edit));
    else if (make) onNew(templateNamed(make.dataset.template));
    else if (e.target.closest('.new-template')) onNewTemplate();
    else return;
    menu.hidden = true;
  });
  menu.addEventListener('change', (e) => {
    if (e.target.matches('select')) setNotesFolder(e.target.value);
  });

  root.addEventListener('click', (e) => {
    const row = e.target.closest('.notes-row');
    if (row) onOpen(row.dataset.id);
    if (e.target.closest('.wrapped-toggle')) {
      wrappedOpen = !wrappedOpen;
      render();
    }
  });

  const templateNamed = (name) => getTemplates().find((t) => t.name === name);

  function showMenu() {
    const folders = getFolders();
    menu.innerHTML = '';
    for (const template of getTemplates()) {
      const item = el('div', 'notes-menu-item');
      const make = el('button', 'notes-menu-make');
      make.dataset.template = template.name;
      make.setAttribute('role', 'menuitem');
      make.innerHTML = PLUS;
      make.append(el('span', '', `New ${template.name.toLowerCase()} note`));
      const edit = el('button', 'icon-button notes-menu-edit');
      edit.dataset.edit = template.name;
      edit.title = `Edit the ${template.name} template`;
      edit.innerHTML = PENCIL;
      item.append(make, edit);
      menu.append(item);
    }
    menu.append(el('div', 'notes-menu-sep'));
    const add = el('button', 'notes-menu-make new-template', 'New template…');
    menu.append(add);
    if (folders.length > 1) {
      const where = el('label', 'notes-menu-folder', 'Save new notes in ');
      const select = document.createElement('select');
      for (const f of folders) select.append(new Option(f.alias, f.alias, false, f.alias === getNotesFolder()));
      where.append(select);
      menu.append(where);
    }
    menu.hidden = false;
  }

  function row(note, info) {
    const button = el('button', 'notes-row' + (note.id === activeId ? ' active' : '') + (info.wrapped ? ' wrapped' : ''));
    button.dataset.id = note.id;
    button.title = `${note.folder} / ${note.path}`;
    const dot = el('span', 'folder-dot');
    dot.style.background = vault.folders.find((f) => f.alias === note.folder)?.color || 'transparent';
    // "2026-10-31 Daily" -> "Daily" (the date is shown on the right).
    const name = note.name.replace(/^\d{4}-\d{2}-\d{2}\s*/, '') || note.name;
    button.append(dot, el('span', 'label', name));
    if (info.started) button.append(el('span', 'notes-date', /^\d{4}-\d{2}-\d{2}$/.test(info.started) ? friendlyDate(info.started) : info.started));
    return button;
  }

  function render() {
    root.classList.toggle('collapsed', !open);
    const notes = [...(vault?.notes.values() || [])]
      .filter((n) => n.inbox)
      .map((note) => ({ note, info: noteInfo(note) }))
      .sort((a, b) => b.info.started.localeCompare(a.info.started) || b.note.name.localeCompare(a.note.name));
    const current = notes.filter((n) => !n.info.wrapped);
    const wrapped = notes.filter((n) => n.info.wrapped);
    $('.notes-count').textContent = current.length || '';

    const list = $('.notes-list');
    list.hidden = !open;
    if (!open) return;
    const rows = current.map(({ note, info }) => row(note, info));
    if (!notes.length) rows.push(el('div', 'notes-empty', 'No notes yet. Press + to start a daily note.'));
    if (wrapped.length) {
      const toggle = el('button', 'wrapped-toggle' + (wrappedOpen ? '' : ' collapsed'));
      toggle.innerHTML = CHEVRON;
      toggle.append(el('span', '', `Wrapped (${wrapped.length})`));
      rows.push(toggle);
      if (wrappedOpen) rows.push(...wrapped.slice(0, WRAPPED_SHOWN).map(({ note, info }) => row(note, info)));
    }
    list.replaceChildren(...rows);
  }

  return {
    setVault(next) {
      vault = next;
      render();
    },
    setActive(id) {
      activeId = id;
      for (const r of root.querySelectorAll('.notes-row')) r.classList.toggle('active', r.dataset.id === id);
    },
  };
}

function el(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function store(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

function load(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
