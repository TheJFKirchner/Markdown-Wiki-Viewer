// The Ingest view's Notes tab: wrapped quick notes that need capturing. Choose some and press
// Capture: the host (captureNotes) captures them into the personal wiki one after another, filed
// under topics like a Claude Code session is (see the Sessions tab). It is written straight into
// the personal wiki; nothing is proposed as cards. The host writes `capture_id` and `ingested` into
// a captured note, and remembers a hash of its text: notesStatus says whether each note is `new`,
// `changed` (edited since it was captured, so it needs capturing again) or `captured`. Progress
// arrives as `notesCapture` events, one per note. (Promotion, the card tab, is ingestview.js.)

import { noteInfo } from './notes.js';
import { rolePrompt } from './roles.js';
import { HAIKU, chosenModel, modelMenu, rememberModel } from './modelmenu.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const AGENT = 'executive-assistant';

export function createCaptureView(container, deps) {
  const { call, on, findFolder, getPersonal, reload, openPage, toast, onChange } = deps;
  let vault = null;
  let running = false;
  let loaded = false;
  let progress = null;               // { index, total, path } of the note being captured
  let statusById = new Map();        // note id -> { status: new | changed | captured, legacy }
  let statusFor = '';                // the notes the statuses were asked for
  let statusTimer = 0;
  const selected = new Set();
  const results = [];                // newest first, this app run only
  const seen = new Set();            // paths whose result came as an event

  container.addEventListener('click', onClick);
  container.addEventListener('change', (e) => {
    if (rememberModel(e)) return draw();
    if (!e.target.matches('.ingest-note input[type=checkbox]')) return;
    if (e.target.checked) selected.add(e.target.dataset.id);
    else selected.delete(e.target.dataset.id);
    draw();
  });

  const fullPath = (note) => `${findFolder(note.folder).root.replace(/[\\/]+$/, '')}/${note.path}`;
  const wrapped = () => [...(vault?.notes.values() || [])].filter((n) => n.inbox && !n.template && noteInfo(n).wrapped && findFolder(n.folder));

  // Wrapped notes that are new or changed since they were captured, newest first. Until the host has
  // answered, a note without `ingested:` counts as new.
  function waiting() {
    return wrapped()
      .filter((n) => {
        const s = statusById.get(n.id);
        return s ? s.status !== 'captured' : !n.properties?.ingested;
      })
      .sort((a, b) => (noteInfo(b).ended || noteInfo(b).started).localeCompare(noteInfo(a).ended || noteInfo(a).started) || a.name.localeCompare(b.name));
  }

  // Asks the host which notes are new, changed or captured (no request to Claude), when the notes changed.
  function askStatus() {
    clearTimeout(statusTimer);
    statusTimer = setTimeout(async () => {
      const notes = wrapped();
      const key = notes.map((n) => `${n.id}:${n.content.length}`).join('|');
      if (key === statusFor || !notes.length) return;
      statusFor = key;
      try {
        const rows = await call('notesStatus', { paths: notes.map(fullPath), root: getPersonal()?.root });
        const byPath = new Map(rows.map((r) => [r.path, r]));
        statusById = new Map(notes.filter((n) => byPath.get(fullPath(n)) && byPath.get(fullPath(n)).status !== 'error')
          .map((n) => [n.id, { status: byPath.get(fullPath(n)).status, legacy: byPath.get(fullPath(n)).legacy }]));
      } catch {
        statusFor = '';          // no personal wiki yet, or the host can't tell: fall back to `ingested:`
        statusById = new Map();
      }
      draw();
      onChange();
    }, 300);
  }

  function why(count) {
    if (running) return 'A capture is running.';
    if (!getPersonal()) return 'Give a wiki the Personal role in Settings first.';
    if (!count) return 'Select the notes to capture.';
    return '';
  }

  function draw() {
    if (!loaded) return;
    const notes = waiting();
    for (const id of [...selected]) if (!notes.some((n) => n.id === id)) selected.delete(id);
    const count = selected.size;
    const blocked = why(count);
    const scroll = container.querySelector('.ingest-right')?.scrollTop || 0;
    container.innerHTML = `
      <div class="ingest">
        <section class="ingest-left">
          <header class="ingest-header"><h1>Notes</h1></header>
          <p class="ingest-intro">Wrapped notes that are new, or that you edited after they were captured. Choose the ones to capture: each is filed into your personal wiki under topics. It's written straight away, with nothing to approve, and only ever into your personal wiki. A note that hasn't changed since its capture is never sent again.</p>
          ${getPersonal() ? '' : rolePrompt('personal')}
          <div class="ingest-list">${notes.length ? notes.map(noteRow).join('') : '<p class="ingest-empty">Nothing needs capturing. Wrap a note in the Notes view and it appears here.</p>'}</div>
          <div class="ingest-actions">
            ${notes.length ? `<button class="link-button" data-action="all">${count && count === notes.length ? 'Select none' : 'Select all'}</button>` : ''}
            <span class="spacer"></span>
            <span class="ingest-why">${esc(blocked && count ? blocked : '')}</span>
            ${modelMenu({ agent: AGENT, fallback: HAIKU, disabled: running, what: 'capturing notes' })}
            <button class="primary-button" data-ai data-action="capture" ${blocked ? 'disabled' : ''}>${running ? 'Capturing…' : `Capture ${count || ''}`}</button>
          </div>
          ${running ? `<div class="ingest-progress"><div class="ingest-bar"><span></span></div><div class="ingest-stage">${progress ? `Capturing ${progress.index + 1} of ${progress.total}: ${esc(nameOf(progress.path))}` : 'Capturing into your personal wiki…'}</div></div>` : ''}
        </section>
        <section class="ingest-right">
          <header class="ingest-cards-header"><h2>Captured</h2></header>
          <div class="ingest-cards">${results.length ? results.map(resultCard).join('') : '<p class="ingest-empty">What each note added to your wiki appears here.</p>'}</div>
        </section>
      </div>`;
    container.querySelector('.ingest-right').scrollTop = scroll;
  }

  const nameOf = (path) => String(path || '').split(/[\\/]/).pop().replace(/\.md$/i, '');

  function noteRow(note) {
    const folder = findFolder(note.folder);
    const { type, started, ended } = noteInfo(note);
    const changed = statusById.get(note.id)?.status === 'changed';
    const here = running && progress && progress.path === fullPath(note);
    return `
      <label class="ingest-note${here ? ' working' : ''}">
        <input type="checkbox" data-id="${esc(note.id)}" ${selected.has(note.id) ? 'checked' : ''} ${running ? 'disabled' : ''}>
        <button class="link-button ingest-note-name" data-action="open" data-id="${esc(note.id)}" title="${esc(note.name)}">${esc(note.name)}</button>
        ${changed ? '<span class="session-tag" title="Edited since it was captured. Capturing again replaces its record in the wiki.">CHANGED</span>' : ''}
        <span class="wiki-chip" style="--wiki:${esc(folder?.color || 'var(--text-faint)')}">${esc(note.folder)}</span>
        <span class="ingest-note-meta">${esc(type)}${ended || started ? ` · wrapped ${esc(ended || started)}` : ''}</span>
      </label>`;
  }

  function resultCard(r) {
    const alias = getPersonal()?.alias;
    const link = (path, label) => `<button class="link-button" data-action="open" data-id="${esc(`${alias}:${path}`)}">${esc(label)}</button>`;
    const topics = (r.topics || []).map((t) => `${t.path ? link(t.path, t.slug || t.path) : esc(t.slug || t)}${t.created ? ' <span class="ingest-kind new">NEW</span>' : ''}`);
    const chip = r.error ? 'FAILED' : r.status === 'unchanged' ? 'UNCHANGED' : 'CAPTURED';
    return `
      <article class="ingest-card session-result ${r.error ? 'failed' : ''}" style="--wiki:${esc(getPersonal()?.color || 'var(--text-faint)')}">
        <div class="ingest-card-header">
          <span class="ingest-card-title">${esc(r.title || nameOf(r.path) || 'Note')}</span><span class="spacer"></span>
          <span class="ingest-kind">${chip}</span>
        </div>
        ${r.error ? `<p class="field-error">Not captured: ${esc(r.error)}</p>`
          : r.status === 'unchanged' ? '<p class="session-faint">Already captured and unchanged since, so nothing was sent to Claude.</p>' : `
          ${r.note ? `<p>${link(r.note, 'Record')}${topics.length ? ` · filed under ${topics.join(', ')}` : ''}</p>` : topics.length ? `<p>Filed under ${topics.join(', ')}</p>` : ''}
          ${(r.new_tags || []).length ? `<p class="session-faint">${plural(r.new_tags.length, 'new tag')} added to your personal tags: ${r.new_tags.map((t) => `#${esc(t.tag)}${t.description ? ` (${esc(t.description)})` : ''}`).join(', ')}.</p>` : ''}
          ${(r.warnings || []).map((w) => `<p class="session-warning">${esc(w)}</p>`).join('')}`}
      </article>`;
  }

  // Progress from the host, one event per note: the note being captured, then its result.
  on('notesCapture', (e) => {
    if (e.status === 'running') {
      progress = { index: e.index, total: e.total, path: e.path };
    } else if (e.result) {
      seen.add(e.path);
      results.unshift(e.result);
    }
    draw();
  });

  async function capture() {
    const personal = getPersonal();
    const notes = [...selected].map((id) => vault.notes.get(id)).filter(Boolean);
    if (running || !personal || !notes.length) return;
    running = true;
    progress = null;
    seen.clear();
    draw();
    try {
      const reply = await call('captureNotes', { paths: notes.map(fullPath), root: personal.root, model: chosenModel(AGENT, HAIKU) });
      for (const r of reply?.results || []) if (!seen.has(r.path)) results.unshift(r);
    } catch (err) {
      results.unshift({ title: plural(notes.length, 'note'), error: err.message });
    }
    running = false;
    progress = null;
    selected.clear();
    statusFor = '';
    draw();
    onChange();
    // The host wrote capture_id and ingested into the notes, and new pages into the personal wiki.
    for (const alias of new Set([...notes.map((n) => n.folder), personal.alias])) await reload(alias).catch(() => {});
    deps.onCaptured?.();
    askStatus();
  }

  function onClick(e) {
    const button = e.target.closest('[data-action]');
    if (!button || button.disabled || button.tagName === 'INPUT' || button.tagName === 'SELECT') return;
    const action = button.dataset.action;
    if (action === 'all') {
      const notes = waiting();
      if (selected.size === notes.length) selected.clear();
      else for (const n of notes) selected.add(n.id);
      draw();
    } else if (action === 'capture') capture();
    else if (action === 'open') openPage(button.dataset.id);
  }

  return {
    setVault(v) {
      vault = v;
      draw();
      askStatus();
    },
    load() { loaded = true; draw(); },
    redraw() { statusFor = ''; draw(); askStatus(); },
    badge: () => (loaded ? waiting().length : 0),
  };
}
