/**
 * configuration.js — Wave 1
 *
 * Sectioned editor driven by /config-schema.
 * Also keeps the original Bot Messages editor + Post-as-Bot panels.
 *
 * Endpoints used:
 *   GET  /config-schema         → sections + fields metadata
 *   GET  /config                → current values
 *   PUT  /config                → partial update
 *   GET  /bot-messages          → message templates
 *   PUT  /bot-messages/{slot}   → update template
 *   DELETE /bot-messages/{slot} → reset to default
 *   GET  /channels              → for post-as-bot
 *   POST /post-as-bot           → queue message
 */

import { get, post, put, del } from '../api.js';

// ── Slot metadata for Bot Messages panel ─────────────────────────────────────

const SLOT_META = {
  warn_dm:         { label: 'Warn DM',         vars: ['{user}', '{reason}'] },
  jail_dm:         { label: 'Jail DM',         vars: ['{user}', '{reason}', '{duration}'] },
  unjail_dm:       { label: 'Unjail DM',       vars: ['{user}'] },
  mute_dm:         { label: 'Mute DM',         vars: ['{user}', '{reason}', '{duration}'] },
  ban_dm:          { label: 'Ban DM',          vars: ['{user}', '{reason}'] },
  join_message:    { label: 'Join Message',    vars: ['{user}'] },
  welcome_message: { label: 'Welcome Message', vars: ['{user}'] },
};

// ── Styles ────────────────────────────────────────────────────────────────────

function injectStyles() {
  if (document.getElementById('cfg-styles')) return;
  const s = document.createElement('style');
  s.id = 'cfg-styles';
  s.textContent = `
    .cfg-wrap { display:flex; flex-direction:column; gap:16px; max-width:900px; padding:24px; }

    .cfg-panel-title {
      font-size:13px; font-weight:600; color:var(--text);
      margin:0 0 4px; padding:16px 20px 12px;
      border-bottom:1px solid var(--border);
      letter-spacing:.02em; display:flex; align-items:center; gap:8px;
    }
    .cfg-panel-desc {
      font-size:11.5px; color:var(--muted);
      padding:0 20px 14px;
      border-bottom:1px solid var(--border);
      line-height:1.5;
    }

    /* Section list (top tabs style) */
    .cfg-tabs {
      display:flex; flex-wrap:wrap; gap:4px;
      padding:12px 12px 0;
      border-bottom:1px solid var(--border);
      background:var(--card-2);
    }
    .cfg-tab {
      background:none; border:none; color:var(--muted);
      font:inherit; font-size:12px; font-weight:500;
      padding:8px 12px; border-radius:6px 6px 0 0;
      cursor:pointer; transition:color var(--fast), background var(--fast);
      border-bottom:2px solid transparent;
    }
    .cfg-tab:hover { color:var(--text); background:rgba(255,255,255,.03); }
    .cfg-tab.active {
      color:var(--gold);
      background:var(--card);
      border-bottom-color:var(--gold);
    }

    .cfg-section-body { padding:18px 20px; display:flex; flex-direction:column; gap:14px; }

    /* Field rows */
    .cfg-field { display:flex; flex-direction:column; gap:5px; }
    .cfg-field-label {
      display:flex; align-items:baseline; gap:8px;
      font-size:12px; font-weight:600; color:var(--text);
    }
    .cfg-field-key {
      font-family:var(--font-mono); font-size:10px;
      color:var(--muted); font-weight:400;
    }
    .cfg-field-hint {
      font-size:11px; color:var(--muted); line-height:1.5;
      margin-top:-1px;
    }
    .cfg-input, .cfg-select, .cfg-ta {
      width:100%; background:var(--card-2); border:1px solid var(--border);
      border-radius:var(--radius); color:var(--text); font-size:13px;
      font-family:inherit; padding:8px 11px; box-sizing:border-box;
      outline:none; transition:border-color var(--fast);
    }
    .cfg-input:focus, .cfg-select:focus, .cfg-ta:focus { border-color:var(--border-focus); }
    .cfg-input.dirty, .cfg-select.dirty, .cfg-ta.dirty { border-color:rgba(212,168,67,.4); }
    .cfg-ta { min-height:60px; resize:vertical; font-family:var(--font-mono); font-size:12px; }
    .cfg-select {
      appearance:none; padding-right:32px;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='11' viewBox='0 0 24 24' fill='none' stroke='%238888A0' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
      background-repeat:no-repeat; background-position:right 10px center;
    }

    /* Bool toggle */
    .cfg-bool {
      display:inline-flex; align-items:center; gap:9px;
      cursor:pointer; user-select:none;
    }
    .cfg-bool input { position:absolute; opacity:0; pointer-events:none; }
    .cfg-bool-vis {
      width:36px; height:20px; background:var(--border);
      border-radius:12px; position:relative; transition:background var(--fast);
    }
    .cfg-bool-vis::after {
      content:''; position:absolute; top:2px; left:2px;
      width:16px; height:16px; border-radius:50%;
      background:var(--text); transition:transform var(--fast);
    }
    .cfg-bool input:checked ~ .cfg-bool-vis { background:var(--gold); }
    .cfg-bool input:checked ~ .cfg-bool-vis::after { transform:translateX(16px); background:#1a1200; }
    .cfg-bool-lbl { font-size:12.5px; color:var(--muted); }

    /* Save row */
    .cfg-save-row {
      display:flex; align-items:center; gap:12px;
      margin-top:8px; padding:14px 20px;
      border-top:1px solid var(--border);
      background:var(--card-2);
    }
    .cfg-status { font-size:12px; }
    .cfg-status.ok  { color:var(--green); }
    .cfg-status.err { color:var(--red); }
    .cfg-dirty-count {
      font-family:var(--font-mono); font-size:11px; color:var(--muted);
      margin-left:auto;
    }

    /* ─── Bot Messages panel (kept) ─── */
    .cfg-slot { padding:16px 20px; border-bottom:1px solid var(--border); }
    .cfg-slot:last-of-type { border-bottom:none; }
    .cfg-slot-header {
      display:flex; align-items:center; gap:8px;
      margin-bottom:8px; flex-wrap:wrap;
    }
    .cfg-slot-label { font-size:13px; font-weight:600; color:var(--text); }
    .cfg-vars { display:flex; gap:4px; flex-wrap:wrap; }
    .cfg-chip {
      font-family:var(--font-mono); font-size:11px;
      color:var(--gold); background:var(--gold-faint);
      border:1px solid rgba(212,168,67,.25);
      border-radius:var(--radius-sm); padding:1px 6px;
    }
    .cfg-reset-link {
      margin-left:auto; font-size:11.5px; color:var(--muted);
      background:none; border:none; padding:0;
      text-decoration:underline; text-underline-offset:2px;
      cursor:pointer; transition:color var(--fast);
    }
    .cfg-reset-link:hover { color:var(--text); }
    .cfg-reset-link[hidden] { display:none; }

    /* ─── Post as Bot ─── */
    .cfg-field-l { display:block; font-size:11.5px; font-weight:600;
      color:var(--muted); text-transform:uppercase;
      letter-spacing:.07em; margin-bottom:6px; }
  `;
  document.head.appendChild(s);
}

// ── State ─────────────────────────────────────────────────────────────────────

let _schema = null;      // { sections: [...] }
let _config = null;      // current config values
let _dirty  = new Map(); // key -> new value
let _activeSection = 'general';

// ── Entry point ───────────────────────────────────────────────────────────────

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="cfg-wrap">
    <div class="skeleton" style="height:340px;border-radius:10px"></div>
    <div class="skeleton" style="height:280px;border-radius:10px"></div>
  </div>`;

  try {
    const [schema, config] = await Promise.all([
      get('/config-schema'),
      get('/config'),
    ]);
    _schema = schema;
    _config = config;
    _dirty  = new Map();
    _activeSection = schema.sections[0]?.id || 'general';

    container.innerHTML = buildPage();
    attach(container);
    await loadBotMessagesPanel(container);
    await loadPostAsBotPanel(container);
  } catch (e) {
    container.innerHTML = `<div class="cfg-wrap"><div class="error-state">
      <div class="state-icon">⚠️</div>
      <p>Could not load configuration. Is the bot running?</p>
      <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
    </div></div>`;
  }
}

function buildPage() {
  return `<div class="cfg-wrap">
    <!-- Sectioned config editor -->
    <div class="card" style="overflow:hidden">
      <div class="cfg-panel-title">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        Server Configuration
      </div>
      <div class="cfg-tabs" id="cfg-tabs">
        ${_schema.sections.map(sec => `
          <button class="cfg-tab ${sec.id === _activeSection ? 'active' : ''}" data-section="${sec.id}">
            ${esc(sec.label)}
          </button>
        `).join('')}
      </div>
      <div id="cfg-section-body">${renderSection(_activeSection)}</div>
      <div class="cfg-save-row">
        <button class="btn btn-primary" id="cfg-save" disabled>Save changes</button>
        <button class="btn btn-ghost"   id="cfg-discard" disabled>Discard</button>
        <span class="cfg-status" id="cfg-status"></span>
        <span class="cfg-dirty-count" id="cfg-dirty-count"></span>
      </div>
    </div>

    <!-- Bot Messages (existing panel) -->
    <div class="card" id="cfg-messages-panel" style="overflow:hidden">
      <div class="cfg-panel-title">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        Bot Messages
      </div>
      <div class="cfg-panel-desc">Templates the bot sends in DMs and channels. Placeholders like <code style="color:var(--gold)">{user}</code> get filled at send time.</div>
      <div id="cfg-messages-body"><div class="skeleton" style="height:200px;margin:20px"></div></div>
    </div>

    <!-- Post as Bot -->
    <div class="card" id="cfg-post-panel" style="overflow:hidden">
      <div class="cfg-panel-title">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        Post as Bot
      </div>
      <div class="cfg-panel-desc">Send a message from the bot to any channel.</div>
      <div id="cfg-post-body" style="padding:18px 20px"><div class="skeleton" style="height:120px"></div></div>
    </div>
  </div>`;
}

// ── Section renderer ─────────────────────────────────────────────────────────

function renderSection(sectionId) {
  const sec = _schema.sections.find(s => s.id === sectionId);
  if (!sec) return `<div style="padding:20px;color:var(--muted)">Unknown section.</div>`;

  return `<div class="cfg-section-body">
    ${sec.description ? `<div class="cfg-panel-desc" style="padding:0;border:none;margin-bottom:6px">${esc(sec.description)}</div>` : ''}
    ${sec.fields.map(f => renderField(f)).join('')}
  </div>`;
}

function renderField(f) {
  const cur   = _dirty.has(f.key) ? _dirty.get(f.key) : _config[f.key];
  const dirty = _dirty.has(f.key);
  const dCls  = dirty ? 'dirty' : '';

  let input = '';

  if (f.type === 'bool') {
    const checked = !!cur ? 'checked' : '';
    input = `
      <label class="cfg-bool">
        <input type="checkbox" data-key="${f.key}" data-type="bool" ${checked}>
        <span class="cfg-bool-vis"></span>
        <span class="cfg-bool-lbl">${checked ? 'On' : 'Off'}</span>
      </label>`;
  } else if (f.type === 'select') {
    input = `
      <select class="cfg-select ${dCls}" data-key="${f.key}" data-type="select">
        ${(f.options || []).map(o =>
          `<option value="${esc(o.value)}"${cur === o.value ? ' selected' : ''}>${esc(o.label)}</option>`
        ).join('')}
      </select>`;
  } else if (f.type === 'number') {
    const min = f.min != null ? `min="${f.min}"` : '';
    const max = f.max != null ? `max="${f.max}"` : '';
    input = `<input class="cfg-input ${dCls}" type="number" data-key="${f.key}" data-type="number" ${min} ${max} value="${cur ?? ''}">`;
  } else if (f.type === 'json_list') {
    let val = cur;
    if (typeof val !== 'string') val = JSON.stringify(val || []);
    input = `<textarea class="cfg-ta ${dCls}" data-key="${f.key}" data-type="json_list" spellcheck="false">${esc(val)}</textarea>`;
  } else {
    input = `<input class="cfg-input ${dCls}" type="text" data-key="${f.key}" data-type="text" value="${esc(cur ?? '')}">`;
  }

  return `<div class="cfg-field">
    <div class="cfg-field-label">
      ${esc(f.label)}
      <span class="cfg-field-key">${esc(f.key)}</span>
    </div>
    ${input}
    ${f.hint ? `<div class="cfg-field-hint">${esc(f.hint)}</div>` : ''}
  </div>`;
}

// ── Interactions ─────────────────────────────────────────────────────────────

function attach(container) {
  // Tab switching
  container.querySelectorAll('.cfg-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      _activeSection = tab.dataset.section;
      container.querySelectorAll('.cfg-tab').forEach(t =>
        t.classList.toggle('active', t.dataset.section === _activeSection)
      );
      document.getElementById('cfg-section-body').innerHTML = renderSection(_activeSection);
      attachFieldHandlers(container);
    });
  });

  attachFieldHandlers(container);

  // Save
  document.getElementById('cfg-save').addEventListener('click', async () => {
    if (_dirty.size === 0) return;
    const status = document.getElementById('cfg-status');
    status.className = 'cfg-status';
    status.textContent = 'Saving…';
    try {
      const values = {};
      for (const [k, v] of _dirty.entries()) values[k] = v;
      const res = await put('/config', { values });
      // Merge back into local config
      Object.assign(_config, values);
      _dirty.clear();
      updateDirtyUI();
      status.className = 'cfg-status ok';
      status.textContent = `Saved ${res.count} field${res.count === 1 ? '' : 's'}.`;
      // Re-render current section to clear "dirty" state visually
      document.getElementById('cfg-section-body').innerHTML = renderSection(_activeSection);
      attachFieldHandlers(container);
      setTimeout(() => { status.textContent = ''; status.className = 'cfg-status'; }, 2500);
    } catch (e) {
      status.className = 'cfg-status err';
      status.textContent = 'Save failed: ' + (e.message || e);
    }
  });

  // Discard
  document.getElementById('cfg-discard').addEventListener('click', () => {
    _dirty.clear();
    updateDirtyUI();
    document.getElementById('cfg-section-body').innerHTML = renderSection(_activeSection);
    attachFieldHandlers(container);
  });
}

function attachFieldHandlers(container) {
  const body = document.getElementById('cfg-section-body');
  if (!body) return;

  body.querySelectorAll('[data-key]').forEach(el => {
    const key  = el.dataset.key;
    const type = el.dataset.type;

    const onChange = () => {
      let v;
      if (type === 'bool') {
        v = el.checked;
        const lbl = el.parentElement.querySelector('.cfg-bool-lbl');
        if (lbl) lbl.textContent = v ? 'On' : 'Off';
      } else if (type === 'number') {
        const raw = el.value;
        v = raw === '' ? null : Number(raw);
      } else if (type === 'json_list') {
        v = el.value;  // send as string; backend accepts JSON string
      } else {
        v = el.value;
      }

      const orig = _config[key];
      const same = (v === orig) || (v == null && (orig == null || orig === ''));
      if (same) {
        _dirty.delete(key);
        el.classList.remove('dirty');
      } else {
        _dirty.set(key, v);
        el.classList.add('dirty');
      }
      updateDirtyUI();
    };

    if (type === 'bool')  el.addEventListener('change', onChange);
    else                  el.addEventListener('input', onChange);
  });
}

function updateDirtyUI() {
  const n = _dirty.size;
  document.getElementById('cfg-save').disabled    = n === 0;
  document.getElementById('cfg-discard').disabled = n === 0;
  document.getElementById('cfg-dirty-count').textContent = n ? `${n} unsaved change${n === 1 ? '' : 's'}` : '';
}

// ── Bot Messages panel (original behaviour) ──────────────────────────────────

async function loadBotMessagesPanel(container) {
  const body = document.getElementById('cfg-messages-body');
  try {
    const data = await get('/bot-messages');
    body.innerHTML = buildMessagesBody(data);
    body.querySelectorAll('[data-slot]').forEach(row => {
      const slot = row.dataset.slot;
      const ta   = row.querySelector('.cfg-ta');
      const rst  = row.querySelector('.cfg-reset-link');
      const orig = ta.value;
      ta.addEventListener('input', () => {
        if (ta.value !== orig) ta.classList.add('dirty');
        else ta.classList.remove('dirty');
      });
      rst?.addEventListener('click', async () => {
        try {
          await del(`/bot-messages/${slot}`);
          await loadBotMessagesPanel(container);
        } catch (e) { alert('Reset failed: ' + e.message); }
      });
      row.querySelector('.cfg-save-slot')?.addEventListener('click', async () => {
        try {
          await put(`/bot-messages/${slot}`, { text: ta.value });
          ta.classList.remove('dirty');
          await loadBotMessagesPanel(container);
        } catch (e) { alert('Save failed: ' + e.message); }
      });
    });
  } catch {
    body.innerHTML = `<div class="empty-state" style="padding:30px"><p style="color:var(--muted)">Could not load bot messages.</p></div>`;
  }
}

function buildMessagesBody(data) {
  const entries = Object.entries(SLOT_META);
  return entries.map(([slot, meta]) => {
    const cur = (data && data[slot]) || {};
    const text = cur.text || '';
    const isDefault = cur.is_default !== false;
    return `<div class="cfg-slot" data-slot="${slot}">
      <div class="cfg-slot-header">
        <span class="cfg-slot-label">${esc(meta.label)}</span>
        <div class="cfg-vars">
          ${meta.vars.map(v => `<span class="cfg-chip">${esc(v)}</span>`).join('')}
        </div>
        <button class="cfg-reset-link" ${isDefault ? 'hidden' : ''}>Reset to default</button>
      </div>
      <textarea class="cfg-ta" placeholder="(using default)">${esc(text)}</textarea>
      <div style="margin-top:8px"><button class="btn btn-primary cfg-save-slot">Save</button></div>
    </div>`;
  }).join('');
}

// ── Post as Bot panel ────────────────────────────────────────────────────────

async function loadPostAsBotPanel(container) {
  const body = document.getElementById('cfg-post-body');
  try {
    const channels = await get('/channels');
    body.innerHTML = `
      <div class="cfg-field">
        <label class="cfg-field-l">Channel</label>
        <select class="cfg-select" id="post-ch">
          <option value="">Select a channel…</option>
          ${channels.map(c => `<option value="${esc(c.channel_id)}">#${esc(c.name)}${c.category ? ' (' + esc(c.category) + ')' : ''}</option>`).join('')}
        </select>
      </div>
      <div class="cfg-field" style="margin-top:12px">
        <label class="cfg-field-l">Message</label>
        <textarea class="cfg-ta" id="post-msg" placeholder="Type your message…"></textarea>
      </div>
      <div style="margin-top:12px;display:flex;align-items:center;gap:12px">
        <button class="btn btn-primary" id="post-send">Post</button>
        <span class="cfg-status" id="post-status"></span>
      </div>
    `;
    document.getElementById('post-send').addEventListener('click', async () => {
      const chId    = document.getElementById('post-ch').value;
      const content = document.getElementById('post-msg').value.trim();
      const status  = document.getElementById('post-status');
      if (!chId)    { status.className = 'cfg-status err'; status.textContent = 'Pick a channel.'; return; }
      if (!content) { status.className = 'cfg-status err'; status.textContent = 'Message is empty.'; return; }
      status.className = 'cfg-status'; status.textContent = 'Queuing…';
      try {
        const res = await post('/post-as-bot', { channel_id: chId, content });
        status.className = 'cfg-status ok';
        status.textContent = `Queued (action #${res.action_id}). Will send within a few seconds.`;
        document.getElementById('post-msg').value = '';
      } catch (e) {
        status.className = 'cfg-status err';
        status.textContent = 'Failed: ' + e.message;
      }
    });
  } catch {
    body.innerHTML = `<div class="empty-state" style="padding:30px"><p style="color:var(--muted)">Could not load channels.</p></div>`;
  }
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
