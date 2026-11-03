// Obsidian-style force-directed graph of notes, drawn on a canvas by force-graph
// (lib/force-graph.min.js, loaded as the global ForceGraph).
//
// Look and feel knobs: node size in radius(), physics in the d3Force calls,
// colors in the --graph-* variables in css/styles.css.

import { withAlpha } from './tags.js';

const LABEL_PX = 12;

export function createGraph(container, { onOpen }) {
  let colors = readColors();
  let hovered = null;
  let neighbors = new Set();
  let activeId = null;
  let pendingFit = false;
  let fitStartedAt = 0;
  let structure = '';
  // Set by setStyle(): per-node fill color (null = default), filtering, and whether the
  // dashed lines joining same-named notes from different folders are shown.
  let colorFor = () => null;
  let isVisible = () => true;
  let showDuplicates = true;
  const linkShown = (link) =>
    (link.kind !== 'duplicate' || showDuplicates) && isVisible(link.source) && isVisible(link.target);

  const graph = new ForceGraph(container)
    .backgroundColor('rgba(0,0,0,0)')
    .nodeId('id')
    // Hover tooltip: the note's description, if its frontmatter has one.
    .nodeLabel((node) =>
      node.description ? `<b>${escapeHtml(node.name)}</b><div>${escapeHtml(node.description)}</div>` : '',
    )
    // Filtered-out nodes are hidden rather than removed, so the layout doesn't jump around.
    .nodeVisibility((node) => isVisible(node))
    .linkVisibility(linkShown)
    .linkLineDash((link) => (link.kind === 'duplicate' ? [4, 3] : null))
    .autoPauseRedraw(false)
    .warmupTicks(40)
    .cooldownTime(6000)
    .d3VelocityDecay(0.35)
    .nodeCanvasObject(drawNode)
    .nodePointerAreaPaint(paintHitArea)
    .linkColor((link) => {
      const base = link.kind === 'duplicate' ? colors.linkDuplicate : colors.link;
      if (!hovered) return base;
      return touchesHovered(link) ? colors.linkHighlight : withAlpha(base, 0.25);
    })
    .linkWidth((link) => (touchesHovered(link) ? 1.6 : 0.8))
    .onNodeHover((node) => {
      hovered = node;
      neighbors = new Set();
      if (node) {
        for (const link of graph.graphData().links) {
          if (!linkShown(link)) continue;
          if (link.source === node) neighbors.add(link.target.id);
          if (link.target === node) neighbors.add(link.source.id);
        }
      }
      container.style.cursor = node && !node.ghost ? 'pointer' : '';
    })
    .onNodeClick((node) => {
      if (!node.ghost) onOpen(node.id);
    })
    .onNodeDragEnd((node) => {
      // Let dragged nodes float back into the simulation instead of pinning them.
      node.fx = undefined;
      node.fy = undefined;
    })
    .onEngineStop(() => {
      // Re-center once the layout has settled after opening a folder.
      if (pendingFit && hasSize()) {
        fitView(600, isVisible);
        pendingFit = false;
      }
    })
    .onZoom(() => {
      // Zooming after the initial fit means the user took over the camera; leave it alone.
      if (Date.now() - fitStartedAt > 600) pendingFit = false;
    });

  graph.d3Force('charge').strength(-80).distanceMax(350);
  graph.d3Force('link').distance(40);
  graph.d3Force('gravity', gravity(0.05)); // keeps unlinked notes from drifting away

  // Hidden views measure 0x0; keep the last real size so the camera math stays valid.
  const hasSize = () => container.clientWidth > 0 && container.clientHeight > 0;
  new ResizeObserver(() => {
    if (hasSize()) graph.width(container.clientWidth).height(container.clientHeight);
  }).observe(container);

  // Zoom to show the given nodes, but never closer than MAX_FIT_ZOOM (a handful of
  // nodes would otherwise fill the screen).
  const MAX_FIT_ZOOM = 2.5;
  function fitView(ms, filter) {
    if (!hasSize()) return;
    graph.zoomToFit(ms, 60, filter);
    setTimeout(() => {
      if (graph.zoom() > MAX_FIT_ZOOM) graph.zoom(MAX_FIT_ZOOM, 300);
    }, ms + 20);
  }

  function radius(node) {
    return 3 + Math.sqrt(node.degree) * 1.6;
  }

  function touchesHovered(link) {
    return hovered && (link.source === hovered || link.target === hovered);
  }

  function drawNode(node, ctx, scale) {
    const r = radius(node);
    const focused = hovered && (node === hovered || neighbors.has(node.id));
    const dimmed = hovered && !focused;

    const tagColor = node.ghost ? null : colorFor(node);
    const highlighted = node === hovered || node.id === activeId;

    ctx.globalAlpha = dimmed ? 0.2 : 1;
    ctx.beginPath();
    // Notes from the Notes folder are small rounded squares, scripts are stars, pages circles.
    if (node.inbox) ctx.roundRect(node.x - r * 0.9, node.y - r * 0.9, r * 1.8, r * 1.8, r * 0.4);
    else if (node.script) star(ctx, node.x, node.y, r * 1.35);
    else ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
    ctx.fillStyle = tagColor || (highlighted ? colors.nodeActive : node.ghost ? colors.nodeGhost : colors.node);
    ctx.fill();
    if (tagColor && highlighted) {
      // A tag-colored node keeps its color; a ring marks it as hovered/open instead.
      ctx.lineWidth = 2 / Math.max(scale, 1);
      ctx.strokeStyle = colors.label;
      ctx.stroke();
    }

    // Labels fade in as you zoom; hovering always shows them for the node and its neighbors.
    let alpha = focused ? 1 : Math.min(1, Math.max(0, (scale - 0.8) / 0.7));
    if (dimmed) alpha *= 0.2;
    if (alpha > 0.02) {
      ctx.globalAlpha = alpha;
      ctx.font = `${LABEL_PX / scale}px ${colors.font}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = colors.label;
      ctx.fillText(node.name, node.x, node.y + r + 3 / scale);
    }
    ctx.globalAlpha = 1;
  }

  function paintHitArea(node, color, ctx) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius(node) + 2, 0, 2 * Math.PI);
    ctx.fill();
  }

  return {
    // fit: zoom to show everything (for a newly opened folder, not for live updates).
    setData(data, { fit = false } = {}) {
      // Edits that don't add or remove notes or links leave the graph untouched.
      const key = structureKey(data);
      if (!fit && key === structure) {
        // Still pick up changed tags and descriptions.
        const fresh = new Map(data.nodes.map((n) => [n.id, n]));
        for (const node of graph.graphData().nodes) {
          const update = fresh.get(node.id);
          if (update) {
            Object.assign(node, { tags: update.tags, description: update.description, linkedFrom: update.linkedFrom });
          }
        }
        return;
      }
      structure = key;

      // Keep existing nodes where they are so live updates don't scramble the layout.
      graph.warmupTicks(fit ? 40 : 0);
      const previous = new Map(graph.graphData().nodes.map((n) => [n.id, n]));
      for (const node of data.nodes) {
        const old = previous.get(node.id);
        if (old) Object.assign(node, { x: old.x, y: old.y, vx: old.vx, vy: old.vy });
      }
      hovered = null;
      neighbors = new Set();
      graph.graphData(data);
      if (fit) {
        pendingFit = true;
        fitStartedAt = Date.now();
        setTimeout(() => fitView(400, isVisible), 60);
      }
    },
    setActive(id) {
      activeId = id;
    },
    // colorFor(node) -> CSS color or null; isVisible(node) -> boolean; showDuplicates: boolean.
    // fit: zoom to the visible nodes (after the filter changes).
    setStyle(style, { fit = false } = {}) {
      colorFor = style.colorFor;
      isVisible = style.isVisible;
      showDuplicates = style.showDuplicates;
      graph.nodeVisibility(graph.nodeVisibility()); // re-applies visibility
      if (fit) {
        pendingFit = false;
        // Wait a frame: when the graph tab was just shown, it needs one render before zooming.
        requestAnimationFrame(() => fitView(500, isVisible));
      }
    },
    setVisible(visible) {
      // Pausing also freezes the layout, so a pending re-center still happens on engine stop.
      if (visible) graph.resumeAnimation();
      else graph.pauseAnimation();
    },
    refreshColors() {
      colors = readColors();
    },
  };
}

// A five-pointed star path of outer radius r around (x, y).
function star(ctx, x, y, r) {
  for (let i = 0; i < 10; i++) {
    const angle = -Math.PI / 2 + (i * Math.PI) / 5;
    const radius = i % 2 ? r * 0.45 : r;
    ctx.lineTo(x + Math.cos(angle) * radius, y + Math.sin(angle) * radius);
  }
  ctx.closePath();
}

function structureKey({ nodes, links }) {
  const ids = nodes.map((n) => n.id + (n.ghost ? '?' : '') + ':' + n.name).sort();
  const pairs = links.map((l) => l.source + '\n' + l.target + '\n' + l.kind).sort();
  return ids.join('|') + '\n\n' + pairs.join('|');
}

function gravity(strength) {
  let nodes = [];
  const force = (alpha) => {
    for (const n of nodes) {
      n.vx -= n.x * strength * alpha;
      n.vy -= n.y * strength * alpha;
    }
  };
  force.initialize = (n) => (nodes = n);
  return force;
}

function readColors() {
  const css = getComputedStyle(document.documentElement);
  const get = (name) => css.getPropertyValue(name).trim();
  return {
    node: get('--graph-node'),
    nodeGhost: get('--graph-node-ghost'),
    nodeActive: get('--graph-node-active'),
    link: get('--graph-link'),
    linkHighlight: get('--graph-link-highlight'),
    linkDuplicate: get('--graph-link-duplicate'),
    label: get('--graph-label'),
    font: get('--font-ui'),
  };
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
