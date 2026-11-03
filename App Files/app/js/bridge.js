// Talks to the native host: host/wikiapp.py (Windows and macOS, through pywebview) or
// host/WikiApp.cs (Windows only, over WebView2's message channel). Both answer the same commands.
//   call('scanVault', { path })  -> Promise of the host's result
//   on('vaultChanged', fn)       -> host-pushed events

const python = window.__wikiappHost === 'python'; // set by the Python host's settings.js
const webview = !python && window.chrome && window.chrome.webview;
const pending = new Map();
const listeners = new Map();
let nextId = 1;

export const isHosted = python || Boolean(webview);

function receive(msg) {
  if (msg.event) {
    for (const fn of listeners.get(msg.event) || []) fn(msg.data);
    return;
  }
  const request = pending.get(msg.id);
  if (!request) return;
  pending.delete(msg.id);
  if (msg.ok) request.resolve(msg.result);
  else request.reject(new Error(msg.error));
}

if (webview) webview.addEventListener('message', (e) => receive(e.data));

// pywebview adds window.pywebview.api once the page has loaded, then fires "pywebviewready".
const pywebviewReady = python && new Promise((resolve) => {
  if (window.pywebview?.api?.call) resolve();
  else window.addEventListener('pywebviewready', () => resolve(), { once: true });
});

if (python) {
  window.__wikiappReceive = receive; // events pushed by host/wikiapp.py
  // The window's title follows the page's (WikiApp.exe does this itself).
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
  const id = nextId++;
  if (python) {
    return pywebviewReady
      .then(() => window.pywebview.api.call({ id, cmd, args }))
      .then((reply) => {
        if (reply.ok) return reply.result;
        throw new Error(reply.error);
      });
  }
  if (!webview) return Promise.reject(new Error('Not running inside WikiApp'));
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    webview.postMessage({ id, cmd, args });
  });
}

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, []);
  listeners.get(event).push(fn);
}
