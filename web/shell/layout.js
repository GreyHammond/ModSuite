import { buildSidebar } from './sidebar.js';
import { buildTopbar }  from './topbar.js';

export async function buildLayout(app) {
  app.innerHTML = `
    <div class="sidebar-overlay" id="sidebar-overlay"></div>
    <aside id="sidebar"></aside>
    <div id="main-wrap">
      <header id="topbar"></header>
      <main id="page-content"></main>
    </div>`;

  buildSidebar(document.getElementById('sidebar'));
  buildTopbar(document.getElementById('topbar'));

  document.getElementById('sidebar-overlay')
    .addEventListener('click', closeSidebar);
}

export function setPageTitle(title) {
  const el = document.getElementById('topbar-title');
  if (el) el.textContent = title;
  document.title = `${title} -- ModSuite`;
}

export function setActiveNav(routeKey) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.route === routeKey);
  });
}

export function openSidebar() {
  document.getElementById('sidebar')?.classList.add('open');
  document.getElementById('sidebar-overlay')?.classList.add('active');
}

export function closeSidebar() {
  document.getElementById('sidebar')?.classList.remove('open');
  document.getElementById('sidebar-overlay')?.classList.remove('active');
}
