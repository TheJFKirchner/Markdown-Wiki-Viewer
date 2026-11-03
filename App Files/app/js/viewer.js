// Renders a note: title, a Properties block built from its frontmatter, the Markdown body
// (via markdown-it, with clickable [[wikilinks]]) and a backlinks list.

import markdownit from '../lib/markdown-it.min.js';
import { parseLink, resolveTarget, normalizeTags, noteLabel, tasksForNote } from './vault.js';
import { statusSummary } from './taskspane.js';
import { withAlpha } from './tags.js';

const ICONS = {
  tags: '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  text: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  number: '<path d="M7 20V4L4 7M14 8a3 3 0 1 1 5 2.2L14 16h6"/>',
  checkbox: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  date: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  object: '<path d="M8 4H6a2 2 0 0 0-2 2v4l-2 2 2 2v4a2 2 0 0 0 2 2h2M16 4h2a2 2 0 0 1 2 2v4l2 2-2 2v4a2 2 0 0 1-2 2h-2"/>',
};

export function createViewer(container, { onOpen, onOpenExternal, onTag, onShowTasks, onEdit, onEditTags, onEditBody, onAddTask, onOpenInNotes, loadText, tagColors }) {
  let vault = null;
  let shownId = null;
  let currentFolder = null; // links resolve from the shown note's folder first

  // Raw HTML stays off: notes come from any folder and must not be able to run scripts.
  // breaks: a line break in a note is a line break on the page, as in the note editors.
  const md = markdownit({ html: false, linkify: true, typographer: true, breaks: true });
  const linkOptions = {
    resolve: (link) => resolveTarget(vault, link, currentFolder),
    describe: (id) => {
      const note = vault.notes.get(id) || vault.scripts.get(id);
      return note.folder === currentFolder ? note.path : `${note.folder}: ${note.path}`;
    },
  };
  md.use(wikilinks, linkOptions);
  // For text being edited as it looks (richtext.js): no typographer (it would turn ' into ’ and
  // the text could no longer be written back as it was), and every mark says how it was written.
  const mdEdit = markdownit({ html: false, linkify: true });
  mdEdit.use(wikilinks, linkOptions);
  for (const rule of ['strong_open', 'em_open', 's_open', 'link_open']) {
    mdEdit.renderer.rules[rule] = (tokens, idx, options, env, self) => {
      if (tokens[idx].markup) tokens[idx].attrSet('data-md', tokens[idx].markup);
      return self.renderToken(tokens, idx, options);
    };
  }
  mdEdit.renderer.rules.code_inline = (tokens, idx) =>
    `<code data-md="${tokens[idx].markup}">${mdEdit.utils.escapeHtml(tokens[idx].content)}</code>`;

  // A click on a tag shows it in the graph, but waits a moment so a double-click (which edits
  // the tags) can cancel it.
  let tagClick = 0;
  container.addEventListener('click', (e) => {
    const tag = e.target.closest('[data-tag]');
    if (tag) {
      clearTimeout(tagClick);
      if (e.detail === 1) tagClick = setTimeout(() => onTag(tag.dataset.tag), 280);
      return;
    }
    if (e.target.closest('.add-tags')) {
      onEditTags({ id: shownId, hide: [e.target.closest('.add-tags')] });
      return;
    }
    const a = e.target.closest('a');
    if (!a) return;
    e.preventDefault();
    const href = a.getAttribute('href') || '';
    if (a.dataset.id) {
      onOpen(a.dataset.id, a.dataset.heading);
    } else if (href.startsWith('#')) {
      // Same-note heading link; a bare "#" is a link to a note that doesn't exist yet.
      if (href.length > 1) headingIn(container, decodeURIComponent(href.slice(1)))?.scrollIntoView();
    } else if (/^(https?|mailto):/i.test(href)) {
      // Only web and mail links go to the browser: a relative one (Planets/Earth.md) would be
      // resolved against the app's own address and hand it to the browser.
      onOpenExternal(href);
    }
  });

  // Double-click the tags to edit them; double-click the title or text to edit the body.
  container.addEventListener('dblclick', (e) => {
    if (!vault.notes.has(shownId) || e.target.closest('.inline-editor, .note-path, .backlinks, .note-tasks')) return;
    const tagsRow = e.target.closest('.property[data-key="tags"], .property[data-key="tag"]');
    if (tagsRow) {
      clearTimeout(tagClick);
      window.getSelection()?.removeAllRanges();
      onEditTags({ id: shownId, hide: [tagsRow] });
      return;
    }
    if (e.target.closest('a, button, input')) return;
    const title = container.querySelector('.note-title');
    const body = container.querySelector('.note-body');
    if (e.target.closest('.note-title') || e.target.closest('.note-body')) {
      const selected = String(window.getSelection() || '').trim(); // the word double-clicked
      window.getSelection()?.removeAllRanges();
      onEditBody({ id: shownId, hide: [title, body], selectText: selected });
    }
  });

  return {
    setVault(next) {
      vault = next;
    },
    // Inline Markdown (links, bold, ...) for text from a note in `folder`.
    renderInline(text, folder) {
      currentFolder = folder;
      return md.renderInline(text);
    },
    // One line of inline Markdown for editing as it looks (richtext.js). -> HTML
    renderEditable(text, folder) {
      currentFolder = folder;
      return mdEdit.renderInline(text);
    },
    // A piece of Markdown from a note in `folder`, rendered like a page (tasks with status
    // icons and chips). -> a <div>
    renderMarkdown(text, folder) {
      currentFolder = folder;
      const div = el('div');
      div.innerHTML = md.render(text);
      decorateTasks(div);
      return div;
    },
    // After a search: mark the terms in the shown note and scroll to the first one, or to
    // the list item containing focusText (a task).
    highlight(terms, focusText) {
      const body = container.querySelector('.note-body');
      if (!body) return;
      let first = null;
      if (terms.length) {
        const source = `(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`;
        const test = new RegExp(source, 'i');
        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        for (const node of nodes) {
          if (!test.test(node.textContent)) continue;
          const fragment = document.createDocumentFragment();
          node.textContent.split(new RegExp(source, 'gi')).forEach((part, i) => {
            if (!part) return;
            if (i % 2) {
              const mark = el('mark', 'search-hit', part);
              first = first || mark;
              fragment.append(mark);
            } else {
              fragment.append(part);
            }
          });
          node.replaceWith(fragment);
        }
      }
      let target = first;
      if (focusText) {
        const item = [...body.querySelectorAll('li')].find((li) => li.textContent.includes(focusText));
        if (item) {
          item.classList.add('flash');
          target = item;
        }
      }
      target?.scrollIntoView({ block: 'center' });
    },
    // id: "alias:path" of a note (or of another file, which gets a placeholder).
    show(id, heading) {
      const note = vault.notes.get(id);
      shownId = id;
      const colon = id.indexOf(':');
      const alias = id.slice(0, colon);
      const path = id.slice(colon + 1);
      currentFolder = alias;

      // "● team / Planets/Jupiter.md"
      const article = document.createElement('div');
      const where = el('div', 'note-path');
      const dot = el('span', 'folder-dot');
      dot.style.background = vault.folders.find((f) => f.alias === alias)?.color || 'transparent';
      where.append(dot, el('span', 'note-folder', alias), ` / ${path}`);
      if (note) {
        where.append(el('span', 'spacer'));
        const add = el('button', 'secondary-button note-action', '+ Task');
        add.title = 'Add a task to this page';
        add.addEventListener('click', () => onAddTask(id));
        const edit = el('button', 'secondary-button note-action', '✎ Edit');
        edit.title = 'Edit this note (Ctrl+E)';
        edit.addEventListener('click', () => onEdit(id));
        where.append(add, edit);
        if (note.inbox) {
          // A note from the Notes folder: back to the Notes view to keep writing in it.
          const jot = el('button', 'secondary-button note-action', 'Open in Notes');
          jot.title = 'Write in this note in the Notes view';
          jot.addEventListener('click', () => onOpenInNotes(id));
          add.before(jot);
        }
      }
      article.append(where);

      const script = vault.scripts.get(id);
      if (script) {
        // A script: its code (read when shown, never searched for links) and the notes linking to it.
        article.append(el('h1', 'note-title', script.name));
        const code = el('pre', 'script-code');
        const inner = el('code', '', 'Loading…');
        code.append(inner);
        article.append(code, backlinks(script));
        loadText(id).then(
          (text) => {
            if (shownId === id) inner.textContent = text;
          },
          (err) => {
            if (shownId === id) inner.textContent = `Couldn't read this file: ${err.message}`;
          },
        );
      } else if (!note) {
        article.append(el('h1', '', path.slice(path.lastIndexOf('/') + 1)));
        article.append(el('p', 'empty-note', 'No preview for this file type.'));
      } else {
        // The title is the note's leading "# Heading" if it has one, otherwise its file name
        // (like Obsidian). Properties sit right under the title.
        let body = note.body;
        const h1 = el('h1', 'note-title');
        const leading = /^\s*#[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n|$)/.exec(body);
        if (leading) {
          h1.innerHTML = md.renderInline(leading[1]);
          body = body.slice(leading[0].length);
        } else {
          h1.textContent = note.name;
        }
        article.append(h1);

        const props = properties(note);
        if (props) article.append(props);
        if (!note.tags.length) {
          // Notes without tags get a way to add some (double-clicking tags edits them too).
          const add = el('button', 'add-tags', '+ Add tags');
          add.title = 'Add tags to this note';
          article.append(add);
        }

        const content = el('div', 'note-body');
        content.title = 'Double-click to edit';
        if (body.trim()) {
          content.innerHTML = md.render(body);
          decorateTasks(content);
        } else {
          content.innerHTML = '<p class="empty-note">This note has no text yet. Double-click to write some.</p>';
        }
        article.append(content);
        const tasks = taskSummary(note);
        if (tasks) article.append(tasks);
        article.append(backlinks(note));
        addHeadingIds(article);
      }

      container.replaceChildren(article);
      const target = heading && headingIn(container, heading);
      if (target) target.scrollIntoView();
      else container.parentElement.scrollTop = 0;
    },
  };

  // ---- Properties (frontmatter) ------------------------------------------------------

  function properties(note) {
    if (!note.properties && !note.propertiesError) return null;
    const section = el('section', 'properties');
    section.append(el('div', 'properties-title', 'Properties'));

    if (note.propertiesError) {
      section.append(el('div', 'property-error', `These properties couldn't be read: ${note.propertiesError}`));
      return section;
    }
    const entries = Object.entries(note.properties);
    if (!entries.length) section.append(el('div', 'property-empty', 'No properties'));
    for (const [key, value] of entries) section.append(propertyRow(key, value));
    return section;
  }

  function propertyRow(key, value) {
    const isTags = key === 'tags' || key === 'tag';
    const type = isTags ? 'tags' : valueType(value);

    const row = el('div', 'property');
    row.dataset.key = key;
    const name = el('div', 'property-key');
    name.innerHTML = `<svg viewBox="0 0 24 24">${ICONS[type]}</svg>`;
    name.append(el('span', '', key));
    name.title = key;

    const cell = el('div', `property-value ${type}`);
    if (isTags) {
      const tags = normalizeTags(value);
      if (!tags.length) cell.append(el('span', 'property-empty', 'Empty'));
      for (const tag of tags) cell.append(tagPill(tag));
    } else {
      renderValue(cell, value);
    }
    row.append(name, cell);
    return row;
  }

  function renderValue(cell, value) {
    if (value == null || value === '' || (Array.isArray(value) && !value.length)) {
      cell.append(el('span', 'property-empty', 'Empty'));
    } else if (Array.isArray(value)) {
      for (const item of value) {
        const chip = el('span', 'chip');
        if (item !== null && typeof item === 'object') chip.textContent = JSON.stringify(item);
        else chip.innerHTML = md.renderInline(String(item));
        cell.append(chip);
      }
    } else if (typeof value === 'boolean') {
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = value;
      box.disabled = true;
      cell.append(box, el('span', '', value ? 'Yes' : 'No'));
    } else if (typeof value === 'object') {
      for (const [k, v] of Object.entries(value)) {
        const line = el('div', 'nested');
        line.append(el('span', 'nested-key', k + ':'), ' ');
        const v2 = el('span');
        if (v !== null && typeof v === 'object') v2.textContent = JSON.stringify(v);
        else v2.innerHTML = md.renderInline(String(v ?? ''));
        line.append(v2);
        cell.append(line);
      }
    } else {
      // Text and numbers; inline Markdown works, so [[links]] and **bold** render.
      cell.innerHTML = md.renderInline(String(value));
    }
  }

  function tagPill(tag) {
    const color = tagColors.get(tag);
    const pill = el('button', 'tag-pill', '#' + tag);
    pill.dataset.tag = tag;
    pill.title = `Show notes tagged #${tag} in the graph`;
    pill.style.color = color;
    pill.style.background = withAlpha(color, 0.15);
    pill.style.borderColor = withAlpha(color, 0.4);
    return pill;
  }

  // ---- Tasks on or about this page -----------------------------------------------------

  function taskSummary(note) {
    const tasks = tasksForNote(vault, note.id);
    if (!tasks.length) return null;
    const section = el('section', 'note-tasks');
    const elsewhere = tasks.filter((t) => t.note.id !== note.id).length;
    const text = el('div', 'note-tasks-text');
    text.append(el('b', '', `Tasks `), statusSummary(tasks));
    if (elsewhere) text.append(el('span', 'note-tasks-elsewhere', ` (${elsewhere} on other pages that link here)`));
    const button = el('button', 'secondary-button show-tasks', 'Show in Tasks');
    button.addEventListener('click', () => onShowTasks(note.id));
    section.append(text, button);
    return section;
  }

  // ---- Backlinks -----------------------------------------------------------------------

  function backlinks(note) {
    const section = el('section', 'backlinks');
    section.append(el('h4', '', `Linked mentions (${note.backlinks.length})`));
    if (!note.backlinks.length) {
      section.append(el('div', 'none', 'No notes link here yet.'));
      return section;
    }
    const list = document.createElement('ul');
    const from = note.backlinks.map((id) => vault.notes.get(id)).sort((a, b) => a.name.localeCompare(b.name));
    for (const source of from) {
      const a = el('a', 'wikilink', noteLabel(source));
      a.href = '#';
      a.dataset.id = source.id;
      const li = document.createElement('li');
      li.append(a);
      // Mentions from other folders show where they come from.
      if (source.folder !== note.folder && !source.duplicate) li.append(el('span', 'from-folder', source.folder));
      list.append(li);
    }
    section.append(list);
    return section;
  }
}

// ---- Tasks in notes ----------------------------------------------------------------------
// "- [ ] text due:2026-11-02 ~alex" renders as a status icon, the text, and chips.

export const TASK_ICONS = {
  open: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg>',
  progress: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/></svg>',
  done: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg>',
};
export const TASK_TITLES = { open: 'Incomplete', progress: 'In progress', done: 'Complete' };
const TASK_PREFIX = /^\[([ xX/])\](?:\s|$)/; // (a new, still empty task is just "[ ]")
const TOKEN = /(?<=^|\s)(due:\d{4}-\d{2}-\d{2}|done:\d{4}-\d{2}-\d{2}|~[\p{L}\p{N}_-]+)/u;

function decorateTasks(root) {
  for (const li of root.querySelectorAll('li')) {
    const host = li.firstElementChild?.tagName === 'P' ? li.firstElementChild : li;
    const first = host.firstChild;
    if (!first || first.nodeType !== Node.TEXT_NODE) continue;
    const m = TASK_PREFIX.exec(first.textContent);
    if (!m) continue;
    const status = { ' ': 'open', '/': 'progress', x: 'done', X: 'done' }[m[1]];
    first.textContent = first.textContent.slice(m[0].length);
    li.classList.add('task-item', `status-${status}`);
    const icon = el('span', 'task-icon');
    icon.innerHTML = TASK_ICONS[status];
    icon.title = TASK_TITLES[status];
    host.prepend(icon);
  }
  // Chips for due:/done: dates and ~signatures in tasks and their subnotes.
  for (const li of root.querySelectorAll('.task-item, .task-item li')) {
    const host = li.firstElementChild?.tagName === 'P' ? li.firstElementChild : li;
    for (const node of [...host.childNodes]) if (node.nodeType === Node.TEXT_NODE) chipify(node);
  }
}

function chipify(textNode) {
  const parts = textNode.textContent.split(new RegExp(TOKEN.source, 'gu'));
  if (parts.length === 1) return;
  const fragment = document.createDocumentFragment();
  parts.forEach((part, i) => {
    if (i % 2 === 0) {
      if (part) fragment.append(part);
    } else if (part.startsWith('~')) {
      fragment.append(el('span', 'sig-chip', part));
    } else {
      const [kind, date] = part.split(':');
      fragment.append(el('span', `date-chip ${kind}`, `${kind === 'due' ? 'due' : 'done'} ${date}`));
    }
  });
  textNode.replaceWith(fragment);
}

function valueType(value) {
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'boolean') return 'checkbox';
  if (typeof value === 'number') return 'number';
  if (value !== null && typeof value === 'object') return 'object';
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}([T ][\d:.]+Z?)?$/.test(value)) return 'date';
  return 'text';
}

function el(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// markdown-it plugin: [[Target]], [[Target|Text]], [[Target#Heading]], [[folder:Target]].
function wikilinks(md, { resolve, describe }) {
  md.inline.ruler.before('link', 'wikilink', (state, silent) => {
    const start = state.pos;
    if (state.src.charCodeAt(start) !== 0x5b || state.src.charCodeAt(start + 1) !== 0x5b) return false;
    const end = state.src.indexOf(']]', start + 2);
    if (end < 0) return false;
    const inner = state.src.slice(start + 2, end);
    if (!inner.trim() || /[[\]\n]/.test(inner)) return false;

    if (!silent) {
      const link = parseLink(inner);
      const { target, heading } = link;
      const id = target ? resolve(link) : null;
      const open = state.push('link_open', 'a', 1);
      open.attrSet('href', '#');
      open.attrSet('data-src', state.src.slice(start, end + 2)); // as written, for editing
      open.attrSet('class', id || !target ? 'wikilink' : 'wikilink unresolved');
      if (id) open.attrSet('data-id', id);
      if (id) open.attrSet('title', describe(id));
      if (heading) open.attrSet('data-heading', heading);
      if (!id && target) open.attrSet('title', `"${link.folder ? link.folder + ':' : ''}${target}" doesn't exist yet`);
      if (!target && heading) open.attrSet('href', '#' + slug(heading));
      const text = state.push('text', '', 0);
      text.content = link.text || (heading ? (target ? `${target} > ${heading}` : heading) : target);
      state.push('link_close', 'a', -1);
    }
    state.pos = end + 2;
    return true;
  });
}

function slug(text) {
  return text.trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '');
}

// Heading ids get a prefix, so a heading such as "Editor" or "Toast" can't take the id of one of
// the app's own elements.
const HEADING_ID = 'h-';

function addHeadingIds(root) {
  for (const h of root.querySelectorAll('h1, h2, h3, h4, h5, h6')) h.id = HEADING_ID + slug(h.textContent);
}

function headingIn(root, heading) {
  const s = slug(heading);
  return s ? root.querySelector(`#${CSS.escape(HEADING_ID + s)}`) : null;
}
