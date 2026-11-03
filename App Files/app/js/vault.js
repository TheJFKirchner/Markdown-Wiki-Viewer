// Turns the host's folder scan into notes, resolved [[wikilinks]], tags and graph data.
// Scripts (.sql, .py, ...) are link targets only: notes can link to them with their file name
// ([[query.sql]]), but they're never read for links of their own.

import { load as loadYaml, CORE_SCHEMA } from '../lib/js-yaml.js';
import { parseTasks, tasksSectionEnd } from './tasks.js';
import { isNotesPath, isTemplatePath } from './notes.js';

const NOTE_EXT = /\.(md|markdown)$/i;
const FRONTMATTER = /^---\r?\n(?:([\s\S]*?)\r?\n)?---[ \t]*(?:\r?\n|$)/;
const ATTACHMENT_EXT = /\.[a-z0-9]{1,5}$/i;
const WIKILINK = /\[\[([^[\]\n]+?)\]\]/g;

export const isNotePath = (path) => NOTE_EXT.test(path);

// Each wiki's instructions for the ingest agent (see ingest/DESIGN.md). Like templates, it isn't
// part of the wiki itself: no graph node, tags, tasks or links.
export const RULES_FILE = 'wiki_rules.md';
export const isRulesPath = (path) => path.toLowerCase() === RULES_FILE;

const SCRIPT_EXT = /\.(sql|py|ipynb|r|js|mjs|ts|ps1|psm1|sh|bash|bat|cmd|vbs|rb|pl|lua|kql|dax)$/i;
export const isScriptPath = (path) => SCRIPT_EXT.test(path);

export function baseName(path) {
  return path.slice(path.lastIndexOf('/') + 1).replace(NOTE_EXT, '');
}

// "team:Target#Heading|Text" -> { folder: 'team', target, heading, text }.
// The "folder:" prefix picks a note in a specific workspace folder; ':' can't appear in
// Windows file names, so it never clashes with a real note name.
export function parseLink(inner) {
  const pipe = inner.indexOf('|');
  let ref = pipe >= 0 ? inner.slice(0, pipe) : inner;
  let folder = '';
  const colon = ref.indexOf(':');
  const firstHash = ref.indexOf('#');
  if (colon > 0 && (firstHash < 0 || colon < firstHash)) {
    folder = ref.slice(0, colon).trim();
    ref = ref.slice(colon + 1);
  }
  const hash = ref.indexOf('#');
  return {
    folder,
    target: (hash >= 0 ? ref.slice(0, hash) : ref).trim().replace(NOTE_EXT, ''),
    heading: hash >= 0 ? ref.slice(hash + 1).trim() : '',
    text: pipe >= 0 ? inner.slice(pipe + 1).trim() : '',
  };
}

// Every note is identified by its folder's alias plus its path inside that folder.
export const noteId = (alias, path) => `${alias}:${path}`;

// "---\n<yaml>\n---\n<body>" -> { properties, error, body }. properties is null when there is
// no frontmatter. CORE_SCHEMA keeps dates as plain text instead of turning them into Date objects.
export function parseFrontmatter(text) {
  const match = FRONTMATTER.exec(text);
  if (!match) return { properties: null, error: null, body: text };
  const body = text.slice(match[0].length);
  try {
    const data = loadYaml(match[1] || '', { schema: CORE_SCHEMA });
    if (data == null) return { properties: {}, error: null, body };
    if (typeof data !== 'object' || Array.isArray(data)) {
      return { properties: null, error: 'Properties must be "key: value" lines.', body };
    }
    return { properties: data, error: null, body };
  } catch (err) {
    return { properties: null, error: err.reason || err.message, body };
  }
}

// Accepts `tags: [a, b]`, a YAML list, or `tags: a, b`; "#" prefixes are optional.
// Tags are case-insensitive, so they're stored lowercase.
export function normalizeTags(raw) {
  const list = Array.isArray(raw) ? raw : typeof raw === 'string' ? raw.split(/[,\s]+/) : raw == null ? [] : [raw];
  const tags = list.map((t) => String(t).trim().replace(/^#/, '').toLowerCase()).filter(Boolean);
  return [...new Set(tags)];
}

// The line edit that sets a note's tags: rewrites the `tags:` entry in its frontmatter
// (any style: [a, b], a YAML list, or "a, b") as `tags: [a, b]`, adds one if missing, or
// creates the frontmatter. Returns { start, expect, replace } for the host's editLines.
export function tagsEdit(content, tags) {
  const lines = content.split(/\r?\n/);
  const item = (t) => (/^[\p{L}\p{N}][\p{L}\p{N}_/-]*$/u.test(t) ? t : JSON.stringify(t));
  const line = tags.length ? `tags: [${tags.map(item).join(', ')}]` : null;
  const close = lines[0] === '---' ? lines.findIndex((l, i) => i > 0 && /^---\s*$/.test(l)) : -1;

  if (close < 0) {
    // No frontmatter yet: start the file with one.
    return line ? { start: 0, expect: [lines[0]], replace: ['---', line, '---', lines[0]] } : null;
  }
  // Lower case only, the keys the app reads tags from: a "Tags:" entry isn't read, so it's left alone.
  const at = lines.findIndex((l, i) => i > 0 && i < close && /^tags?\s*:/.test(l));
  if (at < 0) {
    return line ? { start: 0, expect: [lines[0]], replace: [lines[0], line] } : null;
  }
  // The entry plus any indented / "- item" lines that continue it.
  let end = at + 1;
  while (end < close && (/^\s/.test(lines[end]) || /^-\s/.test(lines[end]))) end++;
  return { start: at, expect: lines.slice(at, end), replace: line ? [line] : [] };
}

// Cleans a typed tag: no leading #, spaces become dashes, lowercase. '' if nothing usable.
export function cleanTag(text) {
  return text.trim().replace(/^#+/, '').replace(/\s+/g, '-').replace(/[^\p{L}\p{N}_/-]/gu, '').toLowerCase();
}

// Nested tags: filtering by "planet" also matches "planet/giant".
export function tagMatches(tag, filter) {
  return tag === filter || tag.startsWith(filter + '/');
}

// Links inside code are examples, not real links.
function stripCode(text) {
  return text.replace(/```[\s\S]*?```/g, '').replace(/`[^`\n]*`/g, '');
}

// Combines the open workspace folders into one model.
//   folders: [{ alias, root, color, scan }] in workspace order (earlier folders win ties).
// Returns { folders, notes: Map(id -> note), byName, duplicates, tags }.
// notesDir: the folder (inside any workspace folder) that holds quick notes (see notes.js).
export function buildVault(folders, { notesDir } = {}) {
  const notes = new Map();   // id -> note
  const byName = new Map();  // lowercase note name -> [ids]
  const scripts = new Map(); // id -> { id, folder, path, name ("query.sql"), backlinks }
  const scriptsByName = new Map(); // lowercase file name -> [ids]
  const folderOrder = new Map(folders.map((f, i) => [f.alias, i]));

  for (const folder of folders) {
    for (const file of folder.scan.files) {
      if (isScriptPath(file.path)) {
        const name = file.path.slice(file.path.lastIndexOf('/') + 1);
        const script = { id: noteId(folder.alias, file.path), folder: folder.alias, path: file.path, name, script: true, backlinks: [] };
        scripts.set(script.id, script);
        if (!scriptsByName.has(name.toLowerCase())) scriptsByName.set(name.toLowerCase(), []);
        scriptsByName.get(name.toLowerCase()).push(script.id);
        continue;
      }
      if (!isNotePath(file.path)) continue;
      const content = file.content ?? '';
      const { properties, error, body } = parseFrontmatter(content);
      // Templates are only a starting point for new notes: no tags, tasks, links or graph node.
      // The ingest rules file is treated the same way.
      const template = isTemplatePath(file.path) || isRulesPath(file.path);
      const note = {
        id: noteId(folder.alias, file.path),
        folder: folder.alias,
        path: file.path,           // path inside its folder
        name: baseName(file.path),
        content,
        body,                      // content without the frontmatter
        properties,                // parsed frontmatter object, or null
        propertiesError: error,    // YAML error message, or null
        tags: normalizeTags(properties && (properties.tags ?? properties.tag)),
        description: typeof properties?.description === 'string' ? properties.description : '',
        duplicate: false,          // another folder has a note with the same name
        inbox: isNotesPath(file.path, notesDir), // a quick note in the notes folder (see notes.js)
        template,
        tasks: template ? [] : parseTasks(content),
        hasTasksSection: tasksSectionEnd(content) >= 0,
        links: [],      // [{ target, id }] where id is null for notes that don't exist yet
        backlinks: [],  // ids of notes linking here
      };
      notes.set(note.id, note);
      const key = note.name.toLowerCase();
      if (!byName.has(key)) byName.set(key, []);
      byName.get(key).push(note.id);
    }
  }

  const duplicates = findDuplicates(byName, notes);
  for (const ids of duplicates.values()) for (const id of ids) notes.get(id).duplicate = true;

  // tag -> number of notes, most used first
  const counts = new Map();
  for (const note of notes.values()) if (!note.template) for (const tag of note.tags) counts.set(tag, (counts.get(tag) || 0) + 1);
  const tags = new Map([...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])));

  // Every task in every note, each pointing back to its note.
  const tasks = [];
  for (const note of notes.values()) for (const task of note.tasks) tasks.push({ ...task, note });

  const vault = { folders, folderOrder, notes, byName, scripts, scriptsByName, duplicates, tags, tasks };

  for (const note of notes.values()) {
    if (note.template) continue;
    const seen = new Set();
    for (const match of stripCode(note.content).matchAll(WIKILINK)) {
      const link = parseLink(match[1]);
      if (!link.target) continue; // [[#Heading]] points inside the same note
      const id = resolveTarget(vault, link, note.folder);
      if (!id && ATTACHMENT_EXT.test(link.target)) continue; // images and other attachments
      const target = link.folder ? `${link.folder}:${link.target}` : link.target;
      const key = id || ghostId(target);
      if (seen.has(key)) continue;
      seen.add(key);
      note.links.push({ target, id });
      if (id && id !== note.id) (notes.get(id) || scripts.get(id)).backlinks.push(note.id);
    }
  }

  // Pages each task mentions with [[links]], so a page can list tasks that point at it.
  for (const task of tasks) {
    task.links = [];
    for (const match of task.text.matchAll(WIKILINK)) {
      const id = resolveTarget(vault, parseLink(match[1]), task.note.folder);
      if (id && !task.links.includes(id)) task.links.push(id);
    }
  }
  return vault;
}

// Tasks that belong to a page: written on it, or linking to it.
export function tasksForNote(vault, id) {
  return vault.tasks.filter((t) => t.note.id === id || t.links.includes(id));
}

// Note names that exist in more than one folder: lowercase name -> [ids].
// Same-named notes inside a single folder aren't counted; paths already tell those apart.
export function findDuplicates(byName, notes) {
  const duplicates = new Map();
  for (const [name, ids] of byName) {
    if (new Set(ids.map((id) => notes.get(id).folder)).size > 1) duplicates.set(name, ids);
  }
  return duplicates;
}

const ghostId = (target) => 'ghost:' + target.toLowerCase();

// Resolves a parsed link to a note id, or null.
//   [[team:Name]]  -> only the folder with alias "team"
//   [[Name]]       -> the linking note's own folder first, then the other folders in order
//   [[sub/Name]]   -> matched by path instead of name
// If several notes still match, the shortest path wins (like Obsidian).
export function resolveLink(vault, { folder, target }, fromFolder) {
  const t = target.toLowerCase();
  let candidates;
  if (t.includes('/')) {
    candidates = [...vault.notes.values()].filter((n) => {
      const bare = n.path.replace(NOTE_EXT, '').toLowerCase();
      return bare === t || bare.endsWith('/' + t);
    });
  } else {
    candidates = (vault.byName.get(t) || []).map((id) => vault.notes.get(id));
  }

  if (folder) {
    candidates = candidates.filter((n) => n.folder.toLowerCase() === folder.toLowerCase());
  } else {
    const own = candidates.filter((n) => n.folder === fromFolder);
    if (own.length) candidates = own;
  }
  if (!candidates.length) return null;
  candidates.sort(
    (a, b) => vault.folderOrder.get(a.folder) - vault.folderOrder.get(b.folder) || a.path.length - b.path.length,
  );
  return candidates[0].id;
}

// A link to a script, by file name with its extension ([[query.sql]], [[team:etl/load.py]]),
// resolved the same way as notes. -> its id, or null.
export function resolveScript(vault, { folder, target }, fromFolder) {
  if (!vault.scripts || !SCRIPT_EXT.test(target)) return null;
  const t = target.toLowerCase();
  let candidates = t.includes('/')
    ? [...vault.scripts.values()].filter((s) => s.path.toLowerCase() === t || s.path.toLowerCase().endsWith('/' + t))
    : (vault.scriptsByName.get(t) || []).map((id) => vault.scripts.get(id));
  if (folder) {
    candidates = candidates.filter((s) => s.folder.toLowerCase() === folder.toLowerCase());
  } else {
    const own = candidates.filter((s) => s.folder === fromFolder);
    if (own.length) candidates = own;
  }
  if (!candidates.length) return null;
  candidates.sort(
    (a, b) => vault.folderOrder.get(a.folder) - vault.folderOrder.get(b.folder) || a.path.length - b.path.length,
  );
  return candidates[0].id;
}

// A link to a note or a script.
export function resolveTarget(vault, link, fromFolder) {
  return resolveLink(vault, link, fromFolder) || resolveScript(vault, link, fromFolder);
}

// Display name for a note: same-named notes from different folders get their folder's alias.
export function noteLabel(note) {
  return note.duplicate ? `${note.name} (${note.folder})` : note.name;
}

// Nodes for every note plus "ghost" nodes for links to notes that don't exist yet.
// Links are wikilinks (kind "link"), plus dashed "duplicate" links joining same-named
// notes from different folders.
export function graphData(vault) {
  const nodes = new Map();
  const graphNotes = [...vault.notes.values()].filter((n) => !n.template);
  for (const note of graphNotes) {
    nodes.set(note.id, {
      id: note.id,
      name: noteLabel(note),
      folder: note.folder,
      ghost: false,
      inbox: note.inbox,
      degree: 0,
      tags: note.tags,
      description: note.description,
    });
  }

  // Every script is a node (drawn as a star); only notes link to them.
  for (const script of vault.scripts.values()) {
    nodes.set(script.id, {
      id: script.id,
      name: script.name,
      folder: script.folder,
      ghost: false,
      script: true,
      degree: 0,
      tags: [],
      description: script.path,
    });
  }

  const links = [];
  const pairs = new Set();
  for (const note of graphNotes) {
    for (const link of note.links) {
      const id = link.id || ghostId(link.target);
      if (id === note.id) continue;
      if (!nodes.has(id)) {
        nodes.set(id, {
          id,
          name: link.target,
          folder: null,
          ghost: true,
          linkedFrom: [], // folders with notes linking here
          degree: 0,
          tags: [],
          description: '',
        });
      }
      const node = nodes.get(id);
      if (node.ghost && !node.linkedFrom.includes(note.folder)) node.linkedFrom.push(note.folder);
      const pair = note.id < id ? note.id + '\n' + id : id + '\n' + note.id;
      if (pairs.has(pair)) continue;
      pairs.add(pair);
      links.push({ source: note.id, target: id, kind: 'link' });
      nodes.get(note.id).degree++;
      nodes.get(id).degree++;
    }
  }

  for (const ids of vault.duplicates.values()) {
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        if (vault.notes.get(ids[i]).folder === vault.notes.get(ids[j]).folder) continue;
        if (!nodes.has(ids[i]) || !nodes.has(ids[j])) continue;
        links.push({ source: ids[i], target: ids[j], kind: 'duplicate' });
      }
    }
  }
  return { nodes: [...nodes.values()], links };
}
