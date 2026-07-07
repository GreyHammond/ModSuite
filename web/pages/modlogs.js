import { apiFetch } from '../api.js';

const PAGE_SIZE = 50;
let _logs = [], _filter = 'all', _page = 1;

function injectStyles() {
  if (document.getElementById('s-modlogs')) return;
  const s = document.createElement('style');
  s.id = 's-modlogs';
  s.textContent = `
    .ml-wrap { padding: 24px; }
    .ml-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
    .ml-table-wrap { border-radius: 10px; border: 1px solid var(--border); overflow: hidden; background: var(--card); }
    .ml-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .ml-table thead tr { border-bottom: 1px solid var(--border); background: rgba(255,255,255,.02); }
    .ml-table th {
      padding: 9px 14px; text-align: left; font-size: 11px; text-transform: uppercase;
      letter-spacing: .06em; color: var(--muted); font-weight: 600; white-space: nowrap;
    }
    .ml-table td { padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
    .ml-table tbody tr:last-child td { border-bottom: none; }
    .ml-table tbody tr { transition: background var(--transition); }
    .ml-table tbody tr:hover { background: rgba(255,255,255,.02); }
    .td-reason { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); }
    .td-by    { color: var(--muted); }
    .td-when  { color: var(--muted); font-size: 11.5px; font-family: var(--font-mono); white-space: nowrap; }
    .empty-row td { text-align: center; padding: 40px; color: var(--muted); }
    @media(max-width:600px){
      .ml-table .td-reason, .ml-table .td-by { display: none; }
    }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="ml-wrap">
    <div class="skeleton" style="height:40px;width:200px;margin-bottom:14px"></div>
    <div class="skeleton" style="height:400px;border-radius:10px"></div>
  </div>`;
  try {
    const data = await apiFetch('/modlogs');
    _logs = Array.isArray(data) ? data : (data?.logs ?? []);
    _filter = 'all'; _page = 1;
    container.innerHTML = buildPage();
    attach(container);
  } catch {
    container.innerHTML = `<div class="ml-wrap"><div class="error-state">
      <div class="state-icon">⚠️</div>
      <p>Could not load mod logs. Is the bot running?</p>
      <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
    </div></div>`;
  }
}

function buildPage() {
  return `<div class="ml-wrap">
    <div class="ml-toolbar">
      <select class="input select-filter" id="ml-filter" style="width:190px">
        <option value="all">All actions</option>
        <option value="jail">Jails</option>
        <option value="warn">Warns</option>
        <option value="ban">Bans</option>
        <option value="kick">Kicks</option>
        <option value="mute">Mutes</option>
      </select>
      <span style="font-size:12px;color:var(--muted);margin-left:auto" id="ml-count"></span>
    </div>
    <div class="ml-table-wrap">
      <table class="ml-table">
        <thead><tr>
          <th>Action</th><th>User</th><th class="td-reason">Reason</th>
          <th class="td-by">By</th><th>When</th>
        </tr></thead>
        <tbody id="ml-body"></tbody>
      </table>
    </div>
    <div class="pagination" id="ml-pages"></div>
  </div>`;
}

function filtered() {
  if (_filter === 'all') return _logs;
  return _logs.filter(l => (l.action || l.type || '').toLowerCase() === _filter);
}

function renderRows() {
  const rows = filtered();
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  _page = Math.min(_page, pages);
  const slice = rows.slice((_page - 1) * PAGE_SIZE, _page * PAGE_SIZE);

  const body  = document.getElementById('ml-body');
  const count = document.getElementById('ml-count');
  const pager = document.getElementById('ml-pages');
  if (!body) return;

  if (count) count.textContent = `${total} entries`;

  body.innerHTML = slice.length === 0
    ? `<tr class="empty-row"><td colspan="5">No entries match this filter</td></tr>`
    : slice.map(log => {
        const action = (log.action || log.type || 'unknown').toLowerCase();
        return `<tr>
          <td><span class="badge badge-${action}">${cap(action)}</span></td>
          <td>${esc(log.username || log.user_name || `User ${log.user_id}`)}</td>
          <td class="td-reason" title="${esc(log.reason || '')}">${esc(log.reason || '—')}</td>
          <td class="td-by">${esc(log.mod_name || log.by || '—')}</td>
          <td class="td-when">${fmtDate(log.created_at || log.timestamp)}</td>
        </tr>`;
      }).join('');

  if (!pager) return;
  if (pages <= 1) { pager.innerHTML = ''; return; }
  pager.innerHTML = `
    <button class="btn btn-ghost btn-sm" id="pg-prev" ${_page <= 1 ? 'disabled' : ''}>← Prev</button>
    <span class="page-info">Page ${_page} of ${pages}</span>
    <button class="btn btn-ghost btn-sm" id="pg-next" ${_page >= pages ? 'disabled' : ''}>Next →</button>`;
  document.getElementById('pg-prev')?.addEventListener('click', () => { _page--; renderRows(); });
  document.getElementById('pg-next')?.addEventListener('click', () => { _page++; renderRows(); });
}

function attach(container) {
  renderRows();
  container.querySelector('#ml-filter')?.addEventListener('change', e => {
    _filter = e.target.value; _page = 1; renderRows();
  });
}

const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function fmtDate(d) {
  if (!d) return '—';
  const dt = new Date(d);
  return dt.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' ' +
         dt.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',hour12:false});
}
