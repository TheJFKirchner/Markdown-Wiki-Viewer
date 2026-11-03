// Keeps the app's settings (open folders, signature, colors, last view...) in a file as well as
// in the browser storage. Browser storage alone can be lost: cleared site data, a closed window
// before it was written to disk, a different WebView2 profile. The host serves the file to the
// page as settings.js (loaded just before this script) and saves it when asked. It lives in
// ~/.wikiapp/settings.json for host/wikiapp.py, which starts each run with empty browser storage,
// and in %LOCALAPPDATA%\WikiApp\settings.json for WikiApp.exe.
//
// Every save bumps "__rev". On start, whichever copy has the higher revision wins, so neither a
// lost browser storage nor a save that didn't reach the file loses anything.
//
// A plain script (not a module) so it runs before any module reads localStorage.

(function () {
  var REV = '__rev';
  var python = window.__wikiappHost === 'python';
  var webview = !python && window.chrome && window.chrome.webview;
  // The same message bridge.js sends, before bridge.js has loaded.
  function post(msg) {
    if (webview) return webview.postMessage(msg);
    var api = window.pywebview && window.pywebview.api;
    if (api && api.call) api.call(msg);
    else window.addEventListener('pywebviewready', function () { window.pywebview.api.call(msg); }, { once: true });
  }
  var storage;
  try {
    storage = window.localStorage;
  } catch (e) {
    return; // storage unavailable: nothing to sync
  }
  var proto = Object.getPrototypeOf(storage);
  var setItem = proto.setItem;
  var removeItem = proto.removeItem;
  var clear = proto.clear;

  var saved = window.__savedSettings;
  var localRev = Number(storage.getItem(REV)) || 0;
  var fileRev = saved && typeof saved === 'object' ? Number(saved[REV]) || 0 : -1;
  if (fileRev >= localRev && fileRev >= 0) {
    clear.call(storage);
    for (var key in saved) {
      if (Object.prototype.hasOwnProperty.call(saved, key)) setItem.call(storage, key, String(saved[key]));
    }
  }

  var timer = 0;
  function save() {
    timer = 0;
    if (!webview && !python) return;
    setItem.call(storage, REV, String((Number(storage.getItem(REV)) || 0) + 1));
    var all = {};
    for (var i = 0; i < storage.length; i++) {
      var k = storage.key(i);
      all[k] = storage.getItem(k);
    }
    post({ id: 'settings', cmd: 'saveSettings', args: { settings: all } });
  }
  function schedule(target) {
    if (target !== storage) return;
    clearTimeout(timer);
    timer = setTimeout(save, 150);
  }

  proto.setItem = function (key, value) {
    setItem.call(this, key, value);
    schedule(this);
  };
  proto.removeItem = function (key) {
    removeItem.call(this, key);
    schedule(this);
  };
  proto.clear = function () {
    clear.call(this);
    schedule(this);
  };
  // Write anything still waiting when the window closes or reloads.
  window.addEventListener('pagehide', function () {
    if (timer) {
      clearTimeout(timer);
      save();
    }
  });

  // The browser storage was newer (or there's no file yet): bring the file up to date.
  if (localRev > fileRev && storage.length) schedule(storage);
})();
