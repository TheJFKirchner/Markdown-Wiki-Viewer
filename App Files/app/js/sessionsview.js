// The Ingest view's Sessions tab: the Claude Code sessions of the last two weeks that haven't
// been captured into the personal wiki yet. Ingest on a row, or Ingest all, sends the session to
// the executive assistant (sessions/sb.py, run by the host), which writes a short session note
// and files it under topics; every topic has a page that collects the sessions about that work. Unlike the Notes tab there are no cards to answer: what's captured
// is written straight away, into the personal wiki only. The right side lists what each capture
// wrote. See sessions/README.md and sessions/INTEGRATION.md.

import { HAIKU, chosenModel, modelMenu, rememberModel } from './modelmenu.js';
import { rolePrompt, roleBadge } from './roles.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
// A cost at API list prices. Small ones keep an extra digit so a half-cent ingest doesn't read as $0.00.
const money = (n) => `$${n < 0.1 ? n.toFixed(3) : n.toFixed(2)}`;
const COST_HINT = 'What the tokens would cost at Claude API list prices, as Claude Code reports it for each request. On a Claude subscription a request is not billed per token: it counts toward your plan\'s usage.';
const DAYS = 14;
const folderName = (path) => String(path || '').split(/[\\/]/).filter(Boolean).pop() || '';

export function createSessionsView(container, deps) {
  const { call, getFolders, findFolder, getPersonalWiki, reload, openPage, toast, onChange } = deps;
  let rows = null;          // the sessions waiting, or null before the first list
  let status = null;        // the chosen folder's sb.py status, or null
  let error = '';
  let loading = false;
  let loadedFor = '';       // the folder root the list was made for
  let hidden = 0;           // sessions left out by the turns filter
  let filter = { min_turns: 0, options: [0, 3, 5, 10, 20] }; // getSessionsFilter
  let batch = null;         // Ingest all: { total, done, current, stop }
  const working = new Set(); // session ids being captured or skipped
  const results = [];       // what each capture wrote, newest first (this app run only)

  container.addEventListener('click', onClick);
  container.addEventListener('change', onInput);

  // ---- Which wiki ---------------------------------------------------------------------------

  // The personal wiki: the connected wiki whose role is Personal (Settings), else none.
  const wiki = () => getPersonalWiki();

  // Sessions a script started through the Agent SDK, and subagents' own transcripts, are never listed (sb.py leaves them out).
  const shown = () => rows || [];

  // ---- Loading ------------------------------------------------------------------------------

  async function load() {
    const folder = wiki();
    if (!folder || loading) return draw();
    loading = true;
    error = '';
    draw();
    try {
      status = await call('sessionsStatus', { root: folder.root });
      filter = await call('getSessionsFilter').catch(() => filter);
      const listed = status.set_up ? await call('sessionsList', { root: folder.root, days: DAYS }) : null;
      rows = Array.isArray(listed) ? listed : listed ? listed.sessions || listed.rows || listed.items || [] : null;
      hidden = (!Array.isArray(listed) && listed?.hidden_count) || 0;
      if (!Array.isArray(listed) && listed?.min_turns !== undefined) filter = { ...filter, min_turns: listed.min_turns };
      loadedFor = folder.root;
    } catch (err) {
      error = err.message;
    }
    loading = false;
    draw();
    onChange();
  }

  // ---- Drawing ------------------------------------------------------------------------------

  function draw() {
    const folder = wiki();
    const scroll = container.querySelector('.ingest-right')?.scrollTop || 0;
    container.innerHTML = `
      <div class="ingest">
        <section class="ingest-left">
          <header class="ingest-header">
            <h1>Sessions</h1>
            <span class="spacer"></span>
            <button class="secondary-button" data-action="refresh" ${loading || batch ? 'disabled' : ''}>Refresh</button>
          </header>
          <p class="ingest-intro">Your Claude Code sessions from the last two weeks that aren't in your personal wiki yet. Ingesting one writes a short note of what was decided and found, and files it under the topic it was about. Each topic has a page that collects every session about that work, and tags that connect it to related topics. It's written straight away, with nothing to approve, and only ever into your personal wiki.</p>
          ${left(folder)}
        </section>
        <section class="ingest-right">
          <header class="ingest-cards-header">
            <h2>Captured</h2>
            ${spendTotal()}
            <span class="ingest-count">${status?.set_up ? `${plural(status.topics, 'topic')} · ${plural(status.sessions, 'session note')}${status.queue_pending ? ` · ${status.queue_pending} for the team wiki` : ''}` : ''}</span>
          </header>
          <div class="ingest-cards">${results.length ? results.map(resultCard).join('') : '<p class="ingest-empty">What each session added to your wiki appears here.</p>'}</div>
        </section>
      </div>`;
    container.querySelector('.ingest-right').scrollTop = scroll;
  }

  // What ingesting has cost in this wiki so far, and since the app started.
  function spendTotal() {
    const all = status?.spend?.capture;
    if (!all?.runs) return '';
    const now = results.filter((r) => r.spend?.calls);
    const session = now.length ? ` · ${money(now.reduce((sum, r) => sum + r.spend.cost, 0))} this time` : '';
    return `<span class="session-spend" title="${esc(COST_HINT)}">≈ ${money(all.cost)} on ${plural(all.runs, 'ingest')} (${money(all.cost / all.runs)} each)${session} ⓘ</span>`;
  }

  function spendLine(r) {
    if (!r.spend?.calls) return '';
    return `<p class="session-faint" title="${esc(COST_HINT)}">≈ ${money(r.spend.cost)} at API prices · ${esc(r.spend.model || '')} · ${r.spend.tokens_in.toLocaleString()} tokens in, ${r.spend.tokens_out.toLocaleString()} out</p>`;
  }

  const filterMenu = () => `
    <label class="session-wiki">
      <span>Hide sessions under</span>
      <select data-action="min-turns" ${batch || working.size ? 'disabled' : ''}>
        ${(filter.options || [0, 3, 5, 10, 20]).map((n) => `<option value="${n}" ${Number(filter.min_turns) === n ? 'selected' : ''}>${n ? `${n} turns` : 'Off'}</option>`).join('')}
      </select>
      ${hidden ? `<span class="session-faint">${hidden} hidden</span>` : ''}
    </label>`;

  function left(folder) {
    const folders = getFolders();
    if (!folders.length) return '<p class="ingest-empty">Add a wiki folder first, then make it your Personal wiki in Settings.</p>';
    if (!folder) return rolePrompt('personal');
    const picker = `<p class="session-faint">Personal wiki: <strong>${esc(folder.alias)}</strong> ${roleBadge(folder.alias)}</p>`;
    if (error) return `${picker}<div class="ingest-setup"><p class="field-error">${esc(error)}</p><button class="secondary-button" data-action="refresh">Try again</button></div>`;
    if (loading && !rows) return `${picker}<p class="ingest-empty">Reading your sessions…</p>`;
    if (status && !status.set_up) return picker + setupBox(folder);
    if (!rows) return picker;

    const list = shown();
    return `
      ${picker}
      ${filterMenu()}
      <div class="ingest-list">${list.length ? list.map(sessionRow).join('') : `<p class="ingest-empty">Nothing is waiting. Every session from the last two weeks has been ingested or skipped${hidden ? `, or is hidden by the turns filter` : ''}.</p>`}</div>
      <div class="session-options">
        <span class="spacer"></span>
        ${modelMenu({ agent: 'executive-assistant', fallback: HAIKU, disabled: Boolean(batch || working.size), what: 'ingesting sessions' })}
        <button class="primary-button" style="margin:0" data-ai data-action="all" ${!list.length || batch || working.size ? 'disabled' : ''}
          title="Ingest every session listed above, one after another">Ingest all ${list.length || ''}</button>
      </div>
      ${progress()}`;
  }

  function setupBox(folder) {
    return `
      <div class="ingest-setup">
        <p><strong>Set up ${esc(folder.alias)} for capture?</strong> This adds an <code>index.md</code>, a <code>promotion-queue.md</code> and a <code>Sessions</code> folder. Topic pages are added at the top of the folder as sessions are ingested. Nothing already in the folder is changed.</p>
        <button class="primary-button" data-action="setup">Set up ${esc(folder.alias)}</button>
      </div>`;
  }

  function sessionRow(row) {
    const busy = working.has(row.session_id);
    const meta = [row.last_active || row.date, folderName(row.project), plural(row.user_messages, 'message')].filter(Boolean).join(' · ');
    const off = busy || batch ? 'disabled' : '';
    return `
      <div class="session-row${busy ? ' working' : ''}" title="${esc(row.first_prompt)}">
        <div class="session-main">
          <span class="session-title">${esc(row.name || row.title || 'Untitled session')}${row.status === 'updated' ? '<span class="session-tag" title="Ingested before, then continued. Ingesting again replaces its note.">CONTINUED</span>' : ''}</span>
          ${row.name && row.title ? `<span class="session-meta session-subtitle">${esc(row.title)}</span>` : ''}
          <span class="session-meta">${esc(meta)}</span>
          ${row.subagents > 0 ? `<span class="session-meta session-subagents" title="Subagents the session started are folded into it">${plural(row.subagents, 'subagent')}</span>` : ''}
        </div>
        <button class="secondary-button" data-action="skip" data-id="${esc(row.session_id)}" ${off} title="Leave this session out. Nothing is written.">Skip</button>
        <button class="secondary-button" data-ai data-action="ingest" data-id="${esc(row.session_id)}" ${off}>${busy ? 'Ingesting…' : 'Ingest'}</button>
      </div>`;
  }

  function progress() {
    if (!batch) return '';
    return `
      <div class="ingest-progress">
        <div class="ingest-bar"><span></span></div>
        <div class="ingest-stage">${batch.stop ? 'Stopping after this one' : `Ingesting ${batch.done + 1} of ${batch.total}`}: ${esc(batch.current)}</div>
        <div class="ingest-stats">${batch.done} done<span class="spacer"></span>
          ${batch.stop ? '' : '<button class="link-button" data-action="stop">Stop after this one</button>'}</div>
      </div>`;
  }

  function resultCard(r) {
    const folder = findFolder(r.alias);
    const link = (path, label) => `<button class="link-button" data-action="open" data-id="${esc(`${r.alias}:${path}`)}">${esc(label)}</button>`;
    let body;
    if (r.error) body = `<p class="field-error">Not ingested: ${esc(r.error)}</p>`;
    else if (r.status === 'skipped') body = `<p class="session-faint">Nothing written. ${esc(r.reason || '')}</p>${spendLine(r)}`;
    else if (r.status === 'unchanged') body = '<p class="session-faint">Already captured and unchanged since, so nothing was sent to Claude.</p>';
    else {
      const topics = (r.topics || []).map((t) => `${link(t.path, t.slug)}${t.created ? ' <span class="ingest-kind new">NEW</span>' : ''}${t.review_due ? ' <span class="session-faint">(due for review)</span>' : ''}`);
      body = `
        <p>${link(r.note, 'Session note')}${topics.length ? ` · filed under ${topics.join(', ')}` : ''}</p>
        ${(r.tags || []).length ? `<p class="session-faint">${r.tags.map((t) => `#${esc(t)}`).join(' ')}</p>` : ''}
        ${(r.new_tags || []).length ? `<p class="session-faint">${plural(r.new_tags.length, 'new tag')} added to your personal tags: ${r.new_tags.map((t) => `#${esc(t.tag)}${t.description ? ` (${esc(t.description)})` : ''}`).join(', ')}.</p>` : ''}
        ${r.queued_findings ? `<p class="session-faint">${plural(r.queued_findings, 'data finding')} added to the ${link('promotion-queue.md', 'promotion queue')} for the team wiki.</p>` : ''}
        ${(r.warnings || []).map((w) => `<p class="session-warning">${esc(w)}</p>`).join('')}
        ${spendLine(r)}`;
    }
    return `
      <article class="ingest-card session-result ${r.error ? 'failed' : esc(r.status)}" style="--wiki:${esc(folder?.color || 'var(--text-faint)')}">
        <div class="ingest-card-header">
          <span class="ingest-card-title">${esc(r.title)}</span>
          <span class="spacer"></span>
          <span class="ingest-kind">${r.error ? 'FAILED' : r.status === 'skipped' ? 'SKIPPED' : r.status === 'unchanged' ? 'UNCHANGED' : 'INGESTED'}</span>
        </div>
        ${body}
      </article>`;
  }

  // ---- Actions ------------------------------------------------------------------------------

  // Captures one session and reports what it wrote. Returns whether it worked.
  async function ingest(id) {
    const folder = wiki();
    const row = rows?.find((r) => r.session_id === id);
    if (!folder || !row || working.has(id)) return false;
    working.add(id);
    draw();
    let result;
    try {
      result = await call('sessionsIngest', { root: folder.root, id, model: chosenModel('executive-assistant', HAIKU) });
      rows = rows.filter((r) => r.session_id !== id);
      if (status?.set_up && result.spend?.calls) {
        const total = ((status.spend ||= {}).capture ||= { cost: 0, runs: 0 });
        total.cost += result.spend.cost;
        total.runs += 1;
      }
      if (status?.set_up && result.status === 'ingested') {
        status.sessions += row.status === 'updated' ? 0 : 1;
        status.topics += (result.topics || []).filter((t) => t.created).length;
        status.queue_pending += result.queued_findings || 0;
      }
    } catch (err) {
      result = { title: row.title, error: err.message };
    }
    working.delete(id);
    results.unshift({ ...result, title: result.name || row.name || result.title || row.title, alias: folder.alias });
    draw();
    onChange();
    // The new pages show in the file tree, the graph and search, and a topic may now be due for review.
    if (!result.error && result.status === 'ingested') {
      reload(folder.alias).catch(() => {});
      deps.onCaptured?.();
    }
    return !result.error;
  }

  async function skip(id) {
    const folder = wiki();
    if (!folder || working.has(id)) return;
    working.add(id);
    draw();
    try {
      await call('sessionsSkip', { root: folder.root, id });
      rows = rows.filter((r) => r.session_id !== id);
    } catch (err) {
      toast(`Couldn't skip it: ${err.message}`);
    }
    working.delete(id);
    draw();
    onChange();
  }

  // One after another, not side by side: each capture is shown the topics the ones before it
  // made, so related sessions land on the same topic.
  async function ingestAll() {
    const todo = shown().map((r) => ({ id: r.session_id, title: r.title }));
    if (!todo.length || batch) return;
    batch = { total: todo.length, done: 0, current: '', stop: false };
    let failed = 0;
    for (const item of todo) {
      if (batch.stop) break;
      batch.current = item.title;
      if (!(await ingest(item.id))) failed++;
      batch.done++;
    }
    const { done, total } = batch;
    batch = null;
    draw();
    toast(`${done === total ? 'Went through' : 'Stopped after'} ${plural(done, 'session')}${failed ? `; ${failed} failed and ${failed === 1 ? 'is' : 'are'} still listed` : ''}.`);
  }

  async function setup() {
    const folder = wiki();
    try {
      status = await call('sessionsSetup', { root: folder.root });
      await reload(folder.alias).catch(() => {});
    } catch (err) {
      toast(`Couldn't set it up: ${err.message}`);
    }
    load();
  }

  function onClick(e) {
    const button = e.target.closest('[data-action]');
    if (!button || button.disabled || button.tagName === 'SELECT' || button.tagName === 'INPUT' || button.tagName === 'OPTION') return;
    const action = button.dataset.action;
    if (action === 'refresh') load();
    else if (action === 'setup') setup();
    else if (action === 'ingest') ingest(button.dataset.id);
    else if (action === 'skip') skip(button.dataset.id);
    else if (action === 'all') ingestAll();
    else if (action === 'stop' && batch) {
      batch.stop = true;
      draw();
    } else if (action === 'open') openPage(button.dataset.id);
  }

  function onInput(e) {
    if (rememberModel(e)) return draw();
    const action = e.target.dataset.action;
    if (action === 'min-turns') {
      call('setSessionsFilter', { min_turns: Number(e.target.value) })
        .then((next) => {
          filter = next || filter;
          rows = null;
          loadedFor = '';
          load();
        })
        .catch((err) => toast(`Couldn't change the filter: ${err.message}`));
    }
  }

  return {
    // The tab came to the front: list the sessions the first time, and when the wiki changed.
    shown() {
      const folder = wiki();
      if (folder && folder.root !== loadedFor && !loading) load();
      else draw();
    },
    count: () => (rows ? shown().length : 0),
    // The roles changed: another wiki may now be the personal one.
    rolesChanged() {
      rows = null;
      status = null;
      loadedFor = '';
      draw();
    },
    // The personal wiki's folder: the Review and Promotion tabs work on the same one.
    wiki,
  };
}

function get(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function set(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}
