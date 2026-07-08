import { apiFetch } from '../api.js';

function injectStyles() {
  if (document.getElementById('s-dashboard')) return;
  const s = document.createElement('style');
  s.id = 's-dashboard';
  s.textContent = `
    .dash-wrap { padding: 24px; display: flex; flex-direction: column; gap: 16px; }

    /* Stat grid */
    .stat-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; }
    @media(max-width:1100px){ .stat-grid { grid-template-columns: repeat(2,1fr); } }
    @media(max-width:500px){  .stat-grid { grid-template-columns: 1fr; } }
    .stat-card { padding: 16px 18px; }
    .stat-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); font-weight: 600; margin-bottom: 6px; }
    .stat-value { font-size: 26px; font-weight: 700; letter-spacing: -.03em; line-height: 1.05; color: var(--text); }
    .stat-value.gold  { color: var(--gold); }
    .stat-value.green { color: var(--green); }
    .stat-value.red   { color: var(--red); }
    .stat-sub { font-size: 11px; color: var(--muted); margin-top: 4px; }

    /* Two-column area */
    .dash-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    @media(max-width:820px){ .dash-cols { grid-template-columns: 1fr; } }

    /* Three-column for lower row */
    .dash-3col { display: grid; grid-template-columns: 1.2fr 1fr 1fr; gap: 12px; }
    @media(max-width:1000px){ .dash-3col { grid-template-columns: 1fr; } }

    .section-card { overflow: hidden; }
    .section-hd {
      padding: 12px 16px 11px; font-size: 12.5px; font-weight: 600; color: var(--text);
      border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 7px;
    }
    .section-hd .hd-count { margin-left: auto; font-size: 11px; color: var(--muted); font-weight: 400; }
    .scroll-list { max-height: 320px; overflow-y: auto; }
    .scroll-list::-webkit-scrollbar { width: 3px; }
    .scroll-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

    /* Activity items */
    .act-item { display: flex; align-items: flex-start; gap: 10px; padding: 9px 16px; transition: background var(--transition); cursor: pointer; }
    .act-item:hover { background: rgba(255,255,255,.04); }
    .act-ico { width: 28px; height: 28px; border-radius: 50%; display:flex; align-items:center; justify-content:center; flex-shrink: 0; font-size: 12px; margin-top: 1px; }
    .act-ico.warn   { background: rgba(245,158,11,.14); }
    .act-ico.jail   { background: rgba(34,197,94,.14); }
    .act-ico.ban    { background: rgba(239,68,68,.14); }
    .act-ico.ticket { background: rgba(96,165,250,.14); }
    .act-ico.note   { background: var(--gold-faint); }
    .act-body { flex: 1; min-width: 0; }
    .act-desc { font-size: 12.5px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .act-time { font-size: 11px; color: var(--muted); margin-top: 2px; }

    /* Jail items */
    .jail-item { display: flex; align-items: center; gap: 10px; padding: 9px 16px; transition: background var(--transition); }
    .jail-item:hover { background: rgba(255,255,255,.02); }
    .jail-user { flex: 1; min-width: 0; }
    .jail-name { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .jail-exp  { font-size: 11px; color: var(--muted); margin-top: 2px; }

    /* Offender rows */
    .off-item { display: flex; align-items: center; gap: 10px; padding: 9px 16px; }
    .off-item:hover { background: rgba(255,255,255,.02); }
    .off-avatar { width: 28px; height: 28px; border-radius: 50%; background: var(--border); flex-shrink: 0; overflow: hidden; }
    .off-avatar img { width: 100%; height: 100%; object-fit: cover; }
    .off-name { flex: 1; font-size: 13px; color: var(--text); min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .off-count { font-family: var(--font-mono); font-size: 11px; color: var(--gold); font-weight: 600; }

    /* AutoMod status card */
    .am-body { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
    .am-row { display: flex; align-items: center; gap: 10px; font-size: 12.5px; }
    .am-row .am-lbl { flex: 1; color: var(--text); }
    .am-row .am-val { font-family: var(--font-mono); font-size: 11px; color: var(--muted); }
    .am-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .am-dot.on  { background: var(--green); box-shadow: 0 0 6px rgba(34,197,94,.5); }
    .am-dot.off { background: rgba(255,255,255,.15); }

    /* Health card */
    .hlth-body { padding: 14px 16px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .hlth-row { display: flex; flex-direction: column; }
    .hlth-lbl { font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 600; }
    .hlth-val { font-family: var(--font-mono); font-size: 14px; color: var(--text); margin-top: 3px; }

    /* Trend chart */
    .trend-wrap { padding: 14px 16px 12px; }
    .trend-svg { width: 100%; height: 90px; display: block; }
    .trend-axis { font-family: var(--font-mono); font-size: 10px; color: var(--muted); display: flex; justify-content: space-between; padding: 6px 2px 0; }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = skeleton();
  try {
    const [stats, activity, jails, health, trends, offenders, automod] = await Promise.all([
      apiFetch('/dashboard/stats'),
      apiFetch('/dashboard/activity'),
      apiFetch('/jails?active_only=true'),
      apiFetch('/health').catch(() => null),
      apiFetch('/warns/trends?days=30').catch(() => []),
      apiFetch('/top-offenders?limit=5').catch(() => []),
      apiFetch('/automod/summary').catch(() => null),
    ]);
    container.innerHTML = buildPage({ stats, activity, jails, health, trends, offenders, automod });
  } catch (e) {
    container.innerHTML = errState();
  }
}

function skeleton() {
  return `<div class="dash-wrap">
    <div class="stat-grid">${Array(4).fill(`<div class="card skeleton" style="height:80px"></div>`).join('')}</div>
    <div class="dash-cols">
      <div class="skeleton" style="height:280px;border-radius:10px"></div>
      <div class="skeleton" style="height:280px;border-radius:10px"></div>
    </div>
    <div class="dash-3col">
      <div class="skeleton" style="height:180px;border-radius:10px"></div>
      <div class="skeleton" style="height:180px;border-radius:10px"></div>
      <div class="skeleton" style="height:180px;border-radius:10px"></div>
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

const ACT_ICONS = { warn:'⚠️', jail:'🔒', unjail:'🔓', ban:'🔨', kick:'👢', mute:'🔇', unmute:'🔊', softban:'⚔️', ticket:'💬', note:'🔖' };

function buildPage({ stats, activity, jails, health, trends, offenders, automod }) {
  const acts     = Array.isArray(activity)  ? activity  : [];
  const jailList = Array.isArray(jails)     ? jails     : [];
  const off      = Array.isArray(offenders) ? offenders : [];
  const trendData= Array.isArray(trends)    ? trends    : [];
  const trendTotal = trendData.reduce((s, d) => s + (d.count || 0), 0);

  return `<div class="dash-wrap">
    <div class="stat-grid">
      ${statCard('Total Warns',  stats?.total_warns  ?? '—', '', 'gold')}
      ${statCard('Active Jails', stats?.active_jails ?? '—', '', jailList.length ? 'red' : '')}
      ${statCard('Open Tickets', stats?.open_tickets ?? '—', '', acts.some(a => a.type==='ticket') ? 'green' : '')}
      ${statCard('Members',      stats?.member_count ?? '—', '')}
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

    <div class="dash-3col">
      <div class="card section-card">
        <div class="section-hd">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M18 9l-6 6-4-4-3 3"/></svg>
          Warns · Last 30 days
          <span class="hd-count">${trendTotal} total</span>
        </div>
        ${trendChart(trendData)}
      </div>

      <div class="card section-card">
        <div class="section-hd">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          Top Offenders
        </div>
        <div class="scroll-list">
          ${off.length === 0
            ? `<div class="empty-state"><div class="state-icon">✨</div><p>No warns yet</p></div>`
            : off.map(offRow).join('')}
        </div>
      </div>

      <div class="card section-card">
        <div class="section-hd">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          AutoMod &amp; Bot
        </div>
        ${automodAndHealth(automod, health)}
      </div>
    </div>
  </div>`;
}

function statCard(label, value, sub, cls) {
  return `<div class="card stat-card">
    <div class="stat-label">${label}</div>
    <div class="stat-value ${cls || ''}">${value}</div>
    ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
  </div>`;
}

const ACT_VERBS = {
  warn: 'Warned', jail: 'Jailed', unjail: 'Unjailed', ban: 'Banned',
  kick: 'Kicked', mute: 'Muted', unmute: 'Unmuted', softban: 'Softbanned',
  ticket: 'Ticket from', note: 'Note on',
};

function actRow(item) {
  const type   = (item.type || 'warn').toLowerCase();
  const target = item.target_username
    ? esc(item.target_username)
    : (item.target_id ? `User ${esc(item.target_id)}` : 'Unknown user');
  const actor  = item.actor_username ? esc(item.actor_username) : '';
  const verb   = ACT_VERBS[type] || (type.charAt(0).toUpperCase() + type.slice(1));
  const reason = item.reason ? ` — ${esc(item.reason)}` : '';

  const desc = `${verb} ${target}${actor ? ` by ${actor}` : ''}${reason}`;

  // No dedicated page per action type — warns go to the Warns page,
  // everything else (jail/ban/kick/mute/etc.) goes to Mod Logs, which
  // lists every action type.
  const route = type === 'warn' ? 'warns' : 'modlogs';

  return `<div class="act-item" onclick="location.hash='#${route}'" title="View in ${route === 'warns' ? 'Warns' : 'Mod Logs'}">
    <div class="act-ico ${type}">${ACT_ICONS[type] || '📋'}</div>
    <div class="act-body">
      <div class="act-desc">${desc}</div>
      <div class="act-time">${ago(item.timestamp)}</div>
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

function offRow(o) {
  return `<div class="off-item">
    <div class="off-avatar">${o.avatar ? `<img src="${esc(o.avatar)}" alt="">` : ''}</div>
    <div class="off-name">${esc(o.username || `User ${o.user_id}`)}</div>
    <div class="off-count">${o.warn_count}</div>
  </div>`;
}

function trendChart(data) {
  if (!data.length) {
    return `<div class="empty-state" style="padding: 40px 20px"><div class="state-icon">📊</div><p>No warns in the last 30 days</p></div>`;
  }
  const max = Math.max(1, ...data.map(d => d.count || 0));
  const W = 300, H = 90, PAD = 4;
  const step = (W - PAD * 2) / Math.max(1, data.length - 1);

  const points = data.map((d, i) => {
    const x = PAD + i * step;
    const y = H - PAD - ((d.count || 0) / max) * (H - PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  const area = `M ${PAD},${H - PAD} L ${points.split(' ').join(' L ')} L ${(PAD + (data.length-1) * step).toFixed(1)},${H - PAD} Z`;

  const first = data[0]?.date || '';
  const last  = data[data.length - 1]?.date || '';

  return `<div class="trend-wrap">
    <svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      <path d="${area}" fill="var(--gold-faint)" stroke="none"/>
      <polyline points="${points}" fill="none" stroke="var(--gold)" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>
    <div class="trend-axis">
      <span>${shortDate(first)}</span>
      <span>peak: ${max}</span>
      <span>${shortDate(last)}</span>
    </div>
  </div>`;
}

function automodAndHealth(am, hl) {
  const rows = [
    { on: !!am?.spam,    label: 'Spam',    val: am ? (am.spam ? am.spam_action : 'off')    : '?' },
    { on: !!am?.links,   label: 'Links',   val: am ? (am.links ? am.link_mode : 'off')     : '?' },
    { on: !!am?.invites, label: 'Invites', val: am ? (am.invites ? 'blocking' : 'off')     : '?' },
  ];

  const health = hl ? `
    <div class="hlth-body">
      <div class="hlth-row"><span class="hlth-lbl">Latency</span><span class="hlth-val">${hl.latency_ms != null ? hl.latency_ms + ' ms' : '—'}</span></div>
      <div class="hlth-row"><span class="hlth-lbl">Uptime</span><span class="hlth-val">${fmtUptime(hl.uptime_seconds)}</span></div>
      <div class="hlth-row"><span class="hlth-lbl">Memory</span><span class="hlth-val">${hl.memory_mb != null ? hl.memory_mb + ' MB' : '—'}</span></div>
      <div class="hlth-row"><span class="hlth-lbl">Guilds</span><span class="hlth-val">${hl.guilds ?? '—'}</span></div>
    </div>
  ` : '';

  return `
    <div class="am-body" style="border-bottom:1px solid var(--border)">
      ${rows.map(r => `
        <div class="am-row">
          <span class="am-dot ${r.on ? 'on' : 'off'}"></span>
          <span class="am-lbl">${r.label}</span>
          <span class="am-val">${r.val}</span>
        </div>
      `).join('')}
    </div>
    ${health}
  `;
}

function fmtUptime(sec) {
  if (!sec && sec !== 0) return '—';
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

function shortDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}/${d.getDate()}`;
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
