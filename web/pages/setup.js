/**
 * setup.js -- Agent 4
 * Server setup checklist + bot messages summary.
 *
 * Data:  GET /bot-messages  •  GET /selfroles/categories
 *
 * Discord-configured resources (roles, channels set via /setup slash command)
 * have no API endpoint in v2.0 -- shown as informational rows.
 */

import { get } from '../api.js';

const VERSION = 'v2.0.0';

// Built-in self-role category names the bot creates during /setup
const BUILTIN_NAMES = ['Colors', 'DM Prefs', 'Pronouns'];

// ── Styles ────────────────────────────────────────────────────────────────────

function injectStyles() {
  if (document.getElementById('setup-styles')) return;
  const s = document.createElement('style');
  s.id = 'setup-styles';
  s.textContent = `
    .setup-wrap { display:flex; flex-direction:column; gap:20px; max-width:680px; }

    /* Version tag */
    .setup-version {
      display:inline-flex; align-items:center;
      font-size:11px; font-weight:600; letter-spacing:.04em;
      color:var(--gold); background:var(--gold-faint);
      border:1px solid rgba(212,168,67,.2);
      border-radius:20px; padding:2px 9px;
      vertical-align:middle; margin-left:10px;
    }

    /* Card section title */
    .setup-card-title {
      font-size:13px; font-weight:600; color:var(--text);
      margin:0 0 0; padding:14px 18px;
      border-bottom:1px solid var(--border);
      letter-spacing:.03em;
    }

    /* Checklist */
    .setup-list { list-style:none; }

    .setup-row {
      display:flex; align-items:center; gap:12px;
      padding:12px 18px;
      border-bottom:1px solid var(--border);
    }
    .setup-row:last-child { border-bottom:none; }

    .setup-icon {
      flex-shrink:0; width:22px; height:22px;
      border-radius:50%; display:flex;
      align-items:center; justify-content:center;
      font-size:11px;
    }
    .setup-icon.ok   { background:rgba(76,175,130,.15); color:var(--green); }
    .setup-icon.warn { background:rgba(224,120,64,.15);  color:var(--orange); }
    .setup-icon.info { background:rgba(136,136,160,.12); color:var(--muted); }

    .setup-row-body { flex:1; min-width:0; }
    .setup-row-name { font-size:13px; color:var(--text); font-weight:500; }
    .setup-row-detail {
      font-size:11.5px; color:var(--muted); margin-top:2px; line-height:1.4;
    }

    /* Summary card */
    .setup-summary { padding:16px 18px; }
    .setup-summary-stat {
      display:flex; align-items:center;
      justify-content:space-between;
      font-size:13px; color:var(--text);
    }
    .setup-summary-val { font-weight:700; color:var(--gold); }
    .setup-summary-note {
      font-size:12px; color:var(--muted); margin-top:6px; line-height:1.5;
    }

    /* Re-run section */
    .setup-rerun {
      display:flex; align-items:center; gap:20px; padding:18px;
    }
    .setup-rerun-body { flex:1; }
    .setup-rerun-title { font-size:13.5px; font-weight:600; color:var(--text); margin:0 0 3px; }
    .setup-rerun-desc  { font-size:12.5px; color:var(--muted); line-height:1.5; }

    .setup-instruction {
      margin-top:10px; padding:10px 13px;
      background:var(--gold-faint-2);
      border:1px solid rgba(212,168,67,.2);
      border-radius:var(--radius-sm);
      font-size:12.5px; color:var(--text); line-height:1.6;
      display:none;
    }
    .setup-instruction.show { display:block; }
    .setup-cmd {
      font-family:var(--font-mono); font-size:12px;
      background:rgba(255,255,255,.07);
      border:1px solid rgba(255,255,255,.1);
      border-radius:4px; padding:1px 6px;
    }
  `;
  document.head.appendChild(s);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

const ICON = {
  ok:   `<svg width="11" height="11" viewBox="0 0 11 11" fill="none">
           <path d="M1.5 5.5l3 3 5-5" stroke="#4CAF82" stroke-width="1.8"
                 stroke-linecap="round" stroke-linejoin="round"/>
         </svg>`,
  warn: `<svg width="11" height="11" viewBox="0 0 11 11" fill="none">
           <path d="M5.5 1.5l4.5 8H1L5.5 1.5z" stroke="#E07840" stroke-width="1.5"
                 stroke-linejoin="round"/>
           <line x1="5.5" y1="5" x2="5.5" y2="7" stroke="#E07840"
                 stroke-width="1.5" stroke-linecap="round"/>
           <circle cx="5.5" cy="8.5" r=".6" fill="#E07840"/>
         </svg>`,
  info: `<svg width="11" height="11" viewBox="0 0 11 11" fill="none">
           <circle cx="5.5" cy="5.5" r="4" stroke="#8888A0" stroke-width="1.5"/>
           <line x1="5.5" y1="5" x2="5.5" y2="8" stroke="#8888A0"
                 stroke-width="1.5" stroke-linecap="round"/>
           <circle cx="5.5" cy="3.2" r=".65" fill="#8888A0"/>
         </svg>`,
};

function buildChecklist(botMessages, categories) {
  const rows = [];

  // Discord-configured resources -- no API endpoint in v2.0
  [
    { name: 'Moderator role',    detail: 'Set via /setup in Discord' },
    { name: 'Owner role',        detail: 'Set via /setup in Discord' },
    { name: 'Mod log channel',   detail: 'Set via /setup in Discord' },
    { name: 'Modmail category',  detail: 'Set via /setup in Discord' },
    { name: 'Jail category',     detail: 'Set via /setup in Discord' },
  ].forEach(r => rows.push({ status: 'info', name: r.name, detail: r.detail, badge: null }));

  // Self-role categories
  const catNames = (categories ?? []).map(c => c.name);

  BUILTIN_NAMES.forEach(name => {
    const found = catNames.includes(name);
    rows.push({
      status: found ? 'ok' : 'warn',
      name:   `Self Roles -- ${name}`,
      detail: found
        ? 'Category configured'
        : 'Run /setup in Discord to create this category',
      badge: found ? 'builtin' : null,
    });
  });

  // Custom categories
  (categories ?? [])
    .filter(c => !c.is_builtin)
    .forEach(c => rows.push({
      status: 'ok',
      name:   `Self Roles -- ${esc(c.name)}`,
      detail: `${c.roles?.length ?? 0} role${c.roles?.length !== 1 ? 's' : ''}`,
      badge:  'custom',
    }));

  return rows;
}

// ── Render ────────────────────────────────────────────────────────────────────

async function renderContent(wrapper) {
  wrapper.innerHTML = '<div class="page-loading"><div class="spinner"></div></div>';

  let botMessages, categories;
  try {
    [botMessages, categories] = await Promise.all([
      get('/bot-messages'),
      get('/selfroles/categories'),
    ]);
  } catch (err) {
    wrapper.innerHTML = `
      <div class="page-error">
        <span class="error-icon">⚠️</span>
        <p>Could not load setup data. Is the bot running?</p>
        <button class="btn btn-ghost btn-sm" id="setup-retry">Retry</button>
      </div>`;
    wrapper.querySelector('#setup-retry').onclick = () => renderContent(wrapper);
    return;
  }

  const checklist   = buildChecklist(botMessages, categories);
  const customCount = (botMessages ?? []).filter(m => m.content !== m.default).length;
  const totalSlots  = 7;

  const rowsHtml = checklist.map(row => {
    const badgeHtml = row.badge === 'builtin'
      ? `<span class="badge" style="background:var(--gold-faint);color:var(--gold);border:1px solid rgba(212,168,67,.2)">Built-in</span>`
      : row.badge === 'custom'
        ? `<span class="badge" style="background:rgba(76,175,130,.12);color:var(--green);border:1px solid rgba(76,175,130,.2)">Custom</span>`
        : '';

    return `
      <li class="setup-row">
        <div class="setup-icon ${row.status}">${ICON[row.status]}</div>
        <div class="setup-row-body">
          <div class="setup-row-name">${esc(row.name)}</div>
          <div class="setup-row-detail">${esc(row.detail)}</div>
        </div>
        ${badgeHtml}
      </li>`;
  }).join('');

  wrapper.innerHTML = `
    <div class="setup-wrap">

      <!-- Checklist -->
      <div class="card" style="padding:0;overflow:hidden;">
        <h3 class="setup-card-title">Configured resources</h3>
        <ul class="setup-list">${rowsHtml}</ul>
      </div>

      <!-- Bot messages summary -->
      <div class="card" style="padding:0;overflow:hidden;">
        <h3 class="setup-card-title">Bot messages</h3>
        <div class="setup-summary">
          <div class="setup-summary-stat">
            <span>Customised messages</span>
            <span class="setup-summary-val">${customCount} of ${totalSlots}</span>
          </div>
          <div class="setup-summary-note">
            ${customCount === 0
              ? 'All messages are using default text. Edit them on the Configuration page.'
              : `${totalSlots - customCount} message${(totalSlots - customCount) !== 1 ? 's' : ''} still using default text.`
            }
          </div>
        </div>
      </div>

      <!-- Re-run setup -->
      <div class="card" style="padding:0;overflow:hidden;">
        <div class="setup-rerun">
          <div class="setup-rerun-body">
            <p class="setup-rerun-title">Re-run server setup</p>
            <p class="setup-rerun-desc">
              Reconfigures roles, channels, and self-role messages via the Discord bot.
              Full web-triggered setup is a future enhancement.
            </p>
            <div class="setup-instruction" id="setup-instruction">
              Run <span class="setup-cmd">/setup</span> in your Discord server to reconfigure ModSuite.
              The bot will walk you through assigning roles, channels, and self-role messages interactively.
            </div>
          </div>
          <button class="btn btn-gold" id="setup-rerun-btn" style="flex-shrink:0;white-space:nowrap">
            Re-run Setup
          </button>
        </div>
      </div>

    </div>`;

  wrapper.querySelector('#setup-rerun-btn').addEventListener('click', () => {
    const instruction = wrapper.querySelector('#setup-instruction');
    instruction.classList.add('show');
    instruction.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
}

// ── Router contract ───────────────────────────────────────────────────────────

export async function render(el) {
  injectStyles();
  el.innerHTML = `
    <div class="page-header">
      <h2>Server Setup <span class="setup-version">${VERSION}</span></h2>
    </div>
    <div id="setup-wrapper"></div>`;
  await renderContent(el.querySelector('#setup-wrapper'));
}
