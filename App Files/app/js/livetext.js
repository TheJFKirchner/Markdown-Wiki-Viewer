// A box of Markdown edited as it looks, used for each part of a note in the Notes view
// (notesview.js) and for the body in the full editor (editor.js):
//   - every line is a row you type in directly, formatted: headings, bullets, numbers and quotes
//     are drawn for you, bold stays bold and [[links]] stay links (richtext.js turns it back
//     into Markdown as you type). Enter, Backspace, Tab and the arrows move between rows like
//     in a word processor; "- ", "1. ", "# ", "> " and "[ ] " at the start of a row make it a
//     bullet, number, heading, quote or task
//   - tasks: click the icon to mark one complete, click the task to edit it in a small form
//     (text, status, due date, dated notes); Ctrl+T or "+ Task" adds one
//   - tables are a grid of cells, with buttons to add or remove rows and columns
//   - code blocks (and the rare line the rows can't show exactly) are edited as Markdown
// Every change fires an "input" event on the box, which is how the Notes view knows to save.

import markdownit from '../lib/markdown-it.min.js';
import { parseTasks, withStatus, withDue, withText, withSubnoteText, emptyTaskLine, newSubnoteLine, isoDate, friendlyDate } from './tasks.js';
import { TASK_ICONS, TASK_TITLES } from './viewer.js';
import { INSERTS, SHORTCUTS, SHIFT_SHORTCUTS } from './textcommands.js';
import { classify, indentDepth, serialize, caretOffset, setCaret, caretAtStart, caretAtEnd, caretOnEdgeLine, cutAfterCaret } from './richtext.js';

const parser = markdownit({ html: false }); // only to find where the blocks are
const LIST_ITEM = /^\s*(?:[-*+]|\d+[.)])\s/;
const TASK_LINE = /^\s*[-*+] \[[ xX/]\] /;
const NEXT_STATUS = { open: 'progress', progress: 'done', done: 'open' };
// Blocks shown as a whole rather than as rows: tables (a grid) and code (edited as Markdown).
const GROUPS = new Set(['table_open', 'fence', 'code_block', 'hr', 'html_block']);
// Typed at the start of a row: turns it into that kind of line.
const STARTERS = [
  [/^(#{1,6}) $/, (m) => `${m[1]} `],
  [/^([-*+]) $/, (m) => `${m[1]} `],
  [/^(\d{1,9})([.)]) $/, (m) => `${m[1]}${m[2]} `],
  [/^> $/, () => '> '],
];

// render(text, folder) -> element with the formatted Markdown (tasks decorated, links resolved).
// renderEditable(text, folder) -> HTML for one line of inline Markdown (see viewer.js).
// setupTextBox(box, commands?): editing commands, shortcuts and toolbar for a text box; rows
//   pass their own commands (same shape as textcommands.js).
// getSignature() -> the alias that signs new tasks and notes ('' if none).
export function createLiveText({ value, folder, readOnly, placeholder, render, renderEditable, setupTextBox, onOpenLink, onOpenExternal, getSignature = () => '' }) {
  let lines = value ? value.split('\n') : [];
  let editing = null;    // the block being edited as Markdown: { start, count, ta }
  let taskEdit = null;   // the task being edited in place: { at, length, panel, kept }
  let lastRow = null;    // the row the toolbar acts on
  let picking = false;   // the [[ page picker is open
  const root = el('div', 'live-text' + (readOnly ? ' read-only' : ''));

  const changed = () => root.dispatchEvent(new Event('input', { bubbles: true }));

  // Top-level blocks as line ranges: [{ start, end, type }]
  function blocks() {
    const tokens = parser.parse(lines.join('\n'), {});
    return tokens
      .filter((t) => t.level === 0 && t.map && t.nesting !== -1)
      .map((t) => ({ start: t.map[0], end: t.map[1], type: t.type }));
  }

  // Rows for lines; a task with its notes as one piece; tables and code as blocks.
  function draw() {
    if (taskEdit) closeTask();
    const groups = blocks().filter((b) => GROUPS.has(b.type));
    const parts = [];
    for (let i = 0; i < lines.length;) {
      const group = groups.find((g) => g.start === i);
      const task = !group && TASK_LINE.test(lines[i]) && taskAt(i);
      if (group) {
        parts.push(group.type === 'table_open' ? tableBlock(group) : textBlock(group));
        i = group.end;
      } else if (task) {
        parts.push(taskBlock(i, task));
        i += task.blockEnd + 1;
      } else {
        parts.push(row(i));
        i++;
      }
    }
    if (!readOnly) parts.push(row(lines.length), addTaskButton());
    else if (!lines.some((l) => l.trim())) parts.push(el('p', 'empty-note', 'Nothing here.'));
    root.replaceChildren(...parts);
  }

  // ---- Formatted blocks -------------------------------------------------------------

  function textBlock(b) {
    const block = render(lines.slice(b.start, b.end).join('\n'), folder);
    block.className = 'live-block';
    block.dataset.start = b.start;
    block.dataset.end = b.end;
    if (!readOnly) block.title = 'Click to edit';
    for (const icon of block.querySelectorAll('.task-icon')) {
      icon.title = icon.closest('.status-done') ? 'Complete: click to reopen' : `${icon.title}: click to mark complete`;
    }
    if (!readOnly) for (const item of block.querySelectorAll('.task-item')) item.title = 'Click to edit this task';
    // Each task's line, for clicks.
    const tasks = parseTasks(lines.slice(b.start, b.end).join('\n'));
    block.querySelectorAll('.task-item').forEach((item, k) => {
      if (tasks[k]) item.dataset.line = b.start + tasks[k].line;
    });
    return block;
  }

  // A task and everything under it (its notes, any subtasks), shown formatted. Click it to edit.
  function taskBlock(at, task) {
    const indent = lines[at].match(/^\s*/)[0];
    const own = lines.slice(at, at + task.blockEnd + 1).map((l) => (l.startsWith(indent) ? l.slice(indent.length) : l.trimStart()));
    const block = render(own.join('\n'), folder);
    block.className = 'live-block live-task';
    block.dataset.start = at;
    block.dataset.end = at + task.blockEnd + 1;
    block.style.setProperty('--depth', indentDepth(indent));
    for (const icon of block.querySelectorAll('.task-icon')) {
      icon.title = icon.closest('.status-done') ? 'Complete: click to reopen' : `${icon.title}: click to mark complete`;
    }
    parseTasks(own.join('\n')).forEach((t, k) => {
      const item = block.querySelectorAll('.task-item')[k];
      if (!item) return;
      item.dataset.line = at + t.line;
      if (!readOnly) item.title = 'Click to edit this task';
    });
    return block;
  }

  // Clicks are handled on mousedown so a block or task being edited can be put back first: that
  // redraws the box, which would otherwise swallow the click. Positions read before the redraw
  // are shifted by the lines the edit added or removed. Clicks in rows and cells are left to
  // place the caret, unless something has to be put back first.
  root.addEventListener('mousedown', (e) => {
    if (readOnly || e.button !== 0) return;
    const t = e.target;
    if (t.closest('a, .live-table-tools, .live-add') || (editing && t === editing.ta)) return;
    if (taskEdit && taskEdit.panel.contains(t) && !t.closest('.task-edit-subtasks')) return; // its own fields
    const line = t.closest('.rich-line');
    const cell = t.closest('.live-cell');
    const item = t.closest('.task-item[data-line]');
    const block = t.closest('.live-block');
    const busy = Boolean(editing) || Boolean(taskEdit);
    if ((line || cell) && !busy) {
      // A click beside a row's text (on its bullet, or past its end) still puts the caret in it.
      if (line && !t.closest('.rich-text')) {
        e.preventDefault();
        focusRow(Number(line.dataset.line), { x: e.clientX, y: e.clientY });
      }
      return;
    }
    if (!line && !cell && !block) return;

    e.preventDefault();
    let target;
    if (item) target = { task: Number(item.dataset.line), toggle: Boolean(t.closest('.task-icon')) };
    else if (line) target = { row: Number(line.dataset.line), x: e.clientX, y: e.clientY };
    else if (block) target = { line: Number(block.dataset.start) };
    else {
      const table = [...root.querySelectorAll('.live-table')].indexOf(cell.closest('.live-table'));
      target = { table, row: cell.dataset.row, col: cell.dataset.col };
    }

    const shift = busy ? settle() : (n) => n;
    if (target.task !== undefined && target.toggle) toggleTask(shift(target.task));
    else if (target.task !== undefined) openTask(shift(target.task));
    else if (target.x !== undefined) focusRow(shift(target.row), { x: target.x, y: target.y });
    else if (target.line !== undefined) editBlock(shift(target.line));
    else root.querySelectorAll('.live-table')[target.table]?.querySelector(`[data-row="${target.row}"][data-col="${target.col}"]`)?.focus();
  });

  // Puts back the block or task being edited, and redraws.
  // -> a function that maps a line number from before to the same line now.
  function settle() {
    let shift = (line) => line;
    if (editing) {
      const { start, count, original } = editing;
      shift = (line) => (line > start ? line + count - original : line);
      editing = null;
    }
    if (taskEdit) shift = closeTask();
    draw();
    return shift;
  }
  root.addEventListener('click', (e) => {
    const a = e.target.closest('a');
    if (!a || !root.contains(a)) return;
    e.preventDefault();
    if (a.dataset.id) onOpenLink(a.dataset.id);
    else if (/^(https?|mailto):/i.test(a.getAttribute('href') || '')) onOpenExternal(a.getAttribute('href'));
  });

  // The task on line `at`: complete <-> not.
  function toggleTask(at) {
    const task = taskAt(at);
    if (!task) return;
    lines[at] = withStatus(task.raw, task.status === 'done' ? 'open' : 'done', isoDate());
    draw();
    changed();
  }

  // The task on line `at` (its line numbers are relative to `at`), or undefined.
  function taskAt(at) {
    const task = parseTasks(lines.slice(at).join('\n'))[0];
    return task && task.line === 0 ? task : undefined;
  }

  // ---- Editing a task as it looks -----------------------------------------------------------
  // The task's list item becomes a small form: status button, text, due date, its dated notes,
  // and Markdown / Delete. Every keystroke rewrites the task's lines (see withText and
  // withSubnoteText in tasks.js); clicking elsewhere shows it formatted again.

  function openTask(at, focus = { part: 'text' }) {
    const item = root.querySelector(`.task-item[data-line="${at}"]`);
    if (!item) return;

    const panel = el('li', 'task-item task-edit');
    // Subtasks nested under the task stay as they are shown (its notes become fields).
    const kept = el('div', 'task-edit-subtasks');
    for (const list of item.querySelectorAll(':scope > ul, :scope > ol')) {
      for (const child of [...list.children]) if (!child.classList.contains('task-item')) child.remove();
      if (list.children.length) kept.append(list);
    }
    taskEdit = { at, length: lines.length, panel, kept };
    item.replaceWith(panel);
    panel.addEventListener('input', onTaskInput);
    panel.addEventListener('change', onTaskChange);
    panel.addEventListener('click', onTaskClick);
    panel.addEventListener('keydown', onTaskKey);
    panel.addEventListener('focusout', () => setTimeout(() => {
      if (taskEdit?.panel === panel && !panel.contains(document.activeElement)) draw();
    }));
    fillTask(focus);
  }

  // (Re)builds the form from the task's lines, then focuses focus.part: 'text', 'due', 'status',
  // 'add' or 'note-<n>'.
  function fillTask(focus) {
    const { at, panel, kept } = taskEdit;
    const task = taskAt(at);
    panel.className = `task-item task-edit status-${task.status}`;

    const status = el('button', 'task-edit-status');
    status.type = 'button';
    status.dataset.part = 'status';
    status.innerHTML = TASK_ICONS[task.status];
    status.title = `${TASK_TITLES[task.status]}: click for ${TASK_TITLES[NEXT_STATUS[task.status]]}`;

    const text = field('task-edit-text', task.text, 'What needs doing?');
    text.dataset.part = 'text';

    const due = el('label', 'task-edit-due' + (task.due ? ' set' : ''));
    due.title = 'Due date';
    const date = el('input');
    date.type = 'date';
    date.value = task.due;
    date.dataset.part = 'due';
    due.append(el('span', '', 'due'), date);
    if (task.due) {
      const clear = el('button', 'task-edit-clear', '×');
      clear.type = 'button';
      clear.dataset.action = 'clear-due';
      clear.title = 'Remove the due date';
      due.append(clear);
    }

    const row = el('div', 'task-edit-row');
    row.append(status, text, due);
    if (task.done) row.append(el('span', 'date-chip done', `done ${friendlyDate(task.done)}`));
    if (task.signature) row.append(el('span', 'sig-chip', `~${task.signature}`));
    row.append(action('markdown', 'Markdown', 'Edit this list as Markdown'), action('delete', 'Delete', 'Delete this task and its notes'));

    const notes = el('ul', 'task-edit-notes');
    task.subnotes.forEach((note, n) => {
      const li = el('li', 'task-edit-note');
      li.dataset.line = at + note.line;
      if (note.date) li.append(el('span', 'date-chip', [friendlyDate(note.date), note.time].filter(Boolean).join(' ')));
      if (note.signature) li.append(el('span', 'sig-chip', `~${note.signature}`));
      const input = field('task-edit-note-text', note.text, 'Note');
      input.dataset.part = `note-${n}`;
      const remove = el('button', 'task-edit-clear', '×');
      remove.type = 'button';
      remove.dataset.action = 'remove-note';
      remove.title = 'Remove this note';
      li.append(input, remove);
      notes.append(li);
    });
    const add = action('add-note', '+ Add a note', 'A dated note under the task (Enter in a note adds the next one)');
    add.dataset.part = 'add';
    const addRow = el('li', 'task-edit-note');
    addRow.append(add);
    notes.append(addRow);

    panel.replaceChildren(row, notes);
    if (kept.children.length) panel.append(kept);

    const target = panel.querySelector(`[data-part="${focus.part}"]`) || text;
    target.focus();
    if (target.matches('input:not([type="date"])')) target.setSelectionRange(target.value.length, target.value.length);
  }

  function field(className, value, hint) {
    const input = el('input', `${className} link-complete`);
    input.value = value;
    input.placeholder = hint;
    input.dataset.folder = folder;
    input.spellcheck = true;
    return input;
  }

  function action(name, label, title) {
    const button = el('button', 'task-edit-action', label);
    button.type = 'button';
    button.dataset.action = name;
    button.title = title;
    return button;
  }

  // Typing rewrites the line; the "input" event then bubbles up to whoever saves.
  function onTaskInput(e) {
    const { at } = taskEdit;
    if (e.target.matches('.task-edit-text')) lines[at] = withText(lines[at], e.target.value);
    else if (e.target.matches('.task-edit-note-text')) {
      const line = Number(e.target.closest('[data-line]').dataset.line);
      lines[line] = withSubnoteText(lines[line], e.target.value);
    }
  }

  function onTaskChange(e) {
    if (e.target.type !== 'date') return;
    lines[taskEdit.at] = withDue(lines[taskEdit.at], e.target.value);
    fillTask({ part: 'due' });
    changed();
  }

  function onTaskClick(e) {
    const button = e.target.closest('button');
    if (!button) return;
    const { at } = taskEdit;
    const task = taskAt(at);
    const name = button.dataset.part === 'status' ? 'status' : button.dataset.action;
    if (name === 'status') {
      lines[at] = withStatus(lines[at], NEXT_STATUS[task.status], isoDate());
      fillTask({ part: 'status' });
    } else if (name === 'clear-due') {
      lines[at] = withDue(lines[at], '');
      fillTask({ part: 'text' });
    } else if (name === 'add-note') {
      addNote(task, task.subnotes.length);
      return;
    } else if (name === 'remove-note') {
      const li = button.closest('[data-line]');
      const n = [...li.parentElement.children].indexOf(li);
      lines.splice(Number(li.dataset.line), 1);
      fillTask({ part: n ? `note-${n - 1}` : 'text' });
    } else if (name === 'markdown') {
      settle();
      editBlock(at);
      return;
    } else if (name === 'delete') {
      if (!button.classList.contains('confirm')) {
        button.classList.add('confirm');
        button.textContent = task.subnotes.length || task.blockEnd ? 'Delete task and notes?' : 'Delete task?';
        return;
      }
      lines.splice(at, task.blockEnd + 1);
      taskEdit = null;
      draw();
    } else {
      return;
    }
    changed();
  }

  // A new note, dated now and signed, as note number n (after the notes before it).
  function addNote(task, n) {
    const after = n ? task.subnotes[n - 1].line : 0;
    lines.splice(taskEdit.at + after + 1, 0, newSubnoteLine(task, '', getSignature()));
    fillTask({ part: `note-${n}` });
    changed();
  }

  function onTaskKey(e) {
    const input = e.target;
    const { at } = taskEdit;
    const empty = input.value === '';
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation(); // ends the task edit only (the full editor closes on Esc otherwise)
      draw();
    } else if (e.key === 'Enter' && input.matches('.task-edit-text, .task-edit-note-text')) {
      // Leaves the autocomplete's Enter (picking a suggestion) alone.
      if (e.defaultPrevented) return;
      e.preventDefault();
      if (input.matches('.task-edit-note-text')) {
        const task = taskAt(at);
        const n = Number(input.dataset.part.slice(5));
        if (empty) {
          lines.splice(at + task.subnotes[n].line, 1);
          fillTask({ part: 'text' });
          changed();
        } else addNote(task, n + 1);
      } else if (empty) {
        draw();
      } else nextTask();
    } else if (e.key === 'Backspace' && empty && input.matches('.task-edit-note-text')) {
      e.preventDefault();
      const n = Number(input.dataset.part.slice(5));
      lines.splice(at + taskAt(at).subnotes[n].line, 1);
      fillTask({ part: n ? `note-${n - 1}` : 'text' });
      changed();
    } else if (e.key === 'Backspace' && empty && input.matches('.task-edit-text')) {
      const task = taskAt(at);
      if (task.subnotes.length || task.blockEnd) return;
      e.preventDefault();
      lines.splice(at, 1);
      taskEdit = null;
      draw();
      changed();
    }
  }

  // Enter in a task's text: a new empty task below it (after its notes), opened for editing.
  function nextTask() {
    const at = taskEdit.at;
    const shift = closeTask();
    const task = taskAt(shift(at));
    if (!task) return draw();
    const line = shift(at) + task.blockEnd + 1;
    lines.splice(line, 0, emptyTaskLine(getSignature(), task.raw));
    draw();
    changed();
    openTask(line);
  }

  // Ends editing the task: notes left empty, and the task itself if it was left empty, are
  // removed. -> a function mapping a line number from before to the same line now.
  function closeTask() {
    const { at, length } = taskEdit;
    taskEdit = null;
    const task = taskAt(at);
    let removed = false;
    if (task) {
      for (const note of [...task.subnotes].reverse()) {
        if (!note.text.trim()) {
          lines.splice(at + note.line, 1);
          removed = true;
        }
      }
      const bare = !task.text && !task.due && !task.done && task.subnotes.every((n) => !n.text.trim());
      if (bare && taskAt(at).blockEnd === 0) {
        lines.splice(at, 1);
        removed = true;
      }
    }
    if (removed) changed();
    const delta = lines.length - length;
    return (line) => (line > at ? line + delta : line);
  }

  // A new task, opened for editing: after row `after` (in its place if that row is empty), or
  // at the end.
  function addTask(after) {
    settle();
    if (after === undefined || after >= lines.length) {
      lines = withWritten(lines, emptyTaskLine(getSignature()));
      after = lines.length - 1;
    } else {
      const kind = classify(lines[after]);
      const like = kind.type === 'bullet' || kind.type === 'number' ? `${kind.indent}- [ ] x` : '';
      const task = emptyTaskLine(getSignature(), like);
      if (kind.content.trim()) lines.splice(++after, 0, task);
      else lines[after] = task;
    }
    draw();
    changed();
    openTask(after);
  }

  function addTaskButton() {
    const button = el('button', 'live-add', '+ Task');
    button.type = 'button';
    button.title = 'Add a task (Ctrl+T)';
    button.addEventListener('mousedown', (e) => e.preventDefault()); // keeps the caret where it is
    button.addEventListener('click', () => addTask());
    return button;
  }

  // ---- Editing a block as Markdown --------------------------------------------------------

  // Shows the block containing line `at` (a code block, or a list from a task's Markdown
  // button) as a text box, in place of everything drawn for those lines.
  function editBlock(at) {
    const b = blocks().find((x) => at >= x.start && at < x.end) || blocks().find((x) => x.start >= at);
    if (!b) return;
    const drawn = [...root.children].filter((node) => {
      const start = Number(node.dataset.line ?? node.dataset.start);
      return start >= b.start && start < b.end;
    });
    if (!drawn.length) return;
    const ta = textBox(lines.slice(b.start, b.end).join('\n'));
    editing = { start: b.start, count: b.end - b.start, original: b.end - b.start, ta };
    drawn[0].before(ta);
    drawn.forEach((node) => node.remove());
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }

  function finishEditing() {
    editing = null;
    draw();
  }

  function textBox(text) {
    const ta = el('textarea', 'jot-text link-complete');
    ta.value = text;
    ta.dataset.folder = folder;
    ta.spellcheck = true;
    setupTextBox(ta);
    ta.addEventListener('input', () => {
      if (editing?.ta !== ta) return;
      const next = ta.value.split('\n');
      lines.splice(editing.start, editing.count, ...next);
      editing.count = next.length;
    });
    ta.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation(); // ends this edit only (the full editor closes on Esc otherwise)
      ta.blur();
    });
    ta.addEventListener('blur', () => {
      if (editing?.ta === ta) finishEditing();
    });
    return ta;
  }

  // ---- Rows: one line each, edited as it looks ----------------------------------------------
  // Row n shows lines[n]; row lines.length is the empty last row ("Write…") that adds a line.
  // A row keeps the kind it was drawn with (row._kind: its prefix), so typing never changes
  // what kind of line it is; the Markdown shortcuts and commands below do, and redraw.

  function row(n) {
    const last = n >= lines.length;
    const kind = last ? classify('') : classify(lines[n]);
    const line = el('div', `rich-line ${kind.type}${last ? ' last' : ''}`);
    line._kind = kind;
    line.dataset.line = n;
    line.style.setProperty('--depth', kind.depth);
    if (kind.type === 'heading') line.classList.add(`h${kind.marker}`);
    if (kind.type === 'bullet') line.append(el('span', 'rich-marker', kind.depth % 2 ? '◦' : '•'));
    if (kind.type === 'number') line.append(el('span', 'rich-marker', kind.marker));
    const text = el('span', 'rich-text');
    if (last) text.dataset.placeholder = placeholder || 'Write…';
    fill(text, kind.content, line);
    if (!readOnly) {
      text.contentEditable = 'true';
      text.spellcheck = true;
      text.addEventListener('input', () => onRowInput(text));
      text.addEventListener('focus', () => (lastRow = text));
      text.addEventListener('blur', () => refresh(text));
      text.addEventListener('paste', (e) => onPaste(e, text));
      setupTextBox(text, commands);
    }
    line.append(text);
    return line;
  }

  // Shows md formatted in text, or as its Markdown if it wouldn't come back exactly the same.
  function fill(text, md, line) {
    const html = renderEditable?.(md, folder);
    const probe = el('span');
    if (html !== undefined) probe.innerHTML = html;
    if (html !== undefined && serialize(probe).trimEnd() === md.trimEnd()) {
      text.innerHTML = html;
      line.classList.remove('raw');
      for (const a of text.querySelectorAll('a[data-src]')) a.contentEditable = 'false';
    } else {
      text.textContent = md;
      line.classList.add('raw');
      line.title = 'Shown as Markdown, so it is kept exactly as written';
    }
  }

  // The Markdown in a row's box.
  const markdownOf = (text) => (text.parentElement.classList.contains('raw') ? text.textContent.replace(/ /g, ' ') : serialize(text));

  // Leaving a row shows what was typed formatted (say, **bold** typed by hand).
  function refresh(text) {
    const line = text.parentElement;
    if (picking || !text.isConnected || line.classList.contains('raw') || line.classList.contains('last')) return;
    const n = Number(line.dataset.line);
    fill(text, lines[n].slice(line._kind.prefix.length), line);
  }

  function onRowInput(text) {
    const line = text.parentElement;
    const n = Number(line.dataset.line);
    const kind = line._kind;
    const md = markdownOf(text);
    if (starter(n, kind, md)) return;
    if (n >= lines.length) {
      // Typing in the last row adds a line (after a blank line if it follows a list, so it
      // isn't read as part of the list's last item).
      if (!md.trim()) return;
      const offset = caretOffset(text);
      lines = withWritten(lines, md.trimStart());
      draw();
      focusRow(lines.length - 1, { offset });
      return;
    }
    lines[n] = kind.prefix + md;
    if (kind.type === 'blank' && md) {
      line._kind = { ...kind, type: 'para' };
      line.classList.replace('blank', 'para');
    }
    if (!line.classList.contains('raw') && textBeforeCaret(text).endsWith('[[')) openLinkPicker(text);
  }

  // "- ", "1. ", "## ", "> " typed into an empty row make it that kind of line; "[ ] " a task.
  // In a list item only the list ones apply (and "[ ] ").
  function starter(n, kind, md) {
    if (!['para', 'blank', 'bullet', 'number'].includes(kind.type)) return false;
    const listItem = kind.type === 'bullet' || kind.type === 'number';
    const put = (next) => {
      if (n < lines.length) {
        lines[n] = next;
        return n;
      }
      lines = withWritten(lines, next);
      return lines.length - 1;
    };
    if (/^\[ ?\] $/.test(md)) {
      const at = put(emptyTaskLine(getSignature(), `${kind.indent || ''}- [ ] x`));
      draw();
      changed();
      openTask(at);
      return true;
    }
    for (const [pattern, make] of STARTERS) {
      const m = pattern.exec(md);
      if (!m) continue;
      const made = make(m);
      if (listItem && !LIST_ITEM.test(made)) return false;
      redrawAt(put((kind.indent || '') + made), 0);
      return true;
    }
    return false;
  }

  // Puts the caret in row n: at a clicked point ({ x, y }), after `offset` characters, or at
  // the end.
  function focusRow(n, at = {}) {
    const text = root.querySelector(`.rich-line[data-line="${n}"] .rich-text`);
    if (!text || readOnly) return;
    if (at.x !== undefined) {
      text.focus();
      const range = document.caretRangeFromPoint?.(at.x, at.y);
      if (range && text.contains(range.startContainer)) {
        getSelection().removeAllRanges();
        getSelection().addRange(range);
        return;
      }
      setCaret(text, at.x < text.getBoundingClientRect().left ? 0 : text.textContent.length);
      return;
    }
    setCaret(text, at.offset ?? text.textContent.length);
  }

  function textBeforeCaret(text) {
    const selection = getSelection();
    if (!selection.rangeCount) return '';
    const before = document.createRange();
    before.selectNodeContents(text);
    before.setEnd(selection.getRangeAt(0).startContainer, selection.getRangeAt(0).startOffset);
    return before.toString();
  }

  // The row above or below (skipping tasks, tables and code), or null.
  function neighbour(line, direction) {
    let node = direction < 0 ? line.previousElementSibling : line.nextElementSibling;
    while (node && !node.classList.contains('rich-line')) node = direction < 0 ? node.previousElementSibling : node.nextElementSibling;
    return node;
  }

  // ---- Keys in a row ----

  function rowKey(e) {
    const text = e.target.closest?.('.rich-text');
    if (!text || !root.contains(text)) return false;
    const line = text.parentElement;
    const n = Number(line.dataset.line);
    const kind = line._kind;
    const ctrl = e.ctrlKey || e.metaKey;
    const cmd = ctrl && !e.altKey && (e.shiftKey ? SHIFT_SHORTCUTS : SHORTCUTS)[e.code];
    if (cmd) {
      e.preventDefault();
      commands.run(cmd);
      return true;
    }
    if (e.isComposing) return false;
    if (e.key === 'Enter' && !ctrl && !e.altKey) {
      e.preventDefault();
      splitRow(text, n, kind);
    } else if (e.key === 'Backspace' && !ctrl && !e.altKey && caretAtStart(text)) {
      e.preventDefault();
      joinUp(line, n, kind);
    } else if (e.key === 'Delete' && !ctrl && !e.altKey && caretAtEnd(text) && n < lines.length) {
      e.preventDefault();
      joinDown(text, n);
    } else if (e.key === 'Tab' && !ctrl && !e.altKey) {
      e.preventDefault();
      shiftRow(n, kind, e.shiftKey ? -1 : 1, caretOffset(text));
    } else if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && !ctrl && !e.shiftKey && !e.altKey && caretOnEdgeLine(text, e.key === 'ArrowUp')) {
      const up = e.key === 'ArrowUp';
      const next = neighbour(line, up ? -1 : 1);
      if (!next) return false;
      e.preventDefault();
      const caret = getSelection().getRangeAt(0).getClientRects()[0];
      const box = next.querySelector('.rich-text').getBoundingClientRect();
      focusRow(Number(next.dataset.line), { x: caret ? caret.left : box.left, y: up ? box.bottom - 4 : box.top + 4 });
    } else if (e.key === 'Escape') {
      e.preventDefault(); // (so the full editor doesn't also close)
      text.blur();
    } else {
      return false;
    }
    return true;
  }

  // Enter: the text after the caret goes to a new row below, of the same kind (the next bullet
  // or number). Enter on an empty item ends the list (a nested one moves out a level first);
  // at the very start of a row, it adds an empty row above.
  function splitRow(text, n, kind) {
    if (n >= lines.length) return;
    const raw = text.parentElement.classList.contains('raw');
    const right = raw ? text.textContent.slice(caretOffset(text)) : cutAfterCaret(text);
    const left = raw ? text.textContent.slice(0, caretOffset(text)) : serialize(text);
    const listy = kind.type === 'bullet' || kind.type === 'number' || kind.type === 'quote';
    if (listy && !left.trim() && !right.trim()) {
      if (kind.indent) {
        lines[n] = outdented(lines[n]);
      } else {
        lines.splice(n, 1, '', '');
        n++;
      }
      return redrawAt(n, 0);
    }
    const next = kind.type === 'number' ? kind.prefix.replace(/\d+/, (d) => String(Number(d) + 1))
      : listy || kind.type === 'para' ? kind.prefix : '';
    if (!left.trim() && right.trim() && kind.type !== 'blank') {
      lines.splice(n, 0, listy ? kind.prefix : kind.indent || '');
      return redrawAt(n + 1, 0);
    }
    lines[n] = kind.prefix + left;
    lines.splice(n + 1, 0, next + right);
    redrawAt(n + 1, 0);
  }

  // Backspace at the start of a row: a bullet, number, quote or heading loses its marker;
  // other rows join the row above.
  function joinUp(line, n, kind) {
    if (n >= lines.length) {
      const above = neighbour(line, -1);
      if (above) focusRow(Number(above.dataset.line));
      return;
    }
    const content = lines[n].slice(kind.prefix.length);
    if (['bullet', 'number', 'quote', 'heading'].includes(kind.type)) {
      lines[n] = (kind.indent || '') + content;
      return redrawAt(n, 0);
    }
    if (n === 0) return;
    const above = root.querySelector(`.rich-line[data-line="${n - 1}"]`);
    if (!above) {
      // The line above is a task, table or code: only an empty row goes.
      if (!content.trim()) {
        lines.splice(n, 1);
        redrawAt(n, 0);
      }
      return;
    }
    if (above._kind.type === 'blank') {
      lines.splice(n - 1, 1);
      return redrawAt(n - 1, 0);
    }
    const at = above.querySelector('.rich-text').textContent.length;
    lines[n - 1] += content;
    lines.splice(n, 1);
    redrawAt(n - 1, at);
  }

  // Delete at the end of a row: the row below joins it.
  function joinDown(text, n) {
    const below = root.querySelector(`.rich-line[data-line="${n + 1}"]`);
    if (!below || n + 1 >= lines.length) return;
    const at = text.textContent.length;
    lines[n] += lines[n + 1].slice(below._kind.prefix.length);
    lines.splice(n + 1, 1);
    redrawAt(n, at);
  }

  // Tab / Shift+Tab: a bullet or number moves in under the item above, or back out.
  function shiftRow(n, kind, direction, offset) {
    if (n >= lines.length || (kind.type !== 'bullet' && kind.type !== 'number')) return;
    if (direction > 0) {
      const above = n > 0 ? classify(lines[n - 1]) : null;
      const under = above && (above.type === 'bullet' || above.type === 'number') ? above.prefix.length : kind.indent.length + 2;
      if (under <= kind.indent.length) return;
      let moved = lines[n].slice(kind.indent.length);
      // The first numbered item at its new level counts from 1.
      const sibling = above && above.type === 'number' && above.indent.length === under;
      if (kind.type === 'number' && !sibling) moved = moved.replace(/^\d+/, '1');
      lines[n] = ' '.repeat(under) + moved;
    } else {
      if (!kind.indent) return;
      lines[n] = outdented(lines[n]);
    }
    redrawAt(n, offset);
  }

  function outdented(line) {
    const indent = line.match(/^\s*/)[0];
    return indent.slice(0, Math.max(0, indent.length - (indent.length % 2 ? 3 : 2))) + line.slice(indent.length);
  }

  // The numbered list that line k is in counts on from its first item, at k's level (nested
  // items in between are skipped).
  function renumber(k) {
    const kind = k >= 0 && k < lines.length ? classify(lines[k]) : null;
    if (kind?.type !== 'number') return;
    const level = kind.indent.length;
    const inRun = (c) => c.type === 'number' && c.indent.length === level;
    const below = (c) => c.type !== 'blank' && (c.indent || '').length > level;
    let start = k;
    for (let j = k - 1; j >= 0; j--) {
      const c = classify(lines[j]);
      if (inRun(c)) start = j;
      else if (!below(c)) break;
    }
    let count = Number(classify(lines[start]).marker.match(/\d+/)[0]) - 1;
    for (let j = start; j < lines.length; j++) {
      const c = classify(lines[j]);
      if (inRun(c)) {
        count++;
        lines[j] = c.indent + c.marker.replace(/\d+/, count) + lines[j].slice(c.indent.length + c.marker.length);
      } else if (!below(c)) break;
    }
  }

  // Redraws after a change to the lines around row n, with the caret back in row n.
  function redrawAt(n, offset) {
    for (let k = n - 2; k <= n + 2; k++) renumber(k);
    draw();
    changed();
    focusRow(n, { offset });
  }

  // Pasting: plain text only; several lines become several rows (Markdown in them is kept).
  function onPaste(e, text) {
    e.preventDefault();
    const pasted = (e.clipboardData?.getData('text/plain') || '').replace(/\r\n?/g, '\n');
    if (!pasted) return;
    const parts = pasted.split('\n');
    if (parts.length === 1) {
      document.execCommand('insertText', false, parts[0]);
      return;
    }
    const line = text.parentElement;
    const n = Number(line.dataset.line);
    const raw = line.classList.contains('raw');
    const right = raw ? text.textContent.slice(caretOffset(text)) : cutAfterCaret(text);
    const left = raw ? text.textContent.slice(0, caretOffset(text)) : serialize(text);
    const added = [left + parts[0], ...parts.slice(1, -1), parts[parts.length - 1] + right];
    const lastAt = n >= lines.length ? withWritten(lines, added.join('\n')).length - 1 : n + added.length - 1;
    if (n >= lines.length) lines = withWritten(lines, added.join('\n'));
    else lines.splice(n, 1, line._kind.prefix + added[0], ...added.slice(1));
    redrawAt(lastAt, parts[parts.length - 1].length);
  }

  // "[[" typed in a row: a small box under the caret suggests pages (autocomplete.js); the
  // chosen page goes in as a link.
  function openLinkPicker(text) {
    picking = true; // (the row isn't redrawn meanwhile, so the caret's place stays valid)
    const at = getSelection().getRangeAt(0).cloneRange();
    const spot = at.getClientRects()[0] || text.getBoundingClientRect();
    const input = el('input', 'rich-link-input link-complete');
    input.dataset.folder = folder;
    input.placeholder = 'Page name';
    input.style.left = `${spot.left}px`;
    input.style.top = `${spot.bottom + 2}px`;
    input.value = '[[';
    document.body.append(input);
    input.focus();
    input.setSelectionRange(2, 2);
    input.dispatchEvent(new Event('input', { bubbles: true })); // opens the suggestions

    const finish = (link) => {
      if (!input.isConnected) return;
      const typed = input.value.slice(2);
      input.remove();
      picking = false;
      text.focus();
      getSelection().removeAllRanges();
      getSelection().addRange(at);
      if (!link) {
        if (typed) document.execCommand('insertText', false, typed);
        return;
      }
      // Replaces the "[[" typed in the row with the link.
      const range = getSelection().getRangeAt(0);
      if (range.startContainer.nodeType === Node.TEXT_NODE && range.startOffset >= 2) {
        range.setStart(range.startContainer, range.startOffset - 2);
        range.deleteContents();
      }
      const holder = el('span');
      holder.innerHTML = renderEditable(link, folder);
      for (const a of holder.querySelectorAll('a[data-src]')) a.contentEditable = 'false';
      const nodes = [...holder.childNodes, document.createTextNode(' ')];
      for (const node of nodes.reverse()) range.insertNode(node);
      range.setStartAfter(nodes[0]);
      range.collapse(true);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      onRowInput(text);
      changed();
    };
    input.addEventListener('input', () => {
      if (/^\[\[[^\]]+\]\]$/.test(input.value)) finish(input.value);
      else if (!input.value.startsWith('[[')) finish(null);
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        finish(null);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const typed = input.value.slice(2).replace(/\]+$/, '').trim();
        if (typed) finish(`[[${typed}]]`);
        else finish(null);
      }
    });
    input.addEventListener('blur', () => setTimeout(() => finish(null)));
  }

  // ---- The toolbar's commands, for rows (the same shape as textcommands.js) ----

  const activeText = () => {
    const focused = document.activeElement?.closest?.('.rich-text');
    if (focused && root.contains(focused)) return focused;
    return lastRow?.isConnected ? lastRow : null;
  };

  const commands = {
    run(cmd) {
      const text = activeText();
      if (!text) return;
      const line = text.parentElement;
      const n = Number(line.dataset.line);
      const kind = line._kind;
      text.focus();
      if (cmd === 'bold') document.execCommand('bold');
      else if (cmd === 'italic') document.execCommand('italic');
      else if (cmd === 'strike') document.execCommand('strikeThrough');
      else if (cmd === 'code') toggleCode(text);
      else if (cmd === 'link') insertLink(text);
      else if (cmd === 'bullet' || cmd === 'number' || cmd === 'quote') setKind(n, kind, cmd, caretOffset(text));
      else if (cmd === 'task') toTask(n, kind);
      else if (cmd === 'fulltask') addTask(n);
      else if (cmd === 'indent' || cmd === 'outdent') shiftRow(n, kind, cmd === 'indent' ? 1 : -1, caretOffset(text));
      else if (cmd === 'codeblock') insertLines(n, ['```', '', '```'], 'code');
      else if (cmd === 'table') insertLines(n, INSERTS.find(([label]) => label.startsWith('Table'))[1]().replace(/§/g, '').split('\n'), 'table');
      else if (cmd === 'divider') insertLines(n, ['---']);
    },
    handleKeydown: rowKey,
    setHeading(level) {
      const text = activeText();
      if (!text) return;
      const line = text.parentElement;
      setKind(Number(line.dataset.line), line._kind, level ? `h${level}` : 'para', caretOffset(text));
    },
    headingLevel() {
      const kind = activeText()?.parentElement._kind;
      return kind?.type === 'heading' ? kind.marker : 0;
    },
    insertSnippet([, make, where]) {
      const text = activeText();
      if (!text) return;
      const n = Number(text.parentElement.dataset.line);
      if (make === 'fulltask') return addTask(n);
      if (where === 'top') return;
      const template = make(getSignature()).replace(/§/g, '');
      if (where === 'block' || where === 'line') insertLines(n, template.split('\n'), template.startsWith('|') ? 'table' : '');
      else {
        text.focus();
        document.execCommand('insertText', false, template);
      }
    },
  };

  // Makes row n a bullet, number, quote, heading ('h1'...) or plain text (toggling off a kind it
  // already is).
  function setKind(n, kind, target, offset) {
    const content = n < lines.length ? lines[n].slice(kind.prefix.length) : '';
    const indent = kind.indent || '';
    const same = (target === 'bullet' && kind.type === 'bullet') || (target === 'number' && kind.type === 'number')
      || (target === 'quote' && kind.type === 'quote') || (target === `h${kind.marker}` && kind.type === 'heading');
    let next;
    if (same || target === 'para') next = (kind.type === 'heading' || kind.type === 'quote' ? '' : indent) + content;
    else if (target === 'bullet') next = `${indent}- ${content}`;
    else if (target === 'number') next = `${indent}1. ${content}`;
    else if (target === 'quote') next = `> ${content}`;
    else next = `${'#'.repeat(Number(target.slice(1)))} ${content}`;
    if (n >= lines.length) {
      lines = withWritten(lines, next);
      n = lines.length - 1;
    } else lines[n] = next;
    if (target === 'number') renumber(n);
    redrawAt(n, offset);
  }

  // Makes row n a task (its text becomes the task's), opened for editing.
  function toTask(n, kind) {
    if (n >= lines.length) return addTask();
    const like = kind.type === 'bullet' || kind.type === 'number' ? `${kind.indent}- [ ] x` : '';
    lines[n] = withText(emptyTaskLine(getSignature(), like), lines[n].slice(kind.prefix.length));
    draw();
    changed();
    openTask(n);
  }

  // Inserts whole lines after row n (in its place if it's empty), then goes to them: 'code'
  // edits the code block, 'table' its first cell, else the end of the last line.
  function insertLines(n, add, then = '') {
    let start;
    if (n >= lines.length) {
      lines = withWritten(lines, add.join('\n'));
      start = lines.length - add.length;
    } else if (!lines[n].trim()) {
      lines.splice(n, 1, ...add);
      start = n;
    } else {
      lines.splice(n + 1, 0, '', ...add);
      start = n + 2;
    }
    draw();
    changed();
    if (then === 'code') {
      editBlock(start);
      editing?.ta.setSelectionRange(4, 4); // inside the fences
    }
    else if (then === 'table') root.querySelector(`.live-table[data-start="${start}"] .live-cell`)?.focus();
    else if (TASK_LINE.test(lines[start])) openTask(start);
    else focusRow(start + add.length - 1);
  }

  function toggleCode(text) {
    const range = getSelection().getRangeAt(0);
    const inside = range.startContainer.parentElement?.closest('code');
    if (inside && text.contains(inside)) {
      inside.replaceWith(...inside.childNodes);
    } else if (!range.collapsed) {
      const code = el('code');
      code.append(range.extractContents());
      range.insertNode(code);
    } else return;
    onRowInput(text);
    changed();
  }

  function insertLink(text) {
    const selected = String(getSelection());
    if (selected && !selected.includes('\n')) {
      document.execCommand('insertText', false, `[[${selected}]]`);
      refresh(text);
      setCaret(text, text.textContent.length);
      return;
    }
    document.execCommand('insertText', false, '[['); // opens the page picker
  }

  // New text at the end. After a list, quote, table or code it goes after a blank line (so it
  // isn't read as part of them), except list items after a list, which continue it.
  function withWritten(base, text) {
    if (!text.trim()) return base.slice();
    const add = text.split('\n');
    const last = base[base.length - 1];
    if (!last || !last.trim()) return base.concat(add);
    if (LIST_ITEM.test(last) || /^\s+\S/.test(last) || /^\s*>/.test(last)) {
      return LIST_ITEM.test(add[0]) ? base.concat(add) : base.concat('', add);
    }
    if (/^\s*\|/.test(last) || /^\s*(```|~~~)/.test(last)) return base.concat('', add);
    return base.concat(add);
  }

  // ---- Tables -----------------------------------------------------------------------------

  function tableBlock(b) {
    const table = parseTable(lines.slice(b.start, b.end));
    const box = el('div', 'live-table');
    box.dataset.start = b.start;
    const grid = el('table');
    const head = el('thead');
    const body = el('tbody');
    const cell = (tag, text, r, c) => {
      const td = el(tag);
      const input = el('input', 'live-cell');
      input.value = text;
      input.readOnly = readOnly;
      input.dataset.row = r;
      input.dataset.col = c;
      input.spellcheck = true;
      input.placeholder = r < 0 ? 'Header' : '';
      td.append(input);
      return td;
    };
    const headRow = el('tr');
    table.header.forEach((text, c) => headRow.append(cell('th', text, -1, c)));
    head.append(headRow);
    table.rows.forEach((row, r) => {
      const tr = el('tr');
      row.forEach((text, c) => tr.append(cell('td', text, r, c)));
      body.append(tr);
    });
    grid.append(head, body);
    box.append(grid);

    if (!readOnly) {
      let current = { row: table.rows.length - 1, col: table.header.length - 1 };
      const tools = el('div', 'live-table-tools');
      for (const [op, label, title] of [
        ['row+', '+ Row', 'Add a row below the selected one'],
        ['col+', '+ Column', 'Add a column right of the selected one'],
        ['row-', '− Row', 'Remove the selected row'],
        ['col-', '− Column', 'Remove the selected column'],
      ]) {
        const button = el('button', 'live-table-button', label);
        button.dataset.op = op;
        button.title = title;
        tools.append(button);
      }
      box.append(tools);

      const save = (focus) => {
        lines.splice(b.start, b.end - b.start, ...tableLines(table));
        draw();
        changed();
        if (focus) root.querySelector(`.live-table[data-start="${b.start}"] [data-row="${focus.row}"][data-col="${focus.col}"]`)?.focus();
      };
      box.addEventListener('focusin', (e) => {
        if (e.target.matches('.live-cell')) current = { row: Number(e.target.dataset.row), col: Number(e.target.dataset.col) };
      });
      box.addEventListener('input', (e) => {
        if (!e.target.matches('.live-cell')) return;
        const { row, col } = e.target.dataset;
        if (Number(row) < 0) table.header[col] = e.target.value;
        else table.rows[row][col] = e.target.value;
        lines.splice(b.start, b.end - b.start, ...tableLines(table)); // same number of lines
      });
      box.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' || !e.target.matches('.live-cell')) return;
        e.preventDefault();
        // Enter moves down a row; in the last row it adds one.
        const row = Number(e.target.dataset.row);
        const col = Number(e.target.dataset.col);
        if (row === table.rows.length - 1) {
          table.rows.push(table.header.map(() => ''));
          save({ row: row + 1, col });
        } else {
          box.querySelector(`[data-row="${row + 1}"][data-col="${col}"]`)?.focus();
        }
      });
      box.addEventListener('mousedown', (e) => {
        if (e.target.closest('.live-table-button')) e.preventDefault();
      });
      tools.addEventListener('click', (e) => {
        const op = e.target.closest('[data-op]')?.dataset.op;
        if (!op) return;
        const row = Math.max(0, current.row);
        const col = current.col;
        const width = table.header.length;
        if (op === 'row+') {
          table.rows.splice(row + 1, 0, Array(width).fill(''));
          save({ row: row + 1, col });
        } else if (op === 'col+') {
          table.header.splice(col + 1, 0, '');
          table.align.splice(col + 1, 0, '---');
          for (const r of table.rows) r.splice(col + 1, 0, '');
          save({ row: current.row, col: col + 1 });
        } else if (op === 'row-' && table.rows.length > 1) {
          table.rows.splice(row, 1);
          save({ row: Math.min(row, table.rows.length - 1), col });
        } else if (op === 'col-' && width > 1) {
          table.header.splice(col, 1);
          table.align.splice(col, 1);
          for (const r of table.rows) r.splice(col, 1);
          save({ row: current.row, col: Math.min(col, width - 2) });
        }
      });
    }
    return box;
  }

  // Text that ended with a line break keeps ending with one, even after lines are added at the
  // end (they take the place of the empty last line).
  const endsWithBreak = Boolean(value?.endsWith('\n'));

  draw();
  return {
    root,
    get value() {
      const text = lines.join('\n');
      return endsWithBreak && !text.endsWith('\n') ? text + '\n' : text;
    },
    // Puts the caret in the last row ("Write…").
    focusEnd() {
      focusRow(lines.length);
    },
  };
}

// ---- Markdown tables ----------------------------------------------------------------------

// "| a | b |" lines -> { header: [...], align: ['---', ':-:'...], rows: [[...]] }, all rows as wide
// as the header.
function parseTable(tableLines) {
  const cells = (line) => {
    let s = line.trim();
    if (s.startsWith('|')) s = s.slice(1);
    if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
    return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
  };
  const header = cells(tableLines[0]);
  const align = cells(tableLines[1] || '').map((a) => a || '---');
  while (align.length < header.length) align.push('---');
  const rows = tableLines.slice(2).map((line) => {
    const row = cells(line).slice(0, header.length);
    while (row.length < header.length) row.push('');
    return row;
  });
  return { header, align: align.slice(0, header.length), rows };
}

function tableLines({ header, align, rows }) {
  const line = (cells) => `| ${cells.map((c) => c.replace(/\|/g, '\\|')).join(' | ')} |`;
  return [line(header), `| ${align.join(' | ')} |`, ...rows.map(line)];
}

function el(tag, className = '', text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
