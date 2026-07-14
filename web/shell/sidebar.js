import { closeSidebar } from './layout.js';
import { apiFetch } from '../api.js';

const NAV = [
  { key: 'dashboard',     label: 'Dashboard',      icon: iGrid()    },
  { key: 'modlogs',       label: 'Mod Logs',       icon: iList()    },
  { key: 'warns',         label: 'Warns',          icon: iWarn()    },
  { key: 'notes',         label: 'Notes',          icon: iBookmark() },
  { key: 'tickets',       label: 'Tickets',        icon: iMessage(), badge: true },
  { key: 'autoresponses', label: 'Autoresponses',  icon: iReply()   },
  null,
  { key: 'configuration', label: 'Configuration',  icon: iSettings() },
  { key: 'selfroles',     label: 'Self Roles',     icon: iTag()     },
  { key: 'setup',         label: 'Setup',          icon: iSetup()   },
];

export function buildSidebar(el) {
  el.innerHTML = `
<style>
  #sidebar {
    width: var(--sidebar-width);
    height: 100vh;
    background: var(--sidebar);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
  }
  .sb-header {
    padding: 18px 14px 14px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .sb-brand-name {
    font-size: 15px; font-weight: 700; color: var(--text); letter-spacing: -0.02em;
  }
  .sb-brand-sub {
    font-size: 10px; color: var(--muted); letter-spacing: 0.02em;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .sb-server {
    margin: 10px 10px 4px;
    padding: 7px 10px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    font-size: 12px;
    color: var(--text);
    transition: border-color var(--transition);
    appearance: none;
    width: calc(100% - 20px);
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='11' viewBox='0 0 24 24' fill='none' stroke='%238888A0' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 9px center;
    background-color: var(--card);
    padding-right: 26px;
    font-family: var(--font);
  }
  .sb-server:focus { border-color: rgba(212,168,67,0.4); outline: none; }
  .sb-nav { flex: 1; padding: 6px 8px; overflow-y: auto; overflow-x: hidden; }
  .sb-nav::-webkit-scrollbar { width: 3px; }
  .sb-nav::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
  .nav-divider { height: 1px; background: var(--border); margin: 6px 2px; }
  .nav-item {
    display: flex; align-items: center; gap: 8px;
    padding: 7px 9px; border-radius: 7px;
    color: var(--muted); font-size: 13px; font-weight: 500;
    cursor: pointer; transition: all var(--transition);
    text-decoration: none; margin-bottom: 1px;
  }
  .nav-item svg { flex-shrink: 0; }
  .nav-item:hover { background: var(--card); color: var(--text); }
  .nav-item.active { background: var(--gold-faint); color: var(--gold); }
  .nav-badge {
    margin-left: auto;
    background: var(--gold); color: #0E0E14;
    font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 999px;
    min-width: 18px; text-align: center;
    display: none;
  }
  .nav-badge.visible { display: block; }
  .sb-footer {
    padding: 11px 14px;
    border-top: 1px solid var(--border);
    font-size: 10px; color: var(--muted);
    letter-spacing: 0.04em; text-align: center;
  }
</style>

<div class="sb-header">
  ${shieldSVG()}
  <div>
    <div class="sb-brand-name">ModSuite</div>
    <div class="sb-brand-sub">Hammond Digital Studios</div>
  </div>
</div>

<select class="sb-server" id="server-selector" style="display:none">
  <option>Loading…</option>
</select>

<nav class="sb-nav">
  ${NAV.map(item => item === null
    ? `<div class="nav-divider"></div>`
    : `<a class="nav-item" href="#${item.key}" data-route="${item.key}">
         ${item.icon}
         <span>${item.label}</span>
         ${item.badge ? `<span class="nav-badge" id="ticket-badge"></span>` : ''}
       </a>`
  ).join('')}
</nav>

<div class="sb-footer">ModSuite · Hammond Digital Studios</div>`;

  // Close on mobile nav click
  el.querySelectorAll('.nav-item').forEach(a =>
    a.addEventListener('click', () => { if (window.innerWidth <= 768) closeSidebar(); })
  );

  loadTicketBadge();
  setInterval(loadTicketBadge, 30_000);
  loadServerSelector();
}

async function loadTicketBadge() {
  try {
    const data = await apiFetch('/tickets?status=open');
    const count = Array.isArray(data) ? data.length : (data?.tickets?.length ?? 0);
    const badge = document.getElementById('ticket-badge');
    if (!badge) return;
    badge.textContent = count > 99 ? '99+' : count;
    badge.classList.toggle('visible', count > 0);
  } catch { /* silent */ }
}

async function loadServerSelector() {
  const sel = document.getElementById('server-selector');
  if (!sel) return;
  try {
    const data = await apiFetch('/guilds');
    const guilds = Array.isArray(data) ? data : [];
    sel.innerHTML = guilds.length
      ? guilds.map(g => `<option value="${esc(String(g.id))}">${esc(g.name)}</option>`).join('')
      : '<option value="">No servers</option>';
  } catch {
    sel.innerHTML = '<option value="">Server</option>';
  }
}

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }

// ── Icons ─────────────────────────────────────────────────────────────────────
function shieldSVG() {
  return `<svg width="30" height="30" viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">
    <path d="M15 3L5 7V14C5 19.8 9.6 25.3 15 27C20.4 25.3 25 19.8 25 14V7L15 3Z"
      fill="rgba(212,168,67,0.12)" stroke="#D4A843" stroke-width="1.4" stroke-linejoin="round"/>
    <path d="M11 14.5L13.5 17L19 12" stroke="#D4A843" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}
function iGrid() { return svg(`<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>`); }
function iList() { return svg(`<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><circle cx="3.5" cy="6" r="1.5" fill="currentColor" stroke="none"/><circle cx="3.5" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="3.5" cy="18" r="1.5" fill="currentColor" stroke="none"/>`); }
function iWarn() { return svg(`<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>`); }
function iBookmark() { return svg(`<path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/>`); }
function iMessage() { return svg(`<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>`); }
function iSettings() { return svg(`<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>`); }
function iTag() { return svg(`<path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>`); }
function iSetup() { return svg(`<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>`); }
function iReply() { return svg(`<polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 00-4-4H4"/>`); }
function svg(paths) {
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}
