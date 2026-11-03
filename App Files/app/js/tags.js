// Tag colors shared by the graph, the tag panel and note properties.
// A new tag gets the next palette color; picked and assigned colors are remembered.

const PALETTE = [
  '#a78bfa', '#60a5fa', '#4ade80', '#facc15', '#fb923c', '#f472b6', '#2dd4bf', '#f87171',
  '#a3e635', '#e879f9', '#38bdf8', '#fcd34d', '#c2410c', '#818cf8', '#86efac', '#fda4af',
];
const STORAGE_KEY = 'tagColors';

export function createTagColors() {
  // No prototype, so tags named like built-in properties (#constructor, #__proto__) are just tags.
  const colors = Object.create(null);
  try { Object.assign(colors, JSON.parse(localStorage.getItem(STORAGE_KEY))); } catch { /* storage unavailable */ }

  const save = () => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(colors)); } catch { /* storage unavailable */ }
  };

  return {
    // Give every tag in this wiki a color, in order (most used tags get the first colors),
    // avoiding colors other tags in the same wiki already have.
    assign(tags) {
      tags = [...tags];
      const used = new Set(tags.filter((t) => colors[t]).map((t) => colors[t]));
      let changed = false;
      tags.forEach((tag, i) => {
        if (colors[tag]) return;
        colors[tag] = PALETTE.find((c) => !used.has(c)) || PALETTE[i % PALETTE.length];
        used.add(colors[tag]);
        changed = true;
      });
      if (changed) save();
    },
    get(tag) {
      return colors[tag] || PALETTE[0];
    },
    set(tag, color) {
      colors[tag] = color;
      save();
    },
  };
}

// "#abc" / "#aabbcc" -> "rgba(r, g, b, alpha)"; other color formats are returned unchanged.
export function withAlpha(color, alpha) {
  let hex = color.replace('#', '');
  if (!/^[0-9a-f]{3}([0-9a-f]{3})?$/i.test(hex)) return color;
  if (hex.length === 3) hex = [...hex].map((c) => c + c).join('');
  const n = parseInt(hex, 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}
