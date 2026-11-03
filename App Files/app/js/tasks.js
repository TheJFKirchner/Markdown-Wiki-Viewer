// Tasks inside notes: reading them and producing the line edits that change them.
//
// Format (plain Markdown, works in any editor):
//   - [ ] Email Sam about the budget due:2026-11-02 ~alex
//   - [/] Book the dark-sky site due:2026-11-03 ~maria          <- in progress
//   - [x] Order a red flashlight done:2026-10-29 ~alex           <- complete
//       - 2026-10-30 14:05 ~alex: Roadblock: the office only answers on weekdays
//
// Status: [ ] incomplete, [/] in progress, [x] complete.
// due:/done: dates and the ~signature are optional and can sit anywhere in the line.
// Indented "- " lines under a task are its subnotes.

export const STATUS = { open: ' ', progress: '/', done: 'x' };
const STATUS_BY_CHAR = { ' ': 'open', '/': 'progress', x: 'done', X: 'done' };

const TASK_LINE = /^(\s*)([-*+]) \[([ xX/])\] (.*)$/;
const LIST_ITEM = /^(\s*)[-*+] (.*)$/;
const SUBNOTE = /^(\d{4}-\d{2}-\d{2})(?: (\d{1,2}:\d{2}))?(?: ~([\p{L}\p{N}_-]+))?: (.*)$/u;
const DUE = /(^|\s)due:(\d{4}-\d{2}-\d{2})(?=\s|$)/;
const DONE = /(^|\s)done:(\d{4}-\d{2}-\d{2})(?=\s|$)/;
const SIGNATURE = /(^|\s)~([\p{L}\p{N}_-]+)(?=\s|$)/u;
export const SIGNATURE_PATTERN = /^[\p{L}\p{N}_-]+$/u;

// All tasks in a note's text. Line numbers are 0-based lines of the whole file.
export function parseTasks(content) {
  const lines = content.split(/\r?\n/);
  const tasks = [];
  let inFence = false;
  let inFrontmatter = lines[0] === '---';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (inFrontmatter) {
      if (i > 0 && line === '---') inFrontmatter = false;
      continue;
    }
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    if (inFence) continue;

    const m = TASK_LINE.exec(line);
    if (!m) continue;
    const indent = m[1].length;
    const rest = m[4];
    const task = {
      line: i,
      raw: line,
      status: STATUS_BY_CHAR[m[3]],
      text: cleanText(rest),
      due: DUE.exec(rest)?.[2] || '',
      done: DONE.exec(rest)?.[2] || '',
      signature: SIGNATURE.exec(rest)?.[2] || '',
      subnotes: [],
      childIndent: '',   // indentation used by existing subnotes
      blockEnd: i,       // last line belonging to this task (it and everything indented under it)
    };

    // Everything indented deeper than the task belongs to it.
    for (let j = i + 1; j < lines.length; j++) {
      const child = lines[j];
      if (!child.trim()) break;
      const childIndent = child.match(/^\s*/)[0];
      if (childIndent.replace(/\t/g, '    ').length <= m[1].replace(/\t/g, '    ').length) break;
      task.blockEnd = j;
      const item = LIST_ITEM.exec(child);
      if (!item || TASK_LINE.test(child)) continue; // subtasks are listed as tasks of their own
      if (!task.childIndent) task.childIndent = item[1];
      const note = SUBNOTE.exec(item[2]);
      task.subnotes.push(
        note
          ? { line: j, date: note[1], time: note[2] || '', signature: note[3] || '', text: note[4] }
          : { line: j, date: '', time: '', signature: '', text: item[2] },
      );
    }
    task.indent = indent;
    tasks.push(task);
  }
  return tasks;
}

// The task text without its due:, done: and ~signature tokens.
function cleanText(rest) {
  return rest
    .replace(new RegExp(DUE.source, 'g'), ' ')
    .replace(new RegExp(DONE.source, 'g'), ' ')
    .replace(new RegExp(SIGNATURE.source, 'gu'), ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// ---- Where a new task goes on a page ---------------------------------------------------

const TASKS_HEADING = /^(#{1,6})\s+tasks\s*#*\s*$/i;

// The line a new task should be inserted after: the last non-blank line of the page's
// first "Tasks" heading section (any level). -1 if the page has no Tasks section.
export function tasksSectionEnd(content) {
  const lines = content.split(/\r?\n/);
  let inFence = false;
  let inFrontmatter = lines[0] === '---';
  let level = 0;   // level of the Tasks heading once found
  let last = -1;   // last non-blank line in the section so far

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (inFrontmatter) {
      if (i > 0 && line === '---') inFrontmatter = false;
      continue;
    }
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    const heading = !inFence && /^(#{1,6})\s/.exec(line);
    if (!level) {
      const tasks = !inFence && TASKS_HEADING.exec(line);
      if (tasks) {
        level = tasks[1].length;
        last = i;
      }
      continue;
    }
    if (heading && heading[1].length <= level) break; // the next section starts
    if (line.trim()) last = i;
  }
  return level ? last : -1;
}

// ---- Building edited lines ----------------------------------------------------------

export function withStatus(line, status, today) {
  let next = line.replace(/^(\s*[-*+] \[)[ xX/](\])/, `$1${STATUS[status]}$2`);
  next = removeToken(next, DONE);
  if (status === 'done') next = addToken(next, `done:${today}`);
  return next;
}

export function withDue(line, due) {
  const next = removeToken(line, DUE);
  return due ? addToken(next, `due:${due}`) : next;
}

// The task line with new text. Its indent, bullet, status and every due:/done:/~signature token
// stay; the tokens move to the end of the line.
const TOKENS = new RegExp(`(?<=^|\\s)(?:due:\\d{4}-\\d{2}-\\d{2}|done:\\d{4}-\\d{2}-\\d{2}|~[\\p{L}\\p{N}_-]+)(?=\\s|$)`, 'gu');
export function withText(line, text) {
  const m = TASK_LINE.exec(line);
  if (!m) return line;
  const tokens = m[4].match(TOKENS) || [];
  return `${m[1]}${m[2]} [${m[3]}] ${[text.replace(/\s+/g, ' ').trim(), ...tokens].filter(Boolean).join(' ')}`;
}

// A subnote line with new text; its bullet, date, time and ~signature stay.
export function withSubnoteText(line, text) {
  const item = LIST_ITEM.exec(line);
  if (!item) return line;
  const note = SUBNOTE.exec(item[2]);
  const head = line.slice(0, line.length - item[2].length) + (note ? item[2].slice(0, item[2].length - note[4].length) : '');
  return head + text.replace(/\s+/g, ' ').trim();
}

// An empty task (just its signature) to fill in, as a sibling of `like` (a task line) if given.
export function emptyTaskLine(signature, like = '') {
  const [, indent = '', bullet = '-'] = TASK_LINE.exec(like) || [];
  return `${indent}${bullet} [ ] ${signature ? `~${signature}` : ''}`;
}

export function newTaskLine(text, due, signature) {
  let line = `- [ ] ${text.trim()}`;
  if (due) line += ` due:${due}`;
  if (signature) line += ` ~${signature}`;
  return line;
}

export function newSubnoteLine(task, text, signature, now = new Date()) {
  const indent = task.childIndent || task.raw.match(/^\s*/)[0] + '  ';
  const sig = signature ? ` ~${signature}` : '';
  return `${indent}- ${isoDate(now)} ${pad(now.getHours())}:${pad(now.getMinutes())}${sig}: ${text.trim()}`;
}

function removeToken(line, pattern) {
  return line.replace(new RegExp(pattern.source, pattern.flags + 'g'), '').replace(/\s+$/, '');
}

// New tokens go before a trailing ~signature, so the signature stays last.
function addToken(line, token) {
  const sig = /(\s~[\p{L}\p{N}_-]+)\s*$/u.exec(line);
  if (sig) return line.slice(0, sig.index) + ` ${token}` + sig[1];
  return `${line.replace(/\s+$/, '')} ${token}`;
}

// ---- Dates ----------------------------------------------------------------------------

const pad = (n) => String(n).padStart(2, '0');

// YYYY-MM-DD in local time.
export function isoDate(date = new Date()) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  return isoDate(new Date(y, m - 1, d + days));
}

// "Today", "Tomorrow", "Yesterday", "Mon, Nov 2", or with the year if it isn't this year.
export function friendlyDate(iso, today = isoDate()) {
  if (iso === today) return 'Today';
  if (iso === addDays(today, 1)) return 'Tomorrow';
  if (iso === addDays(today, -1)) return 'Yesterday';
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const options = { weekday: 'short', month: 'short', day: 'numeric' };
  if (y !== Number(today.slice(0, 4))) options.year = 'numeric';
  return date.toLocaleDateString(undefined, options);
}
