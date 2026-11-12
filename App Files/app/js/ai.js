// Whether the AI features can run. They need the agentlib library; the host (agentlibStatus) says
// whether it is installed and, when it isn't, why. Every AI button in the app carries
// `data-ai`. While AI is off those buttons are disabled and show the host's message, and the
// banner at the top of the Ingest view says it once. A MutationObserver applies this to buttons
// the views draw later, so no view has to know about it.

import { call } from './bridge.js';

let state = { installed: true, message: '' }; // assume on until the host says otherwise
const listeners = [];

export const aiState = () => state;
export const onAiChange = (fn) => listeners.push(fn);

export async function refreshAi() {
  try {
    const status = await call('agentlibStatus');
    state = { installed: Boolean(status.installed), message: status.message || '', path: status.path, found: status.found };
  } catch (err) {
    state = { installed: false, message: `AI features are off: ${err.message}` };
  }
  apply();
  for (const fn of listeners) fn(state);
  return state;
}

// The observer watches for buttons the views draw later. It is switched off while apply() writes, so
// apply()'s own changes (the banner text, a button's disabled flag) never wake it again.
const observer = new MutationObserver(() => {
  if (state.installed) return; // only the "off" state has to catch late buttons
  apply();
});
const watch = () => observer.observe(document.body, { childList: true, subtree: true });

function apply(root = document) {
  observer.disconnect();
  try {
    const off = !state.installed;
    const message = state.message || 'AI features are off.';
    for (const el of root.querySelectorAll('[data-ai]')) {
      if (off) {
        if (!el.disabled) {
          el.disabled = true;
          el.dataset.aiDisabled = '1';
        }
        if (el.dataset.aiTitle === undefined) el.dataset.aiTitle = el.title || '';
        if (el.title !== message) el.title = message;
      } else if (el.dataset.aiTitle !== undefined) {
        if (el.dataset.aiDisabled) el.disabled = false;
        el.title = el.dataset.aiTitle;
        delete el.dataset.aiDisabled;
        delete el.dataset.aiTitle;
      }
    }
    const banner = document.getElementById('ai-banner');
    if (banner) {
      const text = banner.querySelector('.ai-banner-text');
      if (banner.hidden !== !off) banner.hidden = !off;
      if (text.textContent !== message) text.textContent = message;
    }
  } finally {
    if (!state.installed) watch();
  }
}
