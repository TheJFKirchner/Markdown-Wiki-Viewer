// Editing a note in place, in two parts:
//   tags  double-click the tags: chips with ×, type to add (suggestions from tags in use)
//   body  double-click the title or text: everything below the properties becomes one box
// Click away (or ✓ / Ctrl+Enter) saves; Esc cancels. Only those lines of the file change.

import { ICONS, createTextCommands } from './textcommands.js';
import { cleanTag } from './vault.js';
import { withAlpha } from './tags.js';

const TOOLS = [
  ['bold', 'Bold (Ctrl+B)'], ['italic', 'Italic (Ctrl+I)'], ['strike', 'Strikethrough (Ctrl+Shift+X)'], ['code', 'Inline code'],
  null,
  ['link', 'Link to a page (Ctrl+K)'], ['bullet', 'Bulleted list'], ['task', 'Task'], ['number', 'Numbered list'],
];

export function createInlineEditor({ getSignature, getVault, tagColors, onSaveBody, onSaveTags, onClose }) {
  let current = null; // { kind, wrapper, hidden: [elements], save(), isDirty(), saving }

  // ---- Body ---------------------------------------------------------------------------

    // hide: [rendered title, rendered text]; the box goes where the text was.
  function openBody({ note, hide, selectText }) {
    if (current) return;
    const lines = note.content.split(/\r?\n/);
    const close = lines[0] === '---' ? lines.findIndex((l, i) => i > 0 && /^---\s*$/.test(l)) : -1;
    let start = close >= 0 ? close + 1 : 0;
    let original = lines.slice(start);
    while (original.length && !original[0].trim()) {
      original.shift();
      start++;
    }
    while (original.length && !original[original.length - 1].trim()) original.pop();

    const wrapper = el('div', 'inline-editor kind-body');
    wrapper.innerHTML = `
      <div class="block-toolbar">
        ${TOOLS.map((tool) => (tool
          ? `<button class="tool" data-cmd="${tool[0]}" title="${tool[1]}" aria-label="${tool[1]}">${ICONS[tool[0]]}</button>`
          : '<span class="tool-sep"></span>')).join('')}
        <span class="spacer"></span>
        <span class="block-hint">Click away or Ctrl+Enter to save · Esc to cancel</span>
        <button class="tool block-save" title="Save (Ctrl+Enter)">${ICONS.check}</button>
      </div>
      <textarea class="block-text link-complete" spellcheck="true"></textarea>
      <div class="block-error" role="alert"></div>`;
    const ta = wrapper.querySelector('textarea');
    ta.dataset.folder = note.folder;
    ta.value = original.join('\n');
    const commands = createTextCommands(ta, { getSignature });

    // Trailing blank lines don't count as a change (spaces at the end of the last line do).
    const trimEnd = (s) => s.replace(/(\n[ \t]*)+$/, '');
    const changed = () => trimEnd(ta.value) !== trimEnd(original.join('\n'));
    const save = () => {
      if (!changed()) return close_();
      const text = trimEnd(ta.value);
      return persist(() => onSaveBody({ note, start, original, lines: text.trim() ? text.split('\n') : [] }));
    };
    // The box takes the text's place (below the properties); the title is hidden too, since
    // its "# Title" line is the first line in the box.
    show(wrapper, hide, { kind: 'body', save, isDirty: changed }, hide[hide.length - 1]);

    const grow = () => {
      ta.style.height = 'auto';
      ta.style.height = `${ta.scrollHeight + 2}px`;
    };
    grow();
    ta.addEventListener('input', () => {
      grow();
      clearError();
    });
    toolbarClicks(wrapper, (cmd) => commands.run(cmd));
    ta.addEventListener('keydown', (e) => {
      if (handleCommonKeys(e)) return;
      commands.handleKeydown(e);
    });
    saveOnLeave(wrapper);

    ta.focus();
    const at = selectText ? ta.value.indexOf(selectText) : -1;
    if (at >= 0) ta.setSelectionRange(at, at + selectText.length);
    else ta.setSelectionRange(0, 0);
  }

  // ---- Tags ---------------------------------------------------------------------------

  // hide: the rendered tags (or the "Add tags" button); the editor goes in their place.
  function openTags({ note, hide }) {
    if (current) return;
    const original = [...note.tags];
    let tags = [...note.tags];

    const wrapper = el('div', 'inline-editor kind-tags');
    wrapper.innerHTML = `
      <div class="tag-editor">
        <span class="tag-chips"></span>
        <input class="tag-input" placeholder="Add a tag…" autocomplete="off" spellcheck="false">
        <button class="tool block-save" title="Save tags">${ICONS.check}</button>
      </div>
      <div class="tag-suggestions"></div>
      <div class="block-hint tag-hint">Enter, comma or space adds a tag · Backspace removes the last one · click away to save · Esc to cancel</div>
      <div class="block-error" role="alert"></div>`;
    const input = wrapper.querySelector('.tag-input');

    const render = () => {
      wrapper.querySelector('.tag-chips').replaceChildren(...tags.map((tag) => {
        const chip = el('span', 'tag-chip', `#${tag}`);
        const color = tagColors.get(tag);
        chip.style.color = color;
        chip.style.background = withAlpha(color, 0.15);
        const remove = el('button', 'tag-remove', '×');
        remove.title = `Remove #${tag}`;
        remove.dataset.remove = tag;
        chip.append(remove);
        return chip;
      }));
      // Tags already used in the workspace that match what's typed.
      const typed = cleanTag(input.value);
      const known = [...(getVault()?.tags.keys() || [])]
        .filter((t) => !tags.includes(t) && (!typed || t.includes(typed)))
        .slice(0, 8);
      const box = wrapper.querySelector('.tag-suggestions');
      box.replaceChildren(...known.map((t) => {
        const chip = el('button', 'tag-suggestion', `#${t}`);
        chip.dataset.add = t;
        return chip;
      }));
      box.hidden = !known.length;
    };
    const add = (text) => {
      const tag = cleanTag(text);
      if (tag && !tags.includes(tag)) tags.push(tag);
      input.value = '';
      render();
    };

    const save = () => {
      if (input.value.trim()) add(input.value);
      if (tags.join('\n') === original.join('\n')) return close_();
      return persist(() => onSaveTags({ note, tags }));
    };
    show(wrapper, hide, { kind: 'tags', save, isDirty: () => tags.join() !== original.join() || Boolean(input.value.trim()) });
    render();

    wrapper.addEventListener('mousedown', (e) => {
      if (e.target.closest('button')) e.preventDefault(); // keep typing focus
    });
    wrapper.addEventListener('click', (e) => {
      const remove = e.target.closest('[data-remove]');
      if (remove) {
        tags = tags.filter((t) => t !== remove.dataset.remove);
        render();
      }
      const suggestion = e.target.closest('[data-add]');
      if (suggestion) add(suggestion.dataset.add);
      if (e.target.closest('.block-save')) save();
      input.focus();
    });
    input.addEventListener('input', () => {
      if (/[,\s]$/.test(input.value)) add(input.value);
      else render();
      clearError();
    });
    input.addEventListener('keydown', (e) => {
      if (handleCommonKeys(e)) return;
      if (e.key === 'Enter') {
        e.preventDefault();
        if (input.value.trim()) add(input.value);
        else save();
      } else if (e.key === 'Backspace' && !input.value && tags.length) {
        tags.pop();
        render();
      }
    });
    saveOnLeave(wrapper);
    input.focus();
  }

  // ---- Shared ---------------------------------------------------------------------------

  function show(wrapper, hide, state, anchor = hide[0]) {
    anchor.before(wrapper);
    for (const element of hide) element.hidden = true;
    current = { ...state, wrapper, hidden: hide, saving: false };
    wrapper.scrollIntoView({ block: 'nearest' });
  }

  function handleCommonKeys(e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'Enter' || e.code === 'KeyS')) {
      e.preventDefault();
      current?.save();
      return true;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      cancel();
      return true;
    }
    return false;
  }

  function toolbarClicks(wrapper, run) {
    const toolbar = wrapper.querySelector('.block-toolbar');
    toolbar.addEventListener('mousedown', (e) => {
      if (e.target.closest('button')) e.preventDefault();
    });
    toolbar.addEventListener('click', (e) => {
      const tool = e.target.closest('[data-cmd]');
      if (tool) run(tool.dataset.cmd);
      if (e.target.closest('.block-save')) current?.save();
    });
  }

  // Clicking anywhere outside the editor saves it.
  function saveOnLeave(wrapper) {
    wrapper.addEventListener('focusout', () => {
      setTimeout(() => {
        if (current?.wrapper === wrapper && !wrapper.contains(document.activeElement)) current.save();
      }, 150);
    });
  }

  async function persist(write) {
    if (!current || current.saving) return;
    const edit = current;
    edit.saving = true;
    edit.wrapper.classList.add('busy');
    const result = await write();
    edit.saving = false;
    edit.wrapper.classList.remove('busy');
    if (current !== edit) return;
    if (result === true) close_();
    else showError(`${result} Press Esc to cancel and see the latest version.`);
  }

  // Esc: asks first if a body edit would be thrown away.
  function cancel({ force = false } = {}) {
    if (!current || current.saving) return;
    if (!force && current.kind === 'body' && current.isDirty() && !confirm('Discard your changes to this note?')) return;
    close_();
  }

  function close_() {
    if (!current) return;
    current.wrapper.remove();
    for (const element of current.hidden) element.hidden = false;
    current = null;
    onClose();
  }

  function showError(message) {
    const box = current?.wrapper.querySelector('.block-error');
    if (box) box.textContent = message;
  }

  function clearError() {
    const box = current?.wrapper.querySelector('.block-error');
    if (box) box.textContent = '';
  }

  return {
    openBody,
    openTags,
    cancel,
    save: () => current?.save(),
    isOpen: () => current !== null,
    isDirty: () => Boolean(current?.isDirty()),
  };
}

function el(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
