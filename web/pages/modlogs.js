import { apiFetch } from '../api.js';

const PAGE_SIZE = 50;
let _logs = [], _filter = 'all', _page = 1;
let _dateFrom = '', _dateTo = '', _userQuery = '';

function injectStyles() {
  if (document.getElementById('s-modlogs')) return;
  const s = document.createElement('style');
  s.id = 's-modlogs';
  s.textContent = `
    .ml-wrap { padding: 24px; }
    .ml-toolbar {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px; margin-bottom: 14px; align-items: end;
    }
    .ml-toolbar .field { display: flex; flex-direction: column; gap: 4px; }
    .ml-toolbar label {
      font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em;
      color: var(--muted); font-weight: 600;
    }
    .ml-toolbar input, .ml-toolbar select {
      width: 100%; background: var(--card-2); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); font: inherit; font-size: 13px;
      padding: 7px 10px; box-sizing: border-box; outline: none;
      transition: border-color var(--fast);
    }
    .ml-toolbar input:focus, .ml-toolbar select:focus { border-color: var(--border-focus); }
    .ml-toolbar select {
      appearance: none; padding-right: 28px;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='11' viewBox='0 0 24 24' fill='none' stroke='%238888A0' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat; background-position: right 8px center;
    }
    .ml-actions { display: flex; align-items: end; gap: 8px; }
    .ml-count { font-size: 12px; color: var(--muted); padding: 8px 0; }

    .ml-table-wrap { border-radius: 10px; border: 1px solid var(--border); overflow: hidden; background: var(--card); }
    .ml-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .ml-table thead tr { border-bottom: 1px solid var(--border); background: rgba(255,255,255,.02); }
    .ml-table th {
      padding: 9px 14px; text-align: left; font-size: 11px; text-transform: uppercase;
      letter-spacing: .06em; color: var(--muted); font-weight: 600; white-space: nowrap;
    }
    .ml-table td { padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
    .ml-table tbody tr:last-child td { border-bottom: none; }
    .ml-table tbody tr {
      transition: background var(--transition);
      cursor: pointer;
    }
    .ml-table tbody tr:hover { background: rgba(255,255,255,.02); }
    .td-reason { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); }
    .td-by    { color: var(--muted); }
    .td-when  { color: var(--muted); font-size: 11.5px; font-family: var(--font-mono); white-space: nowrap; }
    .empty-row td { text-align: center; padding: 40px; color: var(--muted); }

    /* Expanded detail row */
    .ml-detail-row td {
      padding: 0; background: var(--card-2);
      border-bottom: 1px solid var(--border);
    }
    .ml-detail-body { padding: 14px 22px; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }
    .ml-detail-item { display: flex; flex-direction: column; gap: 3px; }
    .ml-detail-label {
      font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em;
      color: var(--muted); font-weight: 600;
    }
    .ml-detail-value { font-size: 12.5px; color: var(--text); word-break: break-word; }
    .ml-detail-value.mono { font-family: var(--font-mono); font-size: 11.5px; }

    @media(max-width:600px){
      .ml-table .td-reason, .ml-table .td-by { display: none; }
    }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="ml-wrap">
    <div class="skeleton" style="height:76px;margin-bottom:14px;border-radius:8px"></div>
    <div class="skeleton" style="height:400px;border-radius:10px"></div>
  </div>`;
  try {
    // Request a big batch so we can filter client-side by date/user
    const data = await apiFetch('/modlogs?limit=500');
    if (data?.results) _logs = data.results;
    else if (Array.isArray(data)) _logs = data;
    else _logs = data?.logs ?? [];
    _filter = 'all'; _page = 1;
    _dateFrom = ''; _dateTo = ''; _userQuery = '';
    container.innerHTML = buildPage();
    attach(container);
    renderRows();
  } catch (e) {
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
      <div class="field">
        <label>Action</label>
        <select id="ml-filter">
          <option value="all">All actions</option>
          <option value="jail">Jails</option>
          <option value="warn">Warns</option>
          <option value="ban">Bans</option>
          <option value="kick">Kicks</option>
          <option value="mute">Mutes</option>
          <option value="unmute">Unmutes</option>
          <option value="unban">Unbans</option>
          <option value="softban">Softbans</option>
        </select>
      </div>
      <div class="field">
        <label>User contains</label>
        <input type="text" id="ml-user" placeholder="username…" autocomplete="off">
      </div>
      <div class="field">
        <label>From</label>
        <input type="date" id="ml-from">
      </div>
      <div class="field">
        <label>To</label>
        <input type="date" id="ml-to">
      </div>
      <div class="ml-actions">
        <button class="btn btn-ghost btn-sm" id="ml-reset">Reset</button>
        <button class="btn btn-primary btn-sm" id="ml-csv">Export CSV</button>
      </div>
    </div>
    <div class="ml-count" id="ml-count"></div>
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
  return _logs.filter(l => {
    // Action
    if (_filter !== 'all') {
      const act = (l.action || l.type || '').toLowerCase();
      if (act !== _filter) return false;
    }
    // User query
    if (_userQuery) {
      const name = (l.username || l.user_name || l.target_username || '').toLowerCase();
      if (!name.includes(_userQuery.toLowerCase())) return false;
    }
    // Date range
    const ts = l.created_at || l.timestamp;
    if (ts) {
      const d = new Date(ts);
      if (_dateFrom && d < new Date(_dateFrom)) return false;
      if (_dateTo) {
        const end = new Date(_dateTo);
        end.setHours(23, 59, 59, 999);
        if (d > end) return false;
      }
    }
    return true;
  });
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

  if (count) count.textContent = `${total} entr${total === 1 ? 'y' : 'ies'}`;

  body.innerHTML = slice.length === 0
    ? `<tr class="empty-row"><td colspan="5">No entries match these filters</td></tr>`
    : slice.map((log, idx) => {
        const action = (log.action || log.type || 'unknown').toLowerCase();
        const rowIdx = (_page - 1) * PAGE_SIZE + idx;
        return `<tr data-idx="${rowIdx}">
          <td><span class="badge badge-${action}">${cap(action)}</span></td>
          <td>${esc(log.username || log.user_name || log.target_username || `User ${log.user_id || log.target_id || '?'}`)}</td>
          <td class="td-reason" title="${esc(log.reason || '')}">${esc(log.reason || '—')}</td>
          <td class="td-by">${esc(log.mod_name || log.by || log.actor_username || '—')}</td>
          <td class="td-when">${fmtDate(log.created_at || log.timestamp)}</td>
        </tr>`;
      }).join('');

  // Row click → expand detail
  body.querySelectorAll('tr[data-idx]').forEach(tr => {
    tr.addEventListener('click', () => {
      const idx = Number(tr.dataset.idx);
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('ml-detail-row')) {
        next.remove();
        return;
      }
      // Remove any other open details
      body.querySelectorAll('.ml-detail-row').forEach(d => d.remove());
      const log = rows[idx];
      const detail = document.createElement('tr');
      detail.className = 'ml-detail-row';
      detail.innerHTML = `<td colspan="5">${detailHTML(log)}</td>`;
      tr.after(detail);
    });
  });

  if (!pager) return;
  if (pages <= 1) { pager.innerHTML = ''; return; }
  pager.innerHTML = `
    <button class="btn btn-ghost btn-sm" id="pg-prev" ${_page <= 1 ? 'disabled' : ''}>← Prev</button>
    <span class="page-info">Page ${_page} of ${pages}</span>
    <button class="btn btn-ghost btn-sm" id="pg-next" ${_page >= pages ? 'disabled' : ''}>Next →</button>`;
  document.getElementById('pg-prev')?.addEventListener('click', () => { _page--; renderRows(); });
  document.getElementById('pg-next')?.addEventListener('click', () => { _page++; renderRows(); });
}

function detailHTML(log) {
  const items = [
    ['Action ID',      log.id  ?? '—'],
    ['Target ID',      log.target_id ?? log.user_id ?? '—'],
    ['Actor ID',       log.actor_id  ?? log.mod_id  ?? '—'],
    ['Reason (full)',  log.reason ?? '—'],
    ['Timestamp',      log.created_at ?? log.timestamp ?? '—'],
  ];
  return `<div class="ml-detail-body">
    ${items.map(([label, value]) => `
      <div class="ml-detail-item">
        <span class="ml-detail-label">${label}</span>
        <span class="ml-detail-value ${typeof value === 'string' && /^[a-z0-9\-T:.Z]+$/i.test(value) ? 'mono' : ''}">${esc(value)}</span>
      </div>
    `).join('')}
  </div>`;
}

function attach(container) {
  container.querySelector('#ml-filter')?.addEventListener('change', e => {
    _filter = e.target.value; _page = 1; renderRows();
  });
  let userTimer;
  container.querySelector('#ml-user')?.addEventListener('input', e => {
    clearTimeout(userTimer);
    userTimer = setTimeout(() => { _userQuery = e.target.value.trim(); _page = 1; renderRows(); }, 200);
  });
  container.querySelector('#ml-from')?.addEventListener('change', e => {
    _dateFrom = e.target.value; _page = 1; renderRows();
  });
  container.querySelector('#ml-to')?.addEventListener('change', e => {
    _dateTo = e.target.value; _page = 1; renderRows();
  });
  container.querySelector('#ml-reset')?.addEventListener('click', () => {
    _filter = 'all'; _dateFrom = ''; _dateTo = ''; _userQuery = ''; _page = 1;
    container.querySelector('#ml-filter').value = 'all';
    container.querySelector('#ml-user').value = '';
    container.querySelector('#ml-from').value = '';
    container.querySelector('#ml-to').value = '';
    renderRows();
  });
  container.querySelector('#ml-csv')?.addEventListener('click', () => {
    downloadCSV(filtered());
  });
}

function downloadCSV(rows) {
  const headers = ['id', 'action', 'user', 'user_id', 'reason', 'by', 'by_id', 'timestamp'];
  const csv = [headers.join(',')];
  for (const l of rows) {
    csv.push([
      l.id ?? '',
      l.action ?? l.type ?? '',
      l.username ?? l.target_username ?? l.user_name ?? '',
      l.user_id  ?? l.target_id ?? '',
      l.reason ?? '',
      l.mod_name ?? l.actor_username ?? l.by ?? '',
      l.actor_id ?? l.mod_id ?? '',
      l.created_at ?? l.timestamp ?? '',
    ].map(csvCell).join(','));
  }
  const blob = new Blob([csv.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `modlogs-${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function csvCell(v) {
  const s = String(v ?? '');
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function fmtDate(d) {
  if (!d) return '—';
  const dt = new Date(d);
  return dt.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' ' +
         dt.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',hour12:false});
}
