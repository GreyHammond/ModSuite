import { apiFetch } from '../api.js';

function injectStyles() {
  if (document.getElementById('s-dashboard')) return;
  const s = document.createElement('style');
  s.id = 's-dashboard';
  s.textContent = `
    .dash-wrap { padding: 24px; }
    .stat-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 20px; }
    @media(max-width:900px){ .stat-grid { grid-template-columns: repeat(2,1fr); } }
    @media(max-width:500px){ .stat-grid { grid-template-columns: 1fr; } }
    .stat-card { padding: 18px 20px; }
    .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 600; margin-bottom: 8px; }
    .stat-value { font-size: 30px; font-weight: 700; letter-spacing: -.03em; line-height: 1; color: var(--text); }
    .stat-value.gold { color: var(--gold); }
    .dash-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media(max-width:720px){ .dash-cols { grid-template-columns: 1fr; } }
    .section-card { overflow: hidden; }
    .section-hd {
      padding: 12px 16px 11px; font-size: 12.5px; font-weight: 600; color: var(--text);
      border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 7px;
    }
    .section-hd .hd-count { margin-left: auto; font-size: 11px; color: var(--muted); font-weight: 400; }
    .scroll-list { max-height: 340px; overflow-y: auto; }
    .scroll-list::-webkit-scrollbar { width: 3px; }
    .scroll-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
    .act-item { display: flex; align-items: flex-start; gap: 10px; padding: 9px 16px; transition: background var(--transition); }
    .act-item:hover { background: rgba(255,255,255,0.02); }
    .act-ico {
      width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center;
      justify-content: center; flex-shrink: 0; font-size: 12px; margin-top: 1px;
    }
    .act-ico.warn   { background: rgba(245,158,11,.14); }
    .act-ico.jail   { background: rgba(34,197,94,.14); }
    .act-ico.ban    { background: rgba(239,68,68,.14); }
    .act-ico.ticket { background: rgba(96,165,250,.14); }
    .act-ico.note   { background: var(--gold-faint); }
    .act-body { flex: 1; min-width: 0; }
    .act-desc { font-size: 12.5px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .act-time { font-size: 11px; color: var(--muted); margin-top: 2px; }
    .jail-item { display: flex; align-items: center; gap: 10px; padding: 9px 16px; transition: background var(--transition); }
    .jail-item:hover { background: rgba(255,255,255,0.02); }
    .jail-user { flex: 1; min-width: 0; }
    .jail-name { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .jail-exp  { font-size: 11px; color: var(--muted); margin-top: 2px; }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = skeleton();
  try {
    const [stats, activity, jails] = await Promise.all([
      apiFetch('/dashboard/stats'),
      apiFetch('/dashboard/activity'),
      apiFetch('/jails?active_only=true'),
    ]);
    container.innerHTML = buildPage(stats, activity, jails);
  } catch {
    container.innerHTML = errState();
  }
}

function skeleton() {
  return `<div class="dash-wrap">
    <div class="stat-grid">${Array(4).fill(`<div class="card skeleton" style="height:88px"></div>`).join('')}</div>
    <div class="dash-cols">
      <div class="skeleton" style="height:300px;border-radius:10px"></div>
      <div class="skeleton" style="height:300px;border-radius:10px"></div>
    </div>
  </div>`;
}

function errState() {
  return `<div class="dash-wrap"><div class="error-state">
    <div class="state-icon">⚠️</div>
    <p>Could not load dashboard data. Is the bot running?</p>
    <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
  </div></div>`;
}

const ACT_ICONS = { warn:'⚠️', jail:'🔒', ban:'🔨', ticket:'💬', note:'🔖' };

function buildPage(stats, activity, jails) {
  const acts  = Array.isArray(activity) ? activity : [];
  const jailList = Array.isArray(jails) ? jails : [];

  return `<div class="dash-wrap">
    <div class="stat-grid">
      ${statCard('Total Warns',  stats?.total_warns  ?? '—', false)}
      ${statCard('Active Jails', stats?.active_jails ?? '—', true)}
      ${statCard('Open Tickets', stats?.open_tickets ?? '—', false)}
      ${statCard('Members',      stats?.member_count ?? '—', false)}
    </div>
    <div class="dash-cols">
      <div class="card section-card">
        <div class="section-hd">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          Recent Activity
          <span class="hd-count">${acts.length} events</span>
        </div>
        <div class="scroll-list">
          ${acts.length === 0
            ? `<div class="empty-state"><div class="state-icon">📋</div><p>No recent activity</p></div>`
            : acts.map(actRow).join('')}
        </div>
      </div>
      <div class="card section-card">
        <div class="section-hd">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
          Active Jails
          <span class="hd-count">${jailList.length} active</span>
        </div>
        <div class="scroll-list">
          ${jailList.length === 0
            ? `<div class="empty-state"><div class="state-icon">🔓</div><p>No active jails</p></div>`
            : jailList.map(jailRow).join('')}
        </div>
      </div>
    </div>
  </div>`;
}

function statCard(label, value, gold) {
  return `<div class="card stat-card">
    <div class="stat-label">${label}</div>
    <div class="stat-value${gold ? ' gold' : ''}">${value}</div>
  </div>`;
}

function actRow(item) {
  const type = (item.type || 'warn').toLowerCase();
  return `<div class="act-item">
    <div class="act-ico ${type}">${ACT_ICONS[type] || '📋'}</div>
    <div class="act-body">
      <div class="act-desc">${esc(item.description || item.action || '')}</div>
      <div class="act-time">${ago(item.timestamp || item.created_at)}</div>
    </div>
  </div>`;
}

function jailRow(j) {
  const perm = !j.expires_at;
  return `<div class="jail-item">
    <div class="jail-user">
      <div class="jail-name">${esc(j.username || j.user_name || `User ${j.user_id}`)}</div>
      <div class="jail-exp">${perm ? 'Permanent' : 'Expires ' + ago(j.expires_at)}</div>
    </div>
    <span class="badge ${perm ? 'badge-perm' : 'badge-temp'}">${perm ? 'Perm' : 'Temp'}</span>
  </div>`;
}

function ago(d) {
  if (!d) return '—';
  const diff = Date.now() - new Date(d).getTime();
  const future = diff < 0;
  const abs = Math.abs(diff);
  const m = Math.floor(abs / 60000);
  if (m < 1) return 'just now';
  const h = Math.floor(m / 60);
  if (h < 1) return future ? `in ${m}m` : `${m}m ago`;
  const day = Math.floor(h / 24);
  if (day < 1) return future ? `in ${h}h` : `${h}h ago`;
  return future ? `in ${day}d` : `${day}d ago`;
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
