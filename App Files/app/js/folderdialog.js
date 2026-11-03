// The "Add folder" / "Edit folder" window: choose a folder, give it an alias and a color.
// Before a folder is added it is scanned and compared with the open folders, and any
// notes that share a name with an open note are listed.

import { isNotePath, baseName } from './vault.js';

export function createFolderDialog(root, { workspace, call, getVault, onSave, onRemove }) {
  root.innerHTML = `
    <form class="dialog" novalidate>
      <h2 class="dialog-title"></h2>

      <label class="field-label">Folder</label>
      <div class="field-row">
        <div class="path-display"></div>
        <button type="button" class="secondary-button browse">Browse…</button>
      </div>

      <div class="field-pair">
        <div class="field-grow">
          <label class="field-label" for="folder-alias">Alias</label>
          <input id="folder-alias" class="text-input alias" autocomplete="off" spellcheck="false" placeholder="e.g. team">
        </div>
        <div>
          <label class="field-label">Color</label>
          <label class="color-field"><input type="color" class="color"></label>
        </div>
      </div>
      <p class="field-hint">A short name that tells this folder apart from the others. To link to a note
        in this folder specifically, write <code>[[<span class="alias-example">alias</span>:Note]]</code>.</p>
      <p class="field-error" role="alert"></p>

      <div class="dup-report"></div>

      <div class="dialog-actions">
        <button type="button" class="danger-button remove">Remove from workspace</button>
        <span class="spacer"></span>
        <button type="button" class="secondary-button cancel">Cancel</button>
        <button type="submit" class="primary-button save"></button>
      </div>
    </form>`;

  const $ = (sel) => root.querySelector(sel);
  const aliasInput = $('.alias');
  const colorInput = $('.color');
  let mode = 'add';
  let editing = null;   // folder being edited
  let picked = null;    // { root, scan } chosen with Browse
  let removeArmed = false;

  $('.browse').addEventListener('click', browse);
  $('.cancel').addEventListener('click', close);
  root.addEventListener('mousedown', (e) => {
    if (e.target === root) close(); // click outside the window
  });
  root.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
  aliasInput.addEventListener('input', () => {
    $('.field-error').textContent = '';
    updateReport();
  });
  colorInput.addEventListener('input', () => ($('.color-field').style.background = colorInput.value));
  $('.remove').addEventListener('click', () => {
    if (!removeArmed) {
      removeArmed = true;
      $('.remove').textContent = 'Click again to remove';
      return;
    }
    close();
    onRemove(editing.alias);
  });
  $('form').addEventListener('submit', (e) => {
    e.preventDefault();
    save();
  });

  async function browse() {
    const path = await call('pickFolder');
    if (!path) return;
    $('.field-error').textContent = '';
    const existing = workspace.list().find((f) => samePath(f.root, path));
    if (existing) {
      $('.field-error').textContent = `That folder is already open as "${existing.alias}".`;
      return;
    }
    $('.path-display').textContent = 'Checking folder…';
    try {
      const scan = await call('scanVault', { path, watch: false });
      picked = { root: scan.root, scan };
      $('.path-display').textContent = scan.root;
      $('.path-display').title = scan.root;
      if (!aliasInput.value || aliasInput.dataset.suggested === 'true') {
        aliasInput.value = workspace.suggestAlias(scan.root);
        aliasInput.dataset.suggested = 'true';
      }
      updateReport();
      aliasInput.focus();
      aliasInput.select();
    } catch (err) {
      picked = null;
      $('.path-display').textContent = 'No folder chosen';
      $('.field-error').textContent = err.message;
    }
  }

  // The duplicate check: which of this folder's note names already exist in other open folders.
  function updateReport() {
    const report = $('.dup-report');
    const alias = aliasInput.value.trim() || 'alias';
    $('.alias-example').textContent = alias;
    const vault = getVault();
    let names;  // [name, [other folder aliases]]
    let found = null;

    if (mode === 'add') {
      if (!picked) {
        report.replaceChildren();
        return;
      }
      const notes = picked.scan.files.filter((f) => isNotePath(f.path));
      found = notes.length;
      const own = [...new Set(notes.map((f) => baseName(f.path)))];
      names = own
        .map((name) => [name, otherFolders(vault, name.toLowerCase(), null)])
        .filter(([, others]) => others.length);
    } else {
      names = vault
        ? [...vault.duplicates.values()]
            .filter((ids) => ids.some((id) => vault.notes.get(id).folder === editing.alias))
            .map((ids) => {
              const note = vault.notes.get(ids.find((id) => vault.notes.get(id).folder === editing.alias));
              return [note.name, otherFolders(vault, note.name.toLowerCase(), editing.alias)];
            })
        : [];
    }

    report.replaceChildren();
    const summary = document.createElement('p');
    summary.className = 'dup-summary';
    const count = found === null ? '' : `Found ${found} note${found === 1 ? '' : 's'}. `;
    if (!names.length) {
      summary.textContent = count + 'No note names clash with the other open folders.';
      report.append(summary);
      return;
    }
    summary.textContent =
      count +
      `${names.length} note name${names.length === 1 ? ' is' : 's are'} also used in another folder. ` +
      `They'll be labeled with their folder's alias and joined by a dashed line in the graph.`;
    const list = document.createElement('ul');
    list.className = 'dup-list';
    for (const [name, others] of names.sort((a, b) => a[0].localeCompare(b[0]))) {
      const li = document.createElement('li');
      li.innerHTML = '<span class="dup-new"></span><span class="dup-arrow">↔</span><span class="dup-others"></span>';
      li.querySelector('.dup-new').textContent = `${name} (${alias})`;
      li.querySelector('.dup-others').textContent = others.map((o) => `${name} (${o})`).join(', ');
      list.append(li);
    }
    report.append(summary, list);
  }

  function save() {
    const alias = aliasInput.value.trim();
    const error =
      (mode === 'add' && !picked ? 'Choose a folder first.' : '') ||
      workspace.validateAlias(alias, editing && editing.alias);
    if (error) {
      $('.field-error').textContent = error;
      return;
    }
    close();
    if (mode === 'add') onSave({ mode, root: picked.root, scan: picked.scan, alias, color: colorInput.value });
    else onSave({ mode, oldAlias: editing.alias, alias, color: colorInput.value });
  }

  function open(options = {}) {
    mode = options.alias ? 'edit' : 'add';
    editing = options.alias ? workspace.find(options.alias) : null;
    picked = null;
    removeArmed = false;

    $('.dialog-title').textContent = mode === 'add' ? 'Add a folder' : `Edit "${editing.alias}"`;
    $('.save').textContent = mode === 'add' ? 'Add folder' : 'Save';
    $('.browse').hidden = mode === 'edit';
    $('.remove').hidden = mode === 'add';
    $('.remove').textContent = 'Remove from workspace';
    $('.path-display').textContent = mode === 'edit' ? editing.root : 'No folder chosen';
    $('.path-display').title = mode === 'edit' ? editing.root : '';
    $('.field-error').textContent = '';
    aliasInput.value = mode === 'edit' ? editing.alias : '';
    aliasInput.dataset.suggested = 'false';
    colorInput.value = mode === 'edit' ? editing.color : workspace.nextColor();
    $('.color-field').style.background = colorInput.value;
    updateReport();

    root.hidden = false;
    if (mode === 'add') $('.browse').focus();
    else aliasInput.focus();
  }

  function close() {
    root.hidden = true;
  }

  return { open };
}

// Aliases of open folders (other than `except`) that have a note with this name.
function otherFolders(vault, lowerName, except) {
  if (!vault) return [];
  const ids = vault.byName.get(lowerName) || [];
  return [...new Set(ids.map((id) => vault.notes.get(id).folder))].filter((f) => f !== except);
}

function samePath(a, b) {
  const norm = (p) => p.replace(/[\\/]+$/, '').toLowerCase();
  return norm(a) === norm(b);
}
