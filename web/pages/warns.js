import { apiFetch } from '../api.js';

let _warns = [], _search = '', _activeOnly = true;

function injectStyles() {
  if (document.getElementById('s-warns')) return;
  const s = document.createElement('style');
  s.id = 's-warns';
  s.textContent = `
    .wn-wrap { padding: 24px; }
    .wn-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
    .warn-card {
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid; border-radius: 10px; margin-bottom: 10px; overflow: hidden;
      transition: box-shadow var(--transition);
    }
    .warn-card:hover { box-shadow: 0 2px 14px rgba(0,0,0,.3); }
    .warn-card.sev-low  { border-left-color: #F59E0B; }
    .warn-card.sev-high { border-left-color: #EF4444; }
    .warn-card-hd {
      display: flex; align-items: center; gap: 10px; padding: 12px 14px;
      cursor: pointer; user-select: none; transition: background var(--transition);
    }
    .warn-card-hd:hover { background: rgba(255,255,255,.02); }
    .warn-uname { font-size: 14px; font-weight: 600; color: var(--text); }
    .warn-last  { font-size: 12px; color: var(--muted); margin-top: 2px; }
    .warn-chevron { margin-left: auto; color: var(--muted); transition: transform var(--transition); flex-shrink:0; }
    .warn-card.open .warn-chevron { transform: rotate(180deg); }
    .warn-history { display: none; border-top: 1px solid var(--border); padding: 10px 14px; }
    .warn-card.open .warn-history { display: block; }
    .warn-entry {
      display: flex; align-items: flex-start; gap: 10px;
      padding: 8px 0; border-bottom: 1px solid var(--border);
    }
    .warn-entry:last-child { border-bottom: none; padding-bottom: 0; }
    .we-body { flex: 1; min-width: 0; }
    .we-reason { font-size: 13px; color: var(--text); }
    .we-meta { font-size: 11px; color: var(--muted); margin-top: 3px; font-family: var(--font-mono); }
    .we-actions { flex-shrink: 0; display: flex; align-items: center; gap: 6px; }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="wn-wrap">${Array(3).fill(`<div class="skeleton" style="height:76px;border-radius:10px;margin-bottom:10px"></div>`).join('')}</div>`;
  try {
    const data = await apiFetch('/warns');
    _warns = Array.isArray(data) ? data : (data?.warns ?? []);
    _search = ''; _activeOnly = true;
    container.innerHTML = buildPage();
    attach(container);
    renderList(container);
  } catch {
    container.innerHTML = errState();
  }
}

function buildPage() {
  return `<div class="wn-wrap">
    <div class="wn-toolbar">
      <input type="text" class="input" id="wn-search" placeholder="Search by username…" style="max-width:260px">
      <label class="toggle-wrap">
        <input type="checkbox" id="wn-active" checked>
        <div class="toggle-pill"></div>
        Active only
      </label>
      <span style="font-size:12px;color:var(--muted);margin-left:auto" id="wn-count"></span>
    </div>
    <div id="wn-list"></div>
  </div>`;
}

function byUser(warns) {
  const map = {};
  for (const w of warns) {
    const k = w.user_id || w.username || 'unknown';
    if (!map[k]) map[k] = { name: w.username || w.user_name || `User ${w.user_id}`, warns: [] };
    map[k].warns.push(w);
  }
  return Object.values(map);
}

function renderList(container) {
  const list  = document.getElementById('wn-list');
  const count = document.getElementById('wn-count');
  if (!list) return;

  let filtered = _warns;
  if (_activeOnly) filtered = filtered.filter(w => w.active !== false && !w.pardoned);
  if (_search) filtered = filtered.filter(w =>
    (w.username || w.user_name || '').toLowerCase().includes(_search.toLowerCase())
  );

  const groups = byUser(filtered);
  if (count) count.textContent = `${groups.length} users`;

  if (groups.length === 0) {
    list.innerHTML = `<div class="empty-state"><div class="state-icon">✅</div><p>No warns found</p></div>`;
    return;
  }

  list.innerHTML = groups.map(u => {
    const active = u.warns.filter(w => w.active !== false && !w.pardoned).length;
    const sev    = active >= 4 ? 'sev-high' : 'sev-low';
    return `<div class="warn-card ${sev}">
      <div class="warn-card-hd" onclick="this.closest('.warn-card').classList.toggle('open')">
        <div>
          <div class="warn-uname">${esc(u.name)}</div>
          <div class="warn-last">${esc(u.warns.at(-1)?.reason || 'No reason')}</div>
        </div>
        <span class="badge badge-warn" style="margin-left:8px">${active} active</span>
        <svg class="warn-chevron" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
      </div>
      <div class="warn-history">${u.warns.map(entryHTML).join('')}</div>
    </div>`;
  }).join('');

  // Pardon button listeners
  list.querySelectorAll('.pardon-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const id = btn.dataset.warnId;
      btn.textContent = '…'; btn.disabled = true;
      try {
        await apiFetch(`/warns/${id}`, { method: 'DELETE' });
        const w = _warns.find(x => String(x.id) === String(id));
        if (w) { w.active = false; w.pardoned = true; }
        renderList(container);
      } catch {
        btn.textContent = 'Pardon'; btn.disabled = false;
      }
    });
  });
}

function entryHTML(w) {
  const pardoned = w.active === false || w.pardoned;
  return `<div class="warn-entry">
    <div class="we-body">
      <div class="we-reason">${esc(w.reason || 'No reason')}</div>
      <div class="we-meta">ID: ${w.id} · by ${esc(w.mod_name || w.by || '?')} · ${fmtDate(w.created_at)}</div>
    </div>
    <div class="we-actions">
      ${pardoned
        ? `<span class="badge badge-success">Pardoned</span>`
        : `<button class="btn btn-ghost btn-sm pardon-btn" data-warn-id="${w.id}">Pardon</button>`}
    </div>
  </div>`;
}

function attach(container) {
  container.querySelector('#wn-search')?.addEventListener('input', e => {
    _search = e.target.value; renderList(container);
  });
  container.querySelector('#wn-active')?.addEventListener('change', e => {
    _activeOnly = e.target.checked; renderList(container);
  });
}

function errState() {
  return `<div class="wn-wrap"><div class="error-state">
    <div class="state-icon">⚠️</div>
    <p>Could not load warns. Is the bot running?</p>
    <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
  </div></div>`;
}

const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmtDate = d => !d ? '—' : new Date(d).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'2-digit'});
