// Each connected wiki has one role, kept by the host (getWikiRoles / setWikiRole):
//   Personal   your own notes and sessions are captured here (at most one wiki)
//   Team       Promotion proposes pages here (at most one wiki)
//   View only  read, search and link; the agents write nothing there (every other wiki, and any new one)
// This module holds the page's copy and tells the views when it changes.

import { call } from './bridge.js';

export const ROLE_LABEL = { personal: 'Personal', team: 'Team', view: 'View only' };
export const ROLE_HELP = 'Personal: your notes and sessions are captured here. Team: Promotion proposes pages here. View only: read, search and link; nothing is written by the agents. One wiki can be Personal and one Team.';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
let state = { roles: {}, needs_team: false, needs_personal: false };
const listeners = [];

export const onRolesChange = (fn) => listeners.push(fn);
export const roleOf = (alias) => state.roles[alias] || 'view';
export const needsPersonal = () => state.needs_personal;
export const needsTeam = () => state.needs_team;
export const aliasWithRole = (role) => Object.keys(state.roles).find((a) => state.roles[a] === role) || null;

function take(next) {
  state = { roles: {}, needs_team: false, needs_personal: false, ...next };
  for (const fn of listeners) fn(state);
}

export async function loadRoles() {
  try {
    take(await call('getWikiRoles'));
  } catch { /* keep the last copy */ }
  return state;
}

// -> { demoted: alias | null }. A second Personal or Team demotes the wiki that had it to View only.
export async function setRole(alias, role) {
  const result = await call('setWikiRole', { alias, role });
  take(result);
  return { demoted: result.demoted || null };
}

// A small badge to put beside a wiki's name.
export function roleBadge(alias) {
  const role = roleOf(alias);
  return `<span class="role-badge role-${role}" title="${esc(ROLE_HELP)}">${ROLE_LABEL[role]}</span>`;
}

// The prompt a tab shows instead of a failing action when it has no wiki to work on.
export function rolePrompt(role) {
  if (role === 'team') {
    return `<div class="role-hint"><p>Promotion needs a <strong>Team</strong> wiki: the one it proposes pages in. Give one of your wikis that role in Settings when you're ready to promote.</p>
      <button class="secondary-button" data-goto="settings">Open Settings</button></div>`;
  }
  const what = role === 'team' ? 'a Team wiki' : 'a Personal wiki';
  const why = role === 'team' ? 'Promotion proposes pages in your Team wiki.' : 'Your notes and sessions are captured into your Personal wiki.';
  return `<div class="ingest-setup"><p><strong>Choose ${what} first.</strong> ${why} Give one of your wikis that role in Settings.</p>
    <button class="primary-button" data-goto="settings">Open Settings</button></div>`;
}
