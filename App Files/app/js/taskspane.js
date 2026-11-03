// The Tasks tab: every task from every open folder.
//   Group by page (tasks from the same note together, in page order) or by due date.
//   Focus on one page to see every task on it or linking to it, completed ones included.
// Each task has a status dropdown (Incomplete / In progress / Complete), a due date, and
// signed subnotes. Text boxes autocomplete [[wikilinks]] (see autocomplete.js).

import { isoDate, addDays, friendlyDate } from './tasks.js';
import { noteLabel } from './vault.js';

const ICONS = {
  open: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg>',
  progress: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
  done: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg>',
  calendar: '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>',
  note: '<svg viewBox="0 0 24 24"><path d="M5 5h14v10l-4 4H5z"/><path d="M15 19v-4h4"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  clear: '<svg viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17"/></svg>',
  chevron: '<svg class="chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>',
  page: '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>',
};
const STATUSES = ['open', 'progress', 'done'];
const STATUS_LABELS = { open: 'Incomplete', progress: 'In progress', done: 'Complete' };
const FILTERS = [
  ['active', 'Open'],
  ['progress', 'In progress'],
  ['done', 'Complete'],
  ['all', 'All'],
];

export function createTasksPane(container, { renderInline, onOpen, actions, getSignature, requireSignature, getFolders }) {
  let vault = null;
  let filter = 'active';
  let groupBy = load('taskGroupBy') || 'page';
  let search = '';
  let focus = null;           // id of the page being focused on, or null for all tasks
  const expanded = new Set(); // task keys with subnotes shown

  container.innerHTML = `
    <div class="tasks-inner">
      <header class="tasks-header">
        <h2>Tasks</h2>
        <div class="segmented task-filters"></div>
        <input class="text-input task-search" type="search" placeholder="Search tasks">
        <button class="primary-button new-task">${ICONS.plus}New task</button>
      </header>
      <div class="tasks-subheader">
        <div class="focus-chip" hidden></div>
        <span class="spacer"></span>
        <span class="group-label">Group by</span>
        <div class="segmented group-by">
          <button data-group="page">Page</button>
          <button data-group="due">Due date</button>
        </div>
      </div>
      <form class="new-task-form" hidden>
        <div class="new-task-row">
          <input class="text-input new-text link-complete" placeholder="What needs doing? Type [[ to link a page" autocomplete="off">
          <label class="due-input" title="Due date">${ICONS.calendar}<input type="date" class="new-due"></label>
        </div>
        <div class="new-task-row">
          <label class="page-field">${ICONS.page}<span>Add to page</span>
            <input class="text-input new-page page-pick" placeholder="Search pages…" autocomplete="off" spellcheck="false">
          </label>
          <button class="primary-button" type="submit">Add task</button>
        </div>
        <p class="field-hint new-hint"></p>
      </form>
      <div class="task-groups"></div>
    </div>`;

  const $ = (sel) => container.querySelector(sel);
  const form = $('.new-task-form');

  // ---- Header -------------------------------------------------------------------------

  $('.task-filters').addEventListener('click', (e) => {
    const button = e.target.closest('[data-filter]');
    if (!button) return;
    filter = button.dataset.filter;
    render();
  });
  $('.group-by').addEventListener('click', (e) => {
    const button = e.target.closest('[data-group]');
    if (!button) return;
    groupBy = button.dataset.group;
    store('taskGroupBy', groupBy);
    render();
  });
  $('.focus-chip').addEventListener('click', (e) => {
    if (e.target.closest('.clear-focus')) setFocus(null);
    else if (focus) onOpen(focus);
  });
  $('.task-search').addEventListener('input', (e) => {
    search = e.target.value.trim().toLowerCase();
    render();
  });
  $('.new-task').addEventListener('click', () => (form.hidden ? openNewTask() : (form.hidden = true)));
  $('.new-page').addEventListener('change', updateHint);
  $('.new-page').addEventListener('blur', updateHint);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = $('.new-text').value.trim();
    if (!text) return $('.new-text').focus();
    const pageId = $('.new-page').dataset.id;
    if (!pageId) {
      $('.new-hint').textContent = 'Pick a page from the list.';
      $('.new-hint').classList.add('error');
      return $('.new-page').focus();
    }
    if (!requireSignature()) return;
    store('newTaskPage', pageId);
    form.classList.add('busy');
    const ok = await actions.addTask({ pageId, text, due: $('.new-due').value });
    form.classList.remove('busy');
    if (ok) {
      $('.new-text').value = '';
      $('.new-due').value = '';
      $('.new-text').focus();
      updateHint();
    }
  });

  // Opens the New task form. The page defaults to the given page, else the focused page,
  // else the last page used, else the first folder's Tasks page.
  function openNewTask(pageId) {
    if (!vault) return; // no folder has loaded yet
    form.hidden = false;
    const folders = getFolders();
    const candidates = [pageId, focus, load('newTaskPage'), ...folders.map((f) => `${f.alias}:Tasks.md`)];
    const id = candidates.find((c) => c && (vault.notes.has(c) || (/:Tasks\.md$/.test(c) && folders.some((f) => c.startsWith(f.alias + ':')))));
    setPage(id || '');
    $('.new-text').focus();
  }

  function setPage(id) {
    const input = $('.new-page');
    if (!id) {
      input.value = '';
      delete input.dataset.id;
    } else {
      const colon = id.indexOf(':');
      input.value = `${id.slice(0, colon)} / ${id.slice(colon + 1).replace(/\.(md|markdown)$/i, '')}`;
      input.dataset.id = id;
    }
    updateHint();
  }

  function updateHint() {
    const hint = $('.new-hint');
    hint.classList.remove('error');
    const id = $('.new-page').dataset.id;
    const signature = getSignature();
    const signed = signature ? `, signed ~${signature}` : '';
    $('.new-text').dataset.folder = id ? id.slice(0, id.indexOf(':')) : ''; // [[links]] resolve from this folder
    if (!id) {
      hint.textContent = 'Choose the page the task belongs to.';
    } else if (!vault.notes.has(id)) {
      hint.textContent = `Creates the page ${$('.new-page').value} with this task${signed}.`;
    } else {
      const hasSection = vault.notes.get(id).hasTasksSection;
      hint.textContent = hasSection
        ? `Added at the end of the page's Tasks section${signed}.`
        : `The page has no Tasks section yet, so one is added at the end of the page${signed}.`;
    }
  }

  let filterBeforeFocus = filter;
  function setFocus(id) {
    // A page's whole history, completed tasks included; leaving it restores the old filter.
    if (id && !focus) filterBeforeFocus = filter;
    filter = id ? 'all' : filterBeforeFocus;
    focus = id;
    render();
    container.scrollTop = 0;
  }

  // ---- Status dropdown ------------------------------------------------------------------

  function closeMenus(except) {
    for (const menu of container.querySelectorAll('.status-menu:not([hidden])')) {
      if (menu === except) continue;
      menu.hidden = true;
      menu.previousElementSibling.setAttribute('aria-expanded', 'false');
    }
  }
  document.addEventListener('mousedown', (e) => {
    if (!e.target.closest('.status-dropdown')) closeMenus();
  });
  container.addEventListener('keydown', (e) => {
    const menu = e.target.closest('.status-menu');
    if (!menu) return;
    const items = [...menu.querySelectorAll('[data-status]')];
    const at = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      items[(at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === 'Escape') {
      menu.hidden = true;
      menu.previousElementSibling.focus();
    }
  });

  // ---- Clicks on groups and cards ------------------------------------------------------

  container.addEventListener('click', async (e) => {
    const link = e.target.closest('a.wikilink');
    if (link) {
      e.preventDefault();
      if (link.dataset.id) onOpen(link.dataset.id, link.dataset.heading);
      return;
    }
    const groupAction = e.target.closest('[data-page-action]');
    if (groupAction) {
      const id = groupAction.closest('.task-group').dataset.page;
      if (groupAction.dataset.pageAction === 'open') onOpen(id);
      else setFocus(id);
      return;
    }

    const card = e.target.closest('.task-card');
    if (!card) return;
    const task = taskFor(card);
    if (!task) return;

    if (e.target.closest('.status-button')) {
      const menu = card.querySelector('.status-menu');
      closeMenus(menu);
      menu.hidden = !menu.hidden;
      card.querySelector('.status-button').setAttribute('aria-expanded', String(!menu.hidden));
      if (!menu.hidden) menu.querySelector(`[data-status="${task.status}"]`).focus();
      return;
    }
    const choice = e.target.closest('.status-menu [data-status]');
    if (choice) {
      closeMenus();
      if (choice.dataset.status !== task.status) await run(card, () => actions.setStatus(task, choice.dataset.status));
    } else if (e.target.closest('.clear-due')) {
      await run(card, () => actions.setDue(task, ''));
    } else if (e.target.closest('.due-chip')) {
      const input = card.querySelector('.due-chip input');
      try { input.showPicker(); } catch { input.focus(); }
    } else if (e.target.closest('.source')) {
      onOpen(task.note.id);
    } else if (e.target.closest('.notes-toggle')) {
      const key = taskKey(task);
      if (expanded.has(key)) expanded.delete(key);
      else expanded.add(key);
      render();
      if (expanded.has(key)) subnoteInput(key)?.focus();
    }
  });

  container.addEventListener('change', async (e) => {
    if (!e.target.matches('.due-chip input')) return;
    const card = e.target.closest('.task-card');
    const task = taskFor(card);
    if (task && e.target.value !== task.due) await run(card, () => actions.setDue(task, e.target.value));
  });

  container.addEventListener('submit', async (e) => {
    if (!e.target.matches('.add-subnote')) return;
    e.preventDefault();
    const input = e.target.querySelector('input');
    const text = input.value.trim();
    if (!text || !requireSignature()) return;
    const card = e.target.closest('.task-card');
    const task = taskFor(card);
    if (task && (await run(card, () => actions.addSubnote(task, text)))) subnoteInput(taskKey(task))?.focus();
  });

  // Runs an edit with the card marked busy; returns whether it succeeded.
  async function run(card, edit) {
    card.classList.add('busy');
    try {
      return await edit();
    } finally {
      card.classList.remove('busy');
    }
  }

  // Identifies a task across reloads (line numbers move when subnotes are added): its page, its
  // text, and which one it is among tasks with that same text on that page.
  let keys = new WeakMap();
  function taskKey(task) {
    if (!keys.has(task)) {
      keys = new WeakMap();
      const seen = new Map();
      for (const t of vault.tasks) {
        const base = `${t.note.id}|${t.text}`;
        const n = seen.get(base) || 0;
        seen.set(base, n + 1);
        keys.set(t, `${base}|${n}`);
      }
    }
    return keys.get(task) ?? `${task.note.id}|${task.text}|0`;
  }

  function taskFor(card) {
    return vault?.tasks.find((t) => taskKey(t) === card.dataset.key);
  }

  function subnoteInput(key) {
    return container.querySelector(`.task-card[data-key="${CSS.escape(key)}"] .subnote-input`);
  }

  // ---- Rendering -------------------------------------------------------------------

  function render() {
    if (!vault) return;
    if (focus && !vault.notes.has(focus)) focus = null; // the page was deleted or its folder removed
    const today = isoDate();

    let pool = vault.tasks;
    if (focus) pool = pool.filter((t) => t.note.id === focus || t.links.includes(focus));
    if (search) {
      pool = pool.filter(
        (t) =>
          t.text.toLowerCase().includes(search) ||
          t.subnotes.some((n) => n.text.toLowerCase().includes(search)) ||
          t.note.name.toLowerCase().includes(search),
      );
    }

    const counts = {
      active: pool.filter((t) => t.status !== 'done').length,
      progress: pool.filter((t) => t.status === 'progress').length,
      done: pool.filter((t) => t.status === 'done').length,
      all: pool.length,
    };
    $('.task-filters').innerHTML = FILTERS.map(
      ([value, label]) =>
        `<button data-filter="${value}" class="${value === filter ? 'active' : ''}">${label} <span class="count">${counts[value]}</span></button>`,
    ).join('');
    for (const button of container.querySelectorAll('.group-by button')) {
      button.classList.toggle('active', button.dataset.group === groupBy);
    }
    renderFocusChip();

    const shown = pool.filter((t) =>
      filter === 'active' ? t.status !== 'done' : filter === 'all' ? true : t.status === filter,
    );
    const groups = groupBy === 'page' ? pageGroups(shown, pool, today) : dueGroups(shown, today);

    const fragment = document.createDocumentFragment();
    for (const group of groups) fragment.append(group);
    if (!groups.length) {
      const empty = el('div', 'tasks-empty');
      empty.textContent = search
        ? 'No tasks match your search.'
        : focus
          ? 'No tasks match this filter for this page.'
          : filter === 'done'
            ? 'Nothing completed yet.'
            : 'Nothing here. Use New task to add one, or write "- [ ] something" in any note.';
      fragment.append(empty);
    }
    $('.task-groups').replaceChildren(fragment);
  }

  function renderFocusChip() {
    const chip = $('.focus-chip');
    chip.hidden = !focus;
    if (!focus) return;
    const note = vault.notes.get(focus);
    chip.innerHTML = `${ICONS.page}<span>Tasks for <b></b></span><button class="clear-focus" title="Show all tasks">${ICONS.clear}</button>`;
    chip.querySelector('b').textContent = noteLabel(note);
    chip.title = 'Tasks on this page or linking to it. Click to open the page.';
  }

  // One group per note, tasks in the order they appear on the page.
  // When focused, the focused page comes first and the rest are pages linking to it.
  function pageGroups(shown, pool, today) {
    const byNote = new Map();
    for (const task of shown) {
      if (!byNote.has(task.note.id)) byNote.set(task.note.id, []);
      byNote.get(task.note.id).push(task);
    }
    const firstDue = (tasks) => tasks.filter((t) => t.status !== 'done' && t.due).map((t) => t.due).sort()[0] || '9999';
    const ids = [...byNote.keys()].sort(
      (a, b) =>
        (b === focus) - (a === focus) ||
        firstDue(byNote.get(a)).localeCompare(firstDue(byNote.get(b))) ||
        vault.notes.get(a).name.localeCompare(vault.notes.get(b).name),
    );

    return ids.map((id) => {
      const note = vault.notes.get(id);
      const tasks = byNote.get(id).sort((a, b) => a.line - b.line);
      const all = pool.filter((t) => t.note.id === id);
      const section = el('section', 'task-group page-group');
      section.dataset.page = id;

      const header = el('header', 'page-header');
      const title = el('button', 'page-title');
      title.dataset.pageAction = 'open';
      title.title = 'Open this page';
      const dot = el('span', 'folder-dot');
      dot.style.background = vault.folders.find((f) => f.alias === note.folder)?.color || 'transparent';
      const folderPath = note.path.includes('/') ? note.path.slice(0, note.path.lastIndexOf('/')) : '';
      title.append(dot, el('span', 'page-where', folderPath ? `${note.folder} / ${folderPath} /` : `${note.folder} /`), el('span', 'page-name', noteLabel(note)));
      header.append(title);
      if (focus && id !== focus) header.append(el('span', 'page-relation', `links to ${noteLabel(vault.notes.get(focus))}`));

      header.append(el('span', 'page-counts', statusSummary(all)));
      if (id !== focus) {
        const focusButton = el('button', 'link-button page-focus', 'All tasks');
        focusButton.dataset.pageAction = 'focus';
        focusButton.title = 'Every task on this page or linking to it, completed ones included';
        header.append(focusButton);
      }
      section.append(header);
      for (const task of tasks) section.append(card(task, today, false));
      return section;
    });
  }

  function dueGroups(shown, today) {
    const open = shown.filter((t) => t.status !== 'done');
    const byDue = (a, b) =>
      (a.due || '9999').localeCompare(b.due || '9999') ||
      (a.status === 'progress' ? -1 : 0) - (b.status === 'progress' ? -1 : 0) ||
      a.text.localeCompare(b.text);
    const week = addDays(today, 7);
    const groups = [
      ['Overdue', 'overdue', open.filter((t) => t.due && t.due < today)],
      ['Today', 'today', open.filter((t) => t.due === today)],
      ['Next 7 days', '', open.filter((t) => t.due > today && t.due <= week)],
      ['Later', '', open.filter((t) => t.due > week)],
      ['No due date', '', open.filter((t) => !t.due)],
      ['Complete', 'complete', shown.filter((t) => t.status === 'done').sort((a, b) => (b.done || '').localeCompare(a.done || ''))],
    ];
    return groups
      .filter(([, , tasks]) => tasks.length)
      .map(([title, kind, tasks]) => {
        if (kind !== 'complete') tasks.sort(byDue);
        const section = el('section', `task-group ${kind}`);
        const heading = el('h3', '', `${title} `);
        heading.append(el('span', 'group-count', String(tasks.length)));
        section.append(heading);
        for (const task of tasks) section.append(card(task, today, true));
        return section;
      });
  }

  function card(task, today, showSource) {
    const key = taskKey(task);
    const article = el('article', `task-card status-${task.status}`);
    article.dataset.key = key;

    const main = el('div', 'task-main');
    main.append(statusDropdown(task));

    const body = el('div', 'task-body');
    const text = el('div', 'task-text');
    text.innerHTML = renderInline(task.text, task.note.folder);
    const meta = el('div', 'task-meta');

    // Due date chip; clicking it opens a date picker.
    const due = el('span', 'due-chip');
    const overdue = task.status !== 'done' && task.due && task.due < today;
    if (overdue) due.classList.add('overdue');
    else if (task.status !== 'done' && task.due === today) due.classList.add('today');
    else if (!task.due) due.classList.add('empty');
    due.innerHTML = ICONS.calendar;
    due.append(el('span', '', task.due ? (overdue ? `Overdue · ${friendlyDate(task.due, today)}` : friendlyDate(task.due, today)) : 'Add due date'));
    const picker = document.createElement('input');
    picker.type = 'date';
    picker.value = task.due;
    due.append(picker);
    due.title = task.due ? `Due ${task.due}. Click to change.` : 'Set a due date';
    meta.append(due);
    if (task.due) {
      const clear = el('button', 'clear-due');
      clear.title = 'Remove due date';
      clear.innerHTML = ICONS.clear;
      meta.append(clear);
    }
    if (task.status === 'done' && task.done) meta.append(el('span', 'done-chip', `Completed ${friendlyDate(task.done, today)}`));

    if (showSource) {
      const folder = vault.folders.find((f) => f.alias === task.note.folder);
      const source = el('button', 'source');
      const dot = el('span', 'folder-dot');
      dot.style.background = folder?.color || 'transparent';
      source.append(dot, `${task.note.folder} / ${task.note.path}`);
      source.title = 'Open the note this task is in';
      meta.append(source);
    }
    if (task.signature) meta.append(el('span', 'sig-chip', `~${task.signature}`));

    const toggle = el('button', 'notes-toggle' + (expanded.has(key) ? ' open' : ''));
    toggle.innerHTML = ICONS.note;
    toggle.append(task.subnotes.length ? `${task.subnotes.length} note${task.subnotes.length === 1 ? '' : 's'}` : 'Add note');
    meta.append(toggle);

    body.append(text, meta);
    main.append(body);
    article.append(main);

    if (expanded.has(key)) article.append(subnotes(task, today));
    return article;
  }

  function statusDropdown(task) {
    const wrap = el('div', 'status-dropdown');
    const button = el('button', `status-button status-${task.status}`);
    button.setAttribute('aria-haspopup', 'menu');
    button.setAttribute('aria-expanded', 'false');
    button.title = 'Change status';
    button.innerHTML = ICONS[task.status];
    button.append(el('span', 'status-label', STATUS_LABELS[task.status]));
    button.insertAdjacentHTML('beforeend', ICONS.chevron);

    const menu = el('div', 'status-menu');
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    for (const status of STATUSES) {
      const item = el('button', `status-option status-${status}` + (status === task.status ? ' current' : ''));
      item.dataset.status = status;
      item.setAttribute('role', 'menuitemradio');
      item.setAttribute('aria-checked', String(status === task.status));
      item.innerHTML = ICONS[status];
      item.append(el('span', '', STATUS_LABELS[status]));
      menu.append(item);
    }
    wrap.append(button, menu);
    return wrap;
  }

  function subnotes(task, today) {
    const notes = el('div', 'subnotes');
    for (const note of task.subnotes) {
      const row = el('div', 'subnote');
      const stamp = [note.date && friendlyDate(note.date, today), note.time].filter(Boolean).join(' ');
      if (stamp || note.signature) {
        const metaLine = el('div', 'subnote-meta', stamp);
        if (note.signature) metaLine.append(el('span', 'sig-chip', `~${note.signature}`));
        row.append(metaLine);
      }
      const noteText = el('div', 'subnote-text');
      noteText.innerHTML = renderInline(note.text, task.note.folder);
      row.append(noteText);
      notes.append(row);
    }
    const add = el('form', 'add-subnote');
    const input = document.createElement('input');
    input.className = 'text-input subnote-input link-complete';
    input.dataset.folder = task.note.folder;
    input.autocomplete = 'off';
    input.placeholder = 'Add a note, e.g. "Hitting a roadblock on…" Type [[ to link a page. Enter saves.';
    add.append(input);
    notes.append(add);
    return notes;
  }

  return {
    setVault(next) {
      vault = next;
      render();
    },
    // Show every task on this page or linking to it (completed ones included).
    focusPage: setFocus,
    // Open the New task form aimed at a page.
    newTaskOn: (id) => {
      setFocus(id);
      openNewTask(id);
    },
    refreshHint: updateHint,
  };
}

// "2 open · 1 in progress · 3 complete"
export function statusSummary(tasks) {
  const n = (status) => tasks.filter((t) => t.status === status).length;
  return [
    [n('open'), 'open'],
    [n('progress'), 'in progress'],
    [n('done'), 'complete'],
  ]
    .filter(([count]) => count)
    .map(([count, label]) => `${count} ${label}`)
    .join(' · ');
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
