// The Ingest view's Promotion tab (the Notes tab is capturenotes.js, which writes straight into the
// personal wiki). Choose pages, press Promote (ingest/run.py, started by the host): the agent proposes one
// card per page it would change. Each card gets an answer
// (✓ write it, ✗ drop it, ↻ feedback for Claude) and nothing happens until Submit: then the ✓
// changes are written and all the feedback goes back to Claude in one round. Cards (with their
// answers) wait in the app's data folder (ingest/pending-promotion.json) until every one is handled. See ingest/DESIGN.md.
//
// Promotion (the team wiki manager) lists:
// the personal wiki's topic pages and folder pages, and its promotion queue of data findings.
// A topic has to be reviewed (the Review tab) since it last changed before it can be promoted.
// Before it proposes anything, the team wiki manager may ask up to five questions (mostly: where
// should this go?). They show as a form above the cards; the answers continue the same run. Changes may
// only be proposed in the other wikis, and a promoted page gets `promoted: <date>` (the queue's
// lines get ticked) so it leaves the list until it changes again.

import { parseFrontmatter, normalizeTags, parseLink, resolveTarget } from './vault.js';
import { parseNote, withProperties, TEMPLATES_DIR } from './notes.js';
import { isoDate } from './tasks.js';
import { rolePrompt, roleBadge } from './roles.js';
import { chosenModel as chosenModelFor, modelMenu as sharedModelMenu, rememberModel } from './modelmenu.js';

const WIKILINK = /\[\[([^[\]\n]+?)\]\]/g;
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const money = (n) => (typeof n === 'number' ? `$${n < 0.01 ? n.toFixed(3) : n.toFixed(2)}` : '');
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const PLAIN_HINT =
  'Estimate of the same run in a plain Claude Code session, which also sends about 35,000 tokens with every request: ' +
  'its built-in tool definitions (about 14,000), its system prompt (about 12,000), CLAUDE.md and memory (about 5,000) ' +
  'and its skills and MCP lists (about 4,000). Written to the cache once, then read back on each later request, at the run model\'s prices.';
const API_PRICE_HINT =
  'What this run\'s tokens would cost at Claude API list prices. On a Claude subscription a run is not billed per token: it counts toward your plan\'s usage.';
// Used until the host has listed Claude Code's models (ingest/models.py), and as the default.
// Promotion rewrites shared pages, which is worth a stronger model.
const PROMOTION_MODEL = { id: 'claude-sonnet-5-5', name: 'Sonnet 5.5', description: 'Best for careful rewriting' };
const QUEUE_FILE = 'promotion-queue.md';
const day = (v) => (v instanceof Date ? v.toISOString() : String(v ?? '')).slice(0, 10);
// A time as text that sorts in time order: a page's `changed` (written by sessions/sb.py) against its `promoted`.
const stamp = (v) => (v instanceof Date ? v.toISOString() : String(v ?? ''));
const TEXT = {
  promotion: {
    title: 'Promotion', button: 'Promote', model: PROMOTION_MODEL,
    intro: 'Pages in your personal wiki that could be shared: topic pages, folders, and the queue of data findings your sessions turned up. A topic must be reviewed in the Review tab before it can be promoted. Choose what to send to the team wiki manager: it proposes changes to the team wiki. Nothing is written there until you answer ✓ and press Submit.',
    empty: 'Nothing is waiting. Topic pages appear here once sessions are ingested, and again whenever they change after being promoted.',
    select: 'Select the pages to promote.',
    doneHint: 'When every card is handled, these pages are marked as promoted.',
    failHint: 'Review any cards it made; the pages stay in the list.',
    marked: (n) => `${plural(n, 'page')} marked promoted`,
  },
};
// A card's answer buttons: [answer, icon, tooltip].
const ANSWERS = [
  ['accept', '✓', 'Accept: write this change when you submit'],
  ['reject', '✗', 'Reject: drop this change when you submit'],
  ['feedback', '↻', 'Feedback: when you submit, Claude revises this change'],
];

export function createIngestView(container, deps) {
  const { call, on, getVault, getFolders, findFolder, getNotesDir, reload, render, openPage, toast, onChange, onHelp, onEditPrompt, onShowRun } = deps;
  const promotion = true; // (this view only does Promotion now)
  const stateName = 'promotion'; // which saved cards are this tab's
  const T = TEXT[stateName];
  const getSourceWiki = deps.getSourceWiki || (() => null); // promotion: the personal wiki's folder
  // Promotion: the wikis changes may be proposed in (every folder but the personal wiki).
  // Promotion's target is the Team wiki only; View only wikis are never a write target.
  const targets = () => (deps.getTeamWiki?.() ? [deps.getTeamWiki().alias] : []);
  let info = { ready: false, running: false };
  let state = { run: null, cards: [], last: null };
  let pastRuns = []; // [{ runId, transcript (parsed, or null) }], newest first
  let pastOpen = false;
  let vault = null;
  let loaded = false;
  let finishing = false;
  let submitting = false;
  let modelsAsked = false;
  let saveTimer = 0;
  let saving = Promise.resolve();
  const selected = new Set();
  const busy = new Set(); // ids of cards being written

  container.addEventListener('click', onClick);
  container.addEventListener('change', onSelectChange);
  // Feedback being typed is kept on its card (card.draft), so a redraw or a restart keeps it.
  container.addEventListener('input', (e) => {
    // An answer being typed is kept on its question, without a redraw (the cursor stays put).
    const question = e.target.dataset.qAnswer && (state.run?.questions || []).find((q) => q.id === e.target.dataset.qAnswer);
    if (question) {
      question.answer = e.target.value;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(save, 600);
      const missing = pendingQuestions().filter((q) => !answered(q)).length;
      const send = container.querySelector('[data-action="q-send"]');
      if (send) send.disabled = Boolean(missing);
      const status = container.querySelector('.ingest-q-footer .ingest-submit-status');
      if (status) status.textContent = missing ? `${missing} still ${missing === 1 ? 'needs' : 'need'} an answer or a skip` : 'Ready: Claude will propose the changes next.';
      return;
    }
    const card = e.target.dataset.feedback && state.cards.find((c) => c.id === e.target.dataset.feedback);
    if (!card) return;
    card.draft = e.target.value;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 600);
    e.target.closest('.ingest-card').classList.toggle('answered-feedback', answer(card) === 'feedback');
    drawFooter();
  });
  container.addEventListener('keydown', (e) => {
    if (e.target.dataset.feedback && e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit();
    }
  });
  // The view redraws often; keep the Past runs list open or closed as the user left it.
  container.addEventListener('toggle', (e) => {
    if (e.target.matches?.('.ingest-past-runs')) pastOpen = e.target.open;
  }, true);

  // ---- Loading and saving ---------------------------------------------------------------

  async function load() {
    try {
      info = await call('ingestInfo', { name: stateName });
    } catch (err) {
      info = { ready: false, running: false, error: err.message };
    }
    try {
      state = { run: null, cards: [], last: null, ...(info.state ? JSON.parse(info.state) : {}) };
    } catch {
      state = { run: null, cards: [], last: null };
    }
    if (state.run?.status === 'running' && !info.running) {
      if (state.run.revising) endRevision({ ok: false, message: 'WikiApp was closed while Claude was revising.' });
      else {
        state.run.status = 'failed';
        state.run.message = 'WikiApp was closed during the run.';
      }
      save();
    }
    loaded = true;
    draw();
    onChange();
    checkFinish();
    loadRuns();
    if (info.ready && !modelsAsked) loadModels();
  }

  // The models Claude Code offers, once per start (it takes a few seconds and costs nothing).
  // The last list is kept in the settings, so the menu is full straight away next time.
  async function loadModels() {
    modelsAsked = true;
    try {
      const list = await call('listIngestModels');
      if (Array.isArray(list) && list.length) {
        localStorageSet('ingestModels', JSON.stringify(list));
        draw();
      }
    } catch (err) {
      console.warn(`Couldn't list the Claude models: ${err.message}`);
    }
  }

  // The model comes from the engine settings (modelmenu.js), the same one Settings shows.
  const chosenModel = () => chosenModelFor('team-wiki-manager', T.model);

  // The run folders' transcripts, for the Past runs list.
  async function loadRuns() {
    try {
      pastRuns = (await call('listIngestRuns')).map((r) => {
        let transcript = null;
        try {
          transcript = r.transcript ? JSON.parse(r.transcript) : null;
        } catch { /* a transcript cut short */ }
        return { runId: r.runId, transcript };
      });
    } catch {
      pastRuns = [];
    }
    draw();
  }

  // Saves go one after another, so a later state never lands before an earlier one. (The Python
  // host answers each call on its own thread.)
  function save() {
    clearTimeout(saveTimer);
    const text = JSON.stringify(state);
    saving = saving
      .then(() => call('saveIngestState', { state: text, name: stateName }))
      .catch((err) => toast(`Couldn't save the Ingest cards: ${err.message}`));
  }

  // ---- What's listed ----------------------------------------------------------------------

  // Wrapped quick notes without `ingested:` in their frontmatter, newest first.
  function waiting() {
    return promotable();
  }

  // Promotion's list: the personal wiki's topic and folder pages that changed since they were
  // last promoted (all of them with Show already promoted), and its promotion queue while it has
  // findings waiting. The queue comes first.
  const isQueue = (note) => note.path.toLowerCase() === QUEUE_FILE;
  let showPromoted = false;
  const promotedAlready = (p) => Boolean(p.promoted) && !(stamp(p.promoted) < stamp(p.changed ?? p.updated));
  // A topic can be promoted only once the wiki reviewer has rewritten its summary since its last change.
  const needsReview = (note) => promotion && note.properties?.type === 'topic'
    && !(note.properties.state_as_of && !note.properties.needs_review && !Number(note.properties.entries_since_review));
  function promotable() {
    const source = getSourceWiki();
    if (!vault || !source) return [];
    return [...vault.notes.values()]
      .filter((n) => {
        if (n.folder !== source.alias) return false;
        if (isQueue(n)) return /^- \[ \] /m.test(n.content);
        const p = n.properties || {};
        return (p.type === 'topic' || p.type === 'folder') && (showPromoted || !promotedAlready(p));
      })
      .sort((a, b) => isQueue(b) - isQueue(a) || day(b.properties?.updated).localeCompare(day(a.properties?.updated)) || a.name.localeCompare(b.name));
  }

  const openCards = () => state.cards.filter((c) => c.status === 'open');
  // A promotion's questions from the agent that haven't been answered and sent back yet.
  const pendingQuestions = () => (state.run?.questions || []).filter((q) => !q.sent);
  const answered = (q) => q.skip || Boolean((q.answer || '').trim());
  const running = () => state.run?.status === 'running';
  // Cards Claude is revising now. (A round from before answers were submitted together has `card`.)
  const revisingIds = () => {
    const r = state.run?.revising;
    return new Set(r ? r.cards || [r.card] : []);
  };

  // A card's answer as it would be submitted, or '' while it still needs one. A card whose page
  // changed since it was proposed can only be dismissed; feedback needs some text.
  function answer(card) {
    if (isStale(card)) return card.decision === 'dismiss' ? 'dismiss' : '';
    if (card.decision === 'feedback') return (card.draft || '').trim() ? 'feedback' : '';
    return card.decision === 'accept' || card.decision === 'reject' ? card.decision : '';
  }

  // The open cards waiting for an answer (not the ones Claude is revising).
  const toAnswer = () => {
    const revising = revisingIds();
    return openCards().filter((c) => !revising.has(c.id));
  };

  // Why Ingest can't start right now, or '' if it can.
  function blocker(count) {
    if (!info.ready) return 'Ingest needs a one-time setup first.';
    if (running()) return 'A run is going.';
    if (pendingQuestions().length) return 'Answer Claude\'s questions first.';
    if (openCards().length) return `Answer the ${plural(openCards().length, 'proposed change')} and submit first.`;
    if (promotion && !getSourceWiki()) return 'Give a wiki the Personal role in Settings first.';
    if (promotion && !targets().length) return 'Give a wiki the Team role in Settings first.';
    if (!count) return T.select;
    return '';
  }

  // ---- Drawing ------------------------------------------------------------------------------

  function draw() {
    if (!loaded) return;
    // A redraw (a folder rescan, a progress line) mustn't take the cursor out of a feedback box,
    // or lose the place in the list of cards.
    const active = container.contains(document.activeElement) ? document.activeElement : null;
    const typing = active?.dataset?.feedback && { id: active.dataset.feedback, start: active.selectionStart, end: active.selectionEnd };
    const scroll = container.querySelector('.ingest-right')?.scrollTop || 0;
    const notes = waiting();
    for (const id of [...selected]) if (!notes.some((n) => n.id === id && !needsReview(n))) selected.delete(id);
    const count = selected.size;
    const why = blocker(count);
    const cards = state.cards.filter((c) => c.status === 'open' || busy.has(c.id));

    container.innerHTML = `
      <div class="ingest">
        <section class="ingest-left">
          <header class="ingest-header">
            <h1>${T.title}</h1>
          </header>
          <p class="ingest-intro">${esc(T.intro)}</p>
          ${info.ready ? '' : setupBox()}
          ${!getSourceWiki() ? rolePrompt('personal') : !targets().length ? rolePrompt('team') : `<p class="session-faint">Proposes changes in the Team wiki: <strong>${esc(targets()[0])}</strong> ${roleBadge(targets()[0])}</p>`}
          <div class="ingest-list">${notes.length ? notes.map(noteRow).join('') : `<p class="ingest-empty">${esc(blocker(1) && promotion && (!getSourceWiki() || !targets().length) ? '' : T.empty)}</p>`}</div>
          <div class="ingest-actions">
            ${notes.length ? `<button class="link-button" data-action="all">${count && count === notes.filter((n) => !needsReview(n)).length ? 'Select none' : 'Select all'}</button>` : ''}
            ${promotion ? `<label class="ingest-check" style="margin:0" title="Also list pages that haven't changed since they were promoted, to send one again"><input type="checkbox" data-action="show-promoted" ${showPromoted ? 'checked' : ''}> Show already promoted</label>` : ''}
            <span class="spacer"></span>
            <span class="ingest-why">${esc(why && count ? why : '')}</span>
            ${modelMenu()}
            <button class="primary-button" data-ai data-action="start" ${why ? 'disabled' : ''}>${T.button} ${count || ''}</button>
          </div>
          ${progress()}
          ${pastRunsList()}
        </section>
        <section class="ingest-right">
          <header class="ingest-cards-header">
            <h2>Proposed changes</h2>
            <span class="ingest-count">${openCards().length ? `${openCards().length} to review` : ''}</span>
          </header>
          ${questionsBox()}
          <div class="ingest-cards"></div>
          <footer class="ingest-submit" hidden></footer>
        </section>
      </div>`;

    const list = container.querySelector('.ingest-cards');
    if (cards.length) for (const card of cards) list.append(cardElement(card));
    else list.innerHTML = `<p class="ingest-empty">${running() ? 'Changes appear here as Claude proposes them.' : 'Changes Claude proposes appear here. Nothing is written to a page until you answer ✓ and submit.'}</p>`;
    drawFooter();
    container.querySelector('.ingest-right').scrollTop = scroll;

    const box = typing && container.querySelector(`textarea[data-feedback="${CSS.escape(typing.id)}"]`);
    if (box && !box.disabled) {
      box.focus();
      box.setSelectionRange(typing.start, typing.end);
    }
  }

  // A promotion's questions from the team wiki manager: one box each, with the places it is
  // choosing between as buttons, and a way to skip. Once sent, they fold into a short record.
  function questionsBox() {
    const all = state.run?.questions || [];
    if (!all.length) return '';
    const pending = pendingQuestions();
    if (!pending.length) {
      return `<details class="ingest-questions sent"><summary>Your answers to ${plural(all.length, 'question')}</summary>
        ${all.map((q) => `<div class="ingest-question"><p class="ingest-q-about">${esc(q.about)}</p><p>${esc(q.question)}</p>
          <p class="ingest-q-given">${q.skip ? 'Skipped: left out.' : esc(q.answer)}</p></div>`).join('')}</details>`;
    }
    const missing = pending.filter((q) => !answered(q)).length;
    return `
      <section class="ingest-questions">
        <h3>Before it proposes anything, Claude has ${plural(pending.length, 'question')}</h3>
        <p class="ingest-q-intro">Answer in a few words, pick one of the places it suggests, or skip a question to leave that point out of the team wiki.</p>
        ${pending.map((q) => `
          <div class="ingest-question${q.skip ? ' skipped' : ''}" data-question="${esc(q.id)}">
            <p class="ingest-q-about">${esc(q.about)}</p>
            <p class="ingest-q-text">${esc(q.question)}</p>
            ${(q.options || []).length ? `<div class="ingest-q-options">${q.options.map((o) => `<button class="secondary-button${q.answer === o ? ' chosen' : ''}" data-action="q-option" data-value="${esc(o)}" ${q.skip ? 'disabled' : ''}>${esc(o)}</button>`).join('')}</div>` : ''}
            <textarea rows="2" data-q-answer="${esc(q.id)}" placeholder="Your answer" ${q.skip ? 'disabled' : ''}>${esc(q.answer || '')}</textarea>
            <label class="ingest-check"><input type="checkbox" data-q-skip="${esc(q.id)}" ${q.skip ? 'checked' : ''}> Skip: leave this point out</label>
          </div>`).join('')}
        <footer class="ingest-q-footer">
          <span class="ingest-submit-status">${missing ? `${missing} still ${missing === 1 ? 'needs' : 'need'} an answer or a skip` : 'Ready: Claude will propose the changes next.'}</span>
          <button class="primary-button" style="margin:0" data-action="q-send" ${missing ? 'disabled' : ''}>Continue</button>
        </footer>
      </section>`;
  }

  // Sends the answers back: the same run continues, and the agent proposes its cards.
  async function sendAnswers() {
    const run = state.run;
    const pending = pendingQuestions();
    if (!run || running() || !pending.length || pending.some((q) => !answered(q))) return;
    const answers = Object.fromEntries(run.questions.map((q) => [q.id, q.skip ? '' : (q.answer || '').trim()]));
    try {
      await call('answerIngestQuestions', { runId: run.id, answers });
    } catch (err) {
      toast(`Couldn't send the answers: ${err.message}`);
      return;
    }
    for (const q of run.questions) q.sent = true;
    run.status = 'running';
    run.stage = 'Claude is using your answers';
    save();
    draw();
    onChange();
  }

  // The Submit bar under the cards: how many still need an answer, or what Submit will do.
  function drawFooter() {
    const bar = container.querySelector('.ingest-submit');
    if (!bar) return;
    const cards = toAnswer();
    bar.hidden = !cards.length;
    if (!cards.length) return;
    const answers = cards.map(answer);
    const missing = answers.filter((a) => !a).length;
    const n = (a) => answers.filter((x) => x === a).length;
    const plan = [
      n('accept') && `${n('accept')} to write`,
      n('reject') && `${n('reject')} to drop`,
      n('dismiss') && `${n('dismiss')} to dismiss`,
      n('feedback') && `${plural(n('feedback'), 'card')} back to Claude`,
    ].filter(Boolean).join(' · ');
    const wait = running() ? 'Wait for Claude to finish.' : '';
    bar.innerHTML = `
      <span class="ingest-submit-status${missing ? '' : ' ready'}">${esc(wait || (missing
        ? `${missing} of ${plural(cards.length, 'change')} still ${missing === 1 ? 'needs' : 'need'} an answer`
        : plan))}</span>
      <button class="primary-button" data-action="submit" ${missing || wait || submitting ? 'disabled' : ''}
        title="${missing ? 'Answer every card first: ✓, ✗ or ↻ with feedback' : 'Write the accepted changes and send the feedback (Ctrl+Enter in a feedback box)'}">${submitting ? 'Submitting…' : 'Submit'}</button>`;
  }

  const modelMenu = () => sharedModelMenu({ agent: 'team-wiki-manager', fallback: T.model, disabled: running(), what: 'the next run' });

  function setupBox() {
    return `
      <div class="ingest-setup">
        <p><strong>Ingest needs a one-time setup.</strong> It installs the app's Python packages, including the Claude Agent SDK, in <code>App Files/.venv</code>. It needs Python 3.10 or newer, and Claude Code signed in on this computer (Ingest uses that sign-in, no API key).</p>
        ${info.error ? `<p class="field-error">${esc(info.error)}</p>` : ''}
        <button class="primary-button" data-action="setup">Run setup</button>
        <button class="secondary-button" data-action="recheck">Check again</button>
      </div>`;
  }

  function noteRow(note) {
    const folder = findFolder(note.folder);
    if (promotion) {
      const p = note.properties || {};
      const findings = (note.content.match(/^- \[ \] /gm) || []).length;
      const meta = isQueue(note)
        ? `${plural(findings, 'data finding')} from your sessions`
        : [p.type, p.folder && `in ${p.folder}`, needsReview(note) ? 'review it first, in the Review tab' : p.promoted ? (promotedAlready(p) ? `promoted ${day(p.promoted)}` : `changed since promoted ${day(p.promoted)}`) : `updated ${day(p.updated)}`].filter(Boolean).join(' · ');
      return `
        <label class="ingest-note" title="${esc(typeof p.summary === 'string' ? p.summary : '')}">
          <input type="checkbox" data-id="${esc(note.id)}" ${selected.has(note.id) ? 'checked' : ''} ${running() || needsReview(note) ? 'disabled' : ''}>
          <button class="link-button ingest-note-name" data-action="open" data-id="${esc(note.id)}">${esc(isQueue(note) ? 'Promotion queue' : p.title || note.name)}</button>
          <span class="wiki-chip" style="--wiki:${esc(folder?.color || 'var(--text-faint)')}">${esc(note.folder)}</span>
          <span class="ingest-note-meta">${esc(meta)}</span>
        </label>`;
    }
  }

  function progress() {
    const run = state.run;
    if (run) {
      const proposed = state.cards.length;
      if (run.status === 'running') {
        return `
          <div class="ingest-progress">
            <div class="ingest-bar"><span></span></div>
            <div class="ingest-stage">${esc(run.stage || 'Starting')}</div>
            <div class="ingest-stats">${plural(run.reads.length, 'page')} read · ${plural(proposed, 'change')} proposed
              <span class="spacer"></span><button class="link-button" data-action="cancel">Stop</button></div>
          </div>`;
      }
      const ok = run.status === 'done';
      return `
        <div class="ingest-progress ${ok ? 'done' : 'failed'}">
          <div class="ingest-stage">${ok ? (pendingQuestions().length ? `Claude read ${plural(run.reads.length, 'page')} and has ${plural(pendingQuestions().length, 'question')} for you, on the right.` : `Done: ${plural(proposed, 'change')} proposed after reading ${plural(run.reads.length, 'page')}.`) : `The run stopped: ${esc(run.message)}`}</div>
          ${costLine(run)}
          <div class="ingest-stats">${ok ? T.doneHint : T.failHint}
            <span class="spacer"></span><button class="link-button" data-action="folder" data-run="${esc(run.id)}">Open run folder</button></div>
        </div>`;
    }
    const last = state.last;
    if (!last) return '';
    return `
      <div class="ingest-progress ${last.ok ? 'done' : 'failed'}">
        <div class="ingest-stage">Last run: ${esc(last.text)}</div>
        ${costLine(last)}
        <div class="ingest-stats"><span class="spacer"></span><button class="link-button" data-action="folder" data-run="${esc(last.id)}">Open run folder</button></div>
      </div>`;
  }

  function pastRunsList() {
    if (!pastRuns.length) return '';
    const rows = pastRuns.map(({ runId, transcript: t }) => {
      const when = runTime(runId);
      if (!t) {
        return `<button class="ingest-past" data-action="folder" data-run="${esc(runId)}" title="No transcript: open the run folder">
          <span class="ingest-past-when">${esc(when)}</span><span class="ingest-past-what">no transcript</span><span></span></button>`;
      }
      const notes = plural(t.notes.length, 'note');
      const rounds = t.feedback?.length ? ` · ${plural(t.feedback.length, 'feedback round')}` : '';
      const what = (t.ok ? `${notes} · ${plural(t.cards.length, 'change')}` : `${notes} · stopped`) + rounds;
      return `<button class="ingest-past${t.ok ? '' : ' failed'}" data-action="run" data-run="${esc(runId)}" title="Show what this run read, its tokens and cost">
        <span class="ingest-past-when">${esc(when)}</span><span class="ingest-past-what">${esc(what)}</span><span class="ingest-past-cost">${money(t.totals?.cost)}</span></button>`;
    });
    return `<details class="ingest-past-runs" ${pastOpen ? 'open' : ''}><summary>Past runs (${pastRuns.length})</summary><div>${rows.join('')}</div></details>`;
  }

  function costLine(run) {
    if (typeof run.cost !== 'number') return '';
    const plain = run.plain?.cost;
    return `<div class="ingest-cost"><span class="ingest-plain" title="${esc(API_PRICE_HINT)}">≈ ${money(run.cost)} at API prices ⓘ</span>${typeof plain === 'number' ? ` <span class="ingest-plain" title="${esc(PLAIN_HINT)}">· plain Claude Code ≈ ${money(plain)} ⓘ</span>` : ''}
      ${run.tokens ? `<span class="ingest-tokens">${(run.tokens.input + run.tokens.cacheWrite + run.tokens.cacheRead).toLocaleString()} tokens in, ${run.tokens.output.toLocaleString()} out</span>` : ''}</div>`;
  }

  // ---- Cards --------------------------------------------------------------------------------

  function cardElement(card) {
    const folder = findFolder(card.wiki);
    const stale = isStale(card);
    const { tags, links } = additions(card);
    const given = answer(card);
    const revising = revisingIds().has(card.id);
    const locked = revising || submitting || busy.has(card.id);
    const el = document.createElement('article');
    el.className = `ingest-card${stale ? ' stale' : ''}${given ? ` answered-${given}` : ''}`;
    el.style.setProperty('--wiki', folder?.color || 'var(--text-faint)');
    el.dataset.id = card.id;
    const fromNotes = card.fromNotes.map((id) => vault?.notes.get(id)?.name || id.slice(id.indexOf(':') + 1)).join(', ');
    el.innerHTML = `
      <header class="ingest-card-header">
        <span class="wiki-chip" style="--wiki:${esc(folder?.color || 'var(--text-faint)')}">${esc(card.wiki)}</span>
        ${card.kind === 'edit'
          ? `<button class="link-button ingest-card-title" data-action="page" data-id="${esc(card.page)}">${esc(card.title)}</button>`
          : `<span class="ingest-card-title">${esc(card.title)}</span>`}
        <span class="ingest-kind ${card.kind}">${card.kind === 'edit' ? 'EDIT' : 'NEW'}</span>
        <span class="spacer"></span>
        ${stale
          ? `<button class="secondary-button ingest-dismiss${card.decision === 'dismiss' ? ' chosen' : ''}" data-action="decide" data-decision="dismiss" aria-pressed="${card.decision === 'dismiss'}" ${locked ? 'disabled' : ''}>Dismiss</button>`
          : ANSWERS.map(([a, icon, title]) => `<button class="ingest-answer${card.decision === a ? ' chosen' : ''}" data-action="decide" data-decision="${a}"
              title="${title}" aria-label="${title}" aria-pressed="${card.decision === a}" ${locked ? 'disabled' : ''}>${icon}</button>`).join('')}
      </header>
      ${stale ? `<p class="ingest-stale">${card.kind === 'edit' ? 'Page changed since this was proposed.' : 'A page with this name exists now.'} Dismiss it; what it came from stays in the list, to run again.</p>` : ''}
      ${stale ? '' : feedbackParts(card, revising)}
      <p class="ingest-summary">${esc(card.summary)}</p>
      <p class="ingest-from">From ${esc(fromNotes)}</p>
      ${tags.length ? `<div class="ingest-adds"><span>New tags</span>${tags.map((t) => `<span class="chip">#${esc(t)}</span>`).join('')}</div>` : ''}
      ${links.length ? `<div class="ingest-adds"><span>New links</span>${links.map((l) => `<span class="chip${l.exists ? '' : ' missing'}" title="${l.exists ? '' : 'No page with this name yet'}">${esc(l.text)}</span>`).join('')}</div>` : ''}
      ${card.kind === 'new' ? newPageParts(card) : `<div class="ingest-diff">${diffRows(card.before, card.after)}</div>`}`;
    if (card.kind === 'new') {
      const preview = el.querySelector('.ingest-preview');
      try {
        preview.append(render(parseFrontmatter(card.after).body, card.wiki)); // tags are listed above
      } catch {
        preview.textContent = card.after;
      }
    }
    return el;
  }

  // What was said about the card so far, and the feedback box when its answer is ↻. Submitted
  // feedback continues the run's own Claude session (see ingest/AGENT.md, "Feedback rounds").
  function feedbackParts(card, revising) {
    const history = (card.feedback || []).map((f) => `
      <div class="ingest-said"><span>You</span>${esc(f.text)}</div>
      <div class="ingest-said claude"><span>Claude</span>${esc(f.reply || (f.error ? `Couldn't revise: ${f.error}` : f.revised ? 'Revised the card.' : 'No change.'))}</div>`).join('');
    if (revising) {
      return `${history}<div class="ingest-said"><span>You</span>${esc(card.pendingFeedback || '')}</div><p class="ingest-revising">Claude is revising this card…</p>`;
    }
    if (card.decision !== 'feedback') return history;
    return `${history}
      <div class="ingest-feedback">
        <textarea rows="2" data-feedback="${esc(card.id)}" placeholder="What should Claude change on this card? Sent when you submit." ${submitting || busy.has(card.id) ? 'disabled' : ''}>${esc(card.draft || '')}</textarea>
      </div>`;
  }

  function newPageParts(card) {
    const slash = card.path.lastIndexOf('/');
    const dir = slash >= 0 ? card.path.slice(0, slash) : '';
    const file = card.path.slice(slash + 1);
    const folders = pageFolders(card.wiki);
    if (!folders.includes(dir)) folders.push(dir);
    folders.sort((a, b) => a.localeCompare(b));
    return `
      <div class="ingest-path">
        <span>Save as</span>
        <select data-action="folder-pick" ${state.cards.length && !isStale(card) ? '' : 'disabled'}>
          ${folders.map((f) => `<option value="${esc(f)}" ${f === dir ? 'selected' : ''}>${esc(f ? `${f}/` : '(top level)')}</option>`).join('')}
        </select>
        <span class="ingest-file">${esc(file)}</span>
      </div>
      ${card.template ? `<div class="ingest-adds"><span>Template</span><button class="link-button" data-action="page" data-id="${esc(card.template)}" title="Open the page template">${esc(card.templateName || card.template)}</button></div>` : ''}
      <details class="ingest-preview-box"><summary>Preview the new page</summary><div class="ingest-preview note"></div></details>`;
  }

  // Folders a new page may go in: not the notes folder, Templates or hidden ones.
  function pageFolders(alias) {
    const scan = vault?.folders.find((f) => f.alias === alias)?.scan;
    const notesDir = getNotesDir().toLowerCase();
    const skip = (f) => {
      const lower = f.toLowerCase();
      return lower === notesDir || lower.startsWith(notesDir + '/') || f === TEMPLATES_DIR || f.startsWith(TEMPLATES_DIR + '/');
    };
    return ['', ...(scan?.folders || []).filter((f) => !skip(f))];
  }

  // A card can no longer be applied as proposed: the page changed, or the new page's name is taken.
  function isStale(card) {
    if (!vault || card.status !== 'open') return false;
    if (card.kind === 'edit') {
      const note = vault.notes.get(card.page);
      return !note || note.content.replace(/\r\n/g, '\n') !== card.before;
    }
    const path = card.path.toLowerCase();
    return [...vault.notes.values()].some((n) => n.folder === card.wiki && n.path.toLowerCase() === path);
  }

  // The tags and links the change adds, worked out from the text rather than taken from the agent.
  function additions(card) {
    const tagsOf = (text) => {
      const p = parseFrontmatter(text).properties || {};
      return normalizeTags(p.tags ?? p.tag);
    };
    const linksOf = (text) => [...text.replace(/```[\s\S]*?```/g, '').replace(/`[^`\n]*`/g, '').matchAll(WIKILINK)].map((m) => m[1]);
    const key = (inner) => {
      const l = parseLink(inner);
      return `${l.folder}:${l.target}`.toLowerCase();
    };
    const oldTags = new Set(tagsOf(card.before));
    const oldLinks = new Set(linksOf(card.before).map(key));
    const created = new Set(state.cards.filter((c) => c.kind === 'new' && c.status !== 'rejected').map((c) => c.title.toLowerCase()));
    const seen = new Set();
    const links = [];
    for (const inner of linksOf(card.after)) {
      const k = key(inner);
      if (oldLinks.has(k) || seen.has(k)) continue;
      seen.add(k);
      const link = parseLink(inner);
      if (!link.target) continue;
      const exists = Boolean((vault && resolveTarget(vault, link, card.wiki)) || created.has(link.target.toLowerCase()));
      links.push({ text: link.folder ? `${link.folder}:${link.target}` : link.target, exists });
    }
    return { tags: tagsOf(card.after).filter((t) => !oldTags.has(t)), links };
  }

  // ---- Actions ------------------------------------------------------------------------------

  async function onClick(e) {
    const button = e.target.closest('[data-action]');
    if (!button || button.tagName === 'SELECT') return;
    const action = button.dataset.action;
    const card = state.cards.find((c) => c.id === button.closest('.ingest-card')?.dataset.id);
    if (action === 'help') onHelp();
    else if (action === 'prompt') onEditPrompt();
    else if (action === 'setup') {
      await call('runIngestSetup').catch((err) => toast(err.message));
      toast('Setup opened in a console window. When it says Ingest is ready, press Check again.');
    } else if (action === 'recheck') load();
    else if (action === 'open') {
      e.preventDefault();
      openPage(button.dataset.id);
    } else if (action === 'page') openPage(button.dataset.id);
    else if (action === 'all') {
      const notes = waiting().filter((n) => !needsReview(n));
      if (selected.size === notes.length) selected.clear();
      else for (const n of notes) selected.add(n.id);
      draw();
    } else if (action === 'start') startRun();
    else if (action === 'cancel') {
      if (state.run) state.run.cancelled = true;
      call('cancelIngest');
    } else if (action === 'folder') call('openIngestRun', { runId: button.dataset.run }).catch((err) => toast(err.message));
    else if (action === 'run') {
      const run = pastRuns.find((r) => r.runId === button.dataset.run);
      if (run?.transcript) onShowRun(run.transcript, runTime(run.runId));
    }
    else if (action === 'q-option' || action === 'q-send') {
      const q = (state.run?.questions || []).find((x) => x.id === button.closest('[data-question]')?.dataset.question);
      if (action === 'q-send') sendAnswers();
      else if (q) {
        q.answer = q.answer === button.dataset.value ? '' : button.dataset.value;
        save();
        draw();
      }
    }
    else if (card && action === 'decide') decide(card, button.dataset.decision);
    else if (action === 'submit') submit();
  }

  // Sets (or, pressed again, clears) a card's answer. Nothing is written until Submit.
  function decide(card, decision) {
    if (submitting || busy.has(card.id) || revisingIds().has(card.id)) return;
    card.decision = card.decision === decision ? '' : decision;
    save();
    draw();
    if (card.decision === 'feedback') container.querySelector(`textarea[data-feedback="${CSS.escape(card.id)}"]`)?.focus();
  }

  function onSelectChange(e) {
    if (rememberModel(e)) {
      draw();
    } else if (e.target.dataset.qSkip) {
      const q = (state.run?.questions || []).find((x) => x.id === e.target.dataset.qSkip);
      if (q) q.skip = e.target.checked;
      save();
      draw();
    } else if (e.target.matches('[data-action="show-promoted"]')) {
      showPromoted = e.target.checked;
      draw();
    } else if (e.target.matches('.ingest-note input[type=checkbox]')) {
      if (e.target.checked) selected.add(e.target.dataset.id);
      else selected.delete(e.target.dataset.id);
      draw();
    } else if (e.target.matches('select[data-action="folder-pick"]')) {
      const card = state.cards.find((c) => c.id === e.target.closest('.ingest-card')?.dataset.id);
      if (!card) return;
      const file = card.path.slice(card.path.lastIndexOf('/') + 1);
      card.path = e.target.value ? `${e.target.value}/${file}` : file;
      save();
      draw();
    }
  }

  async function startRun() {
    const ids = waiting().filter((n) => !needsReview(n)).map((n) => n.id).filter((id) => selected.has(id));
    if (blocker(ids.length)) return;
    const job = {
      date: isoDate(),
      notesDir: getNotesDir(),
      wikis: getFolders().map((f) => ({ alias: f.alias, root: f.root })),
      notes: ids,
      settings: { logRaw: localStorageGet('ingestLogRaw') === 'true', model: chosenModel() },
      ...(promotion ? { agent: 'team-wiki-manager', targets: targets() } : {}),
    };
    // The queue's findings as they are now: the ones this run saw are ticked when it's done.
    const queue = promotion && ids.map((id) => vault.notes.get(id)).find((n) => n && isQueue(n));
    const queueLines = queue ? queue.content.split(/\r?\n/).filter((line) => line.startsWith('- [ ] ')) : [];
    try {
      const runId = await call('startIngest', { job });
      state.run = { id: runId, notes: ids, queueLines, status: 'running', stage: 'Starting', reads: [], started: new Date().toISOString() };
      state.cards = [];
      save();
      draw();
      onChange();
    } catch (err) {
      toast(`${T.title} didn't start: ${err.message}`);
    }
  }

  // Submit: every card has an answer. The ✓ changes are written, ✗ and dismissed cards dropped,
  // and the ↻ cards go back to Claude together in one feedback round. A change that can't be
  // written (its page changed meanwhile) stays open without an answer.
  async function submit() {
    const cards = toAnswer();
    if (submitting || running() || !cards.length) return;
    const answers = new Map(cards.map((c) => [c, answer(c)]));
    if ([...answers.values()].some((a) => !a)) return;
    submitting = true;
    draw();
    const written = new Set();
    for (const [card, a] of answers) {
      if (a === 'accept' && (await write(card))) written.add(card.wiki);
      else if (a === 'reject') card.status = 'rejected';
      else if (a === 'dismiss') card.status = 'dismissed';
    }
    save();
    for (const alias of written) await reload(alias);
    const asked = cards.filter((c) => answers.get(c) === 'feedback' && c.status === 'open');
    if (asked.length) await sendFeedback(asked);
    submitting = false;
    save();
    draw();
    onChange();
    checkFinish();
  }

  // Writes an accepted card's change. -> whether it was written.
  async function write(card) {
    const folder = findFolder(card.wiki);
    if (!folder) {
      toast(`The ${card.wiki} folder isn't in the workspace any more, so ${card.title} was not written.`);
      card.decision = '';
      return false;
    }
    busy.add(card.id);
    try {
      if (card.kind === 'edit') {
        await call('editLines', { root: folder.root, path: card.path, start: 0, expect: card.before.split('\n'), replace: card.after.split('\n') });
      } else {
        await call('createNote', { root: folder.root, path: card.path, lines: card.after.split('\n') });
      }
      card.status = 'accepted';
      return true;
    } catch (err) {
      toast(/changed on disk/.test(err.message) ? `${card.title} changed since this was proposed, so the change was not written.` : `${card.title} was not written: ${err.message}`);
      card.decision = '';
      return false;
    } finally {
      busy.delete(card.id);
    }
  }

  // Sends the feedback on these cards back to Claude, with which cards were accepted and
  // rejected. It's the same run, continued: the run shows as working again, each card is
  // replaced by Claude's revision (same id), and the round's cost and tokens are added to the run's.
  async function sendFeedback(asked) {
    const run = state.run;
    if (!run) return;
    const ids = (...statuses) => state.cards.filter((c) => statuses.includes(c.status)).map((c) => c.id);
    const feedback = {
      cards: asked.map((c) => ({ card: c.id, text: c.draft.trim() })),
      accepted: ids('accepted'),
      rejected: ids('rejected', 'dismissed'),
    };
    try {
      await call('reviseIngestCards', { runId: run.id, feedback });
    } catch (err) {
      toast(`Couldn't send the feedback: ${err.message}`);
      return;
    }
    run.revising = { cards: asked.map((c) => c.id), status: run.status, message: run.message };
    run.status = 'running';
    run.stage = asked.length === 1 ? `Claude is revising ${asked[0].title}` : `Claude is revising ${asked.length} cards`;
    for (const card of asked) {
      card.pendingFeedback = card.draft.trim();
      card.draft = '';
    }
  }

  // The end of a feedback round: the run goes back to how it was, with the new totals, and the
  // cards that were sent need a new answer.
  function endRevision({ ok, message, reply, revised = [] }) {
    const run = state.run;
    for (const id of run.revising.cards || [run.revising.card]) {
      const card = state.cards.find((c) => c.id === id);
      if (!card) continue;
      card.feedback = [...(card.feedback || []), { text: card.pendingFeedback || '', reply: reply || '', revised: revised.includes(id), error: ok ? '' : message }];
      delete card.pendingFeedback;
      card.decision = '';
    }
    run.status = run.revising.status;
    run.message = run.revising.message;
    run.revising = null;
    if (!ok) toast(`Claude couldn't revise the cards: ${message}`);
  }

  // When a finished run has no cards left to review: mark its notes ingested (unless the run
  // failed, or one of a note's cards was dismissed because its page changed), and clear it.
  async function checkFinish() {
    const run = state.run;
    if (!run || run.status === 'running' || finishing || submitting || busy.size || openCards().length || pendingQuestions().length || !vault) return;
    finishing = true;
    const count = (status) => state.cards.filter((c) => c.status === status).length;
    let marked = [];
    if (run.status === 'done') {
      const blocked = new Set(state.cards.filter((c) => c.status === 'dismissed').flatMap((c) => c.fromNotes));
      marked = await markIngested(run.notes.filter((id) => !blocked.has(id)), run.queueLines || []);
    }
    const parts = [`${plural(state.cards.length, 'change')} proposed`];
    if (state.cards.length) parts.push(`${count('accepted')} accepted, ${count('rejected')} rejected${count('dismissed') ? `, ${count('dismissed')} dismissed` : ''}`);
    parts.push(run.status === 'done' ? T.marked(marked.length) : `stopped: ${run.message}`);
    state.last = { id: run.id, ok: run.status === 'done', text: parts.join(' · '), cost: run.cost, plain: run.plain, tokens: run.tokens };
    state.run = null;
    state.cards = [];
    for (const id of marked) selected.delete(id);
    finishing = false;
    save();
    draw();
    onChange();
  }

  // Adds `ingested: <today>` to each note's frontmatter (a promoted page gets `promoted:`, and
  // the promotion queue has the findings the run saw ticked). -> ids that were marked.
  async function markIngested(ids, queueLines = []) {
    const done = [];
    const folders = new Set();
    for (const id of ids) {
      const note = vault.notes.get(id);
      const folder = note && findFolder(note.folder);
      if (!folder) continue;
      const front = parseNote(note.content).front;
      try {
        if (promotion && isQueue(note)) {
          const lines = note.content.split(/\r?\n/);
          const seen = new Set(queueLines);
          await call('editLines', { root: folder.root, path: note.path, start: 0, expect: lines, replace: lines.map((l) => (seen.has(l) ? l.replace('- [ ] ', '- [x] ') : l)) });
        } else await call('editLines', { root: folder.root, path: note.path, start: 0, expect: front, replace: withProperties(front, promotion ? { promoted: new Date().toISOString() } : { ingested: isoDate() }) });
        done.push(id);
        folders.add(note.folder);
      } catch (err) {
        toast(`Couldn't mark ${note.name} as ${promotion ? 'promoted' : 'ingested'}: ${err.message}`);
      }
    }
    for (const alias of folders) await reload(alias);
    return done;
  }

  // ---- Progress from the host ----------------------------------------------------------------

  on('ingest', (line) => {
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      return;
    }
    const run = state.run;
    if (!run || run.status !== 'running') return;
    if (event.type === 'stage') run.stage = event.text;
    else if (event.type === 'read') run.reads.push(event.page);
    else if (event.type === 'card') {
      const card = { ...event.card, status: 'open' };
      const at = state.cards.findIndex((c) => c.id === card.id);
      if (at >= 0) {
        // A revision: keep the conversation about this card. (tools.py refuses to revise a
        // card that was already accepted or rejected; this is the page's own check.)
        if (state.cards[at].status !== 'open') return;
        card.feedback = state.cards[at].feedback;
        card.pendingFeedback = state.cards[at].pendingFeedback;
        state.cards[at] = card;
      } else state.cards.push(card);
    } else if (event.type === 'questions') {
      // A promotion: the agent asks before it proposes. The run ends here and waits for the answers.
      run.questions = (event.questions || []).map((q) => ({ ...q, answer: '', skip: false, sent: false }));
    } else if (event.type === 'reply') {
      const revised = Array.isArray(event.revised) ? event.revised : event.revised ? [event.card] : [];
      run.reply = { text: event.text, revised };
    } else if (event.type === 'done' && run.revising) {
      // The totals are the whole run's, this round included.
      Object.assign(run, { cost: event.cost, plain: event.plainClaudeCode, tokens: event.tokens });
      endRevision({ ok: event.ok && !run.cancelled, message: run.cancelled ? 'you stopped it.' : event.message, reply: run.reply?.text, revised: run.reply?.revised });
      delete run.reply;
    } else if (event.type === 'done') {
      Object.assign(run, {
        status: event.ok ? 'done' : 'failed',
        message: run.cancelled ? 'you stopped it.' : event.message || '',
        cost: event.cost,
        plain: event.plainClaudeCode,
        tokens: event.tokens,
      });
    } else return;
    save();
    draw();
    onChange();
    if (event.type === 'done') {
      run.cancelled = false;
      checkFinish();
      loadRuns();
    }
  });

  on('ingestExit', ({ code, errors }) => {
    const run = state.run;
    if (!run || run.status !== 'running') return;
    const lastError = String(errors || '').trim().split('\n').pop();
    const why = run.cancelled ? 'you stopped it.' : lastError || `the ingest script ended unexpectedly (exit code ${code}).`;
    if (run.revising) endRevision({ ok: false, message: why });
    else {
      run.status = 'failed';
      run.message = why;
    }
    run.cancelled = false;
    save();
    draw();
    onChange();
    checkFinish();
    loadRuns();
  });

  return {
    load,
    setVault(next) {
      vault = next;
      draw();
      checkFinish();
    },
    // The rail badge: cards to review if there are any, else notes waiting.
    badge: () => (!loaded ? 0 : openCards().length || waiting().filter((n) => !needsReview(n) && !(promotion && !isQueue(n) && promotedAlready(n.properties || {}))).length),
    info: () => info,
    setInfo(changes) {
      Object.assign(info, changes);
    },
  };
}

// "2026-11-01_194742" -> "Nov 1, 19:47"
function runTime(runId) {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})/.exec(runId);
  if (!m) return runId;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return `${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}, ${m[4]}:${m[5]}`;
}

function localStorageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function localStorageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable: the choice lasts this session */ }
}

// ---- A line diff, shown as red/green rows with two lines of context ---------------------------

function diffRows(before, after) {
  const a = before.split('\n');
  const b = after.split('\n');
  const ops = lineDiff(a, b);
  const near = new Set();
  ops.forEach((op, i) => {
    if (op.type !== 'same') for (let j = i - 2; j <= i + 2; j++) near.add(j);
  });
  const rows = [];
  let gap = false;
  ops.forEach((op, i) => {
    if (!near.has(i)) {
      gap = true;
      return;
    }
    if (gap && rows.length) rows.push('<div class="diff-gap">⋯</div>');
    gap = false;
    const sign = op.type === 'add' ? '+' : op.type === 'del' ? '−' : ' ';
    rows.push(`<div class="diff-${op.type}"><span class="diff-sign">${sign}</span>${esc(op.text) || ' '}</div>`);
  });
  return rows.join('');
}

// Longest-common-subsequence diff of two line lists -> [{ type: same|del|add, text }].
// The common start and end are trimmed first, so typical edits stay small.
export function lineDiff(a, b) {
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const head = a.slice(0, start).map((text) => ({ type: 'same', text }));
  const tail = a.slice(endA).map((text) => ({ type: 'same', text }));
  const x = a.slice(start, endA);
  const y = b.slice(start, endB);
  const middle = [];
  if (x.length * y.length > 4_000_000) {
    middle.push(...x.map((text) => ({ type: 'del', text })), ...y.map((text) => ({ type: 'add', text })));
  } else {
    const n = x.length;
    const m = y.length;
    const lcs = new Uint32Array((n + 1) * (m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        lcs[i * (m + 1) + j] = x[i] === y[j] ? lcs[(i + 1) * (m + 1) + j + 1] + 1 : Math.max(lcs[(i + 1) * (m + 1) + j], lcs[i * (m + 1) + j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (x[i] === y[j]) {
        middle.push({ type: 'same', text: x[i++] });
        j++;
      } else if (lcs[(i + 1) * (m + 1) + j] >= lcs[i * (m + 1) + j + 1]) middle.push({ type: 'del', text: x[i++] });
      else middle.push({ type: 'add', text: y[j++] });
    }
    while (i < n) middle.push({ type: 'del', text: x[i++] });
    while (j < m) middle.push({ type: 'add', text: y[j++] });
  }
  return [...head, ...middle, ...tail];
}
