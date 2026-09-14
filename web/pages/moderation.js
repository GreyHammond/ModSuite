/**
 * moderation.js -- Moderation actions page
 *
 * Endpoints used:
 *   POST   /moderation/{action}              -> warn, kick, ban, unban,
 *                                               mute, unmute, jail, unjail
 *   GET    /moderation/active                -> live mutes, jails, timed bans
 *   DELETE /moderation/violations/{user_id}  -> clear violation counter
 *   GET    /bot-actions                      -> audit trail, including failures
 *
 * Everything is keyed on the numeric Discord user ID, so actions that make
 * sense against someone who has left the server (ban, unban, unjail, clearing
 * violations) work on them. Actions that do not (kick, mute, jail) are
 * disabled in the UI with the reason shown, and refused server-side as well.
 *
 * Actions are queued to the bot rather than executed here. The bot re-checks
 * the permission hierarchy against the logged-in staff member before acting,
 * so nothing is possible here that would not be possible with a slash command.
 */

import { get, post, del } from '../api.js';
import { loading, errorState, emptyState, escHtml, timeAgo } from './utils.js';

let _root = null;
let _active = { mutes: [], jails: [], timed_bans: [], counts: {} };
let _audit = [];
let _tab = 'act';

// Which actions need the target to still be in the server.
const NEEDS_PRESENCE = new Set(['kick', 'mute', 'unmute', 'jail']);

const ACTIONS = [
  { key: 'warn',   label: 'Warn',    tone: 'warn',   duration: false },
  { key: 'mute',   label: 'Mute',    tone: 'mute',   duration: true  },
  { key: 'unmute', label: 'Unmute',  tone: 'ok',     duration: false },
  { key: 'kick',   label: 'Kick',    tone: 'kick',   duration: false },
  { key: 'jail',   label: 'Jail',    tone: 'jail',   duration: true  },
  { key: 'unjail', label: 'Unjail',  tone: 'ok',     duration: false },
  { key: 'ban',    label: 'Ban',     tone: 'ban',    duration: true  },
  { key: 'unban',  label: 'Unban',   tone: 'ok',     duration: false },
];

// -- Styles -------------------------------------------------------------------

function injectStyles() {
  if (document.getElementById('md-styles')) return;
  const s = document.createElement('style');
  s.id = 'md-styles';
  s.textContent = `
    .md-wrap { max-width: 940px; padding: 24px; }
    .md-header h2 { font-size: 20px; font-weight: 600; letter-spacing: -0.02em; }
    .md-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .md-tabs { display: flex; gap: 4px; margin: 18px 0 16px;
               border-bottom: 1px solid var(--border); }
    .md-tab {
      background: none; border: none; padding: 8px 14px;
      font-size: 13px; color: var(--muted); border-bottom: 2px solid transparent;
      margin-bottom: -1px; transition: all var(--transition);
    }
    .md-tab:hover { color: var(--text); }
    .md-tab.on { color: var(--gold); border-bottom-color: var(--gold); }
    .md-tab-count {
      font-size: 10.5px; background: var(--input); border-radius: 999px;
      padding: 1px 6px; margin-left: 5px;
    }

    .md-panel {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 10px; padding: 18px; margin-bottom: 16px;
    }
    .md-row { display: flex; gap: 10px; flex-wrap: wrap; align-items: flex-end; }
    .md-field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 160px; }
    .md-field label { font-size: 11px; color: var(--muted); letter-spacing: 0.03em; }
    .md-input {
      background: var(--input); border: 1px solid var(--border);
      border-radius: 7px; padding: 8px 11px; font-size: 13px;
      color: var(--text); width: 100%; transition: border-color var(--transition);
    }
    .md-input:focus { border-color: rgba(212,168,67,0.4); outline: none; }
    .md-input.mono { font-family: var(--font-mono); }

    .md-target {
      display: flex; align-items: center; gap: 9px; margin-top: 12px;
      font-size: 12.5px; color: var(--muted); min-height: 20px;
    }
    .md-target .ok   { color: var(--color-success); }
    .md-target .gone { color: var(--color-warn); }

    .md-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(108px, 1fr));
      gap: 8px; margin-top: 16px;
    }
    .md-act {
      padding: 10px 8px; border-radius: 8px; font-size: 13px; font-weight: 600;
      border: 1px solid var(--border); background: var(--input); color: var(--text);
      transition: all var(--transition);
    }
    .md-act:hover:not(:disabled) { border-color: currentColor; }
    .md-act:disabled { opacity: 0.32; cursor: not-allowed; }
    .md-act.warn { color: var(--color-warn); }
    .md-act.mute { color: var(--color-mute); }
    .md-act.kick { color: var(--color-kick); }
    .md-act.jail { color: var(--color-jail); }
    .md-act.ban  { color: var(--color-ban);  }
    .md-act.ok   { color: var(--color-success); }

    .md-hint { font-size: 12px; color: var(--muted); margin-top: 12px; line-height: 1.55; }

    .md-item {
      display: flex; align-items: center; gap: 11px;
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid var(--gold);
      border-radius: 9px; padding: 11px 15px; margin-bottom: 8px; font-size: 13px;
    }
    .md-item.mute { border-left-color: var(--color-mute); }
    .md-item.jail { border-left-color: var(--color-jail); }
    .md-item.ban  { border-left-color: var(--color-ban);  }
    .md-item.failed { border-left-color: var(--color-ban); }
    .md-item.pending { border-left-color: var(--color-warn); }
    .md-item.completed { border-left-color: var(--color-success); }

    .md-item-main { flex: 1; min-width: 0; }
    .md-item-name { color: var(--text); font-weight: 600; }
    .md-item-sub {
      font-size: 11.5px; color: var(--muted); margin-top: 2px;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .md-mono { font-family: var(--font-mono); font-size: 11.5px; }
    .md-gone-tag {
      font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em;
      background: rgba(245,158,11,0.14); color: var(--color-warn);
      padding: 2px 7px; border-radius: 999px; white-space: nowrap;
    }

    .md-toast {
      position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
      background: var(--card); border: 1px solid var(--border);
      box-shadow: var(--shadow-elevated); border-radius: 9px;
      padding: 11px 18px; font-size: 13px; color: var(--text); z-index: 900;
      max-width: 90vw;
    }
    .md-toast.err { border-color: rgba(239,68,68,0.4); color: #FCA5A5; }

    @media (max-width: 640px) { .md-wrap { padding: 16px; } }
  `;
  document.head.appendChild(s);
}

// -- Helpers ------------------------------------------------------------------

function toast(msg, isError = false) {
  const el = document.createElement('div');
  el.className = 'md-toast' + (isError ? ' err' : '');
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

function currentUserId() {
  const el = document.getElementById('md-user');
  return (el ? el.value : '').trim().replace(/[<@!>]/g, '');
}

function isValidId(id) { return /^\d{15,20}$/.test(id); }

/** Is the entered ID someone the bot can currently see in the guild? */
function targetPresence(id) {
  const all = [..._active.mutes, ..._active.jails, ..._active.timed_bans];
  const hit = all.find(x => x.user_id === id);
  if (hit) return { known: true, in_guild: hit.in_guild, name: hit.display_name };
  return { known: false, in_guild: null, name: null };
}

// -- Rendering ----------------------------------------------------------------

function actionsPanel() {
  const id = currentUserId();
  const valid = isValidId(id);
  const p = valid ? targetPresence(id) : { known: false, in_guild: null };

  // Only disable presence-dependent actions when we positively know they are
  // gone. An unknown ID is left enabled; the server does the real check.
  const knownAbsent = p.known && p.in_guild === false;

  const buttons = ACTIONS.map(a => {
    const blocked = !valid || (knownAbsent && NEEDS_PRESENCE.has(a.key));
    const title = !valid
      ? 'Enter a valid user ID first'
      : (blocked ? `${a.label} needs them to be in the server` : '');
    return `<button class="md-act ${a.tone}" data-action="${a.key}"
              ${blocked ? 'disabled' : ''} title="${escHtml(title)}">${a.label}</button>`;
  }).join('');

  let status = '<span>Enter a Discord user ID to begin.</span>';
  if (valid && p.known) {
    status = p.in_guild
      ? `<span class="ok">&#10003;</span><span>${escHtml(p.name || 'In the server')}</span>`
      : `<span class="gone">&#9888;</span><span>This user has left the server. Ban, unban, unjail, and clearing violations still work.</span>`;
  } else if (valid) {
    status = '<span>Valid ID. Presence is checked when the action runs.</span>';
  }

  return `
  <div class="md-panel">
    <div class="md-row">
      <div class="md-field">
        <label>Discord user ID</label>
        <input class="md-input mono" id="md-user" placeholder="123456789012345678"
               spellcheck="false" value="${escHtml(id)}">
      </div>
      <div class="md-field" style="flex:0 0 130px">
        <label>Duration (optional)</label>
        <input class="md-input" id="md-duration" placeholder="10m, 2h, 1d" spellcheck="false">
      </div>
    </div>
    <div class="md-row" style="margin-top:10px">
      <div class="md-field">
        <label>Reason</label>
        <input class="md-input" id="md-reason" placeholder="No reason provided.">
      </div>
    </div>

    <div class="md-target">${status}</div>
    <div class="md-grid">${buttons}</div>

    <div class="md-row" style="margin-top:14px">
      <button class="btn btn-ghost btn-sm" data-action="clearviol"
              ${isValidId(id) ? '' : 'disabled'}>Clear violation counter</button>
    </div>

    <div class="md-hint">
      Duration applies to mute, jail, and ban. A ban with a duration becomes a
      temporary ban with automatic unban. Actions are carried out by the bot
      within a few seconds and are logged under your Discord account.
    </div>
  </div>`;
}

function activeList() {
  const rows = [];

  for (const m of _active.mutes) {
    rows.push(row('mute', 'Muted', m, m.until ? `until ${new Date(m.until).toLocaleString()}` : '', 'unmute'));
  }
  for (const j of _active.jails) {
    const when = j.ends ? `until ${new Date(j.ends).toLocaleString()}` : 'no end time';
    rows.push(row('jail', 'Jailed', j, `${when}${j.jailed_by ? ` by ${j.jailed_by}` : ''}`, 'unjail'));
  }
  for (const b of _active.timed_bans) {
    rows.push(row('ban', 'Temp banned', b, b.until ? `auto-unban ${new Date(b.until).toLocaleString()}` : '', 'unban'));
  }

  return rows.length
    ? rows.join('')
    : emptyState('&#10003;', 'Nothing is currently in force.');
}

function row(tone, verb, x, detail, undoAction) {
  const name = x.display_name || 'Unknown user';
  const gone = x.in_guild ? '' : '<span class="md-gone-tag">Left server</span>';
  return `
  <div class="md-item ${tone}">
    <div class="md-item-main">
      <div class="md-item-name">${escHtml(name)}
        <span class="md-mono" style="color:var(--muted)">${escHtml(x.user_id)}</span> ${gone}</div>
      <div class="md-item-sub">${escHtml(verb)}${detail ? ' &middot; ' + escHtml(detail) : ''}${x.reason ? ' &middot; ' + escHtml(x.reason) : ''}</div>
    </div>
    <button class="btn btn-ghost btn-sm" data-action="undo"
            data-undo="${undoAction}" data-uid="${escHtml(x.user_id)}">Lift</button>
  </div>`;
}

function auditList() {
  if (!_audit.length) return emptyState('&#128220;', 'No dashboard actions recorded yet.');
  return _audit.map(a => `
    <div class="md-item ${escHtml(a.status)}">
      <div class="md-item-main">
        <div class="md-item-name">${escHtml(a.action_type)}
          ${a.target_id ? `<span class="md-mono" style="color:var(--muted)">${escHtml(a.target_id)}</span>` : ''}</div>
        <div class="md-item-sub">
          ${escHtml(a.status)}${a.actor_name ? ' &middot; by ' + escHtml(a.actor_name) : ''}
          &middot; ${escHtml(timeAgo(a.created_at))}${a.reason ? ' &middot; ' + escHtml(a.reason) : ''}
        </div>
      </div>
    </div>`).join('');
}

function paint() {
  const c = _active.counts || {};
  const live = (c.mutes || 0) + (c.jails || 0) + (c.timed_bans || 0);
  const failed = _audit.filter(a => a.status === 'failed').length;

  let body;
  if (_tab === 'act') body = actionsPanel();
  else if (_tab === 'active') body = activeList();
  else body = auditList();

  _root.innerHTML = `
  <div class="md-wrap">
    <div class="md-header">
      <h2>Moderation</h2>
      <p>Act on any member by user ID, including people who have left.</p>
    </div>

    <div class="md-tabs">
      <button class="md-tab ${_tab === 'act' ? 'on' : ''}" data-tab="act">Take action</button>
      <button class="md-tab ${_tab === 'active' ? 'on' : ''}" data-tab="active">In force
        ${live ? `<span class="md-tab-count">${live}</span>` : ''}</button>
      <button class="md-tab ${_tab === 'audit' ? 'on' : ''}" data-tab="audit">Audit log
        ${failed ? `<span class="md-tab-count">${failed} failed</span>` : ''}</button>
    </div>

    ${body}
  </div>`;

  attach();
}

// -- Actions ------------------------------------------------------------------

async function reload() {
  try {
    const [active, audit] = await Promise.all([
      get('/moderation/active'),
      get('/bot-actions?limit=60').catch(() => ({ actions: [] })),
    ]);
    _active = active;
    _audit = audit.actions || [];
    paint();
  } catch (err) {
    _root.innerHTML = errorState(`Could not load moderation state. ${apiError(err)}`, reload);
  }
}

async function runAction(action, uidOverride) {
  const uid = uidOverride || currentUserId();
  if (!isValidId(uid)) {
    toast('Enter a valid Discord user ID. Turn on Developer Mode, right-click the member, and choose Copy User ID.', true);
    return;
  }

  const durEl = document.getElementById('md-duration');
  const reaEl = document.getElementById('md-reason');
  const duration = durEl ? durEl.value.trim() : '';
  const reason = (reaEl ? reaEl.value.trim() : '') || 'No reason provided.';

  const destructive = ['ban', 'kick', 'jail'].includes(action);
  if (destructive && !confirm(`${action.toUpperCase()} user ${uid}?\n\nReason: ${reason}`)) return;

  try {
    await post(`/moderation/${action}`, {
      user_id: uid,
      reason,
      duration: duration || null,
      notify: true,
    });
    toast(`${action} queued for ${uid}. Check the audit log if it does not take effect.`);
    if (reaEl) reaEl.value = '';
    if (durEl) durEl.value = '';
    setTimeout(reload, 4000);
  } catch (err) {
    toast(apiError(err), true);
  }
}

async function clearViolations() {
  const uid = currentUserId();
  if (!isValidId(uid)) { toast('Enter a valid Discord user ID.', true); return; }
  try {
    const r = await del(`/moderation/violations/${uid}`);
    toast(`Cleared ${r.cleared} violation(s).`);
  } catch (err) {
    toast(apiError(err), true);
  }
}

function attach() {
  _root.querySelectorAll('[data-tab]').forEach(el =>
    el.addEventListener('click', () => { _tab = el.dataset.tab; paint(); }));

  _root.querySelectorAll('[data-action]').forEach(el =>
    el.addEventListener('click', () => {
      const a = el.dataset.action;
      if (a === 'clearviol') return clearViolations();
      if (a === 'undo') return runAction(el.dataset.undo, el.dataset.uid);
      runAction(a);
    }));

  // Repaint the action grid as the ID changes so presence-dependent buttons
  // enable and disable live, without losing focus or caret position.
  const user = document.getElementById('md-user');
  if (user) {
    user.addEventListener('input', () => {
      const pos = user.selectionStart;
      const dur = document.getElementById('md-duration').value;
      const rea = document.getElementById('md-reason').value;
      paint();
      const again = document.getElementById('md-user');
      document.getElementById('md-duration').value = dur;
      document.getElementById('md-reason').value = rea;
      again.focus();
      again.setSelectionRange(pos, pos);
    });
  }
}

// -- Entry point --------------------------------------------------------------

export async function render(el) {
  injectStyles();
  _root = el;
  el.innerHTML = loading('Loading moderation state…');
  await reload();
}
