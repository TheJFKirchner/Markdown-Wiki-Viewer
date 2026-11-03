// The workspace: which folders are open, their aliases and colors. Saved between runs.
//   [{ root, alias, color, hidden }]   hidden = left out of the graph (still in the explorer)

const STORAGE_KEY = 'workspace';
const FOLDER_COLORS = ['#60a5fa', '#fb923c', '#4ade80', '#f472b6', '#facc15', '#a78bfa', '#2dd4bf', '#f87171'];

// Letters, numbers, - and _ so an alias can be typed inside links: [[team:Jupiter]].
const ALIAS_PATTERN = /^[\p{L}\p{N}_-]+$/u;

export function createWorkspace() {
  let folders = load();

  const save = () => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(folders)); } catch { /* storage unavailable */ }
  };

  return {
    list: () => folders,
    find: (alias) => folders.find((f) => f.alias === alias),
    hasRoot: (root) => folders.some((f) => samePath(f.root, root)),

    add(root, alias, color) {
      folders.push({ root, alias, color: color || nextColor(folders), hidden: false });
      save();
    },
    update(alias, changes) {
      const folder = folders.find((f) => f.alias === alias);
      Object.assign(folder, changes);
      save();
    },
    remove(alias) {
      folders = folders.filter((f) => f.alias !== alias);
      save();
    },

    // Returns an error message, or '' if the alias can be used.
    // ignore: the folder being edited (its current alias is fine to keep).
    validateAlias(alias, ignore) {
      if (!alias) return 'Give the folder an alias.';
      if (!ALIAS_PATTERN.test(alias)) return 'Use only letters, numbers, - and _ (no spaces).';
      const taken = folders.some((f) => f.alias.toLowerCase() === alias.toLowerCase() && f.alias !== ignore);
      return taken ? `"${alias}" is already used by another folder.` : '';
    },

    // A starting alias from the folder's name, e.g. "Team Wiki" -> "team-wiki", made unique.
    suggestAlias(root) {
      const base =
        root.split(/[\\/]/).filter(Boolean).pop().toLowerCase().replace(/[^\p{L}\p{N}_-]+/gu, '-').replace(/^-+|-+$/g, '') ||
        'folder';
      let alias = base;
      for (let i = 2; folders.some((f) => f.alias.toLowerCase() === alias); i++) alias = `${base}-${i}`;
      return alias;
    },
    nextColor: () => nextColor(folders),
  };
}

function nextColor(folders) {
  const used = new Set(folders.map((f) => f.color));
  return FOLDER_COLORS.find((c) => !used.has(c)) || FOLDER_COLORS[folders.length % FOLDER_COLORS.length];
}

function samePath(a, b) {
  const norm = (p) => p.replace(/[\\/]+$/, '').toLowerCase();
  return norm(a) === norm(b);
}

function load() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (Array.isArray(saved)) return saved;
    // Earlier versions remembered a single folder.
    const last = localStorage.getItem('lastVault');
    if (last) {
      const alias = last.split(/[\\/]/).filter(Boolean).pop().toLowerCase().replace(/[^\p{L}\p{N}_-]+/gu, '-') || 'notes';
      return [{ root: last, alias, color: FOLDER_COLORS[0], hidden: false }];
    }
  } catch { /* storage unavailable or corrupt */ }
  return [];
}
