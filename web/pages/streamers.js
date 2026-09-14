/**
 * streamers.js -- Streamer management page
 *
 * Endpoints used:
 *   GET    /streamers                              -> list with presence flags
 *   POST   /streamers                              -> register (queues bot work)
 *   PUT    /streamers/{id}                         -> change Twitch username
 *   DELETE /streamers/{id}                         -> remove, channel and role too
 *   POST   /streamers/{id}/links                   -> add a profile link
 *   DELETE /streamers/{id}/links/{label}           -> remove a profile link
 *
 * Every operation is keyed on the numeric Discord user ID rather than a member
 * object, so a streamer who has left the server can still be edited and
 * removed. Those rows are surfaced explicitly at the top of the list, since
 * cleaning them up is the main reason to open this page.
 */

import { get, post, put, del } from '../api.js';
import { loading, errorState, emptyState, escHtml } from './utils.js';

let _streamers = [];
let _expanded = new Set();
let _root = null;

// -- Styles -------------------------------------------------------------------

function injectStyles() {
  if (document.getElementById('st-styles')) return;
  const s = document.createElement('style');
  s.id = 'st-styles';
  s.textContent = `
    .st-wrap { max-width: 940px; padding: 24px; }
    .st-header {
      display: flex; align-items: flex-start; justify-content: space-between;
      margin-bottom: 20px; flex-wrap: wrap; gap: 12px;
    }
    .st-header h2 {
      font-size: 20px; font-weight: 600; color: var(--text);
      letter-spacing: -0.02em;
    }
    .st-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .st-banner {
      display: flex; align-items: center; gap: 10px;
      background: rgba(245,158,11,0.08);
      border: 1px solid rgba(245,158,11,0.25);
      border-radius: 9px; padding: 11px 15px;
      font-size: 13px; color: var(--text); margin-bottom: 16px;
    }
    .st-banner .st-banner-icon { color: var(--color-warn); flex-shrink: 0; }

    .st-list { display: flex; flex-direction: column; gap: 10px; }

    .st-card {
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid var(--gold); border-radius: 10px;
      overflow: hidden; transition: border-color var(--transition);
    }
    .st-card.gone { border-left-color: var(--color-warn); }
    .st-card.live { border-left-color: var(--color-ban); }

    .st-card-header {
      display: flex; align-items: center; gap: 12px;
      padding: 13px 16px; cursor: pointer; user-select: none;
    }
    .st-card-header:hover { background: rgba(255,255,255,0.02); }

    .st-avatar {
      width: 32px; height: 32px; border-radius: 50%;
      background: var(--input); flex-shrink: 0; object-fit: cover;
      display: flex; align-items: center; justify-content: center;
      font-size: 13px; color: var(--muted); font-weight: 600;
    }
    .st-twitch {
      font-family: var(--font-mono); font-size: 13px; font-weight: 600;
      color: var(--gold); background: var(--gold-faint);
      border: 1px solid rgba(212,168,67,0.25);
      border-radius: 6px; padding: 3px 10px; white-space: nowrap;
    }
    .st-who {
      flex: 1; min-width: 0; font-size: 12.5px; color: var(--muted);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .st-id { font-family: var(--font-mono); font-size: 11.5px; }

    .st-pill {
      font-size: 10.5px; font-weight: 600; letter-spacing: 0.04em;
      text-transform: uppercase; padding: 2px 8px; border-radius: 999px;
      white-space: nowrap; flex-shrink: 0;
    }
    .st-pill.live  { background: rgba(239,68,68,0.14); color: var(--color-ban); }
    .st-pill.gone  { background: rgba(245,158,11,0.14); color: var(--color-warn); }
    .st-pill.nochan{ background: rgba(139,92,246,0.14); color: var(--color-jail); }

    .st-actions { display: flex; gap: 6px; flex-shrink: 0; }

    .st-body {
      display: none; padding: 4px 16px 16px;
      border-top: 1px solid var(--border);
    }
    .st-card.open .st-body { display: block; }

    .st-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; margin-top: 14px; }
    .st-field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 170px; }
    .st-field label { font-size: 11px; color: var(--muted); letter-spacing: 0.03em; }
    .st-input {
      background: var(--input); border: 1px solid var(--border);
      border-radius: 7px; padding: 7px 11px; font-size: 13px;
      color: var(--text); width: 100%; transition: border-color var(--transition);
    }
    .st-input:focus { border-color: rgba(212,168,67,0.4); outline: none; }

    .st-subhead {
      font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--muted); margin: 18px 0 8px;
    }
    .st-links { display: flex; flex-direction: column; gap: 6px; }
    .st-link {
      display: flex; align-items: center; gap: 10px;
      background: var(--input); border-radius: 7px; padding: 7px 11px;
      font-size: 12.5px;
    }
    .st-link-label { font-weight: 600; color: var(--text); flex-shrink: 0; }
    .st-link-url {
      flex: 1; min-width: 0; color: var(--muted);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .st-note { font-size: 12px; color: var(--muted); margin-top: 10px; line-height: 1.55; }

    .st-toast {
      position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
      background: var(--card); border: 1px solid var(--border);
      box-shadow: var(--shadow-elevated); border-radius: 9px;
      padding: 11px 18px; font-size: 13px; color: var(--text); z-index: 900;
    }
    .st-toast.err { border-color: rgba(239,68,68,0.4); color: #FCA5A5; }

    @media (max-width: 640px) {
      .st-wrap { padding: 16px; }
      .st-card-header { flex-wrap: wrap; }
      .st-who { flex-basis: 100%; order: 5; }
    }
  `;
  document.head.appendChild(s);
}

// -- Helpers ------------------------------------------------------------------

function toast(msg, isError = false) {
  const el = document.createElement('div');
  el.className = 'st-toast' + (isError ? ' err' : '');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), isError ? 5200 : 2800);
}

/** Pull the readable part out of a FastAPI error body. */
function apiError(err) {
  const raw = String(err && err.message ? err.message : err);
  const at = raw.indexOf('{');
  if (at !== -1) {
    try {
      const parsed = JSON.parse(raw.slice(at));
      const d = parsed.detail;
      if (typeof d === 'string') return d;
      if (d && typeof d.error === 'string') return d.error;
    } catch { /* fall through to the raw text */ }
  }
  return raw;
}

// -- Rendering ----------------------------------------------------------------

function cardHtml(s) {
  const open = _expanded.has(s.streamer_id) ? ' open' : '';
  const state = !s.in_guild ? ' gone' : (s.is_live ? ' live' : '');

  const initial = escHtml((s.display_name || s.twitch_username || '?').slice(0, 1).toUpperCase());
  const avatar = s.avatar_url
    ? `<img class="st-avatar" src="${escHtml(s.avatar_url)}" alt="">`
    : `<div class="st-avatar">${initial}</div>`;

  const who = s.in_guild
    ? `${escHtml(s.display_name || 'Unknown')} <span class="st-id">(${escHtml(s.user_id)})</span>`
    : `<span class="st-id">${escHtml(s.user_id)}</span>`;

  const pills = [];
  if (s.is_live) pills.push('<span class="st-pill live">Live</span>');
  if (!s.in_guild) pills.push('<span class="st-pill gone">Left server</span>');
  if (s.channel_missing) pills.push('<span class="st-pill nochan">No channel</span>');

  const links = (s.links || []).length
    ? s.links.map(l => `
        <div class="st-link">
          <span class="st-link-label">${escHtml(l.label)}</span>
          <span class="st-link-url">${escHtml(l.url)}</span>
          <button class="btn btn-danger btn-sm" data-act="dellink"
                  data-id="${s.streamer_id}" data-label="${escHtml(l.label)}">Remove</button>
        </div>`).join('')
    : `<div class="st-note">No links on their profile card yet.</div>`;

  const goneNote = s.in_guild ? '' : `
    <div class="st-note">
      This streamer is no longer in the server. Removing them still deletes
      their channel and clears the database record; there is simply no role
      left to strip.
    </div>`;

  return `
  <div class="st-card${state}${open}" data-card="${s.streamer_id}">
    <div class="st-card-header" data-act="toggle" data-id="${s.streamer_id}">
      ${avatar}
      <span class="st-twitch">${escHtml(s.twitch_username)}</span>
      <span class="st-who">${who}</span>
      ${pills.join('')}
      <div class="st-actions">
        <button class="btn btn-danger btn-sm" data-act="remove" data-id="${s.streamer_id}">Remove</button>
      </div>
    </div>
    <div class="st-body">
      ${goneNote}
      <div class="st-row">
        <div class="st-field">
          <label>Twitch username</label>
          <input class="st-input" data-edit="${s.streamer_id}"
                 value="${escHtml(s.twitch_username)}" spellcheck="false">
        </div>
        <button class="btn btn-gold btn-sm" data-act="save" data-id="${s.streamer_id}">Save</button>
      </div>
      <div class="st-note">
        Renaming also renames their chat channel. Discord rate limits channel
        renames to twice per ten minutes, so the channel name may lag behind.
      </div>

      <div class="st-subhead">Profile links</div>
      <div class="st-links">${links}</div>
      <div class="st-row">
        <div class="st-field" style="flex:0 0 150px">
          <label>Label</label>
          <input class="st-input" data-linklabel="${s.streamer_id}" placeholder="YouTube">
        </div>
        <div class="st-field">
          <label>URL</label>
          <input class="st-input" data-linkurl="${s.streamer_id}"
                 placeholder="https://youtube.com/@handle" spellcheck="false">
        </div>
        <button class="btn btn-ghost btn-sm" data-act="addlink" data-id="${s.streamer_id}">Add link</button>
      </div>
    </div>
  </div>`;
}

function paint() {
  const orphans = _streamers.filter(s => !s.in_guild).length;

  const banner = orphans ? `
    <div class="st-banner">
      <span class="st-banner-icon">&#9888;</span>
      <span><strong>${orphans}</strong> streamer${orphans === 1 ? ' has' : 's have'}
      left the server. Their channels and records are still here. Remove them
      below to clean up.</span>
    </div>` : '';

  const list = _streamers.length
    ? `<div class="st-list">${_streamers.map(cardHtml).join('')}</div>`
    : emptyState('&#128225;', 'No streamers registered yet.');

  _root.innerHTML = `
  <div class="st-wrap">
    <div class="st-header">
      <div>
        <h2>Streamers</h2>
        <p>Manage streamer channels, Twitch names, and profile links.</p>
      </div>
    </div>

    <div class="st-card" style="border-left-color: var(--color-success); margin-bottom:16px">
      <div class="st-body" style="display:block; border-top:none; padding-top:14px">
        <div class="st-subhead" style="margin-top:0">Add a streamer</div>
        <div class="st-row" style="margin-top:0">
          <div class="st-field">
            <label>Discord user ID</label>
            <input class="st-input" id="st-new-user" placeholder="123456789012345678" spellcheck="false">
          </div>
          <div class="st-field">
            <label>Twitch username</label>
            <input class="st-input" id="st-new-twitch" placeholder="theirhandle" spellcheck="false">
          </div>
          <button class="btn btn-gold btn-sm" data-act="create">Add streamer</button>
        </div>
        <div class="st-note">
          Adding creates their chat channel and grants the Streamer role, so
          they need to be in the server. Everything else on this page works by
          user ID whether they are here or not.
        </div>
      </div>
    </div>

    ${banner}
    ${list}
  </div>`;

  attachHandlers();
}

// -- Actions ------------------------------------------------------------------

async function reload() {
  try {
    const data = await get('/streamers');
    _streamers = data.streamers || [];
    paint();
  } catch (err) {
    _root.innerHTML = errorState(`Could not load streamers. ${apiError(err)}`, reload);
  }
}

async function doCreate() {
  const userEl = document.getElementById('st-new-user');
  const twitchEl = document.getElementById('st-new-twitch');
  const userId = (userEl.value || '').trim();
  const twitch = (twitchEl.value || '').trim();

  if (!/^\d{15,20}$/.test(userId)) {
    toast('That does not look like a Discord user ID. Enable Developer Mode, right-click the member, and choose Copy User ID.', true);
    return;
  }
  if (!twitch) { toast('A Twitch username is required.', true); return; }

  try {
    await post('/streamers', { user_id: userId, twitch_username: twitch });
    userEl.value = '';
    twitchEl.value = '';
    toast('Streamer queued. Their channel appears within a few seconds.');
    // The bot creates the channel on its next poll, so give it a beat.
    setTimeout(reload, 5500);
  } catch (err) {
    toast(apiError(err), true);
  }
}

async function doSave(id) {
  const el = document.querySelector(`[data-edit="${id}"]`);
  const twitch = (el.value || '').trim();
  if (!twitch) { toast('A Twitch username is required.', true); return; }
  try {
    await put(`/streamers/${id}`, { twitch_username: twitch });
    toast('Updated.');
    await reload();
  } catch (err) {
    toast(apiError(err), true);
  }
}

async function doRemove(id) {
  const s = _streamers.find(x => String(x.streamer_id) === String(id));
  if (!s) return;
  const warning = s.in_guild
    ? `Remove ${s.twitch_username}? Their chat channel will be deleted and the Streamer role removed.`
    : `Remove ${s.twitch_username}? They have already left the server, so this deletes their channel and clears the record.`;
  if (!confirm(warning)) return;

  try {
    await del(`/streamers/${id}`);
    toast('Removed. The channel is deleted on the next bot poll.');
    await reload();
  } catch (err) {
    toast(apiError(err), true);
  }
}

async function doAddLink(id) {
  const labelEl = document.querySelector(`[data-linklabel="${id}"]`);
  const urlEl = document.querySelector(`[data-linkurl="${id}"]`);
  const label = (labelEl.value || '').trim();
  const url = (urlEl.value || '').trim();
  if (!label || !url) { toast('Both a label and a URL are required.', true); return; }

  try {
    await post(`/streamers/${id}/links`, { label, url });
    _expanded.add(Number(id));
    toast('Link added.');
    await reload();
  } catch (err) {
    toast(apiError(err), true);
  }
}

async function doDelLink(id, label) {
  try {
    await del(`/streamers/${id}/links/${encodeURIComponent(label)}`);
    _expanded.add(Number(id));
    toast('Link removed.');
    await reload();
  } catch (err) {
    toast(apiError(err), true);
  }
}

function attachHandlers() {
  _root.querySelectorAll('[data-act]').forEach(el => {
    const act = el.dataset.act;
    const id = el.dataset.id;

    el.addEventListener('click', (e) => {
      // Header is the toggle target, but buttons inside it are not.
      if (act === 'toggle' && e.target.closest('button')) return;
      e.stopPropagation();

      switch (act) {
        case 'toggle': {
          const n = Number(id);
          if (_expanded.has(n)) _expanded.delete(n); else _expanded.add(n);
          const card = _root.querySelector(`[data-card="${id}"]`);
          if (card) card.classList.toggle('open');
          break;
        }
        case 'create':  doCreate();  break;
        case 'save':    doSave(id);  break;
        case 'remove':  doRemove(id); break;
        case 'addlink': doAddLink(id); break;
        case 'dellink': doDelLink(id, el.dataset.label); break;
      }
    });
  });
}

// -- Entry point --------------------------------------------------------------

export async function render(el) {
  injectStyles();
  _root = el;
  el.innerHTML = loading('Loading streamers…');
  await reload();
}
