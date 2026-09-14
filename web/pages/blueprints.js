/**
 * blueprints.js -- Server blueprint management page
 *
 * Endpoints used:
 *   GET  /blueprints               -> list all visible blueprints
 *   GET  /blueprints/{name}        -> full blueprint JSON
 *   POST /blueprints/{name}/apply  -> dry run or real apply
 *   POST /blueprints/export        -> snapshot this server
 *   GET  /blueprint-runs           -> audit trail of past runs
 *   DELETE /blueprints/{name}      -> remove a server-owned blueprint
 */

import { get, post, del } from '../api.js';

// -- Styles -------------------------------------------------------------------

function injectStyles() {
  if (document.getElementById('bp-styles')) return;
  const s = document.createElement('style');
  s.id = 'bp-styles';
  s.textContent = `
    .bp-wrap { max-width: 940px; padding: 24px; }
    .bp-header {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 20px; flex-wrap: wrap; gap: 12px;
    }
    .bp-header h2 {
      font-size: 20px; font-weight: 600; color: var(--text);
      letter-spacing: -0.02em;
    }
    .bp-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .bp-list { display: flex; flex-direction: column; gap: 10px; }

    .bp-card {
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid var(--gold); border-radius: 10px;
      overflow: hidden;
    }
    .bp-card-header {
      display: flex; align-items: center; gap: 12px;
      padding: 14px 18px; flex-wrap: wrap;
    }
    .bp-name {
      font-family: var(--font-mono); font-size: 13px; font-weight: 600;
      color: var(--gold); background: var(--gold-faint);
      border: 1px solid rgba(212,168,67,0.25);
      border-radius: 6px; padding: 3px 10px; white-space: nowrap;
    }
    .bp-scope {
      font-size: 10px; color: var(--muted); text-transform: uppercase;
      letter-spacing: 0.05em; border: 1px solid var(--border);
      border-radius: 4px; padding: 2px 6px;
    }
    .bp-desc {
      flex: 1 1 260px; min-width: 0; font-size: 12.5px; color: var(--muted);
      line-height: 1.5;
    }
    .bp-counts {
      font-size: 11.5px; color: var(--muted); font-family: var(--font-mono);
      white-space: nowrap;
    }
    .bp-actions { display: flex; gap: 6px; flex-shrink: 0; }

    .bp-btn {
      font-family: var(--font); font-size: 12px; font-weight: 500;
      padding: 6px 12px; border-radius: 7px; cursor: pointer;
      border: 1px solid var(--border); background: transparent;
      color: var(--text); transition: all 150ms ease;
    }
    .bp-btn:hover { background: rgba(255,255,255,0.04); }
    .bp-btn.primary {
      background: var(--gold-faint); border-color: rgba(212,168,67,0.35);
      color: var(--gold);
    }
    .bp-btn.danger { color: #E06C6C; border-color: rgba(224,108,108,0.3); }
    .bp-btn:disabled { opacity: 0.5; cursor: not-allowed; }

    .bp-plan {
      display: none; border-top: 1px solid var(--border);
      padding: 14px 18px; background: rgba(0,0,0,0.18);
    }
    .bp-card.open .bp-plan { display: block; }

    .bp-summary {
      display: flex; gap: 16px; flex-wrap: wrap;
      font-size: 12px; margin-bottom: 10px;
    }
    .bp-stat b { font-family: var(--font-mono); font-size: 14px; }
    .bp-stat.create b { color: #5FD98A; }
    .bp-stat.skip b   { color: var(--muted); }
    .bp-stat.fail b   { color: #E06C6C; }

    .bp-log {
      font-family: var(--font-mono); font-size: 11.5px; line-height: 1.7;
      max-height: 340px; overflow-y: auto; white-space: pre-wrap;
      color: var(--muted);
    }
    .bp-log .l-add  { color: #5FD98A; }
    .bp-log .l-same { color: #6B7280; }
    .bp-log .l-edit { color: #D4A843; }
    .bp-log .l-fail { color: #E06C6C; }

    .bp-confirm {
      margin-top: 12px; padding: 12px 14px; border-radius: 8px;
      background: rgba(212,168,67,0.06);
      border: 1px solid rgba(212,168,67,0.25);
      font-size: 12.5px; color: var(--text);
    }
    .bp-confirm label {
      display: flex; align-items: center; gap: 7px;
      font-size: 12px; color: var(--muted); margin: 8px 0;
    }

    .bp-section-title {
      font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--muted); margin: 28px 0 10px;
    }
    .bp-run {
      display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap;
      padding: 9px 14px; border: 1px solid var(--border);
      border-radius: 8px; background: var(--card); font-size: 12px;
      margin-bottom: 6px;
    }
    .bp-run .tag {
      font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
      padding: 1px 6px; border-radius: 4px; border: 1px solid var(--border);
      color: var(--muted);
    }
    .bp-run .tag.live { color: #5FD98A; border-color: rgba(95,217,138,0.3); }
    .bp-empty { padding: 40px; text-align: center; color: var(--muted); font-size: 13px; }
    .bp-toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
  `;
  document.head.appendChild(s);
}

// -- Helpers ------------------------------------------------------------------

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function renderLog(lines) {
  if (!lines || !lines.length) return '<span class="l-same">Nothing to do.</span>';
  return lines.map(line => {
    const symbol = line.charAt(0);
    const cls = symbol === '+' ? 'l-add'
      : symbol === '=' ? 'l-same'
      : symbol === '~' ? 'l-edit'
      : symbol === '!' ? 'l-fail' : '';
    return `<span class="${cls}">${esc(line)}</span>`;
  }).join('\n');
}

function summaryHTML(r) {
  return `
    <div class="bp-summary">
      <span class="bp-stat create"><b>${r.created}</b> to create</span>
      <span class="bp-stat skip"><b>${r.skipped}</b> already exist</span>
      <span class="bp-stat fail"><b>${r.failed}</b> failed</span>
    </div>`;
}

// -- Render -------------------------------------------------------------------

export async function render(root) {
  injectStyles();
  root.innerHTML = `<div class="bp-wrap">
    <div class="bp-header">
      <div>
        <h2>Blueprints</h2>
        <p>Build roles, categories, and channels from a saved layout.
           Nothing is ever deleted, and anything that already exists is left alone.</p>
      </div>
      <div class="bp-toolbar">
        <button class="bp-btn" id="bp-export">Export this server</button>
        <button class="bp-btn" id="bp-refresh">Refresh</button>
      </div>
    </div>
    <div class="bp-list" id="bp-list">
      <div class="bp-empty">Loading…</div>
    </div>
    <div class="bp-section-title">Run history</div>
    <div id="bp-runs"><div class="bp-empty">Loading…</div></div>
  </div>`;

  document.getElementById('bp-refresh')
    .addEventListener('click', () => { loadList(); loadRuns(); });
  document.getElementById('bp-export')
    .addEventListener('click', doExport);

  await loadList();
  await loadRuns();
}

async function loadList() {
  const el = document.getElementById('bp-list');
  try {
    const rows = await get('/blueprints');
    if (!rows.length) {
      el.innerHTML = `<div class="bp-empty">
        No blueprints yet. Drop a JSON file into <code>blueprints/</code> and restart
        the bot, or export this server to create one.</div>`;
      return;
    }
    el.innerHTML = rows.map(cardHTML).join('');
    el.querySelectorAll('[data-preview]').forEach(b =>
      b.addEventListener('click', () => runBlueprint(b.dataset.preview, true)));
    el.querySelectorAll('[data-delete]').forEach(b =>
      b.addEventListener('click', () => removeBlueprint(b.dataset.delete)));
  } catch (err) {
    el.innerHTML = `<div class="bp-empty">Could not load blueprints: ${esc(err.message)}</div>`;
  }
}

function cardHTML(bp) {
  const deletable = bp.scope === 'guild';
  return `<div class="bp-card" id="bp-card-${esc(bp.name)}">
    <div class="bp-card-header">
      <span class="bp-name">${esc(bp.name)}</span>
      <span class="bp-scope">${esc(bp.scope)} · ${esc(bp.source)}</span>
      <span class="bp-desc">${esc(bp.description || 'No description.')}</span>
      <span class="bp-counts">${bp.roles}R · ${bp.categories}C · ${bp.channels}CH</span>
      <span class="bp-actions">
        <button class="bp-btn primary" data-preview="${esc(bp.name)}">Preview</button>
        ${deletable ? `<button class="bp-btn danger" data-delete="${esc(bp.name)}">Delete</button>` : ''}
      </span>
    </div>
    <div class="bp-plan" id="bp-plan-${esc(bp.name)}"></div>
  </div>`;
}

async function runBlueprint(name, dryRun, updateExisting = false) {
  const card = document.getElementById(`bp-card-${name}`);
  const plan = document.getElementById(`bp-plan-${name}`);
  if (!card || !plan) return;

  card.classList.add('open');
  plan.innerHTML = `<div class="bp-log">Running…</div>`;

  try {
    const r = await post(`/blueprints/${encodeURIComponent(name)}/apply`, {
      dry_run: dryRun,
      update_existing: updateExisting,
    });

    plan.innerHTML = `
      ${summaryHTML(r)}
      <div class="bp-log">${renderLog(r.log)}</div>
      ${dryRun ? `
        <div class="bp-confirm">
          <div>Nothing has been changed. Applying will create the
               ${r.created} item${r.created === 1 ? '' : 's'} marked above.</div>
          <label>
            <input type="checkbox" id="bp-upd-${name}">
            Also refresh colors and permissions on things that already exist
          </label>
          <button class="bp-btn primary" id="bp-apply-${name}"
            ${r.created === 0 ? 'disabled' : ''}>
            Apply to this server
          </button>
        </div>` : `
        <div class="bp-confirm">Applied. Run history updated below.</div>`}
    `;

    if (dryRun) {
      const btn = document.getElementById(`bp-apply-${name}`);
      if (btn) btn.addEventListener('click', () => {
        const upd = document.getElementById(`bp-upd-${name}`)?.checked || false;
        btn.disabled = true;
        btn.textContent = 'Applying…';
        runBlueprint(name, false, upd).then(loadRuns);
      });
    }
  } catch (err) {
    plan.innerHTML = `<div class="bp-log l-fail">Failed: ${esc(err.message)}</div>`;
  }
}

async function removeBlueprint(name) {
  if (!confirm(`Delete blueprint "${name}"? This removes the saved layout, not any channels.`)) return;
  try {
    await del(`/blueprints/${encodeURIComponent(name)}`);
    await loadList();
  } catch (err) {
    alert(`Could not delete: ${err.message}`);
  }
}

async function doExport() {
  const name = prompt('Save this server\'s current structure as:', 'server-snapshot');
  if (!name) return;
  try {
    const r = await post(`/blueprints/export?save_as=${encodeURIComponent(name)}`, {});
    await loadList();
    alert(`Exported as "${r.name}". It now appears in the list above.`);
  } catch (err) {
    alert(`Export failed: ${err.message}`);
  }
}

async function loadRuns() {
  const el = document.getElementById('bp-runs');
  if (!el) return;
  try {
    const runs = await get('/blueprint-runs?limit=15');
    if (!runs.length) {
      el.innerHTML = `<div class="bp-empty">No runs yet.</div>`;
      return;
    }
    el.innerHTML = runs.map(r => `
      <div class="bp-run">
        <span class="tag ${r.dry_run ? '' : 'live'}">${r.dry_run ? 'preview' : 'applied'}</span>
        <strong>${esc(r.blueprint)}</strong>
        <span style="color:var(--muted)">
          ${r.created} created · ${r.skipped} skipped · ${r.failed} failed
        </span>
        <span style="color:var(--muted);margin-left:auto">
          ${esc(r.actor)} · ${esc(r.timestamp || '')}
        </span>
      </div>`).join('');
  } catch (err) {
    el.innerHTML = `<div class="bp-empty">Could not load history: ${esc(err.message)}</div>`;
  }
}
