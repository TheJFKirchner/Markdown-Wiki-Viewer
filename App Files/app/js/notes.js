// Notes: quick, not-yet-filed notes (a daily or weekly note, meeting jottings...) kept in a
// notes folder ("Notes" unless the user picks another) inside a workspace folder, made from
// templates in that workspace folder's "Templates/Notes" folder. A note is open until it's wrapped:
//
//   ---
//   type: daily
//   started: 2026-10-31
//   status: open            <- "wrapped" once wrapped, with ended: <date>
//   tags: [daily-note]
//   ---
//   # Daily · Saturday, October 31
//
//   Text before the first section.
//
//   ## 09:15 · Standup       <- one "## " section per meeting or topic
//   - ...

import { isoDate } from './tasks.js';

export const DEFAULT_NOTES_DIR = 'Notes';
export const TEMPLATES_DIR = 'Templates';

// A notes folder typed by the user -> "Notes" or "Work/Notes": forward slashes, no leading or
// trailing ones, no "." or "..", no characters Windows doesn't allow. Empty if nothing is left.
export function cleanNotesDir(text) {
  return String(text || '')
    .replace(/\\/g, '/')
    .split('/')
    .map((part) => part.replace(/[<>:"|?*\x00-\x1f]/g, '').trim())
    .filter((part) => part && part !== '.' && part !== '..')
    .join('/');
}

// Used when a wiki's Templates folder doesn't have a file of that name: the Daily and Weekly
// templates from the path list (template.daily, template.weekly), read through the host and given
// to setDefaultTemplates() when the app starts and whenever they change. No text is kept here.
let defaultTemplates = {};
export function setDefaultTemplates(map) {
  defaultTemplates = { ...map };
}

export const isNotesPath = (path, dir = DEFAULT_NOTES_DIR) => path.toLowerCase().startsWith(`${dir.toLowerCase()}/`);
export const isTemplatePath = (path) => path.startsWith(`${TEMPLATES_DIR}/`);
// A wiki's Templates folder has two parts:
//   Templates/Notes/<name>.md  quick-note templates (the New note menu)
//   Templates/Pages/<name>.md  page templates, for the pages Ingest creates, with a frontmatter
//                              `description` saying when to use each
// Older wikis kept quick-note templates directly in Templates/; those still count.
export const NOTE_TEMPLATES_DIR = `${TEMPLATES_DIR}/Notes`;
export const PAGE_TEMPLATES_DIR = `${TEMPLATES_DIR}/Pages`;

// What the Notes list shows about a note.
export function noteInfo(note) {
  const p = note.properties || {};
  const text = (value) => (value === undefined || value === null ? '' : String(value));
  const ended = text(p.ended);
  return {
    type: text(p.type),
    started: text(p.started) || (/^\d{4}-\d{2}-\d{2}/.exec(note.name) || [''])[0],
    ended,
    wrapped: text(p.status).toLowerCase() === 'wrapped' || Boolean(ended),
  };
}

// Quick-note templates available in a workspace folder: the built-in ones, replaced or added to
// by the files in its Templates/Notes folder (or, in older wikis, directly in Templates).
// -> [{ name, id (null for a built-in one not saved yet), text }]
export function templatesIn(vault, alias) {
  const byName = new Map(Object.entries(defaultTemplates).map(([name, text]) => [name.toLowerCase(), { name, id: null, text }]));
  const directlyIn = (path, dir) => path.startsWith(`${dir}/`) && path.indexOf('/', dir.length + 1) < 0;
  const notes = [...(vault?.notes.values() || [])].filter((n) => n.folder === alias);
  // Templates/Notes last, so its file wins over an older one of the same name.
  for (const dir of [TEMPLATES_DIR, NOTE_TEMPLATES_DIR]) {
    for (const note of notes) {
      if (directlyIn(note.path, dir)) byName.set(note.name.toLowerCase(), { name: note.name, id: note.id, text: note.content });
    }
  }
  return [...byName.values()].sort((a, b) => order(a.name) - order(b.name) || a.name.localeCompare(b.name));
}
const order = (name) => ({ daily: 0, weekly: 1 })[name.toLowerCase()] ?? 2;

// Fills in {{date}} 2026-10-31, {{time}} 09:15, {{day}} Saturday, October 31,
// {{week}} 44, {{year}} 2026, {{signature}} alex.
export function fillTemplate(text, { now = new Date(), signature = '' } = {}) {
  const values = {
    date: isoDate(now),
    time: clock(now),
    day: now.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' }),
    week: String(isoWeek(now)),
    year: String(now.getFullYear()),
    signature,
  };
  return text
    .replace(/\r\n/g, '\n')
    .replace(/\{\{\s*(\w+)\s*\}\}/g, (all, key) => (key in values ? values[key] : all));
}

// Notes/2026-10-31 Daily.md (in the notes folder `dir`), or "... Daily 2.md" if that's taken.
export function newNotePath(vault, alias, dir, templateName, now = new Date()) {
  const base = `${dir}/${isoDate(now)} ${templateName}`;
  const taken = (path) => [...vault.notes.values()].some((n) => n.folder === alias && n.path.toLowerCase() === path.toLowerCase());
  let path = `${base}.md`;
  for (let i = 2; taken(path); i++) path = `${base} ${i}.md`;
  return path;
}

export function clock(now = new Date()) {
  return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
}

function isoWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
}

// ---- A note as parts the Notes view edits --------------------------------------------

// -> { front: [frontmatter lines, with the --- lines] or [], title, intro, sections: [{ heading, text }],
//      layout: the lines exactly as they were, so noteLines can give back untouched parts unchanged }
export function parseNote(content) {
  const lines = content.split(/\r?\n/);
  let i = 0;
  let front = [];
  if (lines[0] === '---') {
    const close = lines.findIndex((l, j) => j > 0 && /^---\s*$/.test(l));
    if (close > 0) {
      front = lines.slice(0, close + 1);
      i = close + 1;
    }
  }
  const pre = [];
  while (i < lines.length && !lines[i].trim()) pre.push(lines[i++]);
  let title = '';
  let titleLine = null;
  const h1 = /^#[ \t]+(.*?)[ \t]*$/.exec(lines[i] || '');
  if (h1) {
    title = h1[1];
    titleLine = lines[i++];
  }

  const intro = [];
  const sections = [];
  let inFence = false;
  for (; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence;
    const heading = !inFence && /^##[ \t]+(.*?)[ \t]*$/.exec(line);
    if (heading) sections.push({ heading: heading[1], line, lines: [] });
    else (sections.length ? sections[sections.length - 1].lines : intro).push(line);
  }
  const parts = {
    front,
    title,
    intro: trimBlank(intro).join('\n'),
    sections: sections.map((s) => ({ heading: s.heading, text: trimBlank(s.lines).join('\n') })),
  };
  parts.layout = {
    pre, title, titleLine,
    intro: { text: parts.intro, raw: intro },
    sections: sections.map((s, n) => ({ heading: s.heading, line: s.line, text: parts.sections[n].text, raw: s.lines })),
  };
  return parts;
}

// The file's lines for those parts (ending with an empty line = a final newline). With the
// layout parseNote gave (and each section's `index` in it), a part that wasn't changed keeps
// its lines exactly, blank lines included; a changed part keeps the blank lines around it.
export function noteLines({ front, title, intro, sections, layout }) {
  const out = [...front];
  if (layout) out.push(...layout.pre);
  const hadTitle = layout?.titleLine != null;
  if (hadTitle && title.trim() === layout.title.trim()) out.push(layout.titleLine);
  else if (title.trim()) out.push(`# ${title.trim()}`, ...(hadTitle ? [] : [''])); // the blank line after an old title is the intro's
  out.push(...part(intro, layout?.intro, false));
  for (const section of sections) {
    const was = layout?.sections[section.index];
    const heading = section.heading.trim();
    out.push(was && heading === was.heading.trim() ? was.line : `## ${heading || 'Untitled'}`);
    out.push(...part(section.text, was, true));
  }
  if (!layout && out[out.length - 1] !== '') out.push('');
  return out;
}

// A part's lines: as they were if its text is unchanged, else its new text between the blank
// lines that were around it. A part that's new (or was only blank lines) is followed by one
// blank line; without one, so is an empty intro (alwaysBlank: false) — it's left out.
function part(text, was, alwaysBlank) {
  const lines = trimBlank(text.split('\n'));
  if (was && lines.join('\n') === was.text) return [...was.raw];
  const lead = was ? was.raw.findIndex((l) => l.trim()) : -1;
  if (lead < 0) {
    const blanks = was?.raw.length ? was.raw : [''];
    return lines.length || alwaysBlank ? [...lines, ...blanks] : [...(was?.raw || [])];
  }
  let trail = 0;
  while (!was.raw[was.raw.length - 1 - trail].trim()) trail++;
  return [...was.raw.slice(0, lead), ...lines, ...was.raw.slice(was.raw.length - trail)];
}

// Sets (or, with null, removes) simple "key: value" lines in frontmatter lines.
export function withProperties(front, changes) {
  const lines = front.length ? [...front] : ['---', '---'];
  for (const [key, value] of Object.entries(changes)) {
    const at = lines.findIndex((l, i) => i > 0 && i < lines.length - 1 && new RegExp(`^${key}:`).test(l));
    if (value === null) {
      if (at >= 0) lines.splice(at, 1);
    } else if (at >= 0) {
      lines[at] = `${key}: ${value}`;
    } else {
      lines.splice(lines.length - 1, 0, `${key}: ${value}`);
    }
  }
  return lines;
}

function trimBlank(lines) {
  let a = 0;
  let b = lines.length;
  while (a < b && !lines[a].trim()) a++;
  while (b > a && !lines[b - 1].trim()) b--;
  return lines.slice(a, b);
}
