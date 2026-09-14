/**
 * automod.js -- Word lists and severity profiles
 *
 * Endpoints used:
 *   GET    /word-lists                       -> all lists with their words
 *   POST   /word-lists                       -> create a list
 *   POST   /word-lists/{name}/words          -> add words
 *   DELETE /word-lists/{name}/words/{word}   -> remove one word
 *   DELETE /word-lists/{name}                -> delete a list
 *   POST   /word-lists/test                  -> try a sample message
 *   GET    /profiles                         -> profiles + which is active
 *   GET    /profiles/keys                    -> overridable keys, typed
 *   PUT    /profiles/active                  -> switch profile
 *   POST   /profiles/{name}/snapshot         -> capture current settings
 *   DELETE /profiles/{name}                  -> delete a custom profile
 *
 * The master on/off switch and the action taken on a match live on the
 * Configuration page, since they are plain config columns. This page owns the
 * things that are not: list contents and profile definitions.
 */

import { get, post, put, del } from '../api.js';
import { loading, errorState, emptyState, escHtml } from './utils.js';

let _root = null;
let _lists = [];
let _profiles = { active: 'normal', profiles: [] };
let _keys = { keys: [], actions: [] };
let _cfg = {};
let _tab = 'lists';
let _open = new Set();

// -- Styles -------------------------------------------------------------------

function injectStyles() {
  if (document.getElementById('am-styles')) return;
  const s = document.createElement('style');
  s.id = 'am-styles';
  s.textContent = `
    .am-wrap { max-width: 940px; padding: 24px; }
    .am-header h2 { font-size: 20px; font-weight: 600; letter-spacing: -0.02em; }
    .am-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .am-tabs { display: flex; gap: 4px; margin: 18px 0 16px;
               border-bottom: 1px solid var(--border); }
    .am-tab { background: none; border: none; padding: 8px 14px; font-size: 13px;
              color: var(--muted); border-bottom: 2px solid transparent;
              margin-bottom: -1px; transition: all var(--transition); }
    .am-tab:hover { color: var(--text); }
    .am-tab.on { color: var(--gold); border-bottom-color: var(--gold); }

    .am-banner {
      display: flex; align-items: center; gap: 10px; border-radius: 9px;
      padding: 11px 15px; font-size: 13px; margin-bottom: 16px;
    }
    .am-banner.off { background: rgba(245,158,11,0.08);
                     border: 1px solid rgba(245,158,11,0.25); }
    .am-banner.on  { background: rgba(34,197,94,0.07);
                     border: 1px solid rgba(34,197,94,0.22); }
    .am-banner .ic { flex-shrink: 0; }
    .am-banner.off .ic { color: var(--color-warn); }
    .am-banner.on  .ic { color: var(--color-success); }

    .am-panel { background: var(--card); border: 1px solid var(--border);
                border-radius: 10px; padding: 16px; margin-bottom: 12px; }
    .am-card { background: var(--card); border: 1px solid var(--border);
               border-left: 3px solid var(--gold); border-radius: 10px;
               overflow: hidden; margin-bottom: 10px; }
    .am-card.active { border-left-color: var(--color-success); }
    .am-card.builtin { border-left-color: var(--color-mute); }

    .am-card-head { display: flex; align-items: center; gap: 11px;
                    padding: 13px 16px; cursor: pointer; user-select: none; }
    .am-card-head:hover { background: rgba(255,255,255,0.02); }
    .am-name { font-weight: 600; font-size: 14px; color: var(--text); }
    .am-meta { flex: 1; font-size: 12px; color: var(--muted); }
    .am-tag { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em;
              padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
    .am-tag.builtin { background: rgba(59,130,246,0.14); color: var(--color-mute); }
    .am-tag.active  { background: rgba(34,197,94,0.14); color: var(--color-success); }

    .am-body { display: none; padding: 4px 16px 16px;
               border-top: 1px solid var(--border); }
    .am-card.open .am-body { display: block; }

    .am-words { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
    .am-word {
      display: inline-flex; align-items: center; gap: 6px;
      background: var(--input); border: 1px solid var(--border);
      border-radius: 999px; padding: 3px 5px 3px 11px;
      font-family: var(--font-mono); font-size: 12px; color: var(--text);
    }
    .am-word.phrase { border-color: rgba(212,168,67,0.35); color: var(--gold); }
    .am-word button {
      background: none; border: none; color: var(--muted); font-size: 14px;
      line-height: 1; padding: 0 4px; border-radius: 50%;
    }
    .am-word button:hover { color: var(--color-ban); }

    .am-row { display: flex; gap: 9px; flex-wrap: wrap; align-items: flex-end; margin-top: 14px; }
    .am-field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 150px; }
    .am-field label { font-size: 11px; color: var(--muted); letter-spacing: 0.03em; }
    .am-input {
      background: var(--input); border: 1px solid var(--border); border-radius: 7px;
      padding: 8px 11px; font-size: 13px; color: var(--text); width: 100%;
      transition: border-color var(--transition);
    }
    .am-input:focus { border-color: rgba(212,168,67,0.4); outline: none; }

    .am-hint { font-size: 12px; color: var(--muted); margin-top: 10px; line-height: 1.55; }

    .am-result { margin-top: 12px; border-radius: 8px; padding: 11px 14px; font-size: 13px; }
    .am-result.hit  { background: rgba(239,68,68,0.09); border: 1px solid rgba(239,68,68,0.25); }
    .am-result.miss { background: rgba(34,197,94,0.07); border: 1px solid rgba(34,197,94,0.22); }

    .am-ovr { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px;
              margin-top: 12px; font-size: 12.5px; }
    .am-ovr-k { color: var(--muted); }
    .am-ovr-v { font-family: var(--font-mono); color: var(--text); text-align: right; }

    .am-toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
      background: var(--card); border: 1px solid var(--border);
      box-shadow: var(--shadow-elevated); border-radius: 9px; padding: 11px 18px;
      font-size: 13px; color: var(--text); z-index: 900; max-width: 90vw; }
    .am-toast.err { border-color: rgba(239,68,68,0.4); color: #FCA5A5; }

    @media (max-width: 640px) { .am-wrap { padding: 16px; } }
  `;
  document.head.appendChild(s);
}

// -- Helpers ------------------------------------------------------------------

function toast(msg, isError = false) {
  const el = document.createElement('div');
  el.className = 'am-toast' + (isError ? ' err' : '');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), isError ? 6000 : 3000);
}

function apiError(err) {
  const raw = String(err && err.message ? err.message : err);
  const at = raw.indexOf('{');
  if (at !== -1) {
    try {
      const d = JSON.parse(raw.slice(at)).detail;
      if (typeof d === 'string') return d;
      if (d && typeof d.error === 'string') return d.error;
    } catch { /* fall through */ }
  }
  return raw;
}

/** Split a comma or newline separated blob into words. */
function splitWords(raw) {
  return String(raw || '')
    .split(/[\n,]+/)
    .map(w => w.trim())
    .filter(Boolean);
}

// -- Word lists ---------------------------------------------------------------

function listsView() {
  const enabled = !!_cfg.wordlist_enabled;
  const total = _lists.reduce((n, l) => n + (l.words || []).length, 0);

  const banner = enabled
    ? `<div class="am-banner on"><span class="ic">&#10003;</span>
         <span>Word filtering is <strong>on</strong>. Matches are
         <strong>${escHtml(_cfg.wordlist_action || 'delete')}</strong> and count
         toward the violation counter.</span></div>`
    : `<div class="am-banner off"><span class="ic">&#9888;</span>
         <span>Word filtering is <strong>off</strong>, so nothing below is being
         enforced. Turn it on under Configuration &rarr; AutoMod &middot; Word Lists.</span></div>`;

  const cards = _lists.length ? _lists.map(l => {
    const words = l.words || [];
    const open = _open.has(l.list_name) ? ' open' : '';
    const chips = words.length
      ? words.map(w => `
          <span class="am-word ${w.includes(' ') ? 'phrase' : ''}">${escHtml(w)}
            <button data-act="delword" data-list="${escHtml(l.list_name)}"
                    data-word="${escHtml(w)}" title="Remove">&times;</button>
          </span>`).join('')
      : '<div class="am-hint">This list is empty, so it matches nothing.</div>';

    return `
    <div class="am-card${open}" data-card="${escHtml(l.list_name)}">
      <div class="am-card-head" data-act="toggle" data-list="${escHtml(l.list_name)}">
        <span class="am-name">${escHtml(l.list_name)}</span>
        <span class="am-meta">${words.length} ${words.length === 1 ? 'entry' : 'entries'}</span>
        <button class="btn btn-danger btn-sm" data-act="dellist"
                data-list="${escHtml(l.list_name)}">Delete list</button>
      </div>
      <div class="am-body">
        <div class="am-words">${chips}</div>
        <div class="am-row">
          <div class="am-field">
            <label>Add words or phrases (comma or line separated)</label>
            <input class="am-input" data-addwords="${escHtml(l.list_name)}"
                   placeholder="badword, another phrase here">
          </div>
          <button class="btn btn-gold btn-sm" data-act="addwords"
                  data-list="${escHtml(l.list_name)}">Add</button>
        </div>
        <div class="am-hint">
          A single word matches whole words only, so "ass" will not trip on
          "class". Anything with a space matches as a substring anywhere in the
          message, which is broader. Use the tester before trusting a phrase.
        </div>
      </div>
    </div>`;
  }).join('') : emptyState('&#128221;', 'No word lists yet.');

  return `
    ${banner}
    <div class="am-panel">
      <div class="am-row" style="margin-top:0">
        <div class="am-field">
          <label>New list name</label>
          <input class="am-input" id="am-newlist" placeholder="slurs">
        </div>
        <div class="am-field">
          <label>Starting words (optional)</label>
          <input class="am-input" id="am-newwords" placeholder="comma separated">
        </div>
        <button class="btn btn-gold btn-sm" data-act="newlist">Create list</button>
      </div>
      <div class="am-hint">
        Lists are named only for your own organisation. Every list is checked on
        every message, and all of them share the single action set in Configuration.
      </div>
    </div>

    <div class="am-panel">
      <div class="am-field">
        <label>Test a message against every list</label>
        <input class="am-input" id="am-test" placeholder="Type a message to check…">
      </div>
      <div class="am-row">
        <button class="btn btn-ghost btn-sm" data-act="test">Test</button>
      </div>
      <div id="am-test-result"></div>
      <div class="am-hint">
        Nothing is sent to Discord and no message is deleted. This only reports
        whether the filter would have matched. ${total} ${total === 1 ? 'entry is' : 'entries are'} loaded.
      </div>
    </div>

    ${cards}`;
}

// -- Profiles -----------------------------------------------------------------

function profilesView() {
  const active = _profiles.active;

  const cards = (_profiles.profiles || []).map(p => {
    const open = _open.has('p:' + p.name) ? ' open' : '';
    const cls = p.is_active ? ' active' : (p.built_in ? ' builtin' : '');
    const tags = [
      p.is_active ? '<span class="am-tag active">Active</span>' : '',
      p.built_in ? '<span class="am-tag builtin">Built in</span>' : '',
    ].join(' ');

    const entries = Object.entries(p.overrides || {});
    const rows = entries.length
      ? entries.map(([k, v]) =>
          `<div class="am-ovr-k">${escHtml(k.replace(/_/g, ' '))}</div>
           <div class="am-ovr-v">${escHtml(String(v))}</div>`).join('')
      : '<div class="am-hint">No overrides, so this profile changes nothing.</div>';

    const buttons = [
      p.is_active ? '' :
        `<button class="btn btn-gold btn-sm" data-act="activate" data-name="${escHtml(p.name)}">Activate</button>`,
      (p.built_in || p.is_active) ? '' :
        `<button class="btn btn-danger btn-sm" data-act="delprofile" data-name="${escHtml(p.name)}">Delete</button>`,
    ].join(' ');

    return `
    <div class="am-card${cls}${open}" data-card="p:${escHtml(p.name)}">
      <div class="am-card-head" data-act="toggle" data-list="p:${escHtml(p.name)}">
        <span class="am-name">${escHtml(p.name)}</span>
        <span class="am-meta">${entries.length} override${entries.length === 1 ? '' : 's'}</span>
        ${tags}
        ${buttons}
      </div>
      <div class="am-body">
        <div class="am-ovr">${rows}</div>
      </div>
    </div>`;
  }).join('');

  return `
    <div class="am-banner on">
      <span class="ic">&#9679;</span>
      <span><strong>${escHtml(active)}</strong> is active. Switching takes effect
      immediately with no restart. Raid lockdown switches to
      <strong>raid</strong> on its own and restores the previous profile on unlock.</span>
    </div>

    <div class="am-panel">
      <div class="am-row" style="margin-top:0">
        <div class="am-field">
          <label>Save current settings as a new profile</label>
          <input class="am-input" id="am-snapname" placeholder="before-the-event">
        </div>
        <button class="btn btn-gold btn-sm" data-act="snapshot">Capture</button>
      </div>
      <div class="am-hint">
        Captures every overridable AutoMod setting as it stands right now, so
        you have a known-good state to return to after experimenting. Built-in
        profiles cannot be edited or deleted, which guarantees you always have
        a baseline.
      </div>
    </div>

    ${cards}`;
}

// -- Render -------------------------------------------------------------------

function paint() {
  _root.innerHTML = `
  <div class="am-wrap">
    <div class="am-header">
      <h2>AutoMod</h2>
      <p>Word lists and severity profiles.</p>
    </div>
    <div class="am-tabs">
      <button class="am-tab ${_tab === 'lists' ? 'on' : ''}" data-tab="lists">Word lists</button>
      <button class="am-tab ${_tab === 'profiles' ? 'on' : ''}" data-tab="profiles">Profiles</button>
    </div>
    ${_tab === 'lists' ? listsView() : profilesView()}
  </div>`;
  attach();
}

async function reload() {
  try {
    const [lists, profiles, keys, cfg] = await Promise.all([
      get('/word-lists'),
      get('/profiles'),
      get('/profiles/keys').catch(() => ({ keys: [], actions: [] })),
      get('/config').catch(() => ({})),
    ]);
    _lists = Array.isArray(lists) ? lists : (lists.word_lists || []);
    _profiles = profiles;
    _keys = keys;
    _cfg = cfg;
    paint();
  } catch (err) {
    _root.innerHTML = errorState(`Could not load AutoMod settings. ${apiError(err)}`, reload);
  }
}

// -- Actions ------------------------------------------------------------------

async function newList() {
  const name = (document.getElementById('am-newlist').value || '').trim();
  const words = splitWords(document.getElementById('am-newwords').value);
  if (!name) { toast('A list name is required.', true); return; }
  try {
    await post('/word-lists', { list_name: name, words });
    _open.add(name.toLowerCase());
    toast(`Created "${name}".`);
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function addWords(list) {
  const el = document.querySelector(`[data-addwords="${CSS.escape(list)}"]`);
  const words = splitWords(el ? el.value : '');
  if (!words.length) { toast('Enter at least one word.', true); return; }
  try {
    const r = await post(`/word-lists/${encodeURIComponent(list)}/words`, { words });
    _open.add(list);
    toast(r.added ? `Added ${r.added}.` : 'Already present, nothing added.');
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function delWord(list, word) {
  try {
    await del(`/word-lists/${encodeURIComponent(list)}/words/${encodeURIComponent(word)}`);
    _open.add(list);
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function delList(list) {
  if (!confirm(`Delete the list "${list}" and everything in it?`)) return;
  try {
    await del(`/word-lists/${encodeURIComponent(list)}`);
    toast(`Deleted "${list}".`);
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function runTest() {
  const content = (document.getElementById('am-test').value || '').trim();
  const out = document.getElementById('am-test-result');
  if (!content) { out.innerHTML = ''; return; }
  try {
    const r = await post('/word-lists/test', { content });
    if (r.matched) {
      const hits = r.matches.map(m =>
        `<strong>${escHtml(m.word)}</strong> (${escHtml(m.kind)}, list "${escHtml(m.list_name)}")`
      ).join(', ');
      const live = r.filter_enabled
        ? `This message would be <strong>${escHtml(r.action)}</strong>.`
        : `The filter is currently off, so nothing would actually happen.`;
      out.innerHTML = `<div class="am-result hit">Matched ${hits}. ${live}</div>`;
    } else {
      out.innerHTML = `<div class="am-result miss">No match. This message would pass.</div>`;
    }
  } catch (err) { toast(apiError(err), true); }
}

async function activate(name) {
  try {
    const r = await put('/profiles/active', { name });
    toast(`Switched from ${r.previous} to ${r.active}.`);
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function snapshot() {
  const name = (document.getElementById('am-snapname').value || '').trim();
  if (!name) { toast('Give the profile a name.', true); return; }
  try {
    const r = await post(`/profiles/${encodeURIComponent(name)}/snapshot`, {});
    toast(`Captured ${r.captured} settings into "${r.name}".`);
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function delProfile(name) {
  if (!confirm(`Delete the profile "${name}"?`)) return;
  try {
    await del(`/profiles/${encodeURIComponent(name)}`);
    toast(`Deleted "${name}".`);
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

function attach() {
  _root.querySelectorAll('[data-tab]').forEach(el =>
    el.addEventListener('click', () => { _tab = el.dataset.tab; paint(); }));

  _root.querySelectorAll('[data-act]').forEach(el => {
    el.addEventListener('click', (e) => {
      const act = el.dataset.act;
      if (act === 'toggle' && e.target.closest('button')) return;
      e.stopPropagation();

      switch (act) {
        case 'toggle': {
          const k = el.dataset.list;
          if (_open.has(k)) _open.delete(k); else _open.add(k);
          const card = _root.querySelector(`[data-card="${CSS.escape(k)}"]`);
          if (card) card.classList.toggle('open');
          break;
        }
        case 'newlist':    newList(); break;
        case 'addwords':   addWords(el.dataset.list); break;
        case 'delword':    delWord(el.dataset.list, el.dataset.word); break;
        case 'dellist':    delList(el.dataset.list); break;
        case 'test':       runTest(); break;
        case 'activate':   activate(el.dataset.name); break;
        case 'snapshot':   snapshot(); break;
        case 'delprofile': delProfile(el.dataset.name); break;
      }
    });
  });

  const test = document.getElementById('am-test');
  if (test) test.addEventListener('keydown', e => { if (e.key === 'Enter') runTest(); });
}

// -- Entry point --------------------------------------------------------------

export async function render(el) {
  injectStyles();
  _root = el;
  el.innerHTML = loading('Loading AutoMod settings…');
  await reload();
}
