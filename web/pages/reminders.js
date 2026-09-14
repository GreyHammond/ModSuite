/**
 * reminders.js -- Scheduled reminders
 *
 * Endpoints used:
 *   GET    /reminders?include_fired=  -> guild-wide, not just one user's
 *   DELETE /reminders/{id}            -> cancel
 *
 * Read-mostly by design. Reminders are created by members through /remindme,
 * so the dashboard's job is visibility and cleanup rather than authoring: it
 * answers "what is scheduled to fire in my server" and lets staff cancel
 * something inappropriate or left behind by someone who has since left.
 */

import { get, del } from '../api.js';
import { loading, errorState, emptyState, escHtml } from './utils.js';

let _root = null;
let _reminders = [];
let _showFired = false;

function injectStyles() {
  if (document.getElementById('rm-styles')) return;
  const s = document.createElement('style');
  s.id = 'rm-styles';
  s.textContent = `
    .rm-wrap { max-width: 940px; padding: 24px; }
    .rm-header { display: flex; align-items: flex-start; justify-content: space-between;
                 gap: 12px; flex-wrap: wrap; }
    .rm-header h2 { font-size: 20px; font-weight: 600; letter-spacing: -0.02em; }
    .rm-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .rm-toggle { display: flex; align-items: center; gap: 8px; font-size: 13px;
                 color: var(--muted); }

    .rm-summary { display: flex; gap: 10px; margin: 18px 0 14px; flex-wrap: wrap; }
    .rm-stat { background: var(--card); border: 1px solid var(--border);
               border-radius: 9px; padding: 11px 16px; min-width: 108px; }
    .rm-stat-n { font-size: 20px; font-weight: 600; color: var(--gold); }
    .rm-stat-l { font-size: 11px; color: var(--muted); text-transform: uppercase;
                 letter-spacing: 0.05em; margin-top: 2px; }

    .rm-item { display: flex; align-items: flex-start; gap: 12px;
               background: var(--card); border: 1px solid var(--border);
               border-left: 3px solid var(--gold); border-radius: 9px;
               padding: 12px 15px; margin-bottom: 8px; }
    .rm-item.fired { border-left-color: var(--border); opacity: 0.62; }
    .rm-item.soon  { border-left-color: var(--color-warn); }
    .rm-item.overdue { border-left-color: var(--color-ban); }

    .rm-main { flex: 1; min-width: 0; }
    .rm-msg { font-size: 13.5px; color: var(--text); line-height: 1.5;
              word-break: break-word; }
    .rm-sub { font-size: 11.5px; color: var(--muted); margin-top: 4px; }
    .rm-mono { font-family: var(--font-mono); font-size: 11px; }
    .rm-when { font-weight: 600; color: var(--text); }
    .rm-tag { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em;
              padding: 2px 7px; border-radius: 999px; white-space: nowrap;
              margin-left: 6px; }
    .rm-tag.gone { background: rgba(245,158,11,0.14); color: var(--color-warn); }
    .rm-tag.overdue { background: rgba(239,68,68,0.14); color: var(--color-ban); }
    .rm-tag.fired { background: var(--input); color: var(--muted); }

    .rm-toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
      background: var(--card); border: 1px solid var(--border);
      box-shadow: var(--shadow-elevated); border-radius: 9px; padding: 11px 18px;
      font-size: 13px; color: var(--text); z-index: 900; max-width: 90vw; }
    .rm-toast.err { border-color: rgba(239,68,68,0.4); color: #FCA5A5; }

    @media (max-width: 640px) { .rm-wrap { padding: 16px; } }
  `;
  document.head.appendChild(s);
}

function toast(msg, isError = false) {
  const el = document.createElement('div');
  el.className = 'rm-toast' + (isError ? ' err' : '');
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

/** Human-readable gap between now and a future timestamp. */
function untilText(iso) {
  if (!iso) return { text: 'unknown', state: '' };
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return { text: 'unknown', state: '' };

  const diff = then - Date.now();
  const abs = Math.abs(diff);
  const mins = Math.round(abs / 60000);
  const hrs = Math.round(abs / 3600000);
  const days = Math.round(abs / 86400000);

  let span;
  if (mins < 1) span = 'less than a minute';
  else if (mins < 60) span = `${mins} minute${mins === 1 ? '' : 's'}`;
  else if (hrs < 48) span = `${hrs} hour${hrs === 1 ? '' : 's'}`;
  else span = `${days} day${days === 1 ? '' : 's'}`;

  if (diff < 0) {
    // The bot polls on an interval, so a small overshoot is normal. A large
    // one means the loop is not running.
    return { text: `${span} overdue`, state: mins > 10 ? 'overdue' : '' };
  }
  return { text: `in ${span}`, state: mins < 60 ? 'soon' : '' };
}

function itemHtml(r) {
  const u = r.fired ? { text: 'fired', state: '' } : untilText(r.fire_at);
  const cls = r.fired ? 'fired' : u.state;

  const who = r.display_name
    ? escHtml(r.display_name)
    : `<span class="rm-mono">${escHtml(r.user_id)}</span>`;
  const goneTag = (!r.in_guild && !r.fired)
    ? '<span class="rm-tag gone">Left server</span>' : '';
  const firedTag = r.fired ? '<span class="rm-tag fired">Fired</span>' : '';
  const overdueTag = u.state === 'overdue'
    ? '<span class="rm-tag overdue">Overdue</span>' : '';

  const when = r.fire_at ? new Date(r.fire_at).toLocaleString() : 'unknown';

  return `
  <div class="rm-item ${cls}">
    <div class="rm-main">
      <div class="rm-msg">${escHtml(r.message || '(no message)')}</div>
      <div class="rm-sub">
        For ${who}${goneTag}${firedTag}${overdueTag}
        &middot; <span class="rm-when">${escHtml(u.text)}</span>
        &middot; ${escHtml(when)}
        ${r.channel_name ? '&middot; #' + escHtml(r.channel_name) : ''}
      </div>
    </div>
    <button class="btn btn-danger btn-sm" data-act="cancel" data-id="${r.reminder_id}">
      ${r.fired ? 'Remove' : 'Cancel'}</button>
  </div>`;
}

function paint() {
  const pending = _reminders.filter(r => !r.fired);
  const overdue = pending.filter(r => untilText(r.fire_at).state === 'overdue').length;
  const orphaned = pending.filter(r => !r.in_guild).length;

  const list = _reminders.length
    ? _reminders.map(itemHtml).join('')
    : emptyState('&#9200;', _showFired
        ? 'No reminders at all.'
        : 'Nothing scheduled. Members create these with /remindme.');

  _root.innerHTML = `
  <div class="rm-wrap">
    <div class="rm-header">
      <div>
        <h2>Reminders</h2>
        <p>Everything members have scheduled with /remindme.</p>
      </div>
      <label class="rm-toggle">
        <input type="checkbox" id="rm-fired" ${_showFired ? 'checked' : ''}>
        Show already fired
      </label>
    </div>

    <div class="rm-summary">
      <div class="rm-stat"><div class="rm-stat-n">${pending.length}</div>
        <div class="rm-stat-l">Pending</div></div>
      <div class="rm-stat"><div class="rm-stat-n">${overdue}</div>
        <div class="rm-stat-l">Overdue</div></div>
      <div class="rm-stat"><div class="rm-stat-n">${orphaned}</div>
        <div class="rm-stat-l">Owner left</div></div>
    </div>

    ${overdue ? `<div class="rm-sub" style="color:var(--color-warn);margin-bottom:12px">
      ${overdue} reminder${overdue === 1 ? ' is' : 's are'} more than ten minutes
      past due. That usually means the bot's reminder loop is not running.</div>` : ''}

    ${list}
  </div>`;
  attach();
}

async function reload() {
  try {
    const data = await get(`/reminders?include_fired=${_showFired}&limit=200`);
    _reminders = data.reminders || [];
    paint();
  } catch (err) {
    _root.innerHTML = errorState(`Could not load reminders. ${apiError(err)}`, reload);
  }
}

async function cancel(id) {
  const r = _reminders.find(x => String(x.reminder_id) === String(id));
  const label = r ? `"${r.message}"` : `#${id}`;
  if (!confirm(`Cancel the reminder ${label}?`)) return;
  try {
    await del(`/reminders/${id}`);
    toast('Reminder cancelled.');
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

function attach() {
  _root.querySelectorAll('[data-act="cancel"]').forEach(el =>
    el.addEventListener('click', () => cancel(el.dataset.id)));

  const chk = document.getElementById('rm-fired');
  if (chk) chk.addEventListener('change', () => {
    _showFired = chk.checked;
    reload();
  });
}

export async function render(el) {
  injectStyles();
  _root = el;
  el.innerHTML = loading('Loading reminders\u2026');
  await reload();
}
