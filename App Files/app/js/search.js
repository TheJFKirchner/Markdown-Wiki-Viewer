// Search across every open folder: words, "phrases", -exclusions, #tags, folder:, path:,
// any frontmatter property (owner:maria), links:Page, and tasks (task:open, due:overdue,
// by:alex). See QUERY_HELP for the full list; the search bar shows it when empty.

import { tagMatches, resolveTarget } from './vault.js';
import { isoDate, addDays } from './tasks.js';

// Words that mean a filter rather than a frontmatter property.
const FILTER_KEYS = new Set(['tag', 'folder', 'in', 'path', 'file', 'task', 'is', 'due', 'by', 'links', 'link']);

export const QUERY_HELP = [
  ['jupiter moons', 'Notes with all of these words'],
  ['"red spot"', 'An exact phrase'],
  ['-saturn', 'Leave out notes with a word'],
  ['#planet', 'Notes with a tag (tag:planet works too)'],
  ['folder:personal', 'Only one workspace folder'],
  ['path:Moons', 'Notes whose path contains this'],
  ['owner:maria', 'Any frontmatter property'],
  ['links:Jupiter', 'Notes that link to a page'],
  ['task:open', 'Tasks: open, progress, done (or is:task)'],
  ['due:overdue', 'Tasks due: overdue, today, week'],
  ['by:alex', 'Tasks and notes signed ~alex'],
];

// "jupiter #planet folder:team -saturn" -> structured query.
export function parseQuery(text) {
  const q = { words: [], exclude: [], tags: [], folders: [], paths: [], props: [], links: [], task: null, due: null, by: [] };
  for (const match of text.matchAll(/(-?)(?:([\w-]+):)?(?:"([^"]*)"?|(\S+))/g)) {
    const [, minus, rawKey, phrase, word] = match;
    let value = (phrase ?? word ?? '').trim();
    let key = rawKey?.toLowerCase();
    if (key && /^\d+$/.test(key)) {
      value = `${rawKey}:${value}`; // "10:30" is a word, not a property
      key = undefined;
    }
    if (!value) continue; // includes a half-typed "folder:"
    if (!key && value.startsWith('#') && value.length > 1) {
      q.tags.push(value.slice(1).toLowerCase());
    } else if (!key && value.startsWith('~') && value.length > 1) {
      q.by.push(value.slice(1).toLowerCase());
    } else if (!key) {
      (minus ? q.exclude : q.words).push(value.toLowerCase());
    } else if (key === 'tag') {
      q.tags.push(value.replace(/^#/, '').toLowerCase());
    } else if (key === 'folder' || key === 'in') {
      q.folders.push(value.toLowerCase());
    } else if (key === 'path' || key === 'file') {
      q.paths.push(value.toLowerCase());
    } else if (key === 'task') {
      q.task = { open: 'open', todo: 'open', incomplete: 'open', progress: 'progress', doing: 'progress', done: 'done', complete: 'done', all: 'all' }[value.toLowerCase()] || 'all';
    } else if (key === 'is' && value.toLowerCase() === 'task') {
      q.task = q.task || 'all';
    } else if (key === 'due') {
      q.due = value.toLowerCase();
      q.task = q.task || 'notdone';
    } else if (key === 'by') {
      q.by.push(value.replace(/^~/, '').toLowerCase());
    } else if (key === 'links' || key === 'link') {
      q.links.push(value.replace(/^\[\[|\]\]$/g, ''));
    } else if (!FILTER_KEYS.has(key)) {
      // Anything else is a frontmatter property: owner:maria, status:active.
      q.props.push([key, value.toLowerCase()]);
    }
  }
  return q;
}

export function isEmptyQuery(q) {
  return !q.words.length && !q.exclude.length && !q.tags.length && !q.folders.length && !q.paths.length &&
    !q.props.length && !q.links.length && !q.task && !q.by.length;
}

// Words to highlight in results and in the opened note.
export function highlightTerms(q) {
  return [...q.words].filter(Boolean).sort((a, b) => b.length - a.length);
}

// Runs a query. Returns { pages: [{ note, score, snippet }], tasks: [task] }.
export function search(vault, text) {
  const q = parseQuery(text);
  if (isEmptyQuery(q)) return { query: q, pages: [], tasks: [] };

  // Pages linked to by links:Name filters.
  const linkTargets = q.links.map((name) => {
    const colon = name.indexOf(':');
    const link = colon > 0 ? { folder: name.slice(0, colon), target: name.slice(colon + 1) } : { folder: '', target: name };
    return resolveTarget(vault, link, '');
  });

  // Note-level filters (everything except words and task filters).
  const notePasses = (note) =>
    q.tags.every((t) => note.tags.some((nt) => tagMatches(nt, t))) &&
    q.folders.every((f) => note.folder.toLowerCase() === f) &&
    q.paths.every((p) => note.path.toLowerCase().includes(p)) &&
    q.props.every(([k, v]) => propertyText(note.properties, k).includes(v)) &&
    linkTargets.every((id) => id && note.links.some((l) => l.id === id)) &&
    !q.exclude.some((w) => searchableText(note).includes(w));

  // ---- Tasks ----
  const today = isoDate();
  const week = addDays(today, 7);
  const taskPasses = (task) => {
    if (q.task === 'notdone' && task.status === 'done') return false;
    if (q.task && !['all', 'notdone'].includes(q.task) && task.status !== q.task) return false;
    if (q.due === 'overdue' && !(task.due && task.due < today)) return false;
    if (q.due === 'today' && task.due !== today) return false;
    if (q.due === 'week' && !(task.due && task.due >= today && task.due <= week)) return false;
    if (q.due && /^\d{4}-\d{2}-\d{2}$/.test(q.due) && task.due !== q.due) return false;
    if (q.due === 'none' && task.due) return false;
    const signers = [task.signature, ...task.subnotes.map((n) => n.signature)].map((s) => (s || '').toLowerCase());
    if (!q.by.every((b) => signers.includes(b))) return false;
    const text = (task.text + ' ' + task.subnotes.map((n) => n.text).join(' ')).toLowerCase();
    return q.words.every((w) => text.includes(w)) && !q.exclude.some((w) => text.includes(w));
  };
  const taskMode = Boolean(q.task) || (q.by.length > 0 && !q.words.length);
  let tasks = vault.tasks.filter((t) => notePasses(t.note) && taskPasses(t));
  tasks.sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999') || a.text.localeCompare(b.text));

  // ---- Pages (task searches list tasks only) ----
  const pages = [];
  if (!taskMode) {
    for (const note of vault.notes.values()) {
      if (!notePasses(note)) continue;
      if (q.by.length && !q.by.every((b) => note.content.toLowerCase().includes('~' + b))) continue;
      if (!q.words.every((w) => searchableText(note).includes(w))) continue;
      pages.push({ note, score: score(note, q.words), snippet: snippet(note, highlightTerms(q)) });
    }
    pages.sort((a, b) => b.score - a.score || a.note.name.localeCompare(b.note.name));
    if (!q.words.length) tasks = []; // pure page filters (#tag, folder:) list pages only
  }
  return { query: q, pages, tasks };
}

// Everything a word can match in: name, path, tags, property values and text.
function searchableText(note) {
  if (!note._search) {
    const values = Object.values(note.properties || {}).flat(Infinity).map((v) => (v && typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')));
    note._search = [note.name, note.path, note.tags.join(' '), ...values, note.body].join('\n').toLowerCase();
  }
  return note._search;
}

function propertyText(properties, key) {
  if (!properties) return '';
  const entry = Object.entries(properties).find(([k]) => k.toLowerCase() === key);
  if (!entry || entry[1] == null) return '';
  const value = entry[1];
  return (Array.isArray(value) ? value.join(' ') : typeof value === 'object' ? JSON.stringify(value) : String(value)).toLowerCase();
}

// Name matches count most, then tags/properties/headings, then how often words appear.
function score(note, words) {
  if (!words.length) return 0;
  const name = note.name.toLowerCase();
  let total = 0;
  for (const w of words) {
    if (name === w) total += 30;
    else if (name.startsWith(w)) total += 20;
    else if (name.includes(w)) total += 12;
    if (note.tags.some((t) => t.includes(w))) total += 6;
    if (note.description.toLowerCase().includes(w)) total += 5;
    if (new RegExp(`^#{1,6} .*${escapeRegex(w)}`, 'im').test(note.body)) total += 4;
    total += Math.min(8, countOf(note.body.toLowerCase(), w));
  }
  return total;
}

// A short piece of the note around the first match (or its description).
function snippet(note, terms) {
  const lines = note.body.split(/\r?\n/).filter((l) => l.trim());
  const matches = (l) => terms.some((t) => l.toLowerCase().includes(t));
  // Prefer a matching body line; a heading that just repeats the title isn't useful.
  const line = terms.length
    ? lines.find((l) => !/^#/.test(l) && matches(l)) ||
      (matches(note.description) ? null : lines.find((l) => matches(l) && l.replace(/^#+\s*/, '') !== note.name))
    : null;
  let text = (line || note.description || lines.find((l) => !/^#/.test(l)) || '').trim();
  text = text.replace(/^#+\s+|^[-*+] (\[[ xX/]\] )?|^>\s?/g, '');
  if (line && text.length > 140) {
    const at = text.toLowerCase().indexOf(terms.find((t) => text.toLowerCase().includes(t)));
    const start = Math.max(0, at - 50);
    text = (start ? '…' : '') + text.slice(start, start + 140) + (start + 140 < text.length ? '…' : '');
  } else if (text.length > 140) {
    text = text.slice(0, 140) + '…';
  }
  return text;
}

function countOf(text, word) {
  let n = 0;
  for (let i = text.indexOf(word); i >= 0 && n < 50; i = text.indexOf(word, i + word.length)) n++;
  return n;
}

export function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// HTML with <mark> around the terms (text is escaped).
export function markTerms(text, terms) {
  const escape = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  if (!terms.length) return escape(text);
  const pattern = new RegExp(`(${terms.map(escapeRegex).join('|')})`, 'gi');
  return text.split(pattern).map((part, i) => (i % 2 ? `<mark>${escape(part)}</mark>` : escape(part))).join('');
}
