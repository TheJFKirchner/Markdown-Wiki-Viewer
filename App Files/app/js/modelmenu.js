// The model menu on the Ingest view's tabs: every model Claude Code offers on this computer, by
// name and exact id, with the tab's default marked. The list is the one the host fetches once per
// start (listIngestModels, kept in the settings as ingestModels). Which model an agent uses is
// kept in the engine settings, so Settings and the tabs agree (see below).

import { call } from './bridge.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

// The defaults: Haiku for the jobs that read and file, Sonnet for the ones that rewrite.
export const HAIKU = { id: 'claude-haiku-5-5', name: 'Haiku 5.5', description: 'Fastest for quick answers' };
export const SONNET = { id: 'claude-sonnet-5-5', name: 'Sonnet 5.5', description: 'Best for careful rewriting' };

const get = (key) => {
  try { return localStorage.getItem(key); } catch { return null; }
};

// The model each agent uses is kept in the engine settings (getEngineSettings / setEngineSettings), the one
// place Settings and every tab's menu read and write. `models` is the page's copy: agent id -> model id.
// Agents: executive-assistant (Notes capture and Sessions), wiki-reviewer (Review), team-wiki-manager (Promotion).
let models = {};
let engineId = 'claude';

export async function loadEngineModels() {
  try {
    const settings = await call('getEngineSettings');
    engineId = settings.engine;
    models = { ...(settings.engines?.[settings.engine]?.models || {}) };
  } catch { /* the defaults below are used */ }
}

// Settings saved the engine settings: take their models.
export function syncEngineModels(settings) {
  engineId = settings.engine;
  models = { ...(settings.engines?.[settings.engine]?.models || {}) };
}

export function chosenModel(agent, fallback) {
  return models[agent] || fallback.id;
}

// The models to offer: Claude Code's list, plus the default and the current choice if it lacks them.
export function modelList(agent, fallback) {
  let list = [];
  try {
    list = JSON.parse(get('ingestModels') || '[]');
  } catch { /* a damaged list: use the default */ }
  if (!Array.isArray(list)) list = [];
  if (!list.some((m) => m.id === fallback.id)) list = [fallback, ...list];
  const chosen = chosenModel(agent, fallback);
  if (!list.some((m) => m.id === chosen)) list = [...list, { id: chosen, name: chosen, description: 'Not offered by Claude Code right now' }];
  return list;
}

// "Haiku 5.5 · claude-haiku-5-5 (default)": the name, the exact id that is sent, and the default.
export function modelLabel(model, fallback) {
  const name = model.name && model.name !== model.id ? `${model.name} · ${model.id}` : model.id;
  return `${name}${model.id === fallback.id ? ' (default)' : ''}`;
}

export function modelMenu({ agent, fallback, disabled = false, what = 'the next run' }) {
  const chosen = chosenModel(agent, fallback);
  const list = modelList(agent, fallback);
  const current = list.find((m) => m.id === chosen);
  return `
    <label class="ingest-model" title="${esc(`The model for ${what}: ${chosen}${current?.description ? ` · ${current.description}` : ''}. Also set in Settings.`)}">
      <span>Model</span>
      <select data-action="model" data-agent="${esc(agent)}" ${disabled ? 'disabled' : ''}>
        ${list.map((m) => `<option value="${esc(m.id)}" title="${esc(m.description || '')}" ${m.id === chosen ? 'selected' : ''}>${esc(modelLabel(m, fallback))}</option>`).join('')}
      </select>
    </label>`;
}

// For a tab's change listener: saves a pick from one of these menus to the engine settings. -> whether it was one.
export function rememberModel(e) {
  if (!e.target.matches?.('select[data-action="model"][data-agent]')) return false;
  const { agent } = e.target.dataset;
  models[agent] = e.target.value;
  call('setEngineSettings', { settings: { engines: { [engineId]: { models: { [agent]: e.target.value } } } } }).catch(() => {});
  return true;
}
