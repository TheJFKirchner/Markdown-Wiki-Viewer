// Sidebar file tree: one section per workspace folder, then its subfolders and files.
// Folders first, then files, both sorted naturally ("Note 2" before "Note 10").

import { isNotePath, isScriptPath, noteId } from './vault.js';

const CHEVRON = '<svg class="chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>';
const GEAR =
  '<svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>';
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

export function createExplorer(container, { onOpen, onEditFolder }) {
  const collapsed = new Set(); // "alias:" for a workspace folder, "alias:sub/path" for subfolders
  let vault = null;
  let activeId = null;

  container.addEventListener('click', (e) => {
    const edit = e.target.closest('.edit-folder');
    if (edit) {
      onEditFolder(edit.dataset.alias);
      return;
    }
    const row = e.target.closest('.tree-row');
    if (!row) return;
    if (row.dataset.folder !== undefined) {
      const key = row.dataset.folder;
      if (collapsed.has(key)) collapsed.delete(key);
      else collapsed.add(key);
      render();
    } else {
      onOpen(row.dataset.id);
    }
  });

  function buildTree(folder) {
    const root = { path: '', name: '', folders: new Map(), files: [] };
    const folderAt = (path) => {
      let node = root;
      if (!path) return node;
      for (const part of path.split('/')) {
        if (!node.folders.has(part)) {
          const childPath = node.path ? node.path + '/' + part : part;
          node.folders.set(part, { path: childPath, name: part, folders: new Map(), files: [] });
        }
        node = node.folders.get(part);
      }
      return node;
    };
    for (const sub of folder.scan.folders) folderAt(sub);
    for (const file of folder.scan.files) {
      const slash = file.path.lastIndexOf('/');
      folderAt(slash >= 0 ? file.path.slice(0, slash) : '').files.push(file.path);
    }
    return root;
  }

  function renderFolder(alias, folder, depth, out) {
    const subfolders = [...folder.folders.values()].sort((a, b) => collator.compare(a.name, b.name));
    for (const sub of subfolders) {
      const key = `${alias}:${sub.path}`;
      const row = makeRow(depth, 'folder' + (collapsed.has(key) ? ' collapsed' : ''));
      row.dataset.folder = key;
      row.innerHTML = CHEVRON;
      row.append(label(sub.name));
      out.append(row);
      if (!collapsed.has(key)) renderFolder(alias, sub, depth + 1, out);
    }

    const files = folder.files
      .map((path) => ({ path, file: path.slice(path.lastIndexOf('/') + 1) }))
      .sort((a, b) => collator.compare(a.file, b.file));
    for (const { path, file } of files) {
      const note = isNotePath(path);
      const id = noteId(alias, path);
      // Scripts (.sql, .py...) can be opened and linked to, so they aren't dimmed like other files.
      const row = makeRow(depth, note ? 'file' : isScriptPath(path) ? 'file script' : 'file other');
      row.dataset.id = id;
      if (id === activeId) row.classList.add('active');
      row.append(spacer());
      const dot = file.lastIndexOf('.');
      row.append(label(dot > 0 ? file.slice(0, dot) : file));
      if (!note && dot > 0) {
        const ext = document.createElement('span');
        ext.className = 'ext';
        ext.textContent = file.slice(dot + 1);
        row.append(ext);
      }
      row.title = path;
      out.append(row);
    }
  }

  function render() {
    const scroll = container.scrollTop;
    const fragment = document.createDocumentFragment();
    for (const folder of vault ? vault.folders : []) {
      const key = `${folder.alias}:`;
      const header = document.createElement('div');
      header.className = 'workspace-folder';

      const row = makeRow(0, 'folder root' + (collapsed.has(key) ? ' collapsed' : ''));
      row.dataset.folder = key;
      row.title = folder.root;
      row.innerHTML = CHEVRON;
      const dot = document.createElement('span');
      dot.className = 'folder-dot';
      dot.style.background = folder.color;
      const name = label(folder.alias);
      const where = document.createElement('span');
      where.className = 'folder-name' + (folder.error ? ' missing' : '');
      // The folder's real name, unless the alias already says it.
      const dirName = folder.root.split(/[\\/]/).pop();
      where.textContent = folder.error ? "can't be read" : dirName.toLowerCase() === folder.alias.toLowerCase() ? '' : dirName;
      if (folder.error) row.title = `${folder.root}\n${folder.error}`;
      row.append(dot, name, where);

      const edit = document.createElement('button');
      edit.className = 'icon-button edit-folder';
      edit.dataset.alias = folder.alias;
      edit.title = `Edit "${folder.alias}"`;
      edit.innerHTML = GEAR;
      header.append(row, edit);
      fragment.append(header);

      if (!collapsed.has(key)) renderFolder(folder.alias, buildTree(folder), 1, fragment);
    }
    container.replaceChildren(fragment);
    container.scrollTop = scroll;
  }

  return {
    setVault(next) {
      vault = next;
      render();
    },
    // Closes the deepest open subfolders that are showing: one level per call, so pressing
    // again closes the level above. Workspace folders themselves stay open.
    // Returns false when there was nothing left to close.
    collapseLevel() {
      const open = []; // [key, depth] of showing, open subfolders
      for (const folder of vault ? vault.folders : []) {
        if (collapsed.has(`${folder.alias}:`)) continue;
        for (const sub of folder.scan.folders) {
          const key = `${folder.alias}:${sub}`;
          const parts = sub.split('/');
          const parentClosed = parts.slice(1).some((_, i) => collapsed.has(`${folder.alias}:${parts.slice(0, i + 1).join('/')}`));
          if (!collapsed.has(key) && !parentClosed) open.push([key, parts.length]);
        }
      }
      if (!open.length) return false;
      const deepest = Math.max(...open.map(([, depth]) => depth));
      for (const [key, depth] of open) if (depth === deepest) collapsed.add(key);
      render();
      return true;
    },
    setActive(id) {
      activeId = id;
      // Make sure the active file is visible: expand its workspace folder and subfolders.
      let changed = false;
      if (id) {
        const colon = id.indexOf(':');
        const alias = id.slice(0, colon);
        const path = id.slice(colon + 1);
        changed = collapsed.delete(`${alias}:`) || changed;
        for (let i = path.indexOf('/'); i >= 0; i = path.indexOf('/', i + 1)) {
          changed = collapsed.delete(`${alias}:${path.slice(0, i)}`) || changed;
        }
      }
      if (changed) render();
      for (const row of container.querySelectorAll('.tree-row.file')) {
        const active = row.dataset.id === id;
        row.classList.toggle('active', active);
        if (active) row.scrollIntoView({ block: 'nearest' });
      }
    },
  };
}

function makeRow(depth, kind) {
  const row = document.createElement('button');
  row.className = 'tree-row ' + kind;
  row.style.setProperty('--depth', depth);
  return row;
}

function label(text) {
  const span = document.createElement('span');
  span.className = 'label';
  span.textContent = text;
  return span;
}

function spacer() {
  const span = document.createElement('span');
  span.className = 'spacer';
  return span;
}
