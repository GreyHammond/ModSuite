/**
 * archive.js -- Forensic message archive (Sentinel)
 *
 * Endpoints used:
 *   GET /archive                 -> search
 *   GET /archive/stats           -> counts and settings
 *   GET /archive/vault/{file}    -> one attachment, authenticated
 */

import { get } from '../api.js';

function injectStyles() {
  if (document.getElementById('arc-styles')) return;
  const s = document.createElement('style');
  s.id = 'arc-styles';
  s.textContent = `
    .arc-wrap { max-width: 980px; padding: 24px; }
    .arc-head { margin-bottom: 18px; }
    .arc-head h2 { font-size: 20px; font-weight: 600; letter-spacing: -0.02em; }
    .arc-head p { font-size: 13px; color: var(--muted); margin-top: 3px; }

    .arc-stats { display: flex; gap: 10px; flex-wrap: wrap; margin: 14px 0 18px; }
    .arc-stat {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 9px; padding: 10px 14px; min-width: 108px;
    }
    .arc-stat b { display: block; font-size: 18px; font-family: var(--font-mono); }
    .arc-stat span { font-size: 11px; color: var(--muted);
      text-transform: uppercase; letter-spacing: 0.05em; }

    .arc-controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
    .arc-controls .input { flex: 1 1 240px; }

    .arc-msg {
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid var(--border);
      border-radius: 9px; padding: 12px 15px; margin-bottom: 8px;
    }
    .arc-msg.deleted { border-left-color: var(--gold); }
    .arc-meta {
      display: flex; gap: 10px; flex-wrap: wrap; align-items: baseline;
      font-size: 11.5px; color: var(--muted); margin-bottom: 6px;
    }
    .arc-author { color: var(--text); font-weight: 600; font-size: 12.5px; }
    .arc-body { font-size: 13px; line-height: 1.55; white-space: pre-wrap;
      word-break: break-word; }
    .arc-body.empty { color: var(--muted); font-style: italic; }
    .arc-atts { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 9px; }
    .arc-att {
      font-size: 11.5px; font-family: var(--font-mono);
      border: 1px solid var(--border); border-radius: 6px;
      padding: 3px 9px; color: var(--gold); cursor: pointer;
    }
    .arc-att:hover { background: var(--gold-faint); }
    .arc-att.gone { color: var(--muted); cursor: default; }
    .arc-edits {
      margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border);
      font-size: 11.5px; color: var(--muted);
    }
    .arc-edits div { padding: 2px 0; }
    .arc-empty { padding: 50px; text-align: center; color: var(--muted); font-size: 13px; }
    .arc-notice {
      background: rgba(215,55,57,0.07); border: 1px solid rgba(215,55,57,0.25);
      border-radius: 9px; padding: 11px 14px; font-size: 12.5px;
      color: var(--text); margin-bottom: 16px; line-height: 1.55;
    }
  `;
  document.head.appendChild(s);
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export async function render(root) {
  injectStyles();
  root.innerHTML = `<div class="arc-wrap">
    <div class="arc-head">
      <h2>Archive</h2>
      <p>Every message in scope, including ones that were deleted or edited.</p>
    </div>
    <div class="arc-notice" id="arc-notice">Loading…</div>
    <div class="arc-stats" id="arc-stats"></div>
    <div class="arc-controls">
      <input class="input" id="arc-q" placeholder="Search message text…">
      <input class="input" id="arc-author" placeholder="Author ID" style="flex:0 1 160px">
      <label class="toggle-wrap">
        <input type="checkbox" id="arc-del"><span class="toggle-pill"></span>
        Deleted only
      </label>
      <button class="btn btn-gold" id="arc-go">Search</button>
    </div>
    <div id="arc-results"><div class="arc-empty">Loading…</div></div>
  </div>`;

  const run = () => search();
  document.getElementById('arc-go').addEventListener('click', run);
  document.getElementById('arc-q').addEventListener('keydown', e => {
    if (e.key === 'Enter') run();
  });
  document.getElementById('arc-del').addEventListener('change', run);

  await loadStats();
  await search();
}

async function loadStats() {
  try {
    const s = await get('/archive/stats');
    document.getElementById('arc-stats').innerHTML = `
      <div class="arc-stat"><b>${(s.total || 0).toLocaleString()}</b><span>Messages</span></div>
      <div class="arc-stat"><b>${(s.deleted || 0).toLocaleString()}</b><span>Deleted</span></div>
      <div class="arc-stat"><b>${s.retention_days}d</b><span>Retention</span></div>
      <div class="arc-stat"><b>${esc(s.scope)}</b><span>Scope</span></div>`;

    const n = document.getElementById('arc-notice');
    if (!s.enabled) {
      n.innerHTML = `Archiving is <strong>off</strong>. Turn it on with
        <code>/archive setup</code> in Discord.`;
    } else if (s.scope === 'all') {
      n.innerHTML = `Scope is <strong>all channels</strong>, which includes ModMail
        and private staff discussion. That archive is discoverable in litigation.
        <code>public</code> is the safer setting.`;
    } else {
      n.innerHTML = `Archiving <strong>public channels only</strong>, kept for
        ${s.retention_days} days. Make sure members are told this in writing.`;
    }
  } catch (err) {
    document.getElementById('arc-notice').textContent =
      `Could not load archive settings: ${err.message}`;
  }
}

async function search() {
  const el = document.getElementById('arc-results');
  el.innerHTML = `<div class="arc-empty">Searching…</div>`;
  const q = encodeURIComponent(document.getElementById('arc-q').value.trim());
  const a = encodeURIComponent(document.getElementById('arc-author').value.trim());
  const d = document.getElementById('arc-del').checked;
  try {
    const rows = await get(`/archive?q=${q}&author_id=${a}&deleted_only=${d}&limit=100`);
    if (!rows.length) {
      el.innerHTML = `<div class="arc-empty">Nothing matched.</div>`;
      return;
    }
    el.innerHTML = rows.map(msgHTML).join('');
  } catch (err) {
    el.innerHTML = `<div class="arc-empty">Search failed: ${esc(err.message)}</div>`;
  }
}

function msgHTML(m) {
  const atts = (m.attachments || []).map(a => a.vault
    ? `<a class="arc-att" href="/archive/vault/${encodeURIComponent(a.vault)}"
         target="_blank" rel="noopener">${esc(a.filename)}</a>`
    : `<span class="arc-att gone">${esc(a.filename)} (not held)</span>`).join('');

  const edits = (m.edit_history || []).length
    ? `<div class="arc-edits"><strong>Edited ${m.edit_history.length}x.</strong> Previous:
        ${m.edit_history.map(h => `<div>${esc(h.content)}</div>`).join('')}</div>`
    : '';

  return `<div class="arc-msg ${m.deleted ? 'deleted' : ''}">
    <div class="arc-meta">
      <span class="arc-author">${esc(m.author)}</span>
      <span>#${esc(m.channel)}</span>
      <span>${esc(m.timestamp || '')}</span>
      ${m.deleted ? `<span class="badge badge-ban">deleted</span>` : ''}
      ${m.edited ? `<span class="badge badge-warn">edited</span>` : ''}
    </div>
    <div class="arc-body ${m.content ? '' : 'empty'}">${
      m.content ? esc(m.content) : 'no text content'}</div>
    ${atts ? `<div class="arc-atts">${atts}</div>` : ''}
    ${edits}
  </div>`;
}
