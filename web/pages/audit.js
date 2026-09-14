/**
 * audit.js -- Dashboard audit trail
 *
 * The mod-log answers "what happened to this member". This answers "what did
 * this staff account do", which is the question an audit actually asks.
 *
 * Endpoints:
 *   GET  /audit          -> entries, filterable by actor and path
 *   GET  /audit/actors   -> distinct actors with counts
 *   POST /audit/purge    -> drop entries older than N days
 */

import { get, post } from '../api.js';

function injectStyles() {
  if (document.getElementById('au-styles')) return;
  const s = document.createElement('style');
  s.id = 'au-styles';
  s.textContent = `
    .au-wrap { max-width:1000px; padding:24px; }
    .au-head h2 { font-size:20px; font-weight:600; letter-spacing:-0.02em; }
    .au-head p { font-size:13px; color:var(--muted); margin-top:3px; max-width:600px; }

    .au-actors { display:flex; gap:8px; flex-wrap:wrap; margin:16px 0; }
    .au-actor { background:var(--card); border:1px solid var(--border);
      border-radius:8px; padding:7px 12px; font-size:12px; cursor:pointer;
      transition:all 140ms ease; }
    .au-actor:hover { border-color:var(--gold); }
    .au-actor.active { background:var(--gold-faint); border-color:var(--gold); color:var(--gold); }
    .au-actor b { font-family:var(--font-mono); }

    .au-controls { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; }
    .au-controls .input { flex:1 1 220px; }

    .au-row { display:flex; gap:10px; align-items:baseline; flex-wrap:wrap;
      padding:9px 13px; border:1px solid var(--border); border-radius:8px;
      background:var(--card); margin-bottom:5px; font-size:12.5px; }
    .au-row.err { border-color:rgba(224,108,108,0.4); }
    .au-m { font-family:var(--font-mono); font-size:10.5px; font-weight:700;
      padding:2px 6px; border-radius:4px; letter-spacing:0.03em; }
    .au-m.POST   { background:rgba(95,217,138,0.15);  color:#5FD98A; }
    .au-m.PUT,
    .au-m.PATCH  { background:rgba(212,168,67,0.15);  color:#D4A843; }
    .au-m.DELETE { background:rgba(224,108,108,0.15); color:#E06C6C; }
    .au-m.CMD    { background:rgba(88,101,242,0.18);  color:#8B9BFF; }
    .au-src { font-size:10px; text-transform:uppercase; letter-spacing:0.05em;
      border:1px solid var(--border); border-radius:4px; padding:1px 6px;
      color:var(--muted); }
    .au-src.discord { color:#8B9BFF; border-color:rgba(139,155,255,0.35); }
    .au-target { font-size:11.5px; color:var(--gold); }
    .au-row.readonly { opacity:0.62; }
    .au-path { font-family:var(--font-mono); font-size:11.5px; color:var(--muted); }
    .au-sum { flex:1 1 200px; }
    .au-who { color:var(--text); font-weight:600; }
    .au-when { color:var(--muted); font-size:11.5px; margin-left:auto; white-space:nowrap; }
    .au-status { font-family:var(--font-mono); font-size:11px; color:var(--muted); }
    .au-payload { width:100%; margin-top:6px; font-family:var(--font-mono);
      font-size:11px; color:var(--muted); white-space:pre-wrap;
      background:rgba(0,0,0,0.2); padding:7px 9px; border-radius:6px; display:none; }
    .au-row.open .au-payload { display:block; }
    .au-empty { padding:44px; text-align:center; color:var(--muted); font-size:13px; }
    .au-note { font-size:11.5px; color:var(--muted); margin-top:14px;
      border-top:1px solid var(--border); padding-top:12px; line-height:1.6; }
  `;
  document.head.appendChild(s);
}

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

let _actorFilter = '';

export async function render(root) {
  injectStyles();
  root.innerHTML = `<div class="au-wrap">
    <div class="au-head">
      <h2>Audit Trail</h2>
      <p>One timeline for both surfaces: dashboard requests and slash commands
         run in Discord. Captured globally rather than per route or per cog, so
         nothing added later can forget to log.</p>
    </div>
    <div class="au-actors" id="au-actors"></div>
    <div class="au-controls">
      <input class="input" id="au-path" placeholder="Search path, action, or target…">
      <select class="cfg-input" id="au-source" style="flex:0 1 160px">
        <option value="">Both surfaces</option>
        <option value="discord">Discord commands</option>
        <option value="dashboard">Dashboard</option>
      </select>
      <label class="toggle-wrap">
        <input type="checkbox" id="au-mut" checked><span class="toggle-pill"></span>
        Changes only
      </label>
      <button class="btn btn-gold" id="au-go">Filter</button>
      <button class="btn" id="au-purge">Purge old…</button>
    </div>
    <div id="au-list"><div class="au-empty">Loading…</div></div>
    <div class="au-note">
      Secrets are redacted before the payload is stored. Read-only commands are
      recorded but hidden unless "Changes only" is off, so you can still see who
      looked something up. Failed and refused commands are kept, which is often
      the more interesting half. A minimum 7-day retention is enforced so the
      trail cannot be cleared to hide a recent action.
    </div>
  </div>`;

  document.getElementById('au-go').addEventListener('click', load);
  document.getElementById('au-source').addEventListener('change', load);
  document.getElementById('au-mut').addEventListener('change', load);
  document.getElementById('au-path').addEventListener('keydown',
    e => { if (e.key === 'Enter') load(); });
  document.getElementById('au-purge').addEventListener('click', purge);

  await loadActors();
  await load();
}

async function loadActors() {
  try {
    const actors = await get('/audit/actors');
    const el = document.getElementById('au-actors');
    if (!actors.length) { el.innerHTML = ''; return; }
    el.innerHTML = `<div class="au-actor ${_actorFilter ? '' : 'active'}" data-id="">
        All <b>${actors.reduce((a, x) => a + x.n, 0)}</b></div>` +
      actors.map(a => `<div class="au-actor ${_actorFilter === a.actor_id ? 'active' : ''}"
         data-id="${esc(a.actor_id)}">${esc(a.actor_name || a.actor_id)} <b>${a.n}</b></div>`).join('');
    el.querySelectorAll('.au-actor').forEach(b =>
      b.addEventListener('click', () => {
        _actorFilter = b.dataset.id;
        loadActors(); load();
      }));
  } catch { /* filter bar is optional */ }
}

async function load() {
  const el = document.getElementById('au-list');
  el.innerHTML = `<div class="au-empty">Loading…</div>`;
  const path = encodeURIComponent(document.getElementById('au-path').value.trim());
  try {
    const source = document.getElementById('au-source').value;
    const mut = document.getElementById('au-mut').checked;
    const rows = await get(
      `/audit?actor_id=${encodeURIComponent(_actorFilter)}&path=${path}` +
      `&source=${source}&mutating_only=${mut}&limit=200`);
    if (!rows.length) {
      el.innerHTML = `<div class="au-empty">No matching entries.</div>`;
      return;
    }
    el.innerHTML = rows.map(rowHTML).join('');
    el.querySelectorAll('.au-row').forEach(r =>
      r.addEventListener('click', () => r.classList.toggle('open')));
  } catch (err) {
    el.innerHTML = `<div class="au-empty">Could not load: ${esc(err.message)}</div>`;
  }
}

function rowHTML(r) {
  const bad = r.status >= 400;
  const discord = r.source === 'discord';
  return `<div class="au-row ${bad ? 'err' : ''} ${r.mutating ? '' : 'readonly'}">
    <span class="au-m ${esc(r.method)}">${discord ? 'CMD' : esc(r.method)}</span>
    <span class="au-src ${discord ? 'discord' : ''}">${discord ? 'Discord' : 'Dashboard'}</span>
    <span class="au-who">${esc(r.actor)}</span>
    <span class="au-sum">${esc(r.summary)}</span>
    ${r.target ? `<span class="au-target">→ ${esc(r.target)}</span>` : ''}
    <span class="au-status">${r.status}</span>
    <span class="au-when">${esc(r.timestamp || '')}</span>
    ${r.payload ? `<div class="au-payload">${esc(r.payload)}</div>` : ''}
  </div>`;
}

async function purge() {
  const raw = prompt('Delete audit entries older than how many days? (minimum 7)', '90');
  if (!raw) return;
  const days = parseInt(raw, 10);
  if (isNaN(days) || days < 7) return alert('Must be at least 7 days.');
  if (!confirm(`Permanently delete audit entries older than ${days} days?`)) return;
  try {
    const r = await post('/audit/purge', { older_than_days: days });
    alert(`Deleted ${r.deleted} entries.`);
    await loadActors(); await load();
  } catch (err) {
    alert(`Purge failed: ${err.message}`);
  }
}
