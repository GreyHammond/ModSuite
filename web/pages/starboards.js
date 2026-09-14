/**
 * starboards.js -- Starboard management
 *
 * Endpoints used:
 *   GET    /starboards                          -> boards with emojis + counts
 *   POST   /starboards                          -> create
 *   PUT    /starboards/{id}                     -> channel, threshold, nsfw
 *   DELETE /starboards/{id}                     -> delete board and its entries
 *   POST   /starboards/{id}/emojis              -> add a trigger emoji
 *   DELETE /starboards/{id}/emojis/{emoji}      -> remove one
 *   GET    /channels                            -> channel picker
 *
 * A board is a channel plus a reaction threshold plus one or more trigger
 * emojis. Two failure modes are surfaced explicitly because both are silent in
 * Discord: a board pointing at a deleted channel, and a board with no trigger
 * emoji left.
 */

import { get, post, put, del } from '../api.js';
import { loading, errorState, emptyState, escHtml } from './utils.js';

let _root = null;
let _boards = [];
let _channels = [];
let _open = new Set();

function injectStyles() {
  if (document.getElementById('sb-styles')) return;
  const s = document.createElement('style');
  s.id = 'sb-styles';
  s.textContent = `
    .sb-wrap { max-width: 940px; padding: 24px; }
    .sb-header h2 { font-size: 20px; font-weight: 600; letter-spacing: -0.02em; }
    .sb-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .sb-panel { background: var(--card); border: 1px solid var(--border);
                border-radius: 10px; padding: 16px; margin: 18px 0 14px; }
    .sb-card { background: var(--card); border: 1px solid var(--border);
               border-left: 3px solid var(--gold); border-radius: 10px;
               overflow: hidden; margin-bottom: 10px; }
    .sb-card.broken { border-left-color: var(--color-warn); }

    .sb-head { display: flex; align-items: center; gap: 11px; padding: 13px 16px;
               cursor: pointer; user-select: none; flex-wrap: wrap; }
    .sb-head:hover { background: rgba(255,255,255,0.02); }
    .sb-name { font-weight: 600; font-size: 14px; }
    .sb-emojis { font-size: 15px; letter-spacing: 2px; }
    .sb-meta { flex: 1; font-size: 12px; color: var(--muted); min-width: 120px; }
    .sb-tag { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em;
              padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
    .sb-tag.warn { background: rgba(245,158,11,0.14); color: var(--color-warn); }
    .sb-tag.nsfw { background: rgba(239,68,68,0.14); color: var(--color-ban); }

    .sb-body { display: none; padding: 4px 16px 16px; border-top: 1px solid var(--border); }
    .sb-card.open .sb-body { display: block; }

    .sb-row { display: flex; gap: 9px; flex-wrap: wrap; align-items: flex-end; margin-top: 13px; }
    .sb-field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 145px; }
    .sb-field label { font-size: 11px; color: var(--muted); letter-spacing: 0.03em; }
    .sb-input, .sb-select {
      background: var(--input); border: 1px solid var(--border); border-radius: 7px;
      padding: 8px 11px; font-size: 13px; color: var(--text); width: 100%;
    }
    .sb-input:focus, .sb-select:focus { border-color: rgba(212,168,67,0.4); outline: none; }

    .sb-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
    .sb-chip { display: inline-flex; align-items: center; gap: 6px;
               background: var(--input); border: 1px solid var(--border);
               border-radius: 999px; padding: 4px 6px 4px 12px; font-size: 15px; }
    .sb-chip button { background: none; border: none; color: var(--muted);
                      font-size: 13px; padding: 0 4px; border-radius: 50%; }
    .sb-chip button:hover { color: var(--color-ban); }

    .sb-check { display: flex; align-items: center; gap: 8px; font-size: 13px;
                color: var(--text); margin-top: 12px; }
    .sb-hint { font-size: 12px; color: var(--muted); margin-top: 10px; line-height: 1.55; }

    .sb-toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
      background: var(--card); border: 1px solid var(--border);
      box-shadow: var(--shadow-elevated); border-radius: 9px; padding: 11px 18px;
      font-size: 13px; color: var(--text); z-index: 900; max-width: 90vw; }
    .sb-toast.err { border-color: rgba(239,68,68,0.4); color: #FCA5A5; }

    @media (max-width: 640px) { .sb-wrap { padding: 16px; } }
  `;
  document.head.appendChild(s);
}

function toast(msg, isError = false) {
  const el = document.createElement('div');
  el.className = 'sb-toast' + (isError ? ' err' : '');
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

function channelOptions(selected) {
  return _channels.map(c =>
    `<option value="${escHtml(c.channel_id)}" ${c.channel_id === String(selected) ? 'selected' : ''}>
       #${escHtml(c.name)}${c.category ? ' \u00b7 ' + escHtml(c.category) : ''}</option>`
  ).join('');
}

function cardHtml(b) {
  const open = _open.has(b.board_id) ? ' open' : '';
  const broken = b.channel_missing ? ' broken' : '';

  const tags = [
    b.channel_missing ? '<span class="sb-tag warn">Channel deleted</span>' : '',
    b.nsfw_only ? '<span class="sb-tag nsfw">NSFW only</span>' : '',
  ].join(' ');

  const chips = (b.emojis || []).map(e => `
    <span class="sb-chip">${escHtml(e)}
      <button data-act="delemoji" data-id="${b.board_id}" data-emoji="${escHtml(e)}"
              title="Remove">&times;</button></span>`).join('');

  return `
  <div class="sb-card${broken}${open}" data-card="${b.board_id}">
    <div class="sb-head" data-act="toggle" data-id="${b.board_id}">
      <span class="sb-emojis">${(b.emojis || []).join('')}</span>
      <span class="sb-name">${escHtml(b.name)}</span>
      <span class="sb-meta">
        ${b.channel_name ? '#' + escHtml(b.channel_name) : '<em>missing channel</em>'}
        &middot; ${b.threshold} reaction${b.threshold === 1 ? '' : 's'}
        &middot; ${b.entry_count} post${b.entry_count === 1 ? '' : 's'}
      </span>
      ${tags}
      <button class="btn btn-danger btn-sm" data-act="delboard" data-id="${b.board_id}">Delete</button>
    </div>
    <div class="sb-body">
      ${b.channel_missing ? `<div class="sb-hint" style="color:var(--color-warn)">
        The channel this board posts to no longer exists, so nothing is being
        starred. Pick a new one below.</div>` : ''}

      <div class="sb-row">
        <div class="sb-field">
          <label>Post to channel</label>
          <select class="sb-select" data-chan="${b.board_id}">
            <option value="">Select a channel\u2026</option>
            ${channelOptions(b.channel_id)}
          </select>
        </div>
        <div class="sb-field" style="flex:0 0 120px">
          <label>Reactions needed</label>
          <input class="sb-input" type="number" min="1" max="100"
                 data-thresh="${b.board_id}" value="${b.threshold}">
        </div>
        <button class="btn btn-gold btn-sm" data-act="save" data-id="${b.board_id}">Save</button>
      </div>

      <label class="sb-check">
        <input type="checkbox" data-nsfw="${b.board_id}" ${b.nsfw_only ? 'checked' : ''}>
        Only star posts from NSFW channels
      </label>

      <div class="sb-hint" style="margin-top:16px">Trigger emojis</div>
      <div class="sb-chips">${chips}</div>
      <div class="sb-row">
        <div class="sb-field" style="flex:0 0 130px">
          <label>Add emoji</label>
          <input class="sb-input" data-newemoji="${b.board_id}" placeholder="\u2b50">
        </div>
        <button class="btn btn-ghost btn-sm" data-act="addemoji" data-id="${b.board_id}">Add</button>
      </div>
      <div class="sb-hint">
        An emoji can only drive one board, since the bot looks a board up by
        emoji alone. A board must keep at least one emoji or it can never fire.
      </div>
    </div>
  </div>`;
}

function paint() {
  const broken = _boards.filter(b => b.channel_missing).length;

  _root.innerHTML = `
  <div class="sb-wrap">
    <div class="sb-header">
      <h2>Starboards</h2>
      <p>Pin popular posts to a channel when they hit a reaction threshold.</p>
    </div>

    <div class="sb-panel">
      <div class="sb-row" style="margin-top:0">
        <div class="sb-field" style="flex:0 0 140px">
          <label>Board name</label>
          <input class="sb-input" id="sb-name" placeholder="starboard">
        </div>
        <div class="sb-field">
          <label>Channel</label>
          <select class="sb-select" id="sb-chan">
            <option value="">Select a channel\u2026</option>${channelOptions('')}
          </select>
        </div>
        <div class="sb-field" style="flex:0 0 110px">
          <label>Threshold</label>
          <input class="sb-input" type="number" id="sb-thresh" value="5" min="1" max="100">
        </div>
        <div class="sb-field" style="flex:0 0 100px">
          <label>Emoji</label>
          <input class="sb-input" id="sb-emoji" value="\u2b50">
        </div>
        <button class="btn btn-gold btn-sm" data-act="create">Create</button>
      </div>
      <div class="sb-hint">
        You can run several boards at once with different emojis and thresholds,
        for example a public one on \u2b50 and a staff one on \ud83d\udccc.
      </div>
    </div>

    ${broken ? `<div class="sb-hint" style="color:var(--color-warn);margin-bottom:12px">
      ${broken} board${broken === 1 ? '' : 's'} point at a channel that no longer
      exists and ${broken === 1 ? 'is' : 'are'} silently doing nothing.</div>` : ''}

    ${_boards.length ? _boards.map(cardHtml).join('') : emptyState('&#11088;', 'No starboards yet.')}
  </div>`;
  attach();
}

async function reload() {
  try {
    const [boards, channels] = await Promise.all([
      get('/starboards'),
      get('/channels').catch(() => []),
    ]);
    _boards = boards.starboards || [];
    _channels = Array.isArray(channels) ? channels : [];
    paint();
  } catch (err) {
    _root.innerHTML = errorState(`Could not load starboards. ${apiError(err)}`, reload);
  }
}

async function create() {
  const name = (document.getElementById('sb-name').value || '').trim();
  const channel_id = document.getElementById('sb-chan').value;
  const threshold = parseInt(document.getElementById('sb-thresh').value, 10);
  const emoji = (document.getElementById('sb-emoji').value || '').trim();

  if (!name) { toast('Give the board a name.', true); return; }
  if (!channel_id) { toast('Pick a channel for the board to post into.', true); return; }
  if (!emoji) { toast('Pick at least one trigger emoji.', true); return; }

  try {
    const r = await post('/starboards', {
      name, channel_id, threshold: threshold || 5,
      nsfw_only: false, emojis: [emoji],
    });
    _open.add(r.board_id);
    toast(`Created "${r.name}".`);
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function save(id) {
  const chan = document.querySelector(`[data-chan="${id}"]`).value;
  const thresh = parseInt(document.querySelector(`[data-thresh="${id}"]`).value, 10);
  const nsfw = document.querySelector(`[data-nsfw="${id}"]`).checked;
  if (!chan) { toast('Pick a channel.', true); return; }
  try {
    await put(`/starboards/${id}`, {
      channel_id: chan, threshold: thresh || 5, nsfw_only: nsfw,
    });
    _open.add(Number(id));
    toast('Saved.');
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function delBoard(id) {
  const b = _boards.find(x => String(x.board_id) === String(id));
  const extra = b && b.entry_count
    ? `\n\nIts ${b.entry_count} starred post record${b.entry_count === 1 ? '' : 's'} will also be cleared. Messages already posted to the channel stay.`
    : '';
  if (!confirm(`Delete the "${b ? b.name : id}" board?${extra}`)) return;
  try {
    await del(`/starboards/${id}`);
    toast('Board deleted.');
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function addEmoji(id) {
  const el = document.querySelector(`[data-newemoji="${id}"]`);
  const emoji = (el.value || '').trim();
  if (!emoji) { toast('Enter an emoji.', true); return; }
  try {
    await post(`/starboards/${id}/emojis`, { emoji });
    _open.add(Number(id));
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

async function delEmoji(id, emoji) {
  try {
    await del(`/starboards/${id}/emojis/${encodeURIComponent(emoji)}`);
    _open.add(Number(id));
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

function attach() {
  _root.querySelectorAll('[data-act]').forEach(el => {
    el.addEventListener('click', (e) => {
      const act = el.dataset.act;
      if (act === 'toggle' && (e.target.closest('button') || e.target.closest('select') ||
          e.target.closest('input'))) return;
      e.stopPropagation();
      switch (act) {
        case 'toggle': {
          const n = Number(el.dataset.id);
          if (_open.has(n)) _open.delete(n); else _open.add(n);
          const c = _root.querySelector(`[data-card="${el.dataset.id}"]`);
          if (c) c.classList.toggle('open');
          break;
        }
        case 'create':   create(); break;
        case 'save':     save(el.dataset.id); break;
        case 'delboard': delBoard(el.dataset.id); break;
        case 'addemoji': addEmoji(el.dataset.id); break;
        case 'delemoji': delEmoji(el.dataset.id, el.dataset.emoji); break;
      }
    });
  });
}

export async function render(el) {
  injectStyles();
  _root = el;
  el.innerHTML = loading('Loading starboards\u2026');
  await reload();
}
