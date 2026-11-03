// The Ingest view's windows:
//   Edit ingestion prompt: one tab each for the shipped agent prompt (read-only), the user's own
//     notes for the agent (saved in the app's data folder), the page templates (a list: each
//     wiki's Templates/Pages files), and each wiki's wiki_rules.md.
//   How Ingest works (the ? button): plain-language explanation with a picture of the agent loop.
//   A past run (from Past runs): its transcript.json, request by request, with tokens and cost.

import { RULES_FILE } from './vault.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

const starterRules = (alias) =>
  [
    '---', `description: How the ingest agent writes in the ${alias} wiki.`, '---', `# ${alias} wiki rules`, '',
    '## Where things go', '- (which folder or page each kind of note content belongs on)', '',
    '## New pages', '- (which kinds of page may be created, and in which folder; anything else is left out)', '',
    '## Style', '- ', '',
  ].join('\n');

export function createIngestDialogs(backdrop, {
  getInfo, saveNotes, getWikis, saveRules, getPageTemplates, openPageTemplate, newPageTemplate, getLogRaw, setLogRaw, openRunFolder,
}) {
  let close = null;

  backdrop.addEventListener('mousedown', (e) => {
    if (e.target === backdrop && close) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !backdrop.hidden && close) {
      e.preventDefault();
      close();
    }
  });

  function show(html, onClose) {
    backdrop.innerHTML = html;
    backdrop.hidden = false;
    close = () => {
      if (onClose && onClose() === false) return;
      backdrop.hidden = true;
      backdrop.innerHTML = '';
      close = null;
    };
    backdrop.querySelector('[data-close]')?.addEventListener('click', () => close());
  }

  // ---- Edit ingestion prompt ----------------------------------------------------------------

  function openPrompt(startTab = 'notes') {
    const info = getInfo();
    const wikis = getWikis(); // [{ alias, color, text (or null when there's no rules file) }]
    // The shipped agent prompt (ingest/agent-prompt.md) is shown read-only: it updates with the app.
    const tabs = [
      { id: 'agent', label: 'Agent prompt', text: info.prompt || '', readOnly: true },
      { id: 'notes', label: 'Your notes', text: info.userNotes || '' },
      { id: 'templates', label: 'Page templates', text: '', list: true },
      ...wikis.map((w) => ({ id: `rules:${w.alias}`, label: `${w.alias} rules`, alias: w.alias, color: w.color, exists: w.text !== null, text: w.text ?? starterRules(w.alias) })),
    ];
    const drafts = new Map(tabs.map((t) => [t.id, t.text]));
    const saved = new Map(tabs.map((t) => [t.id, t.text])); // what's on disk (or the starter text)
    let current = tabs.find((t) => t.id === startTab) ? startTab : 'notes';
    let area = null;

    show(
      `<div class="dialog ingest-dialog" role="dialog" aria-label="Edit ingestion prompt">
        <h2 class="dialog-title">Ingestion prompt</h2>
        <p class="field-hint">On every run Claude gets WikiApp's built-in instructions, then your notes, then each wiki's rules. The page templates' names and descriptions come with the index of pages.</p>
        <div class="ingest-tabs" role="tablist">
          ${tabs.map((t) => `<button class="ingest-tab" role="tab" data-tab="${esc(t.id)}" ${t.color ? `style="--wiki:${esc(t.color)}"` : ''}>${esc(t.label)}</button>`).join('')}
        </div>
        <p class="field-hint ingest-tab-hint"></p>
        <textarea class="ingest-prompt-text" spellcheck="false"></textarea>
        <div class="ingest-templates" hidden></div>
        <label class="ingest-check"><input type="checkbox" class="ingest-lograw" ${getLogRaw() ? 'checked' : ''}> Also save each run's raw requests in its run folder, to check exactly what was sent</label>
        <div class="dialog-actions">
          <span class="ingest-save-status"></span>
          <span class="spacer"></span>
          <button class="secondary-button" data-close>Close</button>
          <button class="primary-button ingest-save">Save</button>
        </div>
      </div>`,
      () => {
        keepDraft();
        const unsaved = tabs.filter((t) => drafts.get(t.id) !== saved.get(t.id));
        return !unsaved.length || confirm(`Discard unsaved changes to ${unsaved.map((t) => t.label).join(', ')}?`);
      },
    );

    const dialog = backdrop.querySelector('.ingest-dialog');
    area = dialog.querySelector('.ingest-prompt-text');
    const list = dialog.querySelector('.ingest-templates');
    const hint = dialog.querySelector('.ingest-tab-hint');
    const saveButton = dialog.querySelector('.ingest-save');
    const status = dialog.querySelector('.ingest-save-status');

    // The text being edited on the current tab (the templates tab is a list, not text).
    function keepDraft() {
      if (!tabs.find((t) => t.id === current).list) drafts.set(current, area.value);
    }

    function select(id) {
      keepDraft();
      current = id;
      const tab = tabs.find((t) => t.id === id);
      for (const b of dialog.querySelectorAll('.ingest-tab')) b.classList.toggle('active', b.dataset.tab === id);
      area.hidden = Boolean(tab.list);
      list.hidden = !tab.list;
      area.value = drafts.get(id);
      area.readOnly = Boolean(tab.readOnly);
      saveButton.hidden = Boolean(tab.readOnly || tab.list);
      status.textContent = '';
      if (tab.list) {
        hint.innerHTML = `Pages Claude may follow when it makes a new page: the files in each wiki's <code>Templates/Pages</code> folder. Each run, Claude sees only every template's name and description (from its frontmatter), and opens a template only when it's about to propose a new page that fits.`;
        drawTemplates();
      } else if (id === 'agent') {
        hint.innerHTML = tab.text
          ? 'WikiApp\'s built-in instructions, sent first on every run. Read-only: they come with the app (<code>ingest/agent-prompt.md</code>) and update with it. <code>{{user_notes}}</code> and <code>{{wikis}}</code> mark where your notes and each wiki\'s rules go.'
          : 'The built-in instructions couldn\'t be read (<code>ingest/agent-prompt.md</code> is missing).';
      } else if (id === 'notes') {
        hint.innerHTML = 'Your own instructions, added under "Notes from the user". Kept on this computer, so app updates never replace them.';
      } else {
        hint.innerHTML = `Saved as <code>${esc(tab.alias)}/${RULES_FILE}</code>. Claude follows these when it writes in this wiki.${tab.exists ? '' : ' This wiki has no rules file yet: saving creates one from this starter.'}`;
      }
    }

    // The page templates: one row each (wiki, name, when to use it, file), and a way to add one.
    function drawTemplates() {
      const templates = getPageTemplates();
      const color = (alias) => wikis.find((w) => w.alias === alias)?.color || 'var(--text-faint)';
      const rows = templates.map((t) => `
        <tr>
          <td><span class="wiki-chip" style="--wiki:${esc(color(t.alias))}">${esc(t.alias)}</span></td>
          <td><button class="link-button" data-open-template="${esc(t.id)}" title="Open in the editor">${esc(t.name)}</button></td>
          <td>${t.description ? esc(t.description) : '<span class="field-error">No description: add one to its frontmatter, so Claude knows when to use it.</span>'}</td>
          <td><button class="link-button ingest-template-path" data-open-template="${esc(t.id)}" title="Open in the editor">${esc(t.path)}</button></td>
        </tr>`).join('');
      list.innerHTML = `
        ${templates.length
          ? `<table class="ingest-template-list"><thead><tr><th>Wiki</th><th>Template</th><th>When to use it</th><th>File</th></tr></thead><tbody>${rows}</tbody></table>`
          : '<p class="ingest-empty">No page templates yet. Without one, Claude lays out a new page like the wiki\'s similar pages.</p>'}
        <div class="ingest-template-new">
          <select class="ingest-template-wiki" aria-label="Wiki">${wikis.map((w) => `<option value="${esc(w.alias)}">${esc(w.alias)}</option>`).join('')}</select>
          <input class="ingest-template-name" placeholder="New template's name, for example Planet" spellcheck="false">
          <button class="secondary-button" data-new-template>New page template</button>
        </div>`;
    }

    // Opening a template leaves this window, which asks first if a tab has unsaved changes.
    function leaveFor(open) {
      close();
      if (backdrop.hidden) open();
    }

    list.addEventListener('click', (e) => {
      const opened = e.target.closest('[data-open-template]');
      if (opened) return leaveFor(() => openPageTemplate(opened.dataset.openTemplate));
      if (e.target.closest('[data-new-template]')) {
        const alias = list.querySelector('.ingest-template-wiki').value;
        const name = list.querySelector('.ingest-template-name').value.trim();
        if (!name) return list.querySelector('.ingest-template-name').focus();
        leaveFor(() => newPageTemplate(alias, name));
      }
    });
    list.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target.matches('.ingest-template-name')) list.querySelector('[data-new-template]').click();
    });
    dialog.querySelector('.ingest-tabs').addEventListener('click', (e) => {
      const tab = e.target.closest('[data-tab]');
      if (tab) select(tab.dataset.tab);
    });
    dialog.querySelector('.ingest-lograw').addEventListener('change', (e) => setLogRaw(e.target.checked));
    saveButton.addEventListener('click', async () => {
      const tab = tabs.find((t) => t.id === current);
      const text = area.value.replace(/\r\n/g, '\n');
      saveButton.disabled = true;
      status.textContent = 'Saving…';
      const result = tab.id === 'notes' ? await saveNotes(text) : await saveRules(tab.alias, text, saved.get(tab.id));
      saveButton.disabled = false;
      if (result === true) {
        drafts.set(tab.id, text);
        saved.set(tab.id, text);
        tab.exists = true;
        status.textContent = 'Saved. The next run uses it.';
      } else {
        status.textContent = `Not saved: ${result}`;
      }
    });
    select(current);
  }

  // ---- How Ingest works ---------------------------------------------------------------------

  function openHelp() {
    show(`
      <div class="dialog ingest-dialog ingest-help-dialog" role="dialog" aria-label="How Ingest works">
        <h2 class="dialog-title">How Ingest works</h2>
        <p>Ingest turns finished notes into updates to your wiki pages. Claude reads the notes, works out which pages they belong on, and suggests changes. You decide what is kept: nothing is written until you accept it.</p>
        ${diagram()}
        <h3>What happens when you press Ingest</h3>
        <ol>
          <li>WikiApp builds an <strong>index</strong> of your wikis and gives Claude its instructions, the index and your notes.</li>
          <li>Claude works through the notes in a <strong>loop</strong>: it decides what it needs, reads a page with its <em>Read a page</em> tool, looks at what it found (following links to other pages when needed), and repeats.</li>
          <li>When it knows what should change on a page, it uses its <em>Propose a change</em> tool. Each proposal appears here as a <strong>card</strong>.</li>
          <li>You answer every card: ✓ to write the change, ✗ to drop it, or ↻ to give Claude feedback. Nothing happens until you press <strong>Submit</strong>.</li>
          <li>Submit writes the ✓ changes. Cards with feedback go back to Claude together, and its revisions come back as cards to answer again.</li>
          <li>When every card is handled, the notes are marked as ingested and leave the list.</li>
        </ol>
        <h3>Words you'll see</h3>
        <dl class="ingest-terms">
          <dt>Agent</dt><dd>Claude working on a task in steps on its own: reading, deciding and acting, rather than answering one question.</dd>
          <dt>Agent loop</dt><dd>The agent's routine: think about what it needs, use a tool, look at the result, and go again until the task is done.</dd>
          <dt>Tool</dt><dd>An action the agent is allowed to take. Here it has exactly two: <em>Read a page</em> and <em>Propose a change</em>. It can't write, delete, browse the web or open any other file.</dd>
          <dt>Model</dt><dd>Which Claude does the work, picked next to the Ingest button. The list comes from your Claude Code sign-in. Haiku 5.5, the default, is the cheapest and does this job well; larger models cost more per run.</dd>
          <dt>Claude Agent SDK</dt><dd>The ready-made building block (a "software development kit") that runs the agent loop on your computer. It uses the Claude Code engine and your existing Claude Code sign-in, so there is no separate account or key.</dd>
          <dt>Prompt</dt><dd>The written instructions Claude gets at the start: WikiApp's built-in instructions, your notes and each wiki's rules. Change your notes and the rules with <em>Edit ingestion prompt</em>.</dd>
          <dt>Feedback</dt><dd>A note you write on a card (its ↻ button). On Submit, all the feedback goes to Claude in one message, with which cards you accepted and rejected. It continues the same conversation, so Claude still knows everything it read, and it revises those cards (or explains why not). It counts toward the same run's cost.</dd>
          <dt>Index</dt><dd>A one-line summary of every page (name, description, tags, sections, links), rebuilt each time you press Ingest, so Claude knows what exists without reading every page.</dd>
          <dt>Card</dt><dd>One proposed change to one page, in that wiki's color. A new page shows a preview and lets you pick its folder.</dd>
          <dt>Tokens and cost</dt><dd>Claude reads and writes text in small pieces called tokens, and cost is counted in them. After each run you see what it used, next to an estimate for the same work in a plain Claude Code session, which sends a lot more with every step (all its built-in tools, a long system prompt and its skills list).</dd>
        </dl>
        <div class="dialog-actions"><span class="spacer"></span><button class="primary-button" data-close>Got it</button></div>
      </div>`);
  }

  // ---- A past run: what it read, each request's tokens, and the totals --------------------------

  function openRun(t, when) {
    const n = (x) => (typeof x === 'number' ? x.toLocaleString() : '–');
    const money = (x) => (typeof x === 'number' ? `$${x < 0.01 ? x.toFixed(4) : x.toFixed(3)}` : '–');
    const totals = t.totals || {};
    const tokens = totals.tokens || { input: 0, cacheWrite: 0, cacheRead: 0, output: 0 };
    const sent = tokens.input + tokens.cacheWrite + tokens.cacheRead;
    const context = t.context || {};
    const name = (id) => id.slice(id.indexOf(':') + 1).replace(/\.md$/i, '');

    const upFront = [
      ['System prompt (agent prompt, your notes, wiki rules)', context.systemPrompt],
      ...Object.entries(context.indexes || {}).map(([alias, k]) => [`Index of ${alias}`, k]),
      ...Object.entries(context.notes || {}).map(([id, k]) => [`Note: ${name(id)}`, k]),
    ];

    const toolLine = (c) => {
      if (c.tool === 'read_page') {
        // "→ page" only when the name Claude asked for resolved to something else, or failed.
        const resolved = (c.page || '').replace(/\.md$/i, '');
        const arrow = c.error
          ? ` → <span class="run-error">${esc(c.error)}</span>`
          : resolved && resolved.toLowerCase() !== c.asked.toLowerCase() ? ` → ${esc(resolved)}` : '';
        return `<li>Read <strong>${esc(c.asked)}</strong>${arrow} <span class="run-tokens">≈${n(c.resultTokens)} tokens</span></li>`;
      }
      return `<li>Proposed <strong>${esc(c.target)}</strong>${c.edits ? ` (${plural(c.edits, 'edit')})` : ''}${c.template ? ` from template ${esc(name(c.template))}` : ''}${c.error ? ` → <span class="run-error">${esc(c.error)}</span>` : ''}${c.summary ? `<div class="run-summary">${esc(c.summary)}</div>` : ''}</li>`;
    };
    // A feedback round starts with the user's message, then its requests.
    const rounds = new Map((t.feedback || []).map((f) => [f.firstStep, f]));
    // Rounds from before reviews were submitted together have one card: { card, page, text }.
    const roundRow = (f) => {
      const asked = f.cards || [{ card: f.card, page: f.page, text: f.text, revised: f.revised }];
      const decided = [f.accepted?.length ? `${f.accepted.length} accepted` : '', f.rejected?.length ? `${f.rejected.length} rejected` : ''].filter(Boolean).join(', ');
      return `
      <tr class="run-round"><td></td><td colspan="4"><strong>Feedback round ${f.round}</strong>${decided ? ` <span class="run-muted">(${decided} with it)</span>` : ''}
        ${asked.map((a) => `<div>Card ${esc(a.card)} (${esc(name(a.page || ''))}): “${esc(a.text)}” <span class="run-muted">${a.revised ? 'revised' : 'no new proposal'}</span></div>`).join('')}
        <div class="run-muted">${n(f.requests)} requests · ${money(f.cost)} · ${n(f.tokens?.cacheRead)} tokens read from cache, ${n(f.tokens?.cacheWrite)} newly cached</div></td></tr>`;
    };
    const steps = (t.steps || []).map((s) => `${rounds.has(s.n) ? roundRow(rounds.get(s.n)) : ''}
      <tr>
        <td class="run-n">${s.n}</td>
        <td>${s.tools.length ? `<ul class="run-tools">${s.tools.map(toolLine).join('')}</ul>` : ''}${s.text.map((x) => `<p class="run-text">${esc(x)}</p>`).join('')}${!s.tools.length && !s.text.length ? '<span class="run-muted">(thinking only)</span>' : ''}</td>
        <td class="run-num">${s.tokens ? n(s.tokens.input + s.tokens.cacheWrite + s.tokens.cacheRead) : '–'}<div class="run-muted">${s.tokens ? `${n(s.tokens.cacheRead)} cached` : ''}</div></td>
        <td class="run-num">${s.tokens ? n(s.tokens.output) : '–'}</td>
        <td class="run-num">${money(s.cost)}</td>
      </tr>`).join('');

    show(`
      <div class="dialog ingest-dialog ingest-run-dialog" role="dialog" aria-label="Ingest run">
        <h2 class="dialog-title">Run of ${esc(when)} <span class="run-status ${t.ok ? 'ok' : 'failed'}">${t.ok ? 'finished' : 'stopped'}</span></h2>
        ${t.message ? `<p class="run-error">${esc(t.message)}</p>` : ''}
        <div class="run-totals">
          <div><span title="${esc(API_PRICE_HINT)}">API-price cost ⓘ</span><strong>${money(totals.cost)}</strong><em title="${esc(PLAIN_TOOLTIP)}">plain Claude Code ≈ ${money(totals.plainClaudeCode?.cost)} ⓘ</em></div>
          <div><span>Tokens sent</span><strong>${n(sent)}</strong><em>${n(tokens.cacheRead)} from cache · ${n(tokens.cacheWrite)} cached · ${n(tokens.input)} plain</em></div>
          <div><span>Tokens written</span><strong>${n(tokens.output)}</strong><em>including thinking</em></div>
          <div><span>Requests</span><strong>${n(totals.requests)}</strong><em>${n(totals.reads)} page reads · ${plural(t.cards?.length || 0, 'card')}${t.feedback?.length ? ` · ${plural(t.feedback.length, 'feedback round')}` : ''}${totals.durationSeconds ? ` · ${totals.durationSeconds} s` : ''}</em></div>
        </div>
        <p class="field-hint">Model <code>${esc(t.model || 'unknown')}</code> · ${plural(t.notes.length, 'note')}: ${esc(t.notes.map(name).join(', '))}</p>

        <h3>Sent up front <span class="run-muted">(approximate)</span></h3>
        <table class="run-table run-upfront">${upFront.map(([label, k]) => `<tr><td>${esc(label)}</td><td class="run-num">≈${n(k)}</td></tr>`).join('')}</table>

        <h3>Step by step</h3>
        <p class="field-hint">Each row is one request to Claude: what it did, the tokens it sent (most come back from the cache, which is cheap) and wrote, and its cost at list prices. Tool results are sent with the next request.</p>
        <table class="run-table run-steps">
          <thead><tr><th>#</th><th>What it did</th><th>Sent</th><th>Wrote</th><th>≈ Cost</th></tr></thead>
          <tbody>${steps || '<tr><td colspan="5" class="run-muted">No requests were made.</td></tr>'}</tbody>
        </table>

        ${t.cards?.length ? `<h3>Cards</h3><ul class="run-cards">${t.cards.map((c) => `<li><span class="wiki-chip" style="--wiki:var(--text-muted)">${esc(c.wiki)}</span> <strong>${esc(c.title)}</strong> <span class="ingest-kind ${esc(c.kind)}">${c.kind === 'new' ? 'NEW' : 'EDIT'}</span> ${esc(c.summary)}</li>`).join('')}</ul>` : ''}

        <div class="dialog-actions">
          <button class="link-button" data-folder>Open run folder</button>
          <span class="spacer"></span>
          <button class="primary-button" data-close>Close</button>
        </div>
      </div>`);
    backdrop.querySelector('[data-folder]').addEventListener('click', () => openRunFolder(t.runId));
  }

  return { openPrompt, openHelp, openRun };
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const API_PRICE_HINT =
  'What these tokens would cost at Claude API list prices. On a Claude subscription a run is not billed per token: it counts toward your plan\'s usage.';
const PLAIN_TOOLTIP =
  'Estimate of the same run in a plain Claude Code session, which also sends about 35,000 tokens with every request ' +
  '(built-in tools, system prompt, CLAUDE.md and memory, skills and MCP lists). See ingest/AGENT.md.';

// The agent, its loop and its two tools, between your notes and your pages.
function diagram() {
  return `
    <svg class="ingest-diagram" viewBox="0 0 760 300" role="img" aria-label="Your notes go to Claude, which loops using two tools: read a page, and propose a change. Proposals become cards; accepting one writes it to your wiki.">
      <defs>
        <marker id="ingest-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 10 5 0 10z" class="d-arrowhead"/>
        </marker>
      </defs>
      <rect x="196" y="14" width="378" height="266" rx="14" class="d-zone"/>
      <text x="385" y="270" class="d-zone-label">Runs on your computer with the Claude Agent SDK</text>

      <rect x="10" y="100" width="150" height="100" rx="10" class="d-box"/>
      <text x="85" y="124" class="d-title">What Claude gets</text>
      <text x="85" y="148" class="d-text">Instructions</text>
      <text x="85" y="168" class="d-text">Index of pages</text>
      <text x="85" y="188" class="d-text">Your notes</text>
      <path d="M160 150H222" class="d-line" marker-end="url(#ingest-arrow)"/>

      <path d="M246 104C252 40 330 40 336 104" class="d-loop" marker-end="url(#ingest-arrow)"/>
      <text x="291" y="40" class="d-small">think · use a tool · check · repeat</text>
      <circle cx="291" cy="150" r="62" class="d-agent"/>
      <text x="291" y="146" class="d-agent-title">Claude</text>
      <text x="291" y="166" class="d-agent-text">the agent</text>

      <path d="M350 126 408 92" class="d-line" marker-end="url(#ingest-arrow)"/>
      <path d="M350 174 408 208" class="d-line" marker-end="url(#ingest-arrow)"/>
      <rect x="410" y="60" width="150" height="56" rx="10" class="d-tool"/>
      <text x="485" y="84" class="d-title">Tool 1</text>
      <text x="485" y="104" class="d-text">Read a page</text>
      <rect x="410" y="184" width="150" height="56" rx="10" class="d-tool"/>
      <text x="485" y="208" class="d-title">Tool 2</text>
      <text x="485" y="228" class="d-text">Propose a change</text>

      <rect x="600" y="50" width="150" height="76" rx="10" class="d-box"/>
      <text x="675" y="80" class="d-title">Your wiki pages</text>
      <text x="675" y="102" class="d-text">read, never written</text>
      <path d="M600 88H562" class="d-line" marker-end="url(#ingest-arrow)"/>

      <rect x="600" y="174" width="150" height="76" rx="10" class="d-box d-cards"/>
      <text x="675" y="204" class="d-title">Cards</text>
      <text x="675" y="226" class="d-text">✓, ✗ or ↻, then Submit</text>
      <path d="M560 212H598" class="d-line" marker-end="url(#ingest-arrow)"/>
      <path d="M675 174V128" class="d-accept" marker-end="url(#ingest-arrow)"/>
      <text x="684" y="156" class="d-small d-left">✓ writes it</text>
    </svg>`;
}
