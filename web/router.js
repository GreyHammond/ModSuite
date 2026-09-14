import { buildLayout, setPageTitle, setActiveNav } from './shell/layout.js';

// Route table. Adding a page means adding an entry here and a matching entry
// in NAV in shell/sidebar.js -- a route with no nav entry is unreachable.
const ROUTES = {
  dashboard:       { title: 'Dashboard',       loader: () => import('./pages/dashboard.js') },
  modlogs:         { title: 'Mod Logs',        loader: () => import('./pages/modlogs.js') },
  moderation:      { title: 'Moderation',      loader: () => import('./pages/moderation.js') },
  warns:           { title: 'Warns',           loader: () => import('./pages/warns.js') },
  notes:           { title: 'Notes',           loader: () => import('./pages/notes.js') },
  tickets:         { title: 'Tickets',         loader: () => import('./pages/tickets.js') },
  automod:         { title: 'AutoMod',         loader: () => import('./pages/automod.js') },
  autoresponses:   { title: 'Autoresponses',   loader: () => import('./pages/autoresponses.js') },
  streamers:       { title: 'Streamers',       loader: () => import('./pages/streamers.js') },
  configuration:   { title: 'Configuration',   loader: () => import('./pages/configuration.js') },
  selfroles:       { title: 'Self Roles',      loader: () => import('./pages/selfroles.js') },
  reactroles:      { title: 'React Roles',     loader: () => import('./pages/reactroles.js') },
  starboards:      { title: 'Starboards',      loader: () => import('./pages/starboards.js') },
  reminders:       { title: 'Reminders',       loader: () => import('./pages/reminders.js') },
  civic:           { title: 'Feeds & Events', loader: () => import('./pages/civic.js') },
  foia:            { title: 'Records Requests',loader: () => import('./pages/foia.js') },
  audit:           { title: 'Audit Trail',     loader: () => import('./pages/audit.js') },
  archive:         { title: 'Archive',         loader: () => import('./pages/archive.js') },
  blueprints:      { title: 'Blueprints',      loader: () => import('./pages/blueprints.js') },
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
