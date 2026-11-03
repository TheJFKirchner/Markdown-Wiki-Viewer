// The settings card in the graph view:
//   Color by    folder / tag / none
//   Folders     show or hide each workspace folder, change its color
//   Duplicates  dashed lines joining same-named notes from different folders
//   Tags        pick tags to filter the graph, change each tag's color

const CHEVRON = '<svg class="chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>';
const COLOR_MODES = [['folder', 'Folder'], ['tag', 'Tag'], ['none', 'None']];

export function createGraphPanel(root, { tagColors, onChange, onFolderChange }) {
  const selected = new Set();
  let folders = [];        // [{ alias, color, hidden, count }]
  let tags = new Map();    // tag -> count
  let duplicateCount = 0;
  let colorBy = load('colorBy') || 'folder';
  let showDuplicates = load('showDuplicates') !== 'false';
  let showNotes = load('showNotes') !== 'false';
  let showScripts = load('showScripts') !== 'false';
  let open = load('graphPanelOpen') !== 'false';

  root.innerHTML = `
    <button class="panel-header">${CHEVRON}<span>Graph</span><span class="panel-badge"></span></button>
    <div class="panel-body">
      <div class="panel-section">
        <div class="section-title">Color nodes by</div>
        <div class="segmented">${COLOR_MODES.map(([v, t]) => `<button data-mode="${v}">${t}</button>`).join('')}</div>
      </div>
      <div class="panel-section">
        <div class="section-title">Folders</div>
        <div class="folder-list"></div>
        <label class="switch duplicates">
          <input type="checkbox" class="show-duplicates">
          <span class="switch-track"></span>
          <span class="duplicates-label"></span>
        </label>
        <label class="switch notes-switch" title="Notes from the Notes folder (daily, weekly...), drawn as squares">
          <input type="checkbox" class="show-notes">
          <span class="switch-track"></span>
          <span>Show notes</span>
        </label>
        <label class="switch notes-switch" title="Scripts (.sql, .py, ...) that notes link to, drawn as stars">
          <input type="checkbox" class="show-scripts">
          <span class="switch-track"></span>
          <span>Show scripts</span>
        </label>
      </div>
      <div class="panel-section grow">
        <div class="section-title">Tags</div>
        <div class="tag-list"></div>
        <div class="panel-footer">
          <span class="filter-hint"></span>
          <button class="link-button clear">Show all</button>
        </div>
      </div>
    </div>`;

  const $ = (sel) => root.querySelector(sel);
  $('.show-duplicates').checked = showDuplicates;
  $('.show-notes').checked = showNotes;
  $('.show-notes').addEventListener('change', (e) => {
    showNotes = e.target.checked;
    store('showNotes', showNotes);
    onChange({ fit: false });
  });
  $('.show-scripts').checked = showScripts;
  $('.show-scripts').addEventListener('change', (e) => {
    showScripts = e.target.checked;
    store('showScripts', showScripts);
    onChange({ fit: false });
  });

  $('.panel-header').addEventListener('click', () => {
    open = !open;
    store('graphPanelOpen', open);
    render();
  });
  $('.segmented').addEventListener('click', (e) => {
    const button = e.target.closest('[data-mode]');
    if (!button) return;
    colorBy = button.dataset.mode;
    store('colorBy', colorBy);
    render();
    onChange({ fit: false });
  });
  $('.show-duplicates').addEventListener('change', (e) => {
    showDuplicates = e.target.checked;
    store('showDuplicates', showDuplicates);
    onChange({ fit: false });
  });
  $('.clear').addEventListener('click', () => {
    selected.clear();
    render();
    onChange({ fit: true });
  });

  // Folder rows: click to show/hide in the graph; the dot changes the folder's color.
  $('.folder-list').addEventListener('click', (e) => {
    const row = e.target.closest('.folder-row');
    if (!row || e.target.closest('.swatch')) return;
    const folder = folders.find((f) => f.alias === row.dataset.alias);
    onFolderChange(folder.alias, { hidden: !folder.hidden });
  });
  $('.folder-list').addEventListener('input', (e) => {
    if (!e.target.matches('input[type=color]')) return;
    const alias = e.target.closest('.folder-row').dataset.alias;
    e.target.parentElement.style.background = e.target.value;
    onFolderChange(alias, { color: e.target.value }, { quiet: true });
  });

  // Tag rows: click to filter; the dot changes the tag's color.
  $('.tag-list').addEventListener('click', (e) => {
    const row = e.target.closest('.tag-row');
    if (!row || e.target.closest('.swatch')) return;
    const tag = row.dataset.tag;
    if (selected.has(tag)) selected.delete(tag);
    else selected.add(tag);
    render();
    onChange({ fit: true });
  });
  $('.tag-list').addEventListener('input', (e) => {
    if (!e.target.matches('input[type=color]')) return;
    const tag = e.target.closest('.tag-row').dataset.tag;
    tagColors.set(tag, e.target.value);
    e.target.parentElement.style.background = e.target.value;
    onChange({ fit: false, colorsChanged: true });
  });

  function render() {
    root.classList.toggle('open', open);
    $('.panel-badge').textContent = selected.size ? `${selected.size} tag${selected.size === 1 ? '' : 's'} selected` : '';
    for (const button of root.querySelectorAll('.segmented button')) {
      button.classList.toggle('active', button.dataset.mode === colorBy);
    }

    $('.folder-list').replaceChildren(
      ...folders.map((folder) => {
        const row = swatchRow('folder-row' + (folder.hidden ? ' hidden-folder' : ''), folder.color, folder.alias, folder.count);
        row.dataset.alias = folder.alias;
        row.title = folder.hidden ? 'Hidden from the graph. Click to show.' : 'Click to hide from the graph';
        return row;
      }),
    );
    $('.duplicates-label').textContent = duplicateCount
      ? `Link duplicate names (${duplicateCount})`
      : 'Link duplicate names';
    $('.duplicates').hidden = folders.length < 2;

    $('.panel-footer').hidden = !selected.size;
    $('.filter-hint').textContent = selected.size === 1 ? 'Showing one tag' : `Showing any of ${selected.size} tags`;
    if (!tags.size) {
      $('.tag-list').innerHTML =
        '<p class="panel-empty">No tags yet. Add <code>tags: [example]</code> to a note\'s frontmatter.</p>';
      return;
    }
    $('.tag-list').replaceChildren(
      ...[...tags].map(([tag, count]) => {
        const row = swatchRow('tag-row' + (selected.has(tag) ? ' selected' : ''), tagColors.get(tag), '#' + tag, count);
        row.dataset.tag = tag;
        row.title = selected.has(tag) ? 'Click to stop filtering by this tag' : 'Click to show only notes with this tag';
        return row;
      }),
    );
  }

  render();

  return {
    // keepSelection: on live refresh, keep selected tags that still exist.
    setData(next, { keepSelection = false } = {}) {
      folders = next.folders;
      tags = next.tags;
      duplicateCount = next.duplicateCount;
      for (const tag of [...selected]) if (!keepSelection || !tags.has(tag)) selected.delete(tag);
      render();
    },
    // Filter to exactly these tags (used when clicking a tag in a note).
    select(list) {
      selected.clear();
      for (const tag of list) selected.add(tag);
      open = true;
      render();
    },
    state() {
      return { selected, colorBy, showDuplicates, showNotes, showScripts };
    },
  };
}

function swatchRow(className, color, text, count) {
  const row = document.createElement('div');
  row.className = 'swatch-row ' + className;
  row.innerHTML = `
    <label class="swatch" title="Change color"><input type="color"></label>
    <span class="row-name"></span>
    <span class="row-count">${count}</span>`;
  row.querySelector('.swatch').style.background = color;
  row.querySelector('input').value = color;
  row.querySelector('.row-name').textContent = text;
  return row;
}

function store(key, value) {
  try { localStorage.setItem(key, String(value)); } catch { /* storage unavailable */ }
}

function load(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
