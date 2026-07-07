import { openSidebar } from './layout.js';

export function buildTopbar(el) {
  el.innerHTML = `
<style>
  #topbar {
    height: var(--topbar-height);
    background: var(--sidebar);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 20px;
    gap: 10px;
    flex-shrink: 0;
  }
  .topbar-hamburger {
    display: none;
    background: none;
    border: none;
    color: var(--muted);
    padding: 5px;
    border-radius: 6px;
    transition: color var(--transition), background var(--transition);
    align-items: center;
    justify-content: center;
  }
  .topbar-hamburger:hover { color: var(--text); background: var(--card); }
  #topbar-title {
    flex: 1;
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    letter-spacing: -0.01em;
  }
  .topbar-actions { display: flex; align-items: center; gap: 6px; }
  .tb-bell {
    background: none; border: none;
    color: var(--muted); padding: 6px; border-radius: 7px;
    display: flex; align-items: center; justify-content: center;
    transition: all var(--transition);
  }
  .tb-bell:hover { background: var(--card); color: var(--text); }
  .tb-avatar {
    display: flex; align-items: center; gap: 8px;
    padding: 4px 10px 4px 4px; border-radius: 8px;
    cursor: default; transition: background var(--transition);
    border: 1px solid transparent;
  }
  .tb-avatar:hover { background: var(--card); border-color: var(--border); }
  .avatar-circle {
    width: 28px; height: 28px; border-radius: 50%;
    background: var(--gold-faint);
    border: 1.5px solid rgba(212,168,67,0.3);
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 600; color: var(--gold);
    flex-shrink: 0; overflow: hidden;
  }
  .avatar-circle img { width: 100%; height: 100%; object-fit: cover; }
  .avatar-name { font-size: 13px; font-weight: 500; color: var(--text); }
</style>

<button class="topbar-hamburger" id="hamburger-btn" aria-label="Open menu">
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
    <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
  </svg>
</button>

<span id="topbar-title">Dashboard</span>

<div class="topbar-actions">
  <button class="tb-bell" title="Notifications">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/>
      <path d="M13.73 21a2 2 0 01-3.46 0"/>
    </svg>
  </button>
  <div class="tb-avatar">
    <div class="avatar-circle" id="avatar-circle">A</div>
    <span class="avatar-name" id="avatar-name">Admin</span>
  </div>
</div>`;

  document.getElementById('hamburger-btn')?.addEventListener('click', openSidebar);
}
