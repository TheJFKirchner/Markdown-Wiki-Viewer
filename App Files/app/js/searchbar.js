// The search box in the top bar (Ctrl+F). Results appear as you type: pages (with a
// highlighted snippet) and tasks. Arrow keys + Enter or a click opens one. With an empty box
// it shows search tips and the tags in use.

import { search, highlightTerms, markTerms, QUERY_HELP } from './search.js';
import { noteLabel } from './vault.js';
import { friendlyDate, isoDate } from './tasks.js';
import { withAlpha } from './tags.js';

const MAX_RESULTS = 40;
const ICONS = {
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>',
  clear: '<svg viewBox="0 0 24 24"><path d="m7 7 10 10M17 7 7 17"/></svg>',
  open: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg>',
  progress: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
  done: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg>',
};

export function createSearchBar(root, { getVault, tagColors, onOpenNote, onOpenTask }) {
  root.innerHTML = `
    <div class="search-box">
      ${ICONS.search}
      <input class="search-input" type="text" placeholder="Search notes, #tags, tasks…" autocomplete="off" spellcheck="false" aria-label="Search">
      <kbd class="search-key">Ctrl F</kbd>
      <button class="search-clear" title="Clear" hidden>${ICONS.clear}</button>
    </div>
    <div class="search-panel" role="listbox" hidden></div>`;

  const input = root.querySelector('.search-input');
  const panel = root.querySelector('.search-panel');
  let results = [];   // open() functions for the rows, in order
  let active = 0;
  let timer = 0;

  input.addEventListener('focus', () => {
    root.classList.add('focused');
    render();
  });
  // Leaving the box any way (Tab, a click elsewhere, opening a result) closes the panel.
  // Clicks inside the panel keep focus in the box (see the mousedown handler below).
  input.addEventListener('blur', () => {
    panel.hidden = true;
    root.classList.remove('focused');
  });
  input.addEventListener('input', () => {
    root.querySelector('.search-clear').hidden = !input.value;
    clearTimeout(timer);
    timer = setTimeout(render, 60);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!results.length) return;
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + results.length) % results.length;
      markActive(true);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(timer);
      render();
      results[active]?.();
    } else if (e.key === 'Escape') {
      if (input.value) setQuery('');
      else close();
    }
  });
  root.querySelector('.search-clear').addEventListener('click', () => {
    setQuery('');
    input.focus();
  });
  // mousedown keeps focus in the box while clicking a result.
  panel.addEventListener('mousedown', (e) => e.preventDefault());
  panel.addEventListener('click', (e) => {
    const example = e.target.closest('[data-query]');
    if (example) {
      setQuery(example.dataset.query);
      return;
    }
    const row = e.target.closest('[data-result]');
    if (row) results[Number(row.dataset.result)]?.();
  });
  panel.addEventListener('mousemove', (e) => {
    const row = e.target.closest('[data-result]');
    if (row && Number(row.dataset.result) !== active) {
      active = Number(row.dataset.result);
      markActive(false);
    }
  });
  document.addEventListener('mousedown', (e) => {
    if (!root.contains(e.target)) close();
  });

  function setQuery(text) {
    input.value = text;
    root.querySelector('.search-clear').hidden = !text;
    render();
    input.focus();
    input.setSelectionRange(text.length, text.length);
  }

  function close() {
    panel.hidden = true;
    root.classList.remove('focused');
    input.blur();
  }

  function markActive(scroll) {
    for (const row of panel.querySelectorAll('[data-result]')) {
      const on = Number(row.dataset.result) === active;
      row.classList.toggle('active', on);
      if (on && scroll) row.scrollIntoView({ block: 'nearest' });
    }
  }

  function render() {
    const vault = getVault();
    if (!vault || document.activeElement !== input) return;
    panel.hidden = false;
    results = [];
    active = 0;
    if (!input.value.trim()) return renderHelp(vault);

    const { query, pages, tasks } = search(vault, input.value);
    const terms = highlightTerms(query);
    const today = isoDate();
    const fragment = document.createDocumentFragment();
    const summary = el('div', 'search-summary');
    summary.textContent = [
      pages.length && `${pages.length} page${pages.length === 1 ? '' : 's'}`,
      tasks.length && `${tasks.length} task${tasks.length === 1 ? '' : 's'}`,
    ].filter(Boolean).join(' · ') || 'No matches';
    fragment.append(summary);

    if (pages.length) {
      fragment.append(el('div', 'search-section', 'Pages'));
      for (const { note, snippet } of pages.slice(0, MAX_RESULTS)) {
        const row = resultRow(() => onOpenNote(note.id, terms));
        const title = el('div', 'result-title');
        title.append(folderDot(vault, note.folder));
        const name = el('span', 'result-name');
        name.innerHTML = markTerms(noteLabel(note), terms);
        title.append(name, el('span', 'result-where', `${note.folder} / ${note.path.replace(/\.(md|markdown)$/i, '')}`));
        for (const tag of note.tags.slice(0, 3)) title.append(tagChip(tag));
        row.append(title);
        if (snippet) {
          const text = el('div', 'result-snippet');
          text.innerHTML = markTerms(plain(snippet), terms);
          row.append(text);
        }
        fragment.append(row);
      }
      if (pages.length > MAX_RESULTS) fragment.append(el('div', 'search-more', `${pages.length - MAX_RESULTS} more pages; add words to narrow it down`));
    }

    if (tasks.length) {
      fragment.append(el('div', 'search-section', 'Tasks'));
      for (const task of tasks.slice(0, MAX_RESULTS)) {
        const row = resultRow(() => onOpenTask(task, terms));
        const title = el('div', 'result-title');
        const icon = el('span', `result-status status-${task.status}`);
        icon.innerHTML = ICONS[task.status];
        const text = el('span', 'result-name task');
        text.innerHTML = markTerms(plain(task.text), terms);
        title.append(icon, text);
        if (task.due) {
          const overdue = task.status !== 'done' && task.due < today;
          title.append(el('span', 'result-due' + (overdue ? ' overdue' : ''), friendlyDate(task.due, today)));
        }
        row.append(title);
        const where = el('div', 'result-meta');
        where.append(folderDot(vault, task.note.folder), noteLabel(task.note));
        if (task.signature) where.append(el('span', 'sig-chip', `~${task.signature}`));
        row.append(where);
        fragment.append(row);
      }
      if (tasks.length > MAX_RESULTS) fragment.append(el('div', 'search-more', `${tasks.length - MAX_RESULTS} more tasks`));
    }

    if (!pages.length && !tasks.length) {
      fragment.append(el('div', 'search-empty', 'Nothing matches. Try fewer words, or one of the filters below.'));
      fragment.append(helpList());
    }
    panel.replaceChildren(fragment);
    markActive(false);
  }

  function renderHelp(vault) {
    const fragment = document.createDocumentFragment();
    fragment.append(el('div', 'search-section', 'Search tips'), helpList());
    if (vault.tags.size) {
      fragment.append(el('div', 'search-section', 'Tags'));
      const chips = el('div', 'search-tags');
      for (const tag of [...vault.tags.keys()].slice(0, 24)) {
        const chip = tagChip(tag);
        chip.dataset.query = `#${tag}`;
        chips.append(chip);
      }
      fragment.append(chips);
    }
    panel.replaceChildren(fragment);
  }

  function helpList() {
    const list = el('div', 'search-help');
    for (const [example, meaning] of QUERY_HELP) {
      const row = el('button', 'help-row');
      row.dataset.query = example;
      row.append(el('code', '', example), el('span', '', meaning));
      list.append(row);
    }
    return list;
  }

  function resultRow(open) {
    const row = el('div', 'search-result');
    row.dataset.result = results.length;
    row.setAttribute('role', 'option');
    results.push(() => {
      close();
      open();
    });
    return row;
  }

  function tagChip(tag) {
    const color = tagColors.get(tag);
    const chip = el('span', 'result-tag', `#${tag}`);
    chip.style.color = color;
    chip.style.background = withAlpha(color, 0.14);
    return chip;
  }

  return {
    focus() {
      input.focus();
      input.select();
    },
  };
}

// Readable text from Markdown: [[a|b]] -> b, [[team:a]] -> a, **x** -> x.
export function plain(text) {
  return text
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '$2')
    .replace(/\[\[(?:[^\]:|#]+:)?([^\]|#]+)(#[^\]]*)?\]\]/g, '$1')
    .replace(/\*\*|__|~~|`/g, '')
    .replace(/(^|\s)[_*]([^_*]+)[_*](?=\s|$)/g, '$1$2');
}

function folderDot(vault, alias) {
  const dot = el('span', 'folder-dot');
  dot.style.background = vault.folders.find((f) => f.alias === alias)?.color || 'transparent';
  return dot;
}

function el(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
