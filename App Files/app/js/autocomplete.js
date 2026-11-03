// Note-name suggestions for text boxes. Two kinds of box get them:
//
//   class="link-complete"  (input or textarea) typing "[[" suggests notes and inserts
//                          [[Name]], or [[alias:Name]] when a plain link would open a
//                          different note. data-folder = the folder the text is saved in.
//   class="page-pick"      (input) the whole box picks a page. The chosen note's id goes in
//                          data-id and a "change" event fires. Folders without a Tasks page
//                          also offer "Tasks (new page)".

import { resolveTarget, noteLabel } from './vault.js';

const MAX_SUGGESTIONS = 8;
const OPEN_LINK = /\[\[([^[\]|#\n]*)$/; // "[[" with no closing "]]" before the caret

export function createLinkAutocomplete({ getVault }) {
  const list = document.createElement('div');
  list.className = 'link-suggest';
  list.setAttribute('role', 'listbox');
  list.hidden = true;
  document.body.append(list);

  let input = null;   // the box being completed
  let mode = 'link';  // 'link' or 'pick'
  let start = 0;      // link mode: where the typed query begins (just after "[[")
  let items = [];
  let index = 0;

  const isLinkBox = (el) => el.matches?.('.link-complete');
  const isPickBox = (el) => el.matches?.('input.page-pick');

  document.addEventListener(
    'input',
    (e) => {
      if (isLinkBox(e.target)) updateLink(e.target);
      else if (isPickBox(e.target)) {
        delete e.target.dataset.id; // typing un-picks the page until a suggestion is chosen
        updatePick(e.target);
      }
    },
    true,
  );
  document.addEventListener('focusin', (e) => {
    if (isPickBox(e.target)) updatePick(e.target);
  });
  // Capture phase, so Enter picks a suggestion instead of submitting a form or adding a line.
  document.addEventListener(
    'keydown',
    (e) => {
      if (list.hidden || e.target !== input) return;
      const keys = { ArrowDown: 1, ArrowUp: -1 };
      if (e.key in keys) {
        index = (index + keys[e.key] + items.length) % items.length;
        render();
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        accept(index);
      } else if (e.key === 'Escape') {
        close();
      } else {
        return;
      }
      e.preventDefault();
      e.stopPropagation();
    },
    true,
  );
  document.addEventListener('focusout', (e) => {
    if (e.target === input) close();
  });
  window.addEventListener('resize', close);
  document.addEventListener('scroll', () => input && position(), true);
  // mousedown (not click) so the box doesn't lose focus first.
  list.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const row = e.target.closest('[data-index]');
    if (row) accept(Number(row.dataset.index));
  });

  function updateLink(el) {
    const caret = el.selectionStart;
    const match = OPEN_LINK.exec(el.value.slice(0, caret));
    const vault = getVault();
    if (!match || !vault) return close();
    input = el;
    mode = 'link';
    start = caret - match[1].length;
    items = suggest(vault, match[1], el.dataset.folder, { scripts: true });
    show();
  }

  function updatePick(el) {
    const vault = getVault();
    if (!vault) return close();
    input = el;
    mode = 'pick';
    items = suggest(vault, el.dataset.id ? '' : el.value, '');
    // A "Tasks" page for folders that don't have one yet.
    const q = (el.dataset.id ? '' : el.value).trim().toLowerCase();
    if (!q || 'tasks'.startsWith(q.replace(/^.*[/:]\s*/, ''))) {
      for (const folder of vault.folders) {
        const id = `${folder.alias}:Tasks.md`;
        if (!vault.notes.has(id) && (!q.includes('/') || q.startsWith(folder.alias))) {
          items.push({ id, name: 'Tasks', folder: folder.alias, path: 'Tasks.md', isNew: true });
        }
      }
    }
    show();
  }

  function show() {
    if (!items.length) return close();
    index = 0;
    render();
    position();
  }

  function accept(i) {
    const note = items[i];
    if (!note || !input) return;
    if (mode === 'pick') {
      input.value = pageLabel(note);
      input.dataset.id = note.id;
      const el = input;
      close();
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    const vault = getVault();
    const resolvesHere = resolveTarget(vault, { folder: '', target: note.name }, input.dataset.folder) === note.id;
    const text = resolvesHere ? note.name : `${note.folder}:${note.name}`;
    const caret = input.selectionStart;
    const closing = input.value.slice(caret, caret + 2) === ']]' ? 2 : 0; // don't double an existing "]]"
    replaceText(input, start - 2, caret + closing, `[[${text}]]`);
    close();
  }

  function render() {
    const vault = getVault();
    list.replaceChildren(
      ...items.map((note, i) => {
        const row = document.createElement('div');
        row.className = 'suggestion' + (i === index ? ' active' : '');
        row.dataset.index = i;
        row.setAttribute('role', 'option');
        const dot = document.createElement('span');
        dot.className = 'folder-dot';
        dot.style.background = vault.folders.find((f) => f.alias === note.folder)?.color || 'transparent';
        const name = document.createElement('span');
        name.className = 'suggestion-name';
        name.textContent = note.isNew ? 'Tasks' : noteLabel(note);
        const where = document.createElement('span');
        where.className = 'suggestion-path';
        where.textContent = `${note.folder} / ${note.path.replace(/\.(md|markdown)$/i, '')}` + (note.isNew ? ' · new page' : '');
        row.append(dot, name, where);
        return row;
      }),
    );
    list.hidden = false;
  }

  // Under the caret for a textarea, under the box for an input; above if there's no room.
  function position() {
    const rect = input.getBoundingClientRect();
    const anchor = input.tagName === 'TEXTAREA' ? caretRect(input, input.selectionStart) : rect;
    if (anchor.bottom < rect.top || anchor.top > rect.bottom) return close(); // scrolled out of view
    list.style.left = `${Math.min(anchor.left, window.innerWidth - 300)}px`;
    list.style.width = input.tagName === 'TEXTAREA' ? '360px' : `${Math.min(Math.max(rect.width, 280), 460)}px`;
    const below = window.innerHeight - anchor.bottom;
    if (below < 240 && anchor.top > below) {
      list.style.top = '';
      list.style.bottom = `${window.innerHeight - anchor.top + 4}px`;
    } else {
      list.style.bottom = '';
      list.style.top = `${anchor.bottom + 4}px`;
    }
  }

  function close() {
    list.hidden = true;
    input = null;
  }
}

// "personal / Gear/My Telescope"
export function pageLabel(note) {
  return `${note.folder} / ${note.path.replace(/\.(md|markdown)$/i, '')}`;
}

// Replaces text in an input/textarea the way typing would, so Ctrl+Z can undo it.
export function replaceText(el, from, to, text) {
  el.focus();
  el.setSelectionRange(from, to);
  const ok = text ? document.execCommand('insertText', false, text) : document.execCommand('delete');
  if (!ok) {
    el.setRangeText(text, from, to, 'end');
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }
}

// Screen position of a caret inside a textarea, measured with a hidden copy of it.
function caretRect(textarea, position) {
  const style = getComputedStyle(textarea);
  const mirror = document.createElement('div');
  for (const prop of [
    'boxSizing', 'width', 'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'fontStyle', 'fontVariant', 'fontWeight',
    'fontSize', 'lineHeight', 'fontFamily', 'letterSpacing', 'wordSpacing', 'tabSize', 'textIndent',
  ]) {
    mirror.style[prop] = style[prop];
  }
  Object.assign(mirror.style, {
    position: 'absolute', visibility: 'hidden', top: '0', left: '-9999px', whiteSpace: 'pre-wrap', overflowWrap: 'break-word',
  });
  mirror.textContent = textarea.value.slice(0, position);
  const marker = document.createElement('span');
  marker.textContent = '​';
  mirror.append(marker);
  document.body.append(mirror);
  const box = textarea.getBoundingClientRect();
  const lineHeight = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.4;
  const top = box.top + marker.offsetTop - textarea.scrollTop;
  const left = box.left + marker.offsetLeft - textarea.scrollLeft;
  mirror.remove();
  return { left, top, bottom: top + lineHeight };
}

// Notes whose name matches the query: starts-with first, then word starts, then anywhere.
// "team:jup" (or "team / jup") limits the search to the folder with alias "team".
// scripts: also suggest scripts (.sql, .py...), by file name with the extension.
function suggest(vault, query, fromFolder, { scripts = false } = {}) {
  let folder = '';
  let q = query.trim().toLowerCase();
  const sep = /^([^:/]+)\s*[:/]\s*(.*)$/.exec(q);
  if (sep && vault.folders.some((f) => f.alias.toLowerCase() === sep[1].trim())) {
    folder = sep[1].trim();
    q = sep[2];
  }
  const scored = [];
  const candidates = scripts ? [...vault.notes.values(), ...vault.scripts.values()] : vault.notes.values();
  for (const note of candidates) {
    if (note.template || (folder && note.folder.toLowerCase() !== folder)) continue;
    const name = note.name.toLowerCase();
    let score;
    if (!q || name.startsWith(q)) score = 0;
    else if (name.split(/[\s\-_]+/).some((w) => w.startsWith(q))) score = 1;
    else if (name.includes(q) || note.path.toLowerCase().includes(q)) score = 2;
    else continue;
    if (fromFolder && note.folder !== fromFolder) score += 0.5; // the text's own folder first
    scored.push([score, note]);
  }
  return scored
    .sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name))
    .slice(0, MAX_SUGGESTIONS)
    .map(([, note]) => note);
}
