/**
 * reactroles.js -- React-role message builder
 *
 * Endpoints used:
 *   GET    /react-messages          -> published messages with their mappings
 *   GET    /react-messages/roles    -> assignable roles for the picker
 *   POST   /react-messages          -> compose and publish
 *   PUT    /react-messages/{id}     -> edit and republish in place
 *   DELETE /react-messages/{id}     -> delete, optionally removing the message
 *   GET    /channels                -> channel picker
 *
 * This maps *existing* roles to emojis. That is deliberately different from the
 * Self Roles page, which creates brand new Discord roles from names. Both write
 * to selfrole_categories, so the same reaction handler drives them.
 *
 * The Discord /createreactmessage flow needs a live draft message in a channel
 * to render previews into. Here the form is the preview, so there is no draft
 * step at all: compose, check the preview, publish once.
 */

import { get, post, put, del } from '../api.js';
import { loading, errorState, emptyState, escHtml } from './utils.js';

let _root = null;
let _messages = [];
let _roles = [];
let _channels = [];
let _editing = null;     // null = not composing, 'new' = new message, or an id
let _draft = null;       // { title, intro_text, channel_id, roles: [...] }

function injectStyles() {
  if (document.getElementById('rr-styles')) return;
  const s = document.createElement('style');
  s.id = 'rr-styles';
  s.textContent = `
    .rr-wrap { max-width: 940px; padding: 24px; }
    .rr-header { display: flex; align-items: flex-start; justify-content: space-between;
                 gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
    .rr-header h2 { font-size: 20px; font-weight: 600; letter-spacing: -0.02em; }
    .rr-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .rr-panel { background: var(--card); border: 1px solid var(--border);
                border-radius: 10px; padding: 18px; margin-bottom: 14px; }

    .rr-card { background: var(--card); border: 1px solid var(--border);
               border-left: 3px solid var(--gold); border-radius: 10px;
               padding: 13px 16px; margin-bottom: 9px;
               display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .rr-card.unpublished { border-left-color: var(--color-warn); }
    .rr-card.broken { border-left-color: var(--color-ban); }
    .rr-card-main { flex: 1; min-width: 160px; }
    .rr-card-title { font-weight: 600; font-size: 14px; color: var(--text); }
    .rr-card-sub { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
    .rr-emoji-strip { font-size: 15px; letter-spacing: 3px; }

    .rr-tag { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em;
              padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
    .rr-tag.warn { background: rgba(245,158,11,0.14); color: var(--color-warn); }
    .rr-tag.bad  { background: rgba(239,68,68,0.14); color: var(--color-ban); }
    .rr-tag.mode { background: rgba(59,130,246,0.14); color: var(--color-mute); }

    .rr-row { display: flex; gap: 9px; flex-wrap: wrap; align-items: flex-end; margin-top: 12px; }
    .rr-field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 150px; }
    .rr-field label { font-size: 11px; color: var(--muted); letter-spacing: 0.03em; }
    .rr-input, .rr-select, .rr-textarea {
      background: var(--input); border: 1px solid var(--border); border-radius: 7px;
      padding: 8px 11px; font-size: 13px; color: var(--text); width: 100%;
      font-family: inherit;
    }
    .rr-textarea { min-height: 68px; resize: vertical; line-height: 1.5; }
    .rr-input:focus, .rr-select:focus, .rr-textarea:focus {
      border-color: rgba(212,168,67,0.4); outline: none; }

    .rr-map { display: flex; align-items: center; gap: 8px;
              background: var(--input); border: 1px solid var(--border);
              border-radius: 8px; padding: 7px 10px; margin-bottom: 6px; }
    .rr-map-emoji { font-size: 17px; width: 30px; text-align: center; flex-shrink: 0; }
    .rr-map-role { flex: 1; min-width: 0; font-size: 13px; color: var(--text);
                   overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .rr-map-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
    .rr-map.missing .rr-map-role { color: var(--color-ban); }

    .rr-preview {
      border-left: 4px solid var(--gold); background: rgba(255,255,255,0.02);
      border-radius: 4px; padding: 13px 15px; margin-top: 14px;
    }
    .rr-preview-title { font-weight: 600; font-size: 15px; color: var(--text); margin-bottom: 7px; }
    .rr-preview-body { font-size: 13px; color: var(--text); line-height: 1.6;
                       white-space: pre-wrap; word-break: break-word; }
    .rr-preview-role { color: var(--gold); }
    .rr-preview-foot { font-size: 11px; color: var(--muted); margin-top: 10px; }
    .rr-preview-rx { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 10px; }
    .rr-preview-rx span { background: var(--input); border: 1px solid var(--border);
                          border-radius: 7px; padding: 2px 8px; font-size: 14px; }

    .rr-hint { font-size: 12px; color: var(--muted); margin-top: 11px; line-height: 1.55; }
    .rr-warn { font-size: 12px; color: var(--color-warn); margin-top: 10px; line-height: 1.55; }

    .rr-toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
      background: var(--card); border: 1px solid var(--border);
      box-shadow: var(--shadow-elevated); border-radius: 9px; padding: 11px 18px;
      font-size: 13px; color: var(--text); z-index: 900; max-width: 90vw; }
    .rr-toast.err { border-color: rgba(239,68,68,0.4); color: #FCA5A5; }

    @media (max-width: 640px) { .rr-wrap { padding: 16px; } }
  `;
  document.head.appendChild(s);
}

function toast(msg, isError = false) {
  const el = document.createElement('div');
  el.className = 'rr-toast' + (isError ? ' err' : '');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), isError ? 6500 : 3000);
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

function roleById(id) {
  return _roles.find(r => r.role_id === String(id));
}

function channelOptions(selected) {
  return _channels.map(c =>
    `<option value="${escHtml(c.channel_id)}" ${c.channel_id === String(selected) ? 'selected' : ''}>
       #${escHtml(c.name)}${c.category ? ' \u00b7 ' + escHtml(c.category) : ''}</option>`
  ).join('');
}

function roleOptions(selected) {
  const used = new Set((_draft ? _draft.roles : []).map(r => String(r.role_id)));
  return _roles.map(r => {
    // Already-mapped roles stay listed but disabled, so it is obvious why a
    // role is unavailable rather than it simply vanishing from the list.
    const taken = used.has(r.role_id) && r.role_id !== String(selected);
    const why = !r.assignable ? ' (above the bot, cannot assign)' : (taken ? ' (already used)' : '');
    return `<option value="${escHtml(r.role_id)}"
              ${r.role_id === String(selected) ? 'selected' : ''}
              ${(!r.assignable || taken) ? 'disabled' : ''}>
              ${escHtml(r.name)}${why}</option>`;
  }).join('');
}

// -- Composer -----------------------------------------------------------------

function previewHtml() {
  const d = _draft;
  const lines = d.roles.map(r => {
    const role = roleById(r.role_id);
    return `\u2192 ${escHtml(r.emoji)} <span class="rr-preview-role">@${escHtml(role ? role.name : r.role_id)}</span>`;
  }).join('<br>');

  const body = [escHtml(d.intro_text || ''), lines].filter(Boolean).join('<br><br>');
  const rx = d.roles.map(r => `<span>${escHtml(r.emoji)}</span>`).join('');

  return `
  <div class="rr-preview">
    <div class="rr-preview-title">${escHtml(d.title || 'Untitled')}</div>
    <div class="rr-preview-body">${body || '<em style="color:var(--muted)">Nothing to show yet.</em>'}</div>
    <div class="rr-preview-foot">Remove your reaction to unassign the role.</div>
    ${rx ? `<div class="rr-preview-rx">${rx}</div>` : ''}
  </div>`;
}

function composerHtml() {
  const d = _draft;
  const isNew = _editing === 'new';

  const maps = d.roles.length ? d.roles.map((r, i) => {
    const role = roleById(r.role_id);
    const dot = role && role.color
      ? `<span class="rr-map-dot" style="background:${escHtml(role.color)}"></span>` : '';
    return `
    <div class="rr-map ${role ? '' : 'missing'}">
      <span class="rr-map-emoji">${escHtml(r.emoji)}</span>
      ${dot}
      <span class="rr-map-role">${escHtml(role ? role.name : 'Deleted role ' + r.role_id)}</span>
      <label style="font-size:11.5px;color:var(--muted);display:flex;gap:5px;align-items:center">
        <input type="checkbox" data-toggle="${i}" ${r.toggle ? 'checked' : ''}> single
      </label>
      <button class="btn btn-danger btn-sm" data-act="unmap" data-i="${i}">Remove</button>
    </div>`;
  }).join('') : '<div class="rr-hint">No roles mapped yet. Add at least one below.</div>';

  const anyToggle = d.roles.some(r => r.toggle);
  const cap = d.roles.length >= 20;

  return `
  <div class="rr-panel">
    <div class="rr-header" style="margin-bottom:0">
      <div><h2 style="font-size:16px">${isNew ? 'New react-role message' : 'Editing message'}</h2></div>
      <button class="btn btn-ghost btn-sm" data-act="cancel">Cancel</button>
    </div>

    <div class="rr-row">
      <div class="rr-field">
        <label>Title</label>
        <input class="rr-input" id="rr-title" value="${escHtml(d.title)}"
               placeholder="Pick your roles">
      </div>
      <div class="rr-field">
        <label>Channel</label>
        <select class="rr-select" id="rr-chan" ${isNew ? '' : 'disabled'}>
          <option value="">Select a channel\u2026</option>${channelOptions(d.channel_id)}
        </select>
      </div>
    </div>
    ${isNew ? '' : '<div class="rr-hint">The channel cannot be changed after publishing. Delete and recreate the message to move it.</div>'}

    <div class="rr-row">
      <div class="rr-field">
        <label>Intro text (optional)</label>
        <textarea class="rr-textarea" id="rr-intro"
                  placeholder="React below to give yourself a role.">${escHtml(d.intro_text)}</textarea>
      </div>
    </div>

    <div class="rr-hint" style="margin-top:18px">Emoji to role mappings</div>
    <div style="margin-top:8px">${maps}</div>

    <div class="rr-row">
      <div class="rr-field" style="flex:0 0 110px">
        <label>Emoji</label>
        <input class="rr-input" id="rr-emoji" placeholder="\ud83c\udfae" ${cap ? 'disabled' : ''}>
      </div>
      <div class="rr-field">
        <label>Role</label>
        <select class="rr-select" id="rr-role" ${cap ? 'disabled' : ''}>
          <option value="">Select a role\u2026</option>${roleOptions('')}
        </select>
      </div>
      <button class="btn btn-ghost btn-sm" data-act="map" ${cap ? 'disabled' : ''}>Add mapping</button>
    </div>
    ${cap ? '<div class="rr-warn">Discord allows at most 20 reactions on one message. Split into two messages if you need more.</div>' : ''}

    <div class="rr-hint">
      Ticking <strong>single</strong> on any mapping makes the whole message
      single-choice: reacting to one option removes the others.
      ${anyToggle ? ' It is currently single-choice.' : ' It is currently multi-choice.'}
    </div>

    ${previewHtml()}

    <div class="rr-row">
      <button class="btn btn-gold btn-sm" data-act="publish">
        ${isNew ? 'Publish to Discord' : 'Save and update message'}</button>
    </div>
    <div class="rr-hint">
      ${isNew
        ? 'Publishing posts the message and adds every reaction.'
        : 'Existing reactions are kept where the mapping is unchanged, so members do not lose roles or have to react again.'}
    </div>
  </div>`;
}

// -- List ---------------------------------------------------------------------

function cardHtml(m) {
  const broken = (m.roles || []).some(r => r.role_missing);
  const cls = !m.published ? ' unpublished' : (broken ? ' broken' : '');
  const single = (m.roles || []).some(r => r.toggle);

  const tags = [
    !m.published ? '<span class="rr-tag warn">Not posted</span>' : '',
    broken ? '<span class="rr-tag bad">Deleted role</span>' : '',
    `<span class="rr-tag mode">${single ? 'Single choice' : 'Multi choice'}</span>`,
  ].join(' ');

  return `
  <div class="rr-card${cls}">
    <span class="rr-emoji-strip">${(m.roles || []).map(r => escHtml(r.emoji)).join('')}</span>
    <div class="rr-card-main">
      <div class="rr-card-title">${escHtml(m.title || 'Untitled')}</div>
      <div class="rr-card-sub">
        ${m.channel_name ? '#' + escHtml(m.channel_name) : '<em>no channel</em>'}
        &middot; ${(m.roles || []).length} role${(m.roles || []).length === 1 ? '' : 's'}
      </div>
    </div>
    ${tags}
    <button class="btn btn-ghost btn-sm" data-act="edit" data-id="${m.category_id}">Edit</button>
    <button class="btn btn-danger btn-sm" data-act="delete" data-id="${m.category_id}">Delete</button>
  </div>`;
}

function paint() {
  const notAssignable = _roles.filter(r => !r.assignable).length;

  const body = _editing
    ? composerHtml()
    : `${_messages.length
          ? _messages.map(cardHtml).join('')
          : emptyState('&#127918;', 'No react-role messages yet.')}`;

  _root.innerHTML = `
  <div class="rr-wrap">
    <div class="rr-header">
      <div>
        <h2>React Roles</h2>
        <p>Map existing roles to emojis and post a self-assign message.</p>
      </div>
      ${_editing ? '' : '<button class="btn btn-gold btn-sm" data-act="new">New message</button>'}
    </div>

    ${(!_editing && notAssignable) ? `<div class="rr-warn" style="margin-bottom:12px">
      ${notAssignable} role${notAssignable === 1 ? ' sits' : 's sit'} above the bot's
      highest role and cannot be assigned. Move the bot's role higher in Server
      Settings if you need ${notAssignable === 1 ? 'it' : 'them'} here.</div>` : ''}

    ${body}
  </div>`;
  attach();
}

async function reload() {
  try {
    const [msgs, roles, channels] = await Promise.all([
      get('/react-messages'),
      get('/react-messages/roles').catch(() => ({ roles: [] })),
      get('/channels').catch(() => []),
    ]);
    _messages = msgs.messages || [];
    _roles = roles.roles || [];
    _channels = Array.isArray(channels) ? channels : [];
    paint();
  } catch (err) {
    _root.innerHTML = errorState(`Could not load react-role messages. ${apiError(err)}`, reload);
  }
}

// -- Draft state --------------------------------------------------------------

/** Pull the current form values into _draft so a repaint does not lose them. */
function syncDraft() {
  const t = document.getElementById('rr-title');
  const i = document.getElementById('rr-intro');
  const c = document.getElementById('rr-chan');
  if (t) _draft.title = t.value;
  if (i) _draft.intro_text = i.value;
  if (c && !c.disabled) _draft.channel_id = c.value;
}

function startNew() {
  _editing = 'new';
  _draft = { title: '', intro_text: '', channel_id: '', roles: [] };
  paint();
}

function startEdit(id) {
  const m = _messages.find(x => String(x.category_id) === String(id));
  if (!m) return;
  _editing = m.category_id;
  _draft = {
    title: m.title || '',
    intro_text: m.intro_text || '',
    channel_id: m.channel_id || '',
    roles: (m.roles || []).map(r => ({
      emoji: r.emoji, role_id: String(r.role_id), toggle: !!r.toggle,
    })),
  };
  paint();
}

function addMapping() {
  syncDraft();
  const emoji = (document.getElementById('rr-emoji').value || '').trim();
  const role_id = document.getElementById('rr-role').value;

  if (!emoji) { toast('Pick an emoji.', true); return; }
  if (!role_id) { toast('Pick a role.', true); return; }
  if (_draft.roles.some(r => r.emoji === emoji)) {
    toast('That emoji is already used on this message. Each emoji must map to exactly one role.', true);
    return;
  }
  _draft.roles.push({ emoji, role_id, toggle: false });
  paint();
}

function removeMapping(i) {
  syncDraft();
  _draft.roles.splice(Number(i), 1);
  paint();
}

async function publish() {
  syncDraft();
  const d = _draft;

  if (!d.title.trim()) { toast('Give the message a title.', true); return; }
  if (!d.roles.length) { toast('Add at least one emoji-to-role mapping.', true); return; }
  if (_editing === 'new' && !d.channel_id) { toast('Pick a channel to post into.', true); return; }

  const payload = {
    title: d.title.trim(),
    intro_text: d.intro_text,
    roles: d.roles.map(r => ({ emoji: r.emoji, role_id: r.role_id, toggle: r.toggle })),
  };

  try {
    if (_editing === 'new') {
      await post('/react-messages', { ...payload, channel_id: d.channel_id });
      toast('Publishing. The message appears within a few seconds.');
    } else {
      await put(`/react-messages/${_editing}`, payload);
      toast('Saved. The message updates within a few seconds.');
    }
    _editing = null;
    _draft = null;
    // The bot posts on its next poll, so give it a beat before re-reading.
    setTimeout(reload, 4500);
    paint();
  } catch (err) { toast(apiError(err), true); }
}

async function remove(id) {
  const m = _messages.find(x => String(x.category_id) === String(id));
  const name = m ? m.title : `#${id}`;
  if (!confirm(`Delete "${name}"?\n\nThe posted message will be removed from Discord. Members keep any roles they already have.`)) return;
  try {
    await del(`/react-messages/${id}`);
    toast('Deleted.');
    await reload();
  } catch (err) { toast(apiError(err), true); }
}

function attach() {
  _root.querySelectorAll('[data-act]').forEach(el => {
    el.addEventListener('click', () => {
      switch (el.dataset.act) {
        case 'new':     startNew(); break;
        case 'edit':    startEdit(el.dataset.id); break;
        case 'delete':  remove(el.dataset.id); break;
        case 'cancel':  _editing = null; _draft = null; paint(); break;
        case 'map':     addMapping(); break;
        case 'unmap':   removeMapping(el.dataset.i); break;
        case 'publish': publish(); break;
      }
    });
  });

  // Live preview as the title and intro are typed, without a full repaint
  // (which would steal focus mid-keystroke).
  ['rr-title', 'rr-intro'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => {
      syncDraft();
      const old = _root.querySelector('.rr-preview');
      if (old) old.outerHTML = previewHtml();
    });
  });

  _root.querySelectorAll('[data-toggle]').forEach(el =>
    el.addEventListener('change', () => {
      syncDraft();
      _draft.roles[Number(el.dataset.toggle)].toggle = el.checked;
      paint();
    }));
}

export async function render(el) {
  injectStyles();
  _root = el;
  _editing = null;
  _draft = null;
  el.innerHTML = loading('Loading react-role messages\u2026');
  await reload();
}
