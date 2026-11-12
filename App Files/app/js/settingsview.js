// The Settings screen (the gear at the bottom of the rail): every row of the host's path list
// (listPaths), grouped, plus the AI engine. Opening it only reads; a missing path shows as
// missing and is never made again. Each row has what it allows:
//   Open     the app's markdown editor when the file is in a connected wiki, else the system default
//            (openPath), for files and folders alike
//   Change   point the entry somewhere else (setPath); Browse picks a folder (pickFolder) or a file (pickFile)
//   Reset to default      a prompt or template goes back to the text WikiApp ships (resetPrompt)
//   Back to default location / Clear   when the entry was pointed elsewhere (setPath with "")
// A row's `state` says whether it's there: ok, missing (the only error), not_created (made on first use) or unset.
// The app folder row asks move-or-adopt (relocateFolder). The AI engine section renders the
// engine settings from their shape, so a new engine's fields need no change here.

import { call, on } from './bridge.js';
import { insideWiki, wikiWarning } from './setup.js';
import { refreshAi, aiState, onAiChange } from './ai.js';
import { syncEngineModels } from './modelmenu.js';
import { ROLE_LABEL, ROLE_HELP, roleOf, roleBadge, setRole, onRolesChange } from './roles.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const STATUS = {
  built_in: ['Built in', 'No copy exists: the app\'s own version is in use, and it improves with app updates.'],
  default: ['Default', 'An unedited copy of the text WikiApp ships; it follows newer defaults by itself.'],
  customised: ['Customised', 'You have edited it.'],
  customised_newer_default: ['Customised, newer built-in available', 'You have edited it, and WikiApp now ships a different built-in. Go back to built-in to take the new one (your copy is deleted).'],
};
const isPrompt = (r) => r.name.startsWith('prompt.');
const PROGRESS_ROWS = ['progress', 'run_history', 'indexes', 'pending_notes', 'pending_promotion'];

export function createSettingsView(container, deps) {
  const { getFolders, openInEditor, onChanged, toast } = deps;
  const dialog = document.getElementById('settings-dialog');
  let rows = [];
  let first = null;     // firstRunState: from_env, location...
  let engine = null;    // getEngineSettings
  let engineDraft = null;
  let agentlib = null;
  let connection = null; // connectionStatus: how the engine is set up
  let testing = false;
  let testResult = null;
  let error = '';
  let installing = false;
  let installMessage = '';
  let advancedOpen = false;

  container.addEventListener('click', onClick);
  container.addEventListener('toggle', (e) => {
    if (e.target.matches?.('.settings-advanced')) advancedOpen = e.target.open;
  }, true);
  container.addEventListener('change', onChange_);
  on('agentlibInstalled', async (result) => {
    installing = false;
    installMessage = result?.message || '';
    await refreshAi();
    await load();
  });
  onAiChange(() => draw());
  onRolesChange(() => { if (rows.length) load(); });

  async function load() {
    try {
      [rows, first, engine, agentlib, connection] = await Promise.all([
        call('listPaths'), call('firstRunState'), call('getEngineSettings'), call('agentlibStatus'),
        call('connectionStatus').catch(() => null),
      ]);
      engineDraft = JSON.parse(JSON.stringify(engine));
      error = '';
    } catch (err) {
      error = err.message;
    }
    draw();
  }

  const byName = (name) => rows.find((r) => r.name === name);
  const wikiGroups = () => [...new Set(rows.filter((r) => r.group.startsWith('Wiki: ')).map((r) => r.group))];
  let used = new Set();

  // ---- Drawing ----------------------------------------------------------------------------

  function draw() {
    const scroll = container.scrollTop;
    used = new Set();
    if (error) {
      container.innerHTML = `<div class="settings"><h1>Settings</h1><p class="field-error">${esc(error)}</p><button class="secondary-button" data-act="reload">Try again</button></div>`;
      return;
    }
    const take = (names) => names.map(byName).filter(Boolean);
    const appRows = take(['app_folder', 'pointer_file', 'path_list']);
    // A wiki's rules steer Promotion, so only the Team wiki's rules row is offered: none for a Personal or View only wiki.
    const allRules = rows.filter((r) => /^wiki\..+\.rules$/.test(r.name));
    const ruleRows = allRules.filter((r) => (r.role || roleOf(r.name.slice(5, -6))) === 'team');
    const capture = take(['personal_capture_rules']);
    const templates = rows.filter((r) => r.name.startsWith('template.'));
    const advanced = rows.filter((r) => isPrompt(r) || (r.tier === 'advanced' && !r.name.startsWith('template.')));
    const wikis = wikiGroups().map((g) => [g, rows.filter((r) => r.group === g && !/^wiki\..+\.rules$/.test(r.name))]).filter(([, r]) => r.length);
    const notes = take(['notes_folder']);
    const progress = take(PROGRESS_ROWS);
    const transcripts = take(['transcripts', 'sessions_config']);
    const lib = take(['agentlib']);
    const claimed = new Set([...appRows, ...allRules, ...capture, ...templates, ...advanced, ...notes, ...progress, ...transcripts, ...lib, ...wikis.flatMap(([, r]) => r)].map((r) => r.name));
    const other = rows.filter((r) => !claimed.has(r.name));

    container.innerHTML = `
      <div class="settings">
        <h1>Settings</h1>
        <p class="field-hint">A path that is missing is shown as missing; nothing is made again just because you looked.</p>
        <section class="settings-group"><h2>Rules</h2>
          <p class="field-hint">These are the main way to change how the agents behave: your own capture rules (for your Personal wiki), and the Team wiki's rules (which steer Promotion).</p>
          ${ruleRows.map((r) => row(r)).join('')}
          ${capture.map((r) => row(r, 'Your own rules for what gets captured into your personal wiki: what to pick out of a session or note, and what earns its own page.')).join('')}
        </section>
        ${wikisSection()}
        ${section('Note templates', 'The Daily and Weekly notes the New note menu makes. A wiki\'s own Templates folder takes precedence.', templates)}
        ${section('Notes folder', 'The folder inside each wiki that holds quick notes. One setting for every wiki.', notes)}
        ${wikis.map(([g, r]) => section(`${g.replace('Wiki: ', '')} wiki · ${ROLE_LABEL[roleOf(g.replace('Wiki: ', ''))]}`, 'Connected wiki: its templates, index and progress.', r)).join('')}
        ${section('WikiApp\'s private folder', 'Everything private to you lives in this folder. Change location asks whether to move it or adopt another.', appRows)}
        ${section('Progress and run history', 'What past runs and captures left behind, and what is waiting for review.', progress)}
        ${other.length ? section('Other app data', 'Settings, window position and engine settings.', other) : ''}
        ${section('Claude Code transcripts', 'Where Claude Code keeps session transcripts (read for the Sessions tab).', transcripts)}
        ${engineSection(lib)}
        ${advanced.length ? `<details class="settings-group settings-advanced" ${advancedOpen ? 'open' : ''}><summary><h2>Advanced</h2></summary>
          <p class="field-hint">The agents' own prompts. Most people never need to change these: use the rules above instead. Each one is built in; customising makes a copy you can edit, and going back to built-in deletes your copy.</p>
          ${advanced.map((r) => row(r)).join('')}</details>` : ''}
      </div>`;
    container.scrollTop = scroll;
  }

  function section(title, hint, list) {
    if (!list.length) return '';
    return `<section class="settings-group"><h2>${esc(title)}</h2><p class="field-hint">${esc(hint)}</p>${list.map((r) => row(r)).join('')}</section>`;
  }

  // Every connected wiki with its role (Personal, Team or View only). One of each at most: choosing a second
  // Personal or Team makes the wiki that had it View only, and the host says which.
  function wikisSection() {
    const folders = getFolders();
    return `<section class="settings-group"><h2>Wikis and their roles</h2>
      <p class="field-hint">${esc(ROLE_HELP)}</p>
      ${folders.length ? folders.map((f) => `<div class="settings-row"><div class="settings-row-main"><span class="settings-label">${esc(f.alias)}</span>${roleBadge(f.alias)}</div>
        <div class="settings-path" title="${esc(f.root)}">${esc(f.root)}</div>
        <label class="settings-inline">Role <select data-act="role" data-alias="${esc(f.alias)}">${['personal', 'team', 'view'].map((r) => `<option value="${r}" ${roleOf(f.alias) === r ? 'selected' : ''}>${ROLE_LABEL[r]}</option>`).join('')}</select></label>
        ${roleOf(f.alias) === 'view' ? '<p class="field-hint">View only: to give this wiki a role, choose Personal or Team above.</p>' : ''}</div>`).join('') : '<p class="ingest-empty">No wiki is connected yet. Add a folder from the sidebar.</p>'}
    </section>`;
  }

  // How a row's path stands: ok | missing | not_created | unset. Only `missing` is an error.
  const stateOf = (r) => r.state || (r.exists ? 'ok' : r.path ? 'missing' : 'unset');
  const STATE_TEXT = {
    ok: ['exists', 'It is there'],
    missing: ['missing', 'Not found at this path. Restore it, or point this entry somewhere else.'],
    not_created: ['created on first use', 'Nothing has needed it yet; WikiApp makes it when it first does.'],
    unset: ['not set', 'No path is set for this entry.'],
  };

  function row(r, note = '') {
    used.add(r.name);
    const [statusLabel, statusTip] = STATUS[r.status] || [];
    const state = stateOf(r);
    const [stateLabel, stateTip] = STATE_TEXT[state] || STATE_TEXT.ok;
    const isApp = r.name === 'app_folder';
    const builtIn = r.status === 'built_in';
    const canOpen = !builtIn && r.exists && r.path && r.kind !== 'relative_folder';
    const buttons = [
      r.kind !== 'relative_folder' ? `<button class="secondary-button" data-act="open" data-name="${esc(r.name)}" ${canOpen ? '' : 'disabled'} title="${canOpen ? 'Open it' : 'Nothing to open yet'}">Open</button>` : '',
      isApp ? `<button class="secondary-button" data-act="relocate" ${first?.from_env ? 'disabled' : ''} title="${first?.from_env ? 'WIKIAPP_DATA_DIR decides where this folder is' : 'Move it, or adopt a folder that is already somewhere else'}">Change location…</button>`
        : r.can_change ? `<button class="secondary-button" data-act="change" data-name="${esc(r.name)}">Change…</button>` : '',
      builtIn || r.can_customise ? `<button class="secondary-button" data-act="customise" data-name="${esc(r.name)}" title="Make a copy of the built-in prompt that you can edit">Customise</button>` : '',
      r.can_reset && isPrompt(r) ? `<button class="secondary-button" data-act="reset" data-name="${esc(r.name)}" title="Delete your copy and use the built-in prompt again">Back to built-in</button>`
        : r.can_reset ? `<button class="secondary-button" data-act="reset" data-name="${esc(r.name)}" title="Put back the text WikiApp ships. Your edits are replaced.">Reset to default</button>` : '',
      r.can_clear && r.overridden ? `<button class="secondary-button" data-act="default" data-name="${esc(r.name)}" title="Forget the path set here">Clear</button>`
        : r.overridden ? `<button class="secondary-button" data-act="default" data-name="${esc(r.name)}" title="${esc(r.default || 'The default place')}">Back to default location</button>` : '',
      r.path && r.kind !== 'relative_folder' ? `<button class="link-button" data-act="copy" data-name="${esc(r.name)}" title="Copy the path">Copy path</button>` : '',
    ].join('');
    return `<div class="settings-row${state === 'missing' ? ' missing' : ''}" data-name="${esc(r.name)}">
      <div class="settings-row-main">
        <span class="settings-label">${esc(r.label)}</span>
        ${builtIn ? '' : `<span class="settings-state ${state === 'ok' ? 'ok' : state === 'missing' ? 'bad' : 'neutral'}" title="${esc(stateTip)}">${esc(stateLabel)}</span>`}
        ${statusLabel ? `<span class="ingest-kind ${r.status === 'customised_newer_default' ? 'new' : ''}" title="${esc(statusTip)}">${esc(statusLabel.toUpperCase())}</span>` : ''}
        ${r.overridden && !r.can_clear ? '<span class="ingest-kind" title="Pointed away from its default place">MOVED</span>' : ''}
      </div>
      <div class="settings-path" title="${esc(r.path)}">${esc(builtIn ? 'The app\'s own version is in use.' : r.path || '(not set)')}</div>
      ${note ? `<p class="field-hint">${esc(note)}</p>` : ''}
      <div class="settings-buttons">${buttons}</div>
    </div>`;
  }

  // ---- AI engine ---------------------------------------------------------------------------

  function engineSection(lib) {
    const ai = aiState();
    const a = agentlib || {};
    const current = engineDraft?.engine;
    const fields = engineDraft?.engines?.[current] || {};
    return `<section class="settings-group"><h2>AI engine</h2>
      <p class="field-hint">Which AI engine does the work for Ingest, Sessions, Review and Promotion.</p>
      <label class="settings-inline">Engine
        <select data-act="engine">${(engineDraft?.available || []).map((e) => `<option value="${esc(e.id)}" ${e.id === current ? 'selected' : ''}>${esc(e.label)}</option>`).join('')}</select></label>
      <div class="engine-fields">${renderFields(fields, [])}</div>
      <div class="settings-buttons"><button class="primary-button" style="margin:0" data-act="save-engine">Save engine settings</button><span class="settings-engine-status"></span></div>
      <h3>Connection</h3>
      ${connectionHtml()}
      <h3>Library</h3>
      <p class="settings-libstate"><span class="settings-state ${ai.installed ? 'ok' : 'bad'}">${ai.installed ? 'installed' : 'not installed'}</span> ${installing ? 'Installing… this takes a minute.' : ''}</p>
      ${!ai.installed && (a.message || ai.message) && ![connection?.summary, ...(connection?.problems || [])].includes(a.message || ai.message) ? `<p class="field-error">${esc(a.message || ai.message)}</p>` : ''}
      ${installMessage ? `<p class="field-hint">${esc(installMessage)}</p>` : ''}
      ${a.found?.length > 1 ? `<p class="field-hint">Found more than one: ${a.found.map(esc).join('; ')}</p>` : ''}
      ${lib.map((r) => row(r)).join('')}
      <div class="settings-buttons"><button class="secondary-button" data-act="install" ${installing || !a.path || ai.installed ? 'disabled' : ''} title="${ai.installed ? 'The library is already installed' : 'Install the library from the folder above into the app'}">${installing ? 'Installing…' : 'Install the library'}</button></div>
    </section>`;
  }

  // How the engine is set up (connectionStatus), and a button that proves it with one real, tiny request.
  function connectionHtml() {
    const c = connection;
    const lines = [];
    if (!c) lines.push('<p class="session-faint">The connection status could not be read.</p>');
    else {
      const clean = (t) => String(t ?? '').replace(/`/g, '').trim();
      const summary = clean(c.summary);
      const method = clean(c.method);
      const showMethod = method && !summary.toLowerCase().includes(method.toLowerCase());
      lines.push(`<p><span class="settings-state ${c.ok ? 'ok' : 'bad'}">${c.ok ? 'set up' : 'not set up'}</span> ${esc(summary)}${showMethod ? ` <span class="session-faint">(${esc(method)})</span>` : ''}</p>`);
      for (const p of c.problems || []) lines.push(`<p class="field-error">${esc(clean(p))}</p>`);
      // Developer-facing notes (function names, environment variables) stay out of sight until asked for.
      if ((c.notes || []).length) lines.push(`<details class="settings-notes"><summary class="session-faint">Details</summary>${c.notes.map((n) => `<p class="field-hint">${esc(clean(n))}</p>`).join('')}</details>`);
      if (!c.ok && (c.setup_doc || c.setup_file)) lines.push(`<p class="field-hint">Setup guide: <code>${esc(c.setup_doc || c.setup_file)}</code>${c.setup_file && c.setup_doc ? `<br>Settings file: <code>${esc(c.setup_file)}</code>` : ''}</p>`);
      else if (c.setup_file) lines.push(`<p class="field-hint">Settings file: <code>${esc(c.setup_file)}</code></p>`);
    }
    const t = testResult;
    const result = t ? (t.ok
      ? `<p><span class="settings-state ok">works</span> ${esc(t.model || '')}${typeof t.cost_usd === 'number' ? ` · cost about $${t.cost_usd.toFixed(4)}` : ''}</p>`
      : `<p class="field-error">The test failed: ${esc(t.error || 'unknown error')}</p>${t.fix ? `<p class="field-hint">${esc(t.fix)}</p>` : ''}`)
      + (t.report ? `<details><summary class="session-faint">Report</summary><pre class="settings-report">${esc(typeof t.report === 'string' ? t.report : JSON.stringify(t.report, null, 1))}</pre></details>` : '') : '';
    return `${lines.join('')}
      <div class="settings-buttons"><button class="secondary-button" data-act="test" ${testing ? 'disabled' : ''} title="Sends one tiny real request to the AI engine, which uses a little of your plan or costs a fraction of a cent">${testing ? 'Testing…' : 'Test connection'}</button>
        <span class="session-faint">Sends one tiny real request to the AI engine.</span></div>${result}`;
  }

  // An engine's fields, drawn from their shape: objects nest, text/number/yes-no are inputs.
  function renderFields(value, path) {
    return Object.entries(value).filter(([key]) => key !== 'note-taker').map(([key, v]) => {
      const p = [...path, key];
      const id = esc(JSON.stringify(p));
      if (v && typeof v === 'object' && !Array.isArray(v)) return `<fieldset class="engine-group"><legend>${esc(key)}</legend>${renderFields(v, p)}</fieldset>`;
      if (typeof v === 'boolean') return `<label class="settings-inline"><input type="checkbox" data-field="${id}" ${v ? 'checked' : ''}> ${esc(key)}</label>`;
      const kind = typeof v === 'number' ? 'number' : 'text';
      return `<label class="settings-inline">${esc(key)} <input class="text-input" type="${kind}" data-field="${id}" data-kind="${Array.isArray(v) ? 'list' : kind}" value="${esc(Array.isArray(v) ? v.join(', ') : v)}"></label>`;
    }).join('');
  }

  function setField(root, path, value) {
    let o = root;
    for (const k of path.slice(0, -1)) o = o[k];
    o[path[path.length - 1]] = value;
  }

  // ---- Actions -----------------------------------------------------------------------------

  async function onClick(e) {
    const button = e.target.closest('[data-act]');
    if (!button || button.disabled || button.tagName === 'SELECT') return;
    const { act, name } = button.dataset;
    try {
      if (act === 'reload') await load();
      else if (act === 'open') await openRow(byName(name));
      else if (act === 'test') {
        if (!confirm('This sends one tiny real request to the AI engine. It uses a little of your plan, or costs a fraction of a cent. Go ahead?')) return;
        testing = true;
        testResult = null;
        draw();
        try {
          testResult = await call('testConnection');
        } catch (err) {
          testResult = { ok: false, error: err.message };
        }
        testing = false;
        draw();
      }
      else if (act === 'change') changeDialog(byName(name));
      else if (act === 'relocate') relocateDialog();
      else if (act === 'customise') {
        await call('customisePrompt', { name });
        await afterChange([name]);
        if (confirm('Your copy is made. Open it now?')) await openRow(byName(name));
      } else if (act === 'reset') {
        const r = byName(name);
        if (!confirm(isPrompt(r) ? `Go back to the built-in "${r.label}"? Your copy of it is deleted.` : `Put back the text WikiApp ships for "${r.label}"? Your edits to it are replaced.`)) return;
        await call('resetPrompt', { name });
        await afterChange([name]);
      } else if (act === 'default') {
        await call('setPath', { name, path: '' });
        await afterChange([name]);
      } else if (act === 'copy') {
        await navigator.clipboard.writeText(byName(name).path);
        toast('Path copied.');
      } else if (act === 'install') {
        installing = true;
        installMessage = '';
        draw();
        await call('installAgentlib');
      } else if (act === 'save-engine') {
        engine = await call('setEngineSettings', { settings: { engine: engineDraft.engine, engines: engineDraft.engines } });
        engineDraft = JSON.parse(JSON.stringify(engine));
        syncEngineModels(engine);
        draw();
        toast('Engine settings saved.');
      }
    } catch (err) {
      toast(err.message);
      installing = false;
      draw();
    }
  }

  function onChange_(e) {
    const t = e.target;
    if (t.dataset.act === 'role') {
      setRole(t.dataset.alias, t.value)
        .then(({ demoted }) => {
          if (demoted) toast(`${demoted} is now View only.`);
          return onChanged(['roles']);
        })
        .catch((err) => toast(err.message));
    } else if (t.dataset.act === 'engine') {
      engineDraft.engine = t.value;
      draw();
    } else if (t.dataset.field) {
      const path = JSON.parse(t.dataset.field);
      const fields = (engineDraft.engines[engineDraft.engine] ||= {});
      const value = t.type === 'checkbox' ? t.checked
        : t.dataset.kind === 'number' ? Number(t.value)
        : t.dataset.kind === 'list' ? t.value.split(',').map((x) => x.trim()).filter(Boolean) : t.value;
      setField(fields, path, value);
    }
  }

  async function afterChange(names) {
    await load();
    await onChanged(names);
    if (names.includes('agentlib')) await refreshAi();
  }

  // Open: a file inside a connected wiki goes to the app's editor; everything else opens with the system default.
  async function openRow(r) {
    if (r.kind !== 'folder' && r.path && (await openInEditor(r.path))) return;
    await call('openPath', { name: r.name });
  }

  // ---- Dialogs -----------------------------------------------------------------------------

  function showDialog(html) {
    dialog.hidden = false;
    dialog.innerHTML = `<div class="dialog settings-dialog" role="dialog">${html}</div>`;
    const close = () => { dialog.hidden = true; dialog.innerHTML = ''; };
    dialog.onmousedown = (e) => { if (e.target === dialog) close(); };
    dialog.querySelector('[data-close]')?.addEventListener('click', close);
    return { close, $: (s) => dialog.querySelector(s) };
  }

  function changeDialog(r) {
    const folder = r.kind === 'folder' || r.kind === 'library';
    const relative = r.kind === 'relative_folder';
    const d = showDialog(`
      <h2 class="dialog-title">Change: ${esc(r.label)}</h2>
      <p class="field-hint">${relative ? 'A folder name inside each wiki, such as <code>Notes</code>.' : `Browse for the ${folder ? 'folder' : 'file'}, or type its full path. ${r.kind === 'prompt' || r.kind === 'template' ? 'The file must exist.' : ''}`}</p>
      <div class="field-row"><input class="text-input" value="${esc(r.path)}" spellcheck="false">
        ${relative ? '' : '<button class="secondary-button" data-browse>Browse…</button>'}</div>
      <p class="field-error"></p>
      <div class="dialog-actions"><span class="spacer"></span><button class="secondary-button" data-close>Cancel</button><button class="primary-button" data-ok>Change</button></div>`);
    const input = d.$('input');
    d.$('[data-browse]')?.addEventListener('click', async () => {
      const p = await (folder ? call('pickFolder') : call('pickFile', { start: input.value || r.path })).catch(() => null);
      if (p) input.value = p;
    });
    d.$('[data-ok]').addEventListener('click', async () => {
      try {
        await call('setPath', { name: r.name, path: input.value.trim() });
        d.close();
        await afterChange([r.name]);
      } catch (err) {
        d.$('.field-error').textContent = err.message;
      }
    });
  }

  function relocateDialog() {
    const roots = [...new Set([...(first?.wiki_roots || []), ...getFolders().map((f) => f.root)])];
    const d = showDialog(`
      <h2 class="dialog-title">Change where the private folder is</h2>
      <p class="field-hint">Now: <code>${esc(byName('app_folder')?.path)}</code></p>
      <div class="field-row"><input class="text-input" placeholder="New place" spellcheck="false"><button class="secondary-button" data-browse>Browse…</button></div>
      <p class="setup-warning" hidden></p>
      <label class="settings-radio"><input type="radio" name="mode" value="move" checked> <strong>Move</strong>: everything in the folder goes to the new place, which must be empty or not there yet. The old folder is removed.</label>
      <label class="settings-radio"><input type="radio" name="mode" value="adopt"> <strong>Adopt</strong>: use a <code>.wiki</code> folder that is already at the new place, as it is (missing prompts and templates are filled in). The old folder is left alone.</label>
      <p class="field-hint">The two are never merged.</p>
      <p class="field-error"></p>
      <div class="dialog-actions"><span class="spacer"></span><button class="secondary-button" data-close>Cancel</button><button class="primary-button" data-ok>Change location</button></div>`);
    const input = d.$('input.text-input');
    const warn = () => {
      const hits = insideWiki(input.value, roots);
      d.$('.setup-warning').hidden = !hits.length;
      if (hits.length) d.$('.setup-warning').textContent = wikiWarning(hits);
    };
    input.addEventListener('input', warn);
    d.$('[data-browse]').addEventListener('click', async () => {
      const p = await call('pickFolder').catch(() => null);
      if (p) { input.value = p; warn(); }
    });
    d.$('[data-ok]').addEventListener('click', async () => {
      const mode = dialog.querySelector('input[name="mode"]:checked').value;
      if (!input.value.trim()) {
        d.$('.field-error').textContent = 'Choose a place first, or press Cancel.';
        return;
      }
      if (insideWiki(input.value, roots).length && !confirm('That place is inside a connected wiki, which is shared through git. Use it anyway?')) return;
      try {
        const result = await call('relocateFolder', { path: input.value.trim(), mode });
        const left = result.left_behind || [];
        if (left.length) {
          alert(`The folder moved, but these could not be removed from the old place. Delete them yourself:\n\n${left.join('\n')}`);
        }
        window.location.reload();
      } catch (err) {
        d.$('.field-error').textContent = err.message;
      }
    });
  }

  return { load, shown: load };
}
