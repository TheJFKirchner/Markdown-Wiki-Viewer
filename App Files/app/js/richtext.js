// Editing a note's lines as they look (used by livetext.js). Each Markdown line is a row: its
// structure (heading level, bullet, number, quote, indent) is kept as a prefix you don't see,
// and its text is shown formatted in an editable box. What's typed is turned back into
// Markdown (serialize) on every keystroke. A line whose Markdown wouldn't come back exactly the
// same (escapes, unusual syntax) is shown as its Markdown instead, so nothing is ever changed
// behind the user's back.

const HEADING = /^(#{1,6})( +)(.*)$/;
const LIST = /^(\s*)([-*+]|\d{1,9}[.)])( +)(.*)$/;
const QUOTE = /^(\s*>\s?)(.*)$/;

// A line -> { type, prefix, content, depth, marker }.
// type: 'heading' (level in marker), 'bullet', 'number', 'quote', 'para' or 'blank'.
export function classify(line) {
  if (!line.trim()) return { type: 'blank', prefix: '', content: '', depth: 0, marker: '' };
  let m = HEADING.exec(line);
  if (m) return { type: 'heading', prefix: m[1] + m[2], content: m[3], depth: 0, marker: m[1].length };
  m = LIST.exec(line);
  if (m) {
    return {
      type: /\d/.test(m[2]) ? 'number' : 'bullet',
      prefix: m[1] + m[2] + m[3],
      content: m[4],
      depth: indentDepth(m[1]),
      marker: m[2],
      indent: m[1],
    };
  }
  m = QUOTE.exec(line);
  if (m) return { type: 'quote', prefix: m[1], content: m[2], depth: 0, marker: '>' };
  const indent = line.match(/^\s*/)[0];
  return { type: 'para', prefix: indent, content: line.slice(indent.length), depth: indentDepth(indent), marker: '', indent };
}

export function indentDepth(indent) {
  return Math.floor(indent.replace(/\t/g, '    ').length / 2);
}

// ---- Formatted text -> Markdown --------------------------------------------------------------

// The Markdown for an editable box's contents. Marks keep how they were written (data-md, set
// by the renderer); marks added while editing get the app's usual ones.
export function serialize(node) {
  let out = '';
  for (const child of node.childNodes) out += piece(child);
  return out;
}

function piece(node) {
  if (node.nodeType === Node.TEXT_NODE) return node.data.replace(/ /g, ' ');
  if (node.nodeType !== Node.ELEMENT_NODE) return '';
  if (node.dataset.src) return node.dataset.src; // a [[link]], as written
  const inner = serialize(node);
  switch (node.tagName) {
    case 'BR':
      return '';
    case 'STRONG':
    case 'B':
      return marked(inner, node.dataset.md || '**');
    case 'EM':
    case 'I':
      return marked(inner, node.dataset.md || '_');
    case 'S':
    case 'DEL':
    case 'STRIKE':
      return marked(inner, node.dataset.md || '~~');
    case 'CODE': {
      const text = node.textContent.replace(/ /g, ' ');
      const tick = node.dataset.md || (text.includes('`') ? '``' : '`');
      return text ? tick + text + tick : '';
    }
    case 'A': {
      const kind = node.dataset.md;
      if (kind === 'linkify') return inner;
      if (kind === 'autolink') return `<${node.getAttribute('href')}>`;
      return inner ? `[${inner}](${node.getAttribute('href')})` : '';
    }
    default:
      return inner; // spans and the like that editing can leave behind
  }
}

// "**bold**", with spaces kept outside the marks (Markdown ignores "** bold**").
function marked(inner, mark) {
  const core = inner.trim();
  if (!core) return inner;
  const lead = inner.slice(0, inner.indexOf(core[0]));
  const trail = inner.slice(lead.length + core.length);
  return `${lead}${mark}${core}${mark}${trail}`;
}

// ---- Caret ------------------------------------------------------------------------------------

// Characters of text before the caret in box (0 if the caret isn't in it).
export function caretOffset(box) {
  const selection = getSelection();
  if (!selection.rangeCount) return 0;
  const range = selection.getRangeAt(0);
  if (!box.contains(range.startContainer)) return 0;
  const before = document.createRange();
  before.selectNodeContents(box);
  before.setEnd(range.startContainer, range.startOffset);
  return before.toString().length;
}

// Puts the caret after `offset` characters of text (never inside a link, which isn't editable).
export function setCaret(box, offset) {
  box.focus();
  const range = document.createRange();
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
  let left = offset;
  let placed = false;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const atom = node.parentElement.closest('[contenteditable="false"]');
    if (left <= node.length) {
      if (atom && box.contains(atom)) range.setStartAfter(atom);
      else range.setStart(node, left);
      placed = true;
      break;
    }
    left -= node.length;
  }
  if (!placed) {
    range.selectNodeContents(box);
    range.collapse(false);
  }
  range.collapse(true);
  const selection = getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}

export function caretAtStart(box) {
  const selection = getSelection();
  return selection.isCollapsed && caretOffset(box) === 0;
}

export function caretAtEnd(box) {
  const selection = getSelection();
  return selection.isCollapsed && caretOffset(box) >= box.textContent.length;
}

// Whether the caret sits on the box's first (up) or last (down) line of text.
export function caretOnEdgeLine(box, up) {
  const selection = getSelection();
  if (!selection.rangeCount) return true;
  const rects = selection.getRangeAt(0).getClientRects();
  const caret = rects[0] || box.getBoundingClientRect();
  const outer = box.getBoundingClientRect();
  const line = parseFloat(getComputedStyle(box).lineHeight) || 22;
  return up ? caret.top - outer.top < line * 0.75 : outer.bottom - caret.bottom < line * 0.75;
}

// Cuts everything after the caret (and any selection) out of box. -> its Markdown
export function cutAfterCaret(box) {
  const selection = getSelection();
  const range = selection.getRangeAt(0);
  if (!range.collapsed) range.deleteContents();
  const tail = document.createRange();
  tail.setStart(range.startContainer, range.startOffset);
  tail.setEnd(box, box.childNodes.length);
  const holder = document.createElement('span');
  holder.append(tail.extractContents());
  return serialize(holder);
}
