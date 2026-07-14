import { buildLayout, setPageTitle, setActiveNav } from './shell/layout.js';

// All 9 routes. Agent 4 fills configuration / selfroles / setup page components.
const ROUTES = {
  dashboard:       { title: 'Dashboard',       loader: () => import('./pages/dashboard.js') },
  modlogs:         { title: 'Mod Logs',        loader: () => import('./pages/modlogs.js') },
  warns:           { title: 'Warns',           loader: () => import('./pages/warns.js') },
  notes:           { title: 'Notes',           loader: () => import('./pages/notes.js') },
  tickets:         { title: 'Tickets',         loader: () => import('./pages/tickets.js') },
  autoresponses:   { title: 'Autoresponses',   loader: () => import('./pages/autoresponses.js') },
  configuration:   { title: 'Configuration',   loader: () => import('./pages/configuration.js') },
  selfroles:       { title: 'Self Roles',      loader: () => import('./pages/selfroles.js') },
  setup:           { title: 'Setup',           loader: () => import('./pages/setup.js') },
};

const DEFAULT = 'dashboard';

async function navigate() {
  const hash = location.hash.replace('#', '').trim() || DEFAULT;
  const routeKey = ROUTES[hash] ? hash : DEFAULT;
  const route = ROUTES[routeKey];

  setActiveNav(routeKey);
  setPageTitle(route.title);

  const main = document.getElementById('page-content');
  if (!main) return;

  main.className = '';
  main.innerHTML = '<div class="spinner-wrap"><div class="spinner"></div></div>';

  try {
    const mod = await route.loader();
    main.classList.add('page-enter');
    await mod.render(main);
  } catch (err) {
    console.error('[router] Failed to load page:', routeKey, err);
    main.innerHTML = `<div class="error-state" style="padding:60px">
      <div class="state-icon">⚠️</div>
      <p>Failed to load this page.</p>
    </div>`;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  await buildLayout(document.getElementById('app'));
  navigate();
});

window.addEventListener('hashchange', navigate);
