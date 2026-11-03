// The full-note editor (the ✎ Edit button / Ctrl+E). Like the Notes view, the note shows
// formatted while you edit it (livetext.js: click a paragraph, list or table to edit it), with
// the properties (YAML) in a box above. "Markdown" switches to the whole file as plain text.
// Save writes the file; Cancel drops the changes. The formatting toolbar and Insert menu are
// shared with the Notes view; the editing commands live in textcommands.js.

import { ICONS, INSERTS, createTextCommands } from './textcommands.js';
import { createLiveText } from './livetext.js';

const HEADINGS = ['Normal text', 'Heading 1', 'Heading 2', 'Heading 3', 'Heading 4'];

// [command, tooltip] in toolbar groups.
const TOOLBAR = [
  [['bold', 'Bold (Ctrl+B)'], ['italic', 'Italic (Ctrl+I)'], ['strike', 'Strikethrough (Ctrl+Shift+X)'], ['code', 'Inline code (Ctrl+`)']],
  [['bullet', 'Bulleted list (Ctrl+Shift+8)'], ['number', 'Numbered list (Ctrl+Shift+7)'], ['task', 'Task list (Ctrl+Shift+9)'], ['quote', 'Quote']],
  [['link', 'Link to a page (Ctrl+K)'], ['codeblock', 'Code block'], ['table', 'Table'], ['divider', 'Divider line']],
  [['outdent', 'Outdent (Shift+Tab)'], ['indent', 'Indent (Tab)']],
];

// The formatting toolbar's buttons: text style, the TOOLBAR groups and the Insert menu.
// Shared with the Notes view, which leaves out the text style menu (its sections are the
// headings) and inserts that go at the top of a file. The menus are buttons, not a <select>,
// so using them doesn't take the focus away from the text being edited.
export function toolbarMarkup({ topInserts = true, headings = true } = {}) {
  return `
    ${headings ? `<div class="tool-group heading-group">
      <button class="tool heading-button" title="Text style" aria-haspopup="menu"><span>${HEADINGS[0]}</span>${ICONS.chevron}</button>
      <div class="tool-menu heading-menu" role="menu" hidden>
        ${HEADINGS.map((label, level) => `<button role="menuitem" data-heading="${level}">${label}</button>`).join('')}
      </div>
    </div>` : ''}
    ${TOOLBAR.map((group) => `<div class="tool-group">${group.map(([cmd, title]) =>
      `<button class="tool" data-cmd="${cmd}" title="${title}" aria-label="${title}">${ICONS[cmd]}</button>`).join('')}</div>`).join('')}
    <div class="tool-group insert">
      <button class="tool insert-button" title="Insert a snippet or template" aria-haspopup="menu">${ICONS.plus}<span>Insert</span>${ICONS.chevron}</button>
      <div class="tool-menu" role="menu" hidden>
        ${INSERTS.map(([label, , where], i) => (topInserts || where !== 'top'
          ? `<button role="menuitem" data-insert="${i}">${label}</button>` : '')).join('')}
      </div>
    </div>`;
}

// Makes a toolbar built from toolbarMarkup work on the text box getTarget() returns
// ({ ta, commands }, or null). Returns sync(), which updates the text style label.
export function bindToolbar(toolbar, getTarget) {
  const menus = [...toolbar.querySelectorAll('.tool-menu')];
  const headingLabel = toolbar.querySelector('.heading-button span');
  const closeMenus = () => menus.forEach((m) => (m.hidden = true));
  const toggle = (menu) => {
    const wasHidden = menu.hidden;
    closeMenus();
    menu.hidden = !wasHidden;
  };
  // Keep focus in the text while clicking toolbar buttons.
  toolbar.addEventListener('mousedown', (e) => {
    if (e.target.closest('.tool, .tool-menu button')) e.preventDefault();
  });
  toolbar.addEventListener('click', (e) => {
    const target = getTarget();
    const tool = e.target.closest('[data-cmd]');
    if (tool) {
      target?.commands.run(tool.dataset.cmd);
      return;
    }
    const menuButton = e.target.closest('.insert-button, .heading-button');
    if (menuButton) {
      toggle(menuButton.parentElement.querySelector('.tool-menu'));
      return;
    }
    const item = e.target.closest('[data-insert]');
    if (item) {
      closeMenus();
      target?.commands.insertSnippet(INSERTS[Number(item.dataset.insert)]);
      return;
    }
    const heading = e.target.closest('[data-heading]');
    if (heading) {
      closeMenus();
      target?.commands.setHeading(Number(heading.dataset.heading));
      sync();
    }
  });
  document.addEventListener('mousedown', (e) => {
    if (!toolbar.contains(e.target) || !e.target.closest('.insert, .heading-group')) closeMenus();
  });
  function sync() {
    const target = getTarget();
    if (target && headingLabel) headingLabel.textContent = HEADINGS[Math.min(target.commands.headingLevel(), 4)];
  }
  return {
    sync,
    isMenuOpen: () => menus.some((m) => !m.hidden),
    closeMenu: closeMenus,
  };
}

// render(text, folder): formatted Markdown (the page viewer's); onOpenLink(id) and
// onOpenExternal(url) for links clicked in the formatted text.
export function createEditor(container, { onSave, onCancel, getSignature, render, renderEditable, onOpenLink, onOpenExternal }) {
  container.innerHTML = `
    <div class="editor-toolbar" role="toolbar" aria-label="Formatting">
      ${toolbarMarkup()}
      <span class="spacer"></span>
      <span class="editor-status"></span>
      <button class="secondary-button mode" title="Switch between the formatted note and its Markdown"></button>
      <button class="secondary-button cancel" title="Close without saving (Esc)">Cancel</button>
      <button class="primary-button save" title="Save (Ctrl+S)">Save</button>
    </div>
    <div class="editor-where"></div>
    <div class="editor-live">
      <div class="note jot editor-page">
        <details class="editor-props">
          <summary>Properties</summary>
          <textarea class="editor-props-text" spellcheck="false" placeholder="tags: [example]&#10;description: What this note is about"></textarea>
        </details>
        <div class="editor-body"></div>
      </div>
    </div>
    <textarea class="editor-text link-complete" spellcheck="true" hidden></textarea>`;

  const $ = (sel) => container.querySelector(sel);
  const ta = $('.editor-text');
  const props = $('.editor-props-text');
  const body = $('.editor-body');
  const commandsFor = new WeakMap(); // text box -> its editing commands
  const toolbar = bindToolbar($('.editor-toolbar'), () => {
    if (mode === 'raw') return { ta, commands: commandsFor.get(ta) };
    const box = lastBox?.isConnected && body.contains(lastBox) ? lastBox : body.querySelector('.rich-line.last .rich-text');
    return box && commandsFor.has(box) ? { ta: box, commands: commandsFor.get(box) } : null;
  });
  let note = null;
  let original = '';   // text as last loaded or saved
  let saving = false;
  let mode = 'live';   // 'live': formatted; 'raw': the whole file as Markdown
  let live = null;     // the formatted body (livetext.js)
  let front = null;    // the file's frontmatter: { present, close: its closing "---" line, bodyMissing }
  let lastBox = null;  // the text box the toolbar acts on

  setupTextBox(ta);
  $('.save').addEventListener('click', save);
  $('.cancel').addEventListener('click', () => onCancel());
  $('.mode').addEventListener('click', () => setMode(mode === 'live' ? 'raw' : 'live'));
  container.addEventListener('input', updateStatus);
  // Esc closes the editor, unless it's ending an edit inside the note (that only closes the box).
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented || !note || container.hidden || toolbar.isMenuOpen()) return;
    if (mode === 'live' && e.target.closest?.('.editor-live textarea, .editor-live input, .editor-live [contenteditable="true"]')) return;
    onCancel();
  });

  // Every text box (the raw one and the ones the formatted body makes): editing commands,
  // shortcuts, Ctrl+S, and the toolbar.
  function setupTextBox(box, own) {
    const commands = own || createTextCommands(box, { getSignature });
    commandsFor.set(box, commands);
    box.addEventListener('focus', () => {
      lastBox = box;
      toolbar?.sync();
    });
    for (const type of ['keyup', 'click']) box.addEventListener(type, () => toolbar.sync());
    box.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.code === 'KeyS') {
        e.preventDefault();
        save();
      } else {
        commands.handleKeydown(e);
      }
    });
  }

  // ---- The file as properties + formatted body, or as one Markdown text ---------------------

  // Shows `text` in the current mode.
  function load(text) {
    lastBox = null;
    if (mode === 'raw') {
      ta.value = text;
      return;
    }
    const lines = text.split('\n');
    const close = lines[0] === '---' ? lines.findIndex((l, i) => i > 0 && /^---\s*$/.test(l)) : -1;
    front = close > 0
      ? { present: true, close: lines[close], bodyMissing: close + 1 >= lines.length }
      : { present: false, close: '---', bodyMissing: false };
    props.value = close > 0 ? lines.slice(1, close).join('\n') : '';
    $('.editor-props').open = close > 0 && Boolean(props.value.trim());
    live = createLiveText({
      value: close > 0 ? lines.slice(close + 1).join('\n') : text,
      folder: note.folder,
      readOnly: false,
      placeholder: 'Write…  (Ctrl+T adds a task)',
      render,
      renderEditable,
      setupTextBox,
      onOpenLink,
      onOpenExternal,
      getSignature,
    });
    body.replaceChildren(live.root);
  }

  // The whole file as it stands in the editor.
  function text() {
    if (mode === 'raw') return ta.value;
    const yaml = props.value;
    if (!front.present && !yaml.trim()) return live.value;
    const head = ['---', ...(yaml === '' ? [] : yaml.split('\n')), front.close];
    if (front.bodyMissing && live.value === '') return head.join('\n');
    return [...head, live.value].join('\n');
  }

  function setMode(next) {
    const current = text();
    mode = next;
    $('.editor-live').hidden = mode === 'raw';
    ta.hidden = mode !== 'raw';
    $('.mode').textContent = mode === 'raw' ? 'Formatted' : 'Markdown';
    toolbar.closeMenu();
    load(current);
    if (mode === 'raw') ta.focus();
    updateStatus();
  }

  // ---- Saving --------------------------------------------------------------------------------

  async function save() {
    if (saving || !note) return;
    saving = true;
    container.classList.add('busy');
    try {
      await onSave(note, text(), original);
    } finally {
      saving = false;
      container.classList.remove('busy');
    }
    updateStatus();
  }

  function updateStatus() {
    if (!note) return;
    const words = (text().match(/\S+/g) || []).length;
    const dirty = isDirty();
    $('.editor-status').textContent = `${dirty ? 'Unsaved changes · ' : ''}${words} word${words === 1 ? '' : 's'}`;
    $('.editor-status').classList.toggle('dirty', dirty);
  }

  function isDirty() {
    return note !== null && text() !== original;
  }

  return {
    // Opens a note's text, formatted. color: the folder's color for the header dot.
    open(next, color) {
      note = next;
      original = next.content.replace(/\r\n/g, '\n');
      ta.dataset.folder = next.folder;
      const where = $('.editor-where');
      where.innerHTML = '<span class="folder-dot"></span><b></b><span></span>';
      where.querySelector('.folder-dot').style.background = color;
      where.querySelector('b').textContent = next.folder;
      where.querySelector('span:last-child').textContent = ` / ${next.path}`;
      mode = 'raw'; // so setMode('live') below reads the new text, not the previous note's
      ta.value = original;
      setMode('live');
      $('.editor-live').scrollTop = 0;
    },
    // After the file on disk changed: the new base text (the next Save replaces it).
    setOriginal(text) {
      original = text.replace(/\r\n/g, '\n');
      updateStatus();
    },
    close() {
      note = null;
    },
    isDirty,
    get note() {
      return note;
    },
  };
}
