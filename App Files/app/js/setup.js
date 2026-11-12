// The first-run setup screen: shown instead of the app while no place has been chosen for
// WikiApp's private folder (the `.wiki` folder). Nothing is created until the person confirms.
//   - suggests the default place (the host's `suggested`) and lets them pick another;
//   - previews, from the host (firstRunState with a candidate), what would be created, copied
//     from an older version, or found already there;
//   - warns when the place is inside a connected wiki folder (wikis are shared through git, this
//     folder is private).
// Also exports `insideWiki`, which the Settings screen reuses for "change location".

import { call } from './bridge.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const norm = (p) => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();

// The connected wiki folders in `roots` that `path` is inside (or is), for the private-folder warning.
export function insideWiki(path, roots) {
  const p = norm(path);
  return roots.filter((r) => norm(r) && (p === norm(r) || p.startsWith(`${norm(r)}/`)));
}

export const wikiWarning = (hits) =>
  `This place is inside the connected wiki folder ${hits.map((h) => `"${h}"`).join(', ')}. Wikis are shared through git; this folder is private (your prompts, progress and settings). Choose a place outside your wikis.`;

const ACTIONS = { create: 'will be created', copy: 'will be copied from an older version', found: 'already there, kept as it is' };

// state: the host's firstRunState. roots: () => the wiki folders known so far (may be empty on a first start).
export function showSetup(container, state, roots) {
  container.hidden = false;
  document.getElementById('app').hidden = true;
  let location = state.suggested;
  let preview = state.preview;
  let valid = state.valid !== false; // the host's verdict on the place in the box (a full path whose parent folder exists)
  let wikiRoots = state.wiki_roots || [];
  let busy = false;
  let error = '';
  let details = false; // the full paths, shown on demand
  // What setup does, grouped: one line per kind of thing, not one per file.
  const GROUPS = [
    ['Your settings', (n) => !n.startsWith('template.') && n !== 'personal_capture_rules'],
    ['Your capture rules', (n) => n === 'personal_capture_rules'],
    ['Note templates', (n) => n.startsWith('template.')],
  ];
  function previewRows() {
    const items = preview?.items || [];
    if (!items.length) return '<p class="session-faint">Nothing to create or copy.</p>';
    return GROUPS.map(([title, test]) => {
      const list = items.filter((i) => test(i.name));
      if (!list.length) return '';
      const kinds = [...new Set(list.map((i) => ACTIONS[i.action] || i.action))].join('; ');
      return `<p class="setup-group"><strong>${esc(title)}</strong> <span class="session-faint">${esc(kinds)}</span></p>`;
    }).join('');
  }
  const allRoots = () => [...new Set([...wikiRoots, ...roots()])];

  const draw = () => {
    const hits = location.trim() ? insideWiki(preview?.folder || location, allRoots()) : [];
    container.innerHTML = `
      <div class="setup-card">
        <h1>Welcome to WikiApp</h1>
        <p>WikiApp keeps what is private to you (your settings, capture rules, note templates and progress) in one folder called <code>.wiki</code>. Choose where it goes. Nothing is created until you confirm.</p>
        ${state.chosen && !state.location_exists ? `<p class="field-error">The folder you chose earlier is missing: ${esc(state.location)}. Restore it, or choose a place again.</p>` : ''}
        <label class="field-label">Where should it go?</label>
        <div class="field-row">
          <input class="text-input" id="setup-path" value="${esc(location)}" spellcheck="false">
          <button class="secondary-button" data-act="browse">Browse…</button>
        </div>
        <p class="field-hint">The suggested place is <code>${esc(state.suggested)}</code>, inside WikiApp's own folder: it is kept out of git and survives updates. Picking another folder uses a <code>.wiki</code> folder inside it; picking one already named <code>.wiki</code> uses that folder itself.</p>
        ${hits.length ? `<p class="setup-warning" role="alert">${esc(wikiWarning(hits))}</p>` : ''}
        ${preview && valid && location.trim() ? `<p class="field-label">This will use <code>${esc(preview.folder)}</code>${preview.folder_exists ? ' (it exists already)' : ' (new)'}:</p>
        <div class="setup-preview">${previewRows()}
          ${(preview.items || []).length ? `<button class="link-button" data-act="details">${details ? 'Hide details' : 'Show details'}</button>` : ''}
          ${details ? `<ul>${(preview.items || []).map((i) => `<li>${esc(i.label)}: <code>${esc(i.path)}</code> <span class="session-faint">(${esc(ACTIONS[i.action] || i.action)}${i.source ? `, from ${esc(i.source)}` : ''})</span></li>`).join('')}</ul>` : ''}</div>` : ''}
        <p class="field-error" role="alert">${esc(error)}</p>
        <div class="dialog-actions"><span class="spacer"></span>
          <button class="primary-button" data-act="confirm" ${busy || !location.trim() || !valid ? 'disabled' : ''}>${busy ? 'Setting up…' : 'Create it here and continue'}</button></div>
      </div>`;
  };

  // Asks the host whether the place in the box can be used, and what setup would do there. Answers that
  // arrive after the box changed again are ignored.
  let asked = 0;
  async function refresh() {
    const mine = ++asked;
    if (!location.trim()) {
      preview = null;
      valid = false;
      error = 'Choose a place first.';
      return draw();
    }
    let next = null;
    let failure = '';
    try {
      next = await call('firstRunState', { candidate: location });
    } catch (err) {
      failure = err.message;
    }
    if (mine !== asked) return;
    if (next) {
      valid = next.valid !== false;
      preview = valid ? next.preview : null;
      error = valid ? '' : next.error || 'That place cannot be used.';
      wikiRoots = next.wiki_roots || wikiRoots;
    } else {
      preview = null;
      valid = false;
      error = failure;
    }
    drawKeepingInput();
  }

  // Redraws the card without taking the caret out of the box the person is typing in.
  function drawKeepingInput() {
    const box = container.querySelector('#setup-path');
    const focused = box && document.activeElement === box;
    const [from, to] = focused ? [box.selectionStart, box.selectionEnd] : [0, 0];
    draw();
    if (focused) {
      const again = container.querySelector('#setup-path');
      again.focus();
      again.setSelectionRange(from, to);
    }
  }

  // Every keystroke: the place is not trusted until the host has checked it (shortly after typing stops).
  let timer = 0;
  container.addEventListener('input', (e) => {
    if (e.target.id !== 'setup-path') return;
    location = e.target.value;
    valid = false;
    preview = null;
    error = location.trim() ? '' : 'Choose a place first.';
    asked++;
    clearTimeout(timer);
    drawKeepingInput();
    if (location.trim()) timer = setTimeout(refresh, 250);
  });
  container.addEventListener('change', (e) => {
    if (e.target.id === 'setup-path') {
      clearTimeout(timer);
      refresh();
    }
  });
  container.addEventListener('click', async (e) => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'details') {
      details = !details;
      draw();
    } else if (act === 'browse') {
      const picked = await call('pickFolder').catch(() => null);
      if (picked) {
        location = picked;
        refresh();
      }
    } else if (act === 'confirm' && !busy) {
      if (!valid || !location.trim()) return;
      const hits = insideWiki(preview?.folder || location, allRoots());
      if (hits.length && !confirm(`${wikiWarning(hits)}\n\nUse this place anyway?`)) return;
      busy = true;
      error = '';
      draw();
      try {
        await call('chooseFolder', { path: location });
        location_reload();
      } catch (err) {
        busy = false;
        error = err.message;
        draw();
      }
    }
  });
  draw();
  if (!preview) refresh();
}

function location_reload() {
  window.location.reload();
}

// The one-time list of old files the person may want to delete themselves, with a dismiss.
export function showLeftovers(backdrop, items) {
  backdrop.hidden = false;
  backdrop.innerHTML = `
    <div class="dialog" role="dialog" aria-label="Old files">
      <h2 class="dialog-title">Old files you may want to remove</h2>
      <p class="field-hint">Older versions of WikiApp left these behind. WikiApp no longer uses them and never deletes anything of yours; remove them yourself if you like.</p>
      <ul class="leftovers">${items.map((i) => `<li><code>${esc(i.path)}</code><br><span class="session-faint">${esc(i.note)}</span></li>`).join('')}</ul>
      <div class="dialog-actions"><span class="spacer"></span><button class="primary-button" data-dismiss>Dismiss (don't show again)</button><button class="secondary-button" data-later>Later</button></div>
    </div>`;
  const close = () => { backdrop.hidden = true; backdrop.innerHTML = ''; };
  backdrop.querySelector('[data-later]').addEventListener('click', close);
  backdrop.querySelector('[data-dismiss]').addEventListener('click', async () => {
    await call('dismissLeftovers').catch(() => {});
    close();
  });
}
