// Talks to the native host, host/wikiapp.py (Windows and macOS), through pywebview.
//   call('scanVault', { path })  -> Promise of the host's result
//   on('vaultChanged', fn)       -> host-pushed events

const hosted = window.__wikiappHost === 'python'; // set by the host's settings.js; absent in a plain browser
const listeners = new Map();
let nextId = 1;

export const isHosted = hosted;

// Events pushed by host/wikiapp.py: { event, data }.
function receive(msg) {
  if (!msg.event) return;
  for (const fn of listeners.get(msg.event) || []) fn(msg.data);
}

// pywebview adds window.pywebview.api once the page has loaded, then fires "pywebviewready".
const pywebviewReady = hosted && new Promise((resolve) => {
  if (window.pywebview?.api?.call) resolve();
  else window.addEventListener('pywebviewready', () => resolve(), { once: true });
});

if (hosted) {
  window.__wikiappReceive = receive;
  // The window's title follows the page's.
  const title = document.querySelector('title');
  const sendTitle = () => call('setTitle', { title: document.title }).catch(() => {});
  new MutationObserver(sendTitle).observe(title, { childList: true, characterData: true, subtree: true });
  sendTitle();
  // F5 (or Cmd+R on a Mac) reloads the app after an edit, once the page agrees (setBeforeReload).
  document.addEventListener('keydown', async (e) => {
    if (e.key === 'F5' || (e.metaKey && !e.shiftKey && e.key === 'r')) {
      e.preventDefault();
      if (!beforeReload || (await beforeReload())) location.reload();
    }
  });
}

let beforeReload = null;
// fn() -> Promise of whether F5 may reload the page (it saves, or asks about unsaved text).
export function setBeforeReload(fn) {
  beforeReload = fn;
}

export function call(cmd, args = {}) {
  if (!hosted) return Promise.reject(new Error('Not running inside WikiApp'));
  const id = nextId++;
  return pywebviewReady
    .then(() => window.pywebview.api.call({ id, cmd, args }))
    .then((reply) => {
      if (reply.ok) return reply.result;
      throw new Error(reply.error);
    });
}

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, []);
  listeners.get(event).push(fn);
}
