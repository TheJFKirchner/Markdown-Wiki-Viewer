// The signature in the bottom-left corner: a short alias (e.g. "alex") that signs every
// task and note you add, written as ~alex. Saved between runs.

import { SIGNATURE_PATTERN } from './tasks.js';

export function createSignature(root, { onChange }) {
  let value = load();
  let editing = false;

  root.addEventListener('click', (e) => {
    if (!editing && e.target.closest('.signature-show')) startEditing();
  });
  root.addEventListener('submit', (e) => {
    e.preventDefault();
    const next = root.querySelector('input').value.trim().replace(/^~/, '');
    if (next && !SIGNATURE_PATTERN.test(next)) {
      root.querySelector('.signature-error').textContent = 'Letters, numbers, - and _ only.';
      return;
    }
    value = next;
    save(value);
    editing = false;
    render();
    onChange(value);
  });
  root.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && editing) {
      editing = false;
      render();
    }
  });

  function startEditing(message = '', hint = false) {
    editing = true;
    render();
    const note = root.querySelector('.signature-error');
    note.textContent = message;
    note.classList.toggle('hint', hint);
    const input = root.querySelector('input');
    input.focus();
    input.select();
  }

  function render() {
    root.classList.toggle('unset', !value);
    if (editing) {
      root.innerHTML = `
        <form class="signature-form">
          <label class="signature-label" for="signature-input">Sign my notes as</label>
          <div class="signature-row">
            <span class="tilde">~</span>
            <input id="signature-input" class="text-input" autocomplete="off" spellcheck="false" placeholder="e.g. alex">
            <button class="primary-button" type="submit">Save</button>
          </div>
          <div class="signature-error"></div>
        </form>`;
      root.querySelector('input').value = value;
      return;
    }
    root.innerHTML = value
      ? `<button class="signature-show" title="Your signature. Click to change.">
           <span class="avatar"></span>
           <span class="signature-text"><span class="signature-label">Signed as</span><span class="signature-value"></span></span>
         </button>`
      : `<button class="signature-show" title="Set the alias that signs your tasks and notes">
           <span class="avatar">?</span>
           <span class="signature-text"><span class="signature-label">No signature yet</span><span class="signature-value">Set your signature</span></span>
         </button>`;
    if (value) {
      root.querySelector('.avatar').textContent = value.slice(0, 2).toUpperCase();
      root.querySelector('.signature-value').textContent = '~' + value;
    }
  }

  render();
  // Someone opening the app for the first time (each Windows user has their own settings)
  // picks their signature straight away. Escape skips it until the next start.
  if (!value) startEditing('Pick a short alias to sign the tasks and notes you add.', true);

  return {
    get: () => value,
    // True if a signature is set; otherwise opens the editor and asks for one.
    require() {
      if (value) return true;
      startEditing('Set a signature first. It signs everything you add.');
      return false;
    },
  };
}

function load() {
  try { return localStorage.getItem('signature') || ''; } catch { return ''; }
}

function save(value) {
  try { localStorage.setItem('signature', value); } catch { /* storage unavailable */ }
}
