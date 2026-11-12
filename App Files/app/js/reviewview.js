// The Ingest view's Review tab: the wiki reviewer's work on the personal wiki's topic pages.
//   Reviews (left): a topic becomes due once three new sessions are filed under it, a session
//     reversed one of its decisions, a session was taken off it, or topics were merged into it.
//     Review (or Review all) has the reviewer rewrite the page's "Current state" from all of the
//     topic's session notes. It's written straight away; your own Notes section and the dated log
//     on the page are never touched. A topic has to be reviewed before it can be promoted.
//   Organise (right), each suggestion a card to accept or dismiss:
//     Folders: when three or more topics share a tag, the tag can become a folder, with a page
//       that lists them. These are worked out from the pages themselves, with no request to Claude.
//     Merges: Suggest merges asks the reviewer which topics are the same work under two names,
//       and which tags mean the same thing.
//   Links go by page name, so moving or merging a page never leaves a broken link.
// The work is done by sessions/sb.py, run by the host. See sessions/README.md.

import { rolePrompt } from './roles.js';
import { SONNET, chosenModel, modelMenu, rememberModel } from './modelmenu.js';

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

export function createReviewView(container, deps) {
  const { call, getWiki, reload, openPage, toast, onChange } = deps;
  let topics = null;          // every topic, those due first, or null before the first list
  let folders = [];           // [{ tag, new, title, topics }]: tags that could become folders
  let merges = null;          // [{ kind, keep, merge, reason }], or null before asking
  let error = '';
  let loading = false;
  let loadedFor = '';
  let showAll = false;        // also list topics that aren't due
  let batch = null;           // Review all: { total, done, current, stop }
  let suggesting = false;
  let conflicts = [];         // [{ id, topic, note_text, session_text, session_ref }] waiting for a decision
  const dismissed = new Set(); // suggestions turned down in this app run
  const working = new Set();  // topic names being reviewed, and suggestion keys being applied
  const results = [];         // what was reviewed, grouped or merged in this app run, newest first

  container.addEventListener('click', onClick);
  container.addEventListener('change', (e) => {
    if (rememberModel(e)) return draw();
    if (e.target.dataset.action === 'show-all') {
      showAll = e.target.checked;
      draw();
    }
  });

  const due = () => (topics || []).filter((t) => t.due);
  const folderKey = (f) => `folder:${f.tag}`;
  const mergeKey = (m) => `merge:${m.kind}:${m.keep}:${m.merge.join(',')}`;

  async function load() {
    const folder = getWiki();
    if (!folder || loading) return draw();
    loading = true;
    error = '';
    draw();
    try {
      const status = await call('sessionsStatus', { root: folder.root });
      topics = status.set_up ? await call('reviewList', { root: folder.root }) : null;
      folders = status.set_up ? await call('suggestFolders', { root: folder.root }) : [];
      conflicts = status.set_up ? await call('listConflicts', {}).catch(() => []) : [];
      error = status.set_up ? '' : 'setup';
      loadedFor = folder.root;
    } catch (err) {
      error = err.message;
    }
    loading = false;
    draw();
    onChange();
  }

  // ---- Drawing ------------------------------------------------------------------------------

  function draw() {
    const folder = getWiki();
    const scroll = container.querySelector('.ingest-right')?.scrollTop || 0;
    container.innerHTML = `
      <div class="ingest">
        <section class="ingest-left">
          <header class="ingest-header">
            <h1>Review</h1>
            <span class="spacer"></span>
            <button class="secondary-button" data-action="refresh" ${loading || batch ? 'disabled' : ''}>Refresh</button>
          </header>
          <p class="ingest-intro">Each topic has a page that collects every session about that piece of work. When new sessions have landed on a topic, the wiki reviewer rewrites the page's summary of where the work stands. It's written straight away. Your own notes on the page, and its dated log, are never changed. A topic must be reviewed before it can be promoted.</p>
          ${left(folder)}
        </section>
        <section class="ingest-right">
          <header class="ingest-cards-header">
            <h2>Organise</h2>
            <span class="spacer"></span>
            <button class="secondary-button" data-ai data-action="suggest" ${(topics?.length || 0) < 2 || suggesting || batch ? 'disabled' : ''}
              title="One request to Claude. Nothing changes until you accept a suggestion.">${suggesting ? 'Thinking…' : 'Suggest merges'}</button>
          </header>
          <p class="ingest-intro">Tags connect related topics. When three or more topics share a tag, it can become a folder, with a page that lists them. Suggest merges looks for topics that are the same work under two names, and tags that mean the same thing. Links go by page name, so nothing breaks when a page moves.</p>
          <div class="ingest-cards">${right()}</div>
        </section>
      </div>`;
    container.querySelector('.ingest-right').scrollTop = scroll;
  }

  function left(folder) {
    if (!folder) return rolePrompt('personal');
    if (error === 'setup') return `<p class="ingest-empty">${esc(folder.alias)} isn't set up as your personal wiki yet. Set it up in the Sessions tab.</p>`;
    if (error) return `<div class="ingest-setup"><p class="field-error">${esc(error)}</p><button class="secondary-button" data-action="refresh">Try again</button></div>`;
    if (!topics) return `<p class="ingest-empty">${loading ? 'Reading your topics…' : ''}</p>`;
    const list = showAll ? topics : due();
    const none = topics.length
      ? 'No topics are due for a review. A topic becomes due once several new sessions are filed under it, or when a decision on it is reversed, a session is taken off it, or topics are merged into it. Tick Show all to review one anyway, for example before promoting it.'
      : 'No topics yet. Ingest a session in the Sessions tab and its topics appear here.';
    return `
      <div class="ingest-list">${list.length ? list.map(topicRow).join('') : `<p class="ingest-empty">${none}</p>`}</div>
      <div class="session-options">
        ${topics.length ? `<label><input type="checkbox" data-action="show-all" ${showAll ? 'checked' : ''}> Show all ${plural(topics.length, 'topic')}</label>` : ''}
        <span class="spacer"></span>
        ${modelMenu({ agent: 'wiki-reviewer', fallback: SONNET, disabled: Boolean(batch || working.size || suggesting), what: 'reviews and merge suggestions' })}
        <button class="primary-button" style="margin:0" data-ai data-action="all" ${!due().length || batch || working.size ? 'disabled' : ''}
          title="Review every topic that is due, one after another">Review all ${due().length || ''}</button>
      </div>
      ${progress()}`;
  }

  function topicRow(topic) {
    const busy = working.has(topic.slug);
    const personal = new Set(topic.personal_tags || []);
    const meta = [topic.why, topic.state_as_of ? `reviewed ${topic.state_as_of}` : 'never reviewed'].filter(Boolean).join(' · ');
    const tags = (topic.tags || []).map((t) => (personal.has(t) ? `<span class="tag-personal" title="One of your own tags: it isn't in the reference tag list">#${esc(t)}</span>` : `#${esc(t)}`)).join(' ');
    return `
      <div class="session-row${busy ? ' working' : ''}" title="${esc(topic.summary)}">
        <div class="session-main">
          <span class="session-title"><button class="link-button" data-action="open" data-path="${esc(topic.path)}">${esc(topic.title)}</button>${topic.due ? '<span class="session-tag">DUE</span>' : ''}</span>
          <span class="session-meta">${esc(meta)}${tags ? ' · ' : ''}${tags}</span>
        </div>
        <button class="secondary-button" data-ai data-action="review" data-topic="${esc(topic.slug)}" ${busy || batch ? 'disabled' : ''}>${busy ? 'Reviewing…' : 'Review'}</button>
      </div>`;
  }

  function progress() {
    if (!batch) return '';
    return `
      <div class="ingest-progress">
        <div class="ingest-bar"><span></span></div>
        <div class="ingest-stage">${batch.stop ? 'Stopping after this one' : `Reviewing ${batch.done + 1} of ${batch.total}`}: ${esc(batch.current)}</div>
        <div class="ingest-stats">${batch.done} done<span class="spacer"></span>
          ${batch.stop ? '' : '<button class="link-button" data-action="stop">Stop after this one</button>'}</div>
      </div>`;
  }

  // A conflict: what the note says and what a session says about the same topic, side by side.
  function conflictCard(c) {
    const key = `conflict:${c.id}`;
    const busy = working.has(key);
    const off = busy ? 'disabled' : '';
    const ref = String(c.session_ref || '');
    return `
      <article class="ingest-card session-result conflict-card" style="--wiki:${esc(getWiki()?.color || 'var(--text-faint)')}">
        <div class="ingest-card-header">
          <span class="ingest-card-title">${esc(c.topic)}</span>
          <span class="ingest-kind new">CONFLICT</span>
        </div>
        <p class="session-faint">The note and a session disagree. Nothing has been changed yet.</p>
        <div class="conflict-sides">
          <div><h4>Your note</h4><pre>${esc(c.note_text)}</pre></div>
          <div><h4>The session${/\.md$/i.test(ref) ? ` · <button class="link-button" data-action="open" data-path="${esc(ref)}">${esc(ref)}</button>` : ref ? ` · ${esc(ref)}` : ''}</h4><pre>${esc(c.session_text)}</pre></div>
        </div>
        <div class="conflict-actions">
          <button class="secondary-button" data-action="resolve" data-id="${esc(c.id)}" data-resolution="dismiss" ${off} title="Settle nothing now and drop this conflict">Dismiss</button>
          <button class="secondary-button" data-action="resolve" data-id="${esc(c.id)}" data-resolution="accept_session" ${off} title="The note file is not edited. The topic page's Current state takes the session's version, and the conflict is recorded as settled.">Accept session</button>
          <button class="primary-button" style="margin:0" data-action="resolve" data-id="${esc(c.id)}" data-resolution="keep_note" ${off} title="Keep what the note says. The topic page is left as it is and the conflict is recorded as settled.">Keep note</button>
        </div>
      </article>`;
  }

  async function resolve(id, resolution) {
    const key = `conflict:${id}`;
    if (working.has(key)) return;
    working.add(key);
    draw();
    try {
      await call('resolveConflict', { id, resolution });
      conflicts = conflicts.filter((c) => String(c.id) !== String(id));
      const folder = getWiki();
      if (folder && resolution === 'accept_session') reload(folder.alias).catch(() => {});
    } catch (err) {
      toast(`Couldn't settle it: ${err.message}`);
    }
    working.delete(key);
    draw();
    onChange();
  }

  // Conflicts a review run found join the list (the same one is never listed twice).
  function addConflicts(list) {
    for (const c of list || []) if (!conflicts.some((x) => String(x.id) === String(c.id))) conflicts.push(c);
  }

  function right() {
    const cards = [
      ...conflicts.map(conflictCard),
      ...folders.filter((f) => !dismissed.has(folderKey(f))).map(folderCard),
      ...(merges || []).filter((m) => !dismissed.has(mergeKey(m))).map(mergeCard),
    ];
    if (merges && !merges.length) cards.push('<p class="ingest-empty">The reviewer found nothing to merge.</p>');
    cards.push(...results.map(resultCard));
    return cards.join('') || '<p class="ingest-empty">Nothing to organise yet. A folder is suggested here once three topics share a tag.</p>';
  }

  // A suggestion: a title, a chip saying what kind, Dismiss and Accept, then what it would do.
  function suggestionCard(key, title, chip, isNew, lines) {
    const busy = working.has(key);
    return `
      <article class="ingest-card session-result" style="--wiki:${esc(getWiki()?.color || 'var(--text-faint)')}">
        <div class="ingest-card-header">
          <span class="ingest-card-title">${esc(title)}</span>
          <span class="ingest-kind ${isNew ? 'new' : ''}">${chip}</span>
          <span class="spacer"></span>
          <button class="secondary-button" data-action="dismiss" data-key="${esc(key)}" ${busy ? 'disabled' : ''}>Dismiss</button>
          <button class="primary-button" style="margin:0" data-action="accept" data-key="${esc(key)}" ${busy ? 'disabled' : ''}>${busy ? 'Working…' : 'Accept'}</button>
        </div>
        ${lines.join('')}
      </article>`;
  }

  function folderCard(f) {
    return suggestionCard(folderKey(f), `#${f.tag}`, f.new ? 'NEW FOLDER' : 'ADD TO FOLDER', f.new, [
      `<p>${f.new ? `${plural(f.topics.length, 'topic')} share this tag.` : `${plural(f.topics.length, 'more topic')} with this tag.`}</p>`,
      `<p class="session-faint">Moves ${esc(f.topics.join(', '))} into <code>${esc(f.tag)}/</code>${f.new ? `, with a page <code>${esc(f.tag)}.md</code> that lists them` : ''}.</p>`,
    ]);
  }

  function mergeCard(m) {
    const topic = m.kind === 'topic';
    return suggestionCard(mergeKey(m), topic ? m.keep : `#${m.keep}`, topic ? 'MERGE TOPICS' : 'MERGE TAGS', false, [
      `<p>${esc(m.reason)}</p>`,
      `<p class="session-faint">${topic
        ? `Folds ${esc(m.merge.join(', '))} into ${esc(m.keep)}: their sessions, tags, tasks and your notes move over, links are repointed, and the merged ${m.merge.length === 1 ? 'page is' : 'pages are'} removed.`
        : `Replaces ${esc(m.merge.map((t) => `#${t}`).join(', '))} with #${esc(m.keep)} on every topic and session note.`}</p>`,
    ]);
  }

  function resultCard(r) {
    const link = (path, label) => `<button class="link-button" data-action="open" data-path="${esc(path)}">${esc(label)}</button>`;
    let body;
    let chip;
    if (r.error) {
      body = `<p class="field-error">${esc(r.error)}</p>`;
      chip = 'FAILED';
    } else if (r.what === 'folder') {
      body = `<p>${link(r.hub, r.tag)} now holds ${esc(r.moved.join(', ') || 'the same topics as before')}.</p>`;
      chip = 'GROUPED';
    } else if (r.what === 'merge') {
      body = r.kind === 'topic'
        ? `<p>${esc(r.merged.join(', '))} folded into ${link(r.path, r.keep)}. It is now due for a review.</p>`
        : `<p>${esc(r.merged.map((t) => `#${t}`).join(', '))} replaced by #${esc(r.keep)} on ${plural(r.pages, 'page')}.</p>`;
      chip = 'MERGED';
    } else {
      const related = (r.related || []).map((x) => `<li>${esc(x.topic)}${x.why ? ` <span class="session-faint">· ${esc(x.why)}</span>` : ''}</li>`).join('');
      body = `<p>${link(r.path, 'Current state')} rewritten from ${plural(r.sessions_used, 'session')}.</p>
        ${related ? `<p class="session-faint">Related section:</p><ul class="review-related">${related}</ul>` : ''}
        ${(r.new_tags || []).length ? `<p class="session-faint">${plural(r.new_tags.length, 'new tag')} added to your personal tags: ${r.new_tags.map((t) => `#${esc(t.tag)}${t.description ? ` (${esc(t.description)})` : ''}`).join(', ')}.</p>` : ''}
        ${(r.warnings || []).map((w) => `<p class="session-warning">${esc(w)}</p>`).join('')}${r.spend?.calls ? `<p class="session-faint">≈ $${r.spend.cost.toFixed(3)} at API prices · ${esc(r.spend.model || '')} · ${r.spend.tokens_in.toLocaleString()} tokens in, ${r.spend.tokens_out.toLocaleString()} out</p>` : ''}`;
      chip = 'REVIEWED';
    }
    return `
      <article class="ingest-card session-result ${r.error ? 'failed' : ''}" style="--wiki:${esc(getWiki()?.color || 'var(--text-faint)')}">
        <div class="ingest-card-header">
          <span class="ingest-card-title">${esc(r.title)}</span>
          <span class="spacer"></span>
          <span class="ingest-kind">${chip}</span>
        </div>
        ${body}
      </article>`;
  }

  // ---- Actions ------------------------------------------------------------------------------

  // Has the reviewer rewrite one topic's current state. Returns whether it worked.
  async function review(slug) {
    const folder = getWiki();
    const topic = topics?.find((t) => t.slug === slug);
    if (!folder || !topic || working.has(slug)) return false;
    working.add(slug);
    draw();
    let result;
    try {
      result = await call('reviewTopic', { root: folder.root, topic: slug, model: chosenModel('wiki-reviewer', SONNET) });
      addConflicts(result.conflicts);
      Object.assign(topic, { due: false, reviewed: true, new_sessions: 0, why: 'nothing new', state_as_of: result.state_as_of });
    } catch (err) {
      result = { title: topic.title, error: err.message };
    }
    working.delete(slug);
    results.unshift({ ...result, what: 'review' });
    draw();
    onChange();
    if (!result.error) reload(folder.alias).catch(() => {});
    return !result.error;
  }

  async function reviewAll() {
    const todo = due().map((t) => ({ slug: t.slug, title: t.title }));
    if (!todo.length || batch) return;
    batch = { total: todo.length, done: 0, current: '', stop: false };
    let failed = 0;
    for (const item of todo) {
      if (batch.stop) break;
      batch.current = item.title;
      if (!(await review(item.slug))) failed++;
      batch.done++;
    }
    const { done } = batch;
    batch = null;
    draw();
    toast(`Reviewed ${plural(done - failed, 'topic')}${failed ? `; ${failed} failed and ${failed === 1 ? 'is' : 'are'} still due` : ''}.`);
  }

  async function suggest() {
    const folder = getWiki();
    if (!folder || suggesting) return;
    suggesting = true;
    draw();
    try {
      merges = await call('suggestMerges', { root: folder.root, model: chosenModel('wiki-reviewer', SONNET) });
    } catch (err) {
      toast(`Couldn't get suggestions: ${err.message}`);
    }
    suggesting = false;
    draw();
  }

  // Applies a folder or merge suggestion, then lists everything again: names and places changed.
  async function accept(key) {
    const folder = getWiki();
    const asFolder = folders.find((f) => folderKey(f) === key);
    const asMerge = (merges || []).find((m) => mergeKey(m) === key);
    if (!folder || (!asFolder && !asMerge) || working.has(key)) return;
    working.add(key);
    draw();
    let result;
    try {
      result = asFolder
        ? { ...(await call('applyFolder', { root: folder.root, folder: asFolder })), what: 'folder', title: `#${asFolder.tag}` }
        : { ...(await call('applyMerge', { root: folder.root, merge: asMerge })), what: 'merge', title: asMerge.kind === 'topic' ? asMerge.keep : `#${asMerge.keep}` };
    } catch (err) {
      result = { error: err.message, title: asFolder ? `#${asFolder.tag}` : asMerge.keep };
    }
    working.delete(key);
    if (!result.error && asMerge) merges = null; // the other suggestions may name pages that are gone
    results.unshift(result);
    draw();
    if (!result.error) {
      await reload(folder.alias).catch(() => {});
      load();
    }
  }

  function onClick(e) {
    const button = e.target.closest('[data-action]');
    if (!button || button.disabled || button.tagName === 'INPUT' || button.tagName === 'SELECT' || button.tagName === 'OPTION') return;
    const action = button.dataset.action;
    if (action === 'refresh') load();
    else if (action === 'review') review(button.dataset.topic);
    else if (action === 'resolve') resolve(button.dataset.id, button.dataset.resolution);
    else if (action === 'all') reviewAll();
    else if (action === 'suggest') suggest();
    else if (action === 'accept') accept(button.dataset.key);
    else if (action === 'dismiss') {
      dismissed.add(button.dataset.key);
      draw();
    } else if (action === 'stop' && batch) {
      batch.stop = true;
      draw();
    } else if (action === 'open') openPage(`${getWiki().alias}:${button.dataset.path}`);
  }

  return {
    // The tab came to the front: list the topics the first time, and when something changed.
    shown() {
      const folder = getWiki();
      if (folder && folder.root !== loadedFor && !loading) load();
      else draw();
    },
    // Something was captured: what's due, and which folders are possible, may have changed.
    refresh() {
      loadedFor = '';
    },
    count: () => due().length + conflicts.length,
  };
}
