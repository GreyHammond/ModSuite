import { apiFetch } from '../api.js';

let _tickets = [], _status = 'open';
const ONE_HOUR = 3_600_000;

function injectStyles() {
  if (document.getElementById('s-tickets')) return;
  const s = document.createElement('style');
  s.id = 's-tickets';
  s.textContent = `
    .tk-wrap { padding: 24px; }
    .tk-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
    .filter-tabs {
      display: flex; gap: 3px; background: var(--card);
      padding: 3px; border-radius: 8px; border: 1px solid var(--border);
    }
    .ftab {
      padding: 5px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;
      color: var(--muted); background: none; border: none; cursor: pointer;
      transition: all var(--transition); font-family: var(--font);
    }
    .ftab.active { background: var(--gold-faint); color: var(--gold); }
    .ftab:hover:not(.active) { color: var(--text); }
    .ticket-card {
      background: var(--card); border: 1px solid var(--border); border-radius: 10px;
      padding: 14px 16px; margin-bottom: 10px;
      display: flex; align-items: flex-start; gap: 12px;
      transition: box-shadow var(--transition), border-color var(--transition);
    }
    .ticket-card:hover { box-shadow: 0 2px 14px rgba(0,0,0,.3); }
    .ticket-card.urgent { border-color: rgba(239,68,68,.28); }
    .tk-ico {
      width: 36px; height: 36px; border-radius: 8px;
      background: rgba(96,165,250,.12); display: flex; align-items: center;
      justify-content: center; flex-shrink: 0; color: #60A5FA;
    }
    .tk-body { flex: 1; min-width: 0; }
    .tk-head {
      display: flex; align-items: center; gap: 8px; margin-bottom: 5px; flex-wrap: wrap;
    }
    .tk-opener { font-size: 14px; font-weight: 600; }
    .tk-subject { font-size: 13px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
    .tk-meta { display: flex; align-items: center; gap: 12px; font-size: 11px; color: var(--muted); flex-wrap: wrap; }
    .tk-meta-item { display: flex; align-items: center; gap: 4px; }
    .tk-urgent-warn { color: #EF4444; font-weight: 600; }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="tk-wrap">${Array(3).fill(`<div class="skeleton" style="height:84px;border-radius:10px;margin-bottom:10px"></div>`).join('')}</div>`;
  try {
    const data = await apiFetch('/tickets');
    _tickets = Array.isArray(data) ? data : (data?.tickets ?? []);
    _status = 'open';
    container.innerHTML = buildPage();
    attach(container);
    renderTickets(container);
  } catch {
    container.innerHTML = errState();
  }
}

function buildPage() {
  return `<div class="tk-wrap">
    <div class="tk-toolbar">
      <div class="filter-tabs">
        <button class="ftab active" data-s="open">Open</button>
        <button class="ftab" data-s="closed">Closed</button>
        <button class="ftab" data-s="all">All</button>
      </div>
      <span style="font-size:12px;color:var(--muted);margin-left:auto" id="tk-count"></span>
    </div>
    <div id="tk-list"></div>
  </div>`;
}

function isUrgent(t) {
  if ((t.status || 'open').toLowerCase() !== 'open') return false;
  const msgs = t.message_count ?? t.messages ?? 1;
  if (msgs > 1) return false;
  return Date.now() - new Date(t.opened_at || t.created_at).getTime() > ONE_HOUR;
}

function renderTickets(container) {
  const list  = document.getElementById('tk-list');
  const count = document.getElementById('tk-count');
  if (!list) return;

  let filtered = _tickets;
  if (_status !== 'all') filtered = filtered.filter(t => (t.status || 'open').toLowerCase() === _status);

  if (count) count.textContent = `${filtered.length} tickets`;

  if (filtered.length === 0) {
    const label = _status === 'all' ? '' : _status + ' ';
    list.innerHTML = `<div class="empty-state"><div class="state-icon">💬</div><p>No ${label}tickets</p></div>`;
    return;
  }

  list.innerHTML = filtered.map(t => {
    const urgent = isUrgent(t);
    const statusKey = urgent ? 'urgent' : (t.status || 'open').toLowerCase();
    const msgCount = t.message_count ?? t.messages;
    return `<div class="ticket-card${urgent ? ' urgent' : ''}">
      <div class="tk-ico">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
        </svg>
      </div>
      <div class="tk-body">
        <div class="tk-head">
          <span class="tk-opener">${esc(t.username || t.user_name || `User ${t.user_id}`)}</span>
          <span class="tk-subject">— ${esc(t.subject || 'No subject')}</span>
          <span class="badge badge-${statusKey}" style="flex-shrink:0">${urgent ? 'Urgent' : cap(t.status || 'open')}</span>
        </div>
        <div class="tk-meta">
          <span class="tk-meta-item">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
            Opened ${ago(t.opened_at || t.created_at)}
          </span>
          ${msgCount != null ? `<span class="tk-meta-item">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
            ${msgCount} messages
          </span>` : ''}
          ${urgent ? `<span class="tk-urgent-warn tk-meta-item">⚠ No response for 1h+</span>` : ''}
        </div>
      </div>
    </div>`;
  }).join('');
}

function attach(container) {
  container.querySelectorAll('.ftab').forEach(tab => {
    tab.addEventListener('click', () => {
      container.querySelectorAll('.ftab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      _status = tab.dataset.s;
      renderTickets(container);
    });
  });
}

function errState() {
  return `<div class="tk-wrap"><div class="error-state">
    <div class="state-icon">⚠️</div>
    <p>Could not load tickets. Is the bot running?</p>
    <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
  </div></div>`;
}

const cap = s => String(s).charAt(0).toUpperCase() + String(s).slice(1);
const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function ago(d) {
  if (!d) return '—';
  const m = Math.floor((Date.now() - new Date(d).getTime()) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
