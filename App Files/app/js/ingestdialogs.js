// The Ingest view's windows:
//   Agents and rules: an Agents tab listing the three agents (executive assistant, wiki reviewer,
//     team wiki manager) with a way to see and edit each one's prompt, the page templates (a list: each
//     wiki's Templates/Pages files), and the rules files: "My capture rules" and the Team wiki's.
//   How Ingest works (the ? button): plain-language explanation with a picture of the agent loop.
//   A past run (from Past runs): its transcript.json, request by request, with tokens and cost.


const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

export function createIngestDialogs(backdrop, {
  getAgents, saveAgent, resetAgent, getWikis, getRulesTabs, saveRules, getPageTemplates, openPageTemplate, newPageTemplate, getLogRaw, setLogRaw, openRunFolder,
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

  // ---- Agents and rules ------------------------------------------------------------------------

  async function openPrompt(startTab = 'agents') {
    const wikis = await getWikis(); // [{ alias, color }]
    // The rules files: [{ key, label, name, path, color, text (or null when missing), starter, about }].
    const rulesTabs = await getRulesTabs();
    // The three agents and their prompts: [{ id, name, tab, job, path, text, default, changed }].
    let agents = [];
    let agentsError = '';
    try {
      agents = await getAgents();
    } catch (err) {
      agentsError = err.message;
    }
    const tabs = [
      { id: 'agents', label: 'Agents', list: true },
      { id: 'templates', label: 'Page templates', list: true },
      ...rulesTabs.map((w) => ({ id: `rules:${w.key}`, label: w.label, ruleName: w.name, about: w.about, path: w.path, color: w.color, exists: w.text !== null, text: w.text ?? w.starter })),
    ];
    // What's being edited, by key: a rules tab's id, or "agent:<id>" for an agent's prompt.
    const drafts = new Map([...tabs.filter((t) => !t.list).map((t) => [t.id, t.text]), ...agents.map((a) => [`agent:${a.id}`, a.text])]);
    const saved = new Map(drafts); // what's on disk (or the starter text)
    const labels = new Map([...tabs.map((t) => [t.id, t.label]), ...agents.map((a) => [`agent:${a.id}`, `${a.name}'s prompt`])]);
    let current = tabs.find((t) => t.id === startTab) ? startTab : 'agents';
    let openAgent = null; // the agent whose prompt is shown, on the Agents tab

    show(
      `<div class="dialog ingest-dialog" role="dialog" aria-label="Agents and rules">
        <h2 class="dialog-title">Agents and rules</h2>
        <p class="field-hint">Three agents do the Ingest view's work. The rules are the main way to steer them: <strong>My capture rules</strong> steer capture and Review in your Personal wiki, and the <strong>Team wiki's rules</strong> steer Promotion. A View only wiki's rules are not used. The agents' own prompts are built in; most people never change them.</p>
        <div class="ingest-tabs" role="tablist">
          ${tabs.map((t) => `<button class="ingest-tab" role="tab" data-tab="${esc(t.id)}" ${t.color ? `style="--wiki:${esc(t.color)}"` : ''}>${esc(t.label)}</button>`).join('')}
        </div>
        <p class="field-hint ingest-tab-hint"></p>
        <textarea class="ingest-prompt-text" spellcheck="false"></textarea>
        <div class="ingest-templates" hidden></div>
        <label class="ingest-check"><input type="checkbox" class="ingest-lograw" ${getLogRaw() ? 'checked' : ''}> Also save each Notes and Promotion run's raw requests in its run folder, to check exactly what was sent</label>
        <div class="dialog-actions">
          <span class="ingest-save-status"></span>
          <span class="spacer"></span>
          <button class="secondary-button ingest-reset" hidden title="Delete your copy of this prompt and use the built-in one again">Back to built-in</button>
          <button class="secondary-button" data-close>Close</button>
          <button class="primary-button ingest-save">Save</button>
        </div>
      </div>`,
      () => {
        keepDraft();
        const unsaved = [...drafts.keys()].filter((k) => drafts.get(k) !== saved.get(k));
        return !unsaved.length || confirm(`Discard unsaved changes to ${unsaved.map((k) => labels.get(k)).join(', ')}?`);
      },
    );

    const dialog = backdrop.querySelector('.ingest-dialog');
    const area = dialog.querySelector('.ingest-prompt-text');
    const list = dialog.querySelector('.ingest-templates');
    const hint = dialog.querySelector('.ingest-tab-hint');
    const saveButton = dialog.querySelector('.ingest-save');
    const resetButton = dialog.querySelector('.ingest-reset');
    const status = dialog.querySelector('.ingest-save-status');

    // The key of the text in the box right now, or null when a list is showing instead.
    const editing = () => (current === 'agents' ? (openAgent ? `agent:${openAgent}` : null) : tabs.find((t) => t.id === current).list ? null : current);

    function keepDraft() {
      const key = editing();
      if (key) drafts.set(key, area.value);
    }

    function select(id, agentId = null) {
      keepDraft();
      current = id;
      openAgent = id === 'agents' ? agentId : null;
      const tab = tabs.find((t) => t.id === id);
      const key = editing();
      for (const b of dialog.querySelectorAll('.ingest-tab')) b.classList.toggle('active', b.dataset.tab === id);
      area.hidden = !key;
      list.hidden = Boolean(key);
      saveButton.hidden = !key;
      resetButton.hidden = !openAgent || agents.find((a) => a.id === openAgent)?.status === 'built_in';
      status.textContent = '';
      if (key) area.value = drafts.get(key);
      if (id === 'agents' && openAgent) {
        const agent = agents.find((a) => a.id === openAgent);
        hint.innerHTML = `<button class="link-button ingest-back" data-back>← All agents</button> <strong>${esc(agent.name)}</strong> · the ${esc(agent.tab)} tab. ${agent.status === 'built_in' ? 'This is the <strong>built-in</strong> prompt; saving makes your own copy.' : 'This is your own copy of the prompt.'} Most people never need to change it: wiki rules do the same job. WikiApp sends everything below the top block (the lines between the two <code>---</code>), then adds the material to work on and the rules of the wikis involved.`;
      } else if (id === 'agents') {
        hint.innerHTML = 'Each agent\'s prompt is built in and improves with app updates. Most people never need to change one: wiki rules (in Settings) are the main way. If you do, saving makes your own copy, which app updates never replace.';
        drawAgents();
      } else if (tab.list) {
        hint.innerHTML = `Pages the team wiki manager may follow when it makes a new page: the files in each wiki's <code>Templates/Pages</code> folder. An agent sees only every template's name and description (from its frontmatter), and opens a template only when it's about to propose a new page that fits.`;
        drawTemplates();
      } else {
        hint.innerHTML = `${esc(tab.about)} Saved as <code>${esc(tab.path || '(no path set)')}</code>.${tab.exists ? '' : ' There is no file yet: saving creates one from this starter.'}`;
      }
    }

    // The three agents: who does which tab's work, and a way to see each one's prompt.
    function drawAgents() {
      if (agentsError) {
        list.innerHTML = `<p class="field-error">The agents' prompt files couldn't be read: ${esc(agentsError)}</p>`;
        return;
      }
      const rows = agents.map((a) => `
        <tr>
          <td><strong>${esc(a.name)}</strong></td>
          <td><span class="ingest-kind">${esc(a.tab.toUpperCase())}</span></td>
          <td>${esc(a.job)}${a.status === 'built_in' ? ' <span class="session-faint">Built in.</span>' : String(a.status || '').startsWith('customised') ? ' <span class="session-faint">Customised.</span>' : drafts.get(`agent:${a.id}`) !== a.default ? ' <span class="session-faint">Edited.</span>' : ''}</td>
          <td><button class="secondary-button" data-agent="${esc(a.id)}" title="${esc(a.path)}">See the prompt</button></td>
        </tr>`).join('');
      list.innerHTML = `<table class="ingest-template-list ingest-agent-list"><thead><tr><th>Agent</th><th>Tab</th><th>What it does</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
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

    // Opening a template leaves this window, which asks first if anything is unsaved.
    function leaveFor(open) {
      close();
      if (backdrop.hidden) open();
    }

    list.addEventListener('click', (e) => {
      const agent = e.target.closest('[data-agent]');
      if (agent) return select('agents', agent.dataset.agent);
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
    hint.addEventListener('click', (e) => {
      if (e.target.closest('[data-back]')) select('agents');
    });
    dialog.querySelector('.ingest-tabs').addEventListener('click', (e) => {
      const tab = e.target.closest('[data-tab]');
      if (tab) select(tab.dataset.tab);
    });
    dialog.querySelector('.ingest-lograw').addEventListener('change', (e) => setLogRaw(e.target.checked));
    // Deletes the person's copy (resetPrompt), after asking, and shows the built-in prompt again.
    resetButton.addEventListener('click', async () => {
      const agent = agents.find((a) => a.id === openAgent);
      if (!agent || !confirm(`Go back to the built-in "${agent.name}" prompt? Your copy of it is deleted.`)) return;
      const result = await resetAgent(agent.slot);
      if (result !== true) {
        status.textContent = `Not reset: ${result}`;
        return;
      }
      try {
        const fresh = (await getAgents()).find((a) => a.id === agent.id);
        if (fresh) Object.assign(agent, fresh);
      } catch { /* the old text stays until the window is reopened */ }
      drafts.set(`agent:${agent.id}`, agent.text);
      saved.set(`agent:${agent.id}`, agent.text);
      select('agents', agent.id);
      status.textContent = 'Back to the built-in prompt.';
    });
    saveButton.addEventListener('click', async () => {
      const key = editing();
      const tab = tabs.find((t) => t.id === current);
      const text = area.value.replace(/\r\n/g, '\n');
      saveButton.disabled = true;
      status.textContent = 'Saving…';
      const result = openAgent ? await saveAgent(openAgent, text) : await saveRules(tab.ruleName, text, saved.get(key));
      saveButton.disabled = false;
      if (result === true) {
        drafts.set(key, text);
        saved.set(key, text);
        if (!openAgent) tab.exists = true;
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
        <p>The Ingest view has four tabs. Three of them (Notes, Sessions and Review) write straight into your <strong>personal wiki</strong>, with nothing to approve. Promotion is the one place you accept changes one by one: it proposes changes to a shared wiki.</p>
        <h3>Notes and Sessions: capture</h3>
        <ol>
          <li>Notes lists your wrapped notes that are new, or that you edited after they were captured. Sessions lists your recent Claude Code sessions.</li>
          <li>Press <strong>Capture</strong> (or Ingest). Claude reads the note or session and writes a short record of what was decided and found, filed under a topic page in your personal wiki. A tag it has to invent is added to your personal tags.</li>
          <li>It is written straight away, and only ever into your personal wiki. A note or session that hasn't changed since its capture is never sent again.</li>
        </ol>
        <h3>Review</h3>
        <p>When enough new sessions or notes have landed on a topic, the wiki reviewer rewrites the page's summary of where the work stands and its Related section. When a note and a session disagree, the conflict is held here for you: <strong>Keep note</strong>, <strong>Accept session</strong> (the topic page takes the session's version), or <strong>Dismiss</strong>.</p>
        <h3>Promotion: cards you accept</h3>
        <ol>
          <li>WikiApp builds an <strong>index</strong> of your wikis and gives Claude its instructions, the index and the pages you chose.</li>
          <li>Claude works through them in a <strong>loop</strong>: it decides what it needs, reads a page with its <em>Read a page</em> tool, looks at what it found, and repeats.</li>
          <li>When it knows what should change on a team wiki page, it uses its <em>Propose a change</em> tool. Each proposal appears here as a <strong>card</strong>.</li>
          <li>You answer every card: ✓ to write the change, ✗ to drop it, or ↻ to give Claude feedback. Nothing happens until you press <strong>Submit</strong>.</li>
          <li>Submit writes the ✓ changes. Cards with feedback go back to Claude together, and its revisions come back as cards to answer again.</li>
          <li>When every card is handled, the promoted pages are marked and leave the list.</li>
        </ol>
        ${diagram()}
        <h3>Words you'll see</h3>
        <dl class="ingest-terms">
          <dt>Agent</dt><dd>Claude working on a task in steps on its own: reading, deciding and acting, rather than answering one question.</dd>
          <dt>Agent loop</dt><dd>The agent's routine: think about what it needs, use a tool, look at the result, and go again until the task is done.</dd>
          <dt>Tool</dt><dd>An action the agent is allowed to take. Here it has exactly two: <em>Read a page</em> and <em>Propose a change</em>. It can't write, delete, browse the web or open any other file.</dd>
          <dt>Model</dt><dd>Which Claude does the work, picked next to each tab's button, and also in Settings (they are the same setting). The list comes from your Claude Code sign-in. Larger models cost more per run.</dd>
          <dt>Claude Agent SDK</dt><dd>The ready-made building block (a "software development kit") that runs the agent loop on your computer. It uses the Claude Code engine and your existing Claude Code sign-in, so there is no separate account or key.</dd>
          <dt>Prompt</dt><dd>The written instructions Claude gets at the start: the agent's own prompt and the rules that apply (your capture rules, or the Team wiki's). See and change them with <em>Agents and rules</em>, above the tabs.</dd>
          <dt>Feedback</dt><dd>A note you write on a card (its ↻ button). On Submit, all the feedback goes to Claude in one message, with which cards you accepted and rejected. It continues the same conversation, so Claude still knows everything it read, and it revises those cards (or explains why not). It counts toward the same run's cost.</dd>
          <dt>Index</dt><dd>A one-line summary of every page (name, description, tags, sections, links), rebuilt each time you press Promote, so Claude knows what exists without reading every page.</dd>
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
      ['System prompt (the agent\'s prompt and the rules)', context.systemPrompt],
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
    <svg class="ingest-diagram" viewBox="0 0 760 300" role="img" aria-label="Your chosen pages go to Claude, which loops using two tools: read a page, and propose a change. Proposals become cards; accepting one writes it to your wiki.">
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
      <text x="85" y="188" class="d-text">Chosen pages</text>
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
      <text x="675" y="80" class="d-title">Team wiki pages</text>
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
