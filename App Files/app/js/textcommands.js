// Markdown editing commands for a <textarea>, shared by the full editor (editor.js), the
// in-place editor (inlineeditor.js) and the Notes view (notesview.js): bold/italic/..., lists,
// headings, indenting, links, snippets, full tasks (Ctrl+T), lists that continue on Enter,
// and keyboard shortcuts. Every change goes through
// replaceText, so Ctrl+Z / Ctrl+Y undo and redo work as usual.

import { replaceText } from './autocomplete.js';
import { isoDate, addDays } from './tasks.js';

const ICON = (path) => `<svg viewBox="0 0 24 24">${path}</svg>`;
export const ICONS = {
  bold: ICON('<path d="M7 5h6a3.5 3.5 0 0 1 0 7H7zM7 12h7a3.5 3.5 0 0 1 0 7H7z"/>'),
  italic: ICON('<path d="M10 5h8M6 19h8M14 5l-4 14"/>'),
  strike: ICON('<path d="M5 12h14M16 7.5C15.4 6 13.9 5 12 5c-2.5 0-4 1.3-4 3 0 1.4 1 2.4 3 3M8 16.5c.6 1.5 2.1 2.5 4 2.5 2.5 0 4-1.3 4-3 0-.8-.3-1.5-.9-2"/>'),
  code: ICON('<path d="m9 8-4 4 4 4M15 8l4 4-4 4"/>'),
  bullet: ICON('<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1" fill="currentColor"/><circle cx="4.5" cy="12" r="1" fill="currentColor"/><circle cx="4.5" cy="18" r="1" fill="currentColor"/>'),
  number: ICON('<path d="M10 6h10M10 12h10M10 18h10M4 5h1.5v4M4 9h3M4 15.5a1.5 1.5 0 1 1 2.5 1L4 19h3"/>'),
  task: ICON('<rect x="3.5" y="5" width="6" height="6" rx="1.5"/><path d="m4.8 16.5 1.6 1.6 2.8-3M13 8h8M13 17h8"/>'),
  quote: ICON('<path d="M5 7h14M9 12h10M9 17h10M5 11v7"/>'),
  link: ICON('<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'),
  codeblock: ICON('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m9 10-2 2 2 2M15 10l2 2-2 2"/>'),
  table: ICON('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M3 15h18M10 5v14"/>'),
  divider: ICON('<path d="M3 12h18"/><path d="M8 6h8M8 18h8" opacity=".45"/>'),
  outdent: ICON('<path d="M11 6h10M11 12h10M11 18h10M7 9l-3 3 3 3"/>'),
  indent: ICON('<path d="M11 6h10M11 12h10M11 18h10M4 9l3 3-3 3"/>'),
  plus: ICON('<path d="M12 5v14M5 12h14"/>'),
  check: ICON('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
  chevron: '<svg class="chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>',
};

// The Insert menu: [label, (signature) -> template, placement].
// In templates "§" marks the caret and "§text§" selects text. Placement: 'block' = on its own
// lines, 'line' = on a new line, 'top' = top of the note, default = at the caret.
const now = () => `${isoDate()} ${new Date().toTimeString().slice(0, 5)}`;
const signed = (sig) => (sig ? ` ~${sig}` : '');
export const INSERTS = [
  ["Today's date", () => isoDate()],
  ['Date and time', () => now()],
  ['Signed note', (sig) => `${now()}${signed(sig)}: `],
  ['Task with due date', (sig) => `- [ ] §task§ due:${isoDate()}${signed(sig)}`, 'line'],
  ['Task with a note (Ctrl+T)', 'fulltask'],
  ['Tasks section', () => '## Tasks\n- [ ] §', 'block'],
  ['Properties (frontmatter)', () => '---\ntags: [§]\ndescription: \n---\n', 'top'],
  ['Meeting notes', (sig) => `## Meeting: §title§\n- **Date:** ${isoDate()}\n- **Attendees:** \n\n### Agenda\n- \n\n### Notes\n- \n\n### Decisions\n- \n\n### Action items\n- [ ] ${signed(sig)}`, 'block'],
  ['Decision record', () => `## Decision: §title§\n- **Status:** proposed\n- **Date:** ${isoDate()}\n\n### Context\n\n### Options\n1. \n2. \n\n### Decision\n\n### Consequences\n`, 'block'],
  ['Table (3 columns)', () => '| §Column§ | Column | Column |\n| --- | --- | --- |\n|  |  |  |\n|  |  |  |', 'block'],
  ['Note callout', () => '> **Note:** §', 'line'],
];

const LIST_PREFIX = /^(\s*)((?:[-*+] \[[ xX/]\] )|(?:[-*+] )|(?:\d+[.)] )|(?:> ))?/;

// Ctrl+key and Ctrl+Shift+key shortcuts (e.code, so they work on any keyboard layout).
export const SHORTCUTS = { KeyB: 'bold', KeyI: 'italic', KeyK: 'link', Backquote: 'code', KeyT: 'fulltask' };
export const SHIFT_SHORTCUTS = { KeyX: 'strike', Digit8: 'bullet', Digit7: 'number', Digit9: 'task' };

// A full task (Ctrl+T): placeholders for its text, due date (a week out) and one subnote.
// Tab / Shift+Tab move between the three placeholders.
const TASK_TEXT = 'New task';
const TASK_NOTE = 'Notes';
const TASK_PARTS = /^(\s*[-*+] \[[ xX/]\] )(.*?)(?=\s+due:|\s+~|$)/;

export function createTextCommands(ta, { getSignature }) {
  let filling = -1; // while filling in a full task: where its line starts

  function run(cmd) {
    const actions = {
      bold: () => wrap('**', 'bold text'),
      italic: () => wrap('_', 'italic text'),
      strike: () => wrap('~~', 'struck text'),
      code: () => wrap('`', 'code'),
      bullet: () => toggleList('bullet'),
      number: () => toggleList('number'),
      task: () => toggleList('task'),
      quote: () => toggleList('quote'),
      link: insertLink,
      fulltask: insertFullTask,
      codeblock: () => insertBlock('```\n§\n```'),
      table: () => insertBlock(INSERTS.find(([label]) => label.startsWith('Table'))[1]()),
      divider: () => insertBlock('---\n§'),
      indent: () => shiftLines(1),
      outdent: () => shiftLines(-1),
    };
    actions[cmd]?.();
    ta.focus();
  }

  // Shortcuts, Tab/Shift+Tab and list-continuing Enter. Returns true if it handled the key.
  function handleKeydown(e) {
    const ctrl = e.ctrlKey || e.metaKey;
    const cmd = ctrl && !e.altKey && (e.shiftKey ? SHIFT_SHORTCUTS : SHORTCUTS)[e.code];
    if (cmd) {
      e.preventDefault();
      run(cmd);
      return true;
    }
    if (e.key === 'Tab' && !ctrl) {
      e.preventDefault();
      if (nextTaskPart(e.shiftKey ? -1 : 1)) return true;
      run(e.shiftKey ? 'outdent' : 'indent');
      return true;
    }
    if (e.key === 'Enter' && !ctrl && !e.shiftKey && !e.altKey) return continueList(e);
    return false;
  }

  // Wraps the selection in a marker (or removes it if it's already there).
  function wrap(marker, placeholder) {
    const { selectionStart: s, selectionEnd: e, value } = ta;
    const sel = value.slice(s, e);
    const m = marker.length;
    if (value.slice(s - m, s) === marker && value.slice(e, e + m) === marker) {
      replaceText(ta, s - m, e + m, sel);
      ta.setSelectionRange(s - m, e - m);
    } else if (sel.length > 2 * m && sel.startsWith(marker) && sel.endsWith(marker)) {
      const inner = sel.slice(m, -m);
      replaceText(ta, s, e, inner);
      ta.setSelectionRange(s, s + inner.length);
    } else {
      const inner = sel || placeholder;
      replaceText(ta, s, e, marker + inner + marker);
      ta.setSelectionRange(s + m, s + m + inner.length);
    }
  }

  // The full lines touched by the selection.
  function selectedLines() {
    const { selectionStart: s, value } = ta;
    let e = ta.selectionEnd;
    if (e > s && value[e - 1] === '\n') e--; // a selection ending at a line start doesn't include that line
    const start = value.lastIndexOf('\n', s - 1) + 1;
    let end = value.indexOf('\n', e);
    if (end < 0) end = value.length;
    return { start, end, lines: value.slice(start, end).split('\n') };
  }

  // Replaces whole lines; keeps a caret at the end of a single line, else selects the block.
  function setLines({ start, end, lines: before }, lines) {
    const collapsed = ta.selectionStart === ta.selectionEnd;
    const text = lines.join('\n');
    if (text === before.join('\n')) return;
    replaceText(ta, start, end, text);
    if (collapsed && lines.length === 1) ta.setSelectionRange(start + text.length, start + text.length);
    else ta.setSelectionRange(start, start + text.length);
  }

  function toggleList(kind) {
    const range = selectedLines();
    const prefixOf = (n) => ({ bullet: '- ', task: '- [ ] ', quote: '> ' })[kind] || `${n + 1}. `;
    const has = (line) => {
      const p = LIST_PREFIX.exec(line)[2] || '';
      if (kind === 'task') return /^[-*+] \[/.test(p);
      if (kind === 'bullet') return /^[-*+] $/.test(p);
      if (kind === 'quote') return p === '> ';
      return /^\d/.test(p);
    };
    const filled = range.lines.filter((l) => l.trim());
    const removing = filled.length > 0 && filled.every(has);
    let n = 0;
    setLines(range, range.lines.map((line) => {
      if (!line.trim() && range.lines.length > 1) return line;
      const m = LIST_PREFIX.exec(line);
      const rest = line.slice(m[0].length);
      return removing ? m[1] + rest : m[1] + prefixOf(n++) + rest;
    }));
  }

  function setHeading(level) {
    const range = selectedLines();
    setLines(range, range.lines.map((line) => {
      const rest = line.replace(/^#{1,6}\s+/, '');
      return level ? `${'#'.repeat(level)} ${rest}` : rest;
    }));
  }

  // Heading level (0-6) of the line the caret is on.
  function headingLevel() {
    const m = /^(#{1,6})\s/.exec(selectedLines().lines[0]);
    return m ? m[1].length : 0;
  }

  function shiftLines(direction) {
    const range = selectedLines();
    setLines(range, range.lines.map((line) => (direction > 0 ? '  ' + line : line.replace(/^( {1,2}|\t)/, ''))));
  }

  // Enter in a list starts the next item; Enter on an empty item ends the list.
  function continueList(e) {
    const { selectionStart: s, selectionEnd: end, value } = ta;
    if (s !== end) return false;
    const lineStart = value.lastIndexOf('\n', s - 1) + 1;
    let lineEnd = value.indexOf('\n', s);
    if (lineEnd < 0) lineEnd = value.length;
    const line = value.slice(lineStart, lineEnd);
    const m = /^(\s*)([-*+] \[[ xX/]\] |[-*+] |(\d+)([.)]) |> )/.exec(line);
    if (!m || s - lineStart < m[0].length) return false;
    e.preventDefault();
    if (!line.slice(m[0].length).trim() && s === lineEnd) {
      // Empty item: a nested one moves out a level; a top-level one ends the list, leaving a
      // blank line so the next paragraph isn't read as part of the last item.
      replaceText(ta, lineStart, lineEnd, m[1].length >= 2 ? m[1].slice(2) + m[2] : '\n');
      return true;
    }
    let prefix = m[2];
    if (m[3]) prefix = `${Number(m[3]) + 1}${m[4]} `;
    else if (/\[[ xX/]\]/.test(prefix)) prefix = prefix.replace(/\[[ xX/]\]/, '[ ]');
    replaceText(ta, s, s, '\n' + m[1] + prefix);
    return true;
  }

  // Adds "- [ ] New task due:<a week out> ~sig" and an indented "- <now> ~sig: Notes" subnote
  // on their own lines (in place of an empty line, else after the current one), keeping the
  // current list indent, and selects "New task".
  function insertFullTask() {
    const sig = getSignature();
    const signedBy = sig ? ` ~${sig}` : '';
    const { selectionStart: s, value } = ta;
    const lineStart = value.lastIndexOf('\n', s - 1) + 1;
    let lineEnd = value.indexOf('\n', s);
    if (lineEnd < 0) lineEnd = value.length;
    const line = value.slice(lineStart, lineEnd);
    // An empty line or an empty list item ("- ") is replaced by the task.
    const empty = /^\s*(?:(?:[-*+]|\d+[.)])(?: \[[ xX/]\])?)?\s*$/.test(line);
    const indent = /^\s*[-*+] |^\s*\d+[.)] /.test(line) || empty ? line.match(/^\s*/)[0] : '';
    const block =
      `${indent}- [ ] ${TASK_TEXT} due:${addDays(isoDate(), 7)}${signedBy}\n` +
      `${indent}  - ${now()}${signedBy}: ${TASK_NOTE}`;
    replaceText(ta, empty ? lineStart : lineEnd, lineEnd, (empty ? '' : '\n') + block);
    filling = empty ? lineStart : lineEnd + 1;
    selectTaskPart(0);
  }

  // The three placeholder ranges of the task being filled in: [text, due date, subnote].
  function taskParts() {
    const { value } = ta;
    let end = value.indexOf('\n', filling);
    if (end < 0) end = value.length;
    const line = value.slice(filling, end);
    const m = TASK_PARTS.exec(line);
    if (!m) return null;
    const parts = [[filling + m[1].length, filling + m[1].length + m[2].length]];
    const due = /(\sdue:)(\S*)/.exec(line);
    if (due) parts.push([filling + due.index + due[1].length, filling + due.index + due[0].length]);
    let noteEnd = value.indexOf('\n', end + 1);
    if (noteEnd < 0) noteEnd = value.length;
    const note = /^\s+[-*+] .*?: /.exec(value.slice(end + 1, noteEnd));
    if (end < value.length && note) parts.push([end + 1 + note[0].length, noteEnd]);
    return parts;
  }

  function selectTaskPart(i) {
    const parts = taskParts();
    if (parts?.[i]) ta.setSelectionRange(...parts[i]);
  }

  // Tab / Shift+Tab inside a task being filled in. Returns false when not filling one in (the
  // caret left it), so Tab indents as usual. Tab after the last part ends the fill-in.
  function nextTaskPart(direction) {
    if (filling < 0) return false;
    const parts = taskParts();
    const caret = ta.selectionStart;
    if (!parts || caret < parts[0][0] - 8 || caret > parts[parts.length - 1][1]) {
      filling = -1;
      return false;
    }
    let current = parts.findIndex(([a, b]) => caret >= a && caret <= b);
    if (current < 0) current = 0;
    const next = current + direction;
    if (next >= parts.length) {
      filling = -1;
      const end = parts[parts.length - 1][1];
      ta.setSelectionRange(end, end);
    } else {
      ta.setSelectionRange(...parts[Math.max(0, next)]);
    }
    return true;
  }

  // "[[" then the autocomplete list; a selection becomes the link text.
  function insertLink() {
    const { selectionStart: s, selectionEnd: e, value } = ta;
    if (s !== e) {
      replaceText(ta, s, e, `[[${value.slice(s, e)}]]`);
      return;
    }
    replaceText(ta, s, s, '[[]]');
    ta.setSelectionRange(s + 2, s + 2);
    ta.dispatchEvent(new Event('input', { bubbles: true })); // opens the suggestions
  }

  // Inserts a template on its own lines: in place of an empty line, or after the current one.
  function insertBlock(template) {
    const { selectionStart: s, value } = ta;
    const lineStart = value.lastIndexOf('\n', s - 1) + 1;
    let lineEnd = value.indexOf('\n', s);
    if (lineEnd < 0) lineEnd = value.length;
    if (!value.slice(lineStart, lineEnd).trim()) insertTemplate(lineStart, lineEnd, template);
    else insertTemplate(lineEnd, lineEnd, '\n\n' + template);
  }

  function insertSnippet([, make, where]) {
    if (make === 'fulltask') return run('fulltask');
    const template = make(getSignature());
    if (where === 'top') {
      if (ta.value.startsWith('---\n')) return; // already has properties
      insertTemplate(0, 0, template);
    } else if (where === 'block') {
      insertBlock(template);
    } else if (where === 'line') {
      const { selectionStart: s, value } = ta;
      const lineStart = value.lastIndexOf('\n', s - 1) + 1;
      const onEmptyLine = !value.slice(lineStart, s).trim();
      insertTemplate(s, ta.selectionEnd, (onEmptyLine ? '' : '\n') + template);
    } else {
      insertTemplate(ta.selectionStart, ta.selectionEnd, template + '§');
    }
  }

  // Inserts a template; "§" marks the caret, "§text§" selects that text.
  function insertTemplate(from, to, template) {
    const marks = [...template.matchAll(/§/g)].map((m) => m.index).slice(0, 2);
    const text = template.replace(/§/g, '');
    replaceText(ta, from, to, text);
    if (marks.length) {
      const a = from + marks[0];
      const b = marks.length > 1 ? from + marks[1] - 1 : a;
      ta.setSelectionRange(a, b);
    }
  }

  return { run, handleKeydown, setHeading, headingLevel, insertSnippet };
}
