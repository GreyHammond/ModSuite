/**
 * autoresponses.js -- Autoresponse management page
 *
 * Endpoints used:
 *   GET    /autoresponses         -> list all
 *   POST   /autoresponses         -> create
 *   PUT    /autoresponses/{id}    -> update (toggle, edit)
 *   DELETE /autoresponses/{id}    -> remove
 */

import { get, post, put, del } from '../api.js';

// -- Styles -------------------------------------------------------------------

function injectStyles() {
  if (document.getElementById('ar-styles')) return;
  const s = document.createElement('style');
  s.id = 'ar-styles';
  s.textContent = `
    .ar-wrap { max-width: 900px; padding: 24px; }
    .ar-header {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 20px; flex-wrap: wrap; gap: 12px;
    }
    .ar-header h2 {
      font-size: 20px; font-weight: 600; color: var(--text);
      letter-spacing: -0.02em;
    }
    .ar-header p { font-size: 13px; color: var(--muted); margin-top: 2px; }

    .ar-list { display: flex; flex-direction: column; gap: 10px; }

    .ar-card {
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid var(--gold); border-radius: 10px;
      overflow: hidden; transition: border-color 150ms ease;
    }
    .ar-card.disabled { opacity: 0.55; border-left-color: var(--muted); }

    .ar-card-header {
      display: flex; align-items: center; gap: 12px;
      padding: 14px 18px; cursor: pointer; user-select: none;
    }
    .ar-card-header:hover { background: rgba(255,255,255,0.02); }

    .ar-trigger {
      font-family: var(--font-mono); font-size: 13px; font-weight: 600;
      color: var(--gold); background: var(--gold-faint);
      border: 1px solid rgba(212,168,67,0.25);
      border-radius: 6px; padding: 3px 10px; white-space: nowrap;
    }
    .ar-mode {
      font-size: 11px; color: var(--muted); text-transform: uppercase;
      letter-spacing: 0.04em; flex-shrink: 0;
    }
    .ar-preview {
      flex: 1; min-width: 0; font-size: 12.5px; color: var(--muted);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .ar-actions {
      display: flex; align-items: center; gap: 6px; flex-shrink: 0;
    }

    .ar-expand {
      display: none; border-top: 1px solid var(--border);
      padding: 14px 18px; background: rgba(0,0,0,0.15);
    }
    .ar-card.open .ar-expand { display: block; }

    .ar-response-text {
      font-size: 13px; color: var(--text); line-height: 1.6;
      white-space: pre-wrap; word-break: break-word;
      padding: 10px 14px; background: var(--input);
      border: 1px solid var(--border); border-radius: 7px;
      margin-bottom: 10px;
    }

    .ar-expand-meta {
      font-size: 11px; color: var(--muted);
    }

    /* -- Create form -- */
    .ar-form-card {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 10px; margin-bottom: 20px; overflow: hidden;
    }
    .ar-form-title {
      font-size: 13px; font-weight: 600; color: var(--text);
      padding: 14px 18px; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 8px;
    }
    .ar-form-body { padding: 18px; display: flex; flex-direction: column; gap: 14px; }
    .ar-form-body[hidden] { display: none; }

    .ar-field { display: flex; flex-direction: column; gap: 5px; }
    .ar-field label {
      font-size: 12px; font-weight: 600; color: var(--text);
    }
    .ar-field .hint {
      font-size: 11px; color: var(--muted); margin-top: -2px;
    }
    .ar-field input, .ar-field textarea, .ar-field select {
      width: 100%; background: var(--input); border: 1px solid var(--border);
      border-radius: 7px; color: var(--text); font-size: 13px;
      font-family: inherit; padding: 8px 11px; outline: none;
      transition: border-color 150ms ease; box-sizing: border-box;
    }
    .ar-field textarea {
      min-height: 80px; resize: vertical; font-family: inherit;
    }
    .ar-field input:focus, .ar-field textarea:focus, .ar-field select:focus {
      border-color: rgba(212,168,67,0.45);
    }
    .ar-field select {
      appearance: none; padding-right: 30px; cursor: pointer;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='11' viewBox='0 0 24 24' fill='none' stroke='%238888A0' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
      background-repeat: no-repeat; background-position: right 10px center;
      background-color: var(--input);
    }

    .ar-form-actions {
      display: flex; align-items: center; gap: 10px;
    }
    .ar-status { font-size: 12px; }
    .ar-status.ok  { color: #22C55E; }
    .ar-status.err { color: #EF4444; }

    /* -- Edit modal (inline) -- */
    .ar-edit-row { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
    .ar-edit-row input, .ar-edit-row textarea, .ar-edit-row select {
      width: 100%; background: var(--input); border: 1px solid var(--border);
      border-radius: 7px; color: var(--text); font-size: 13px;
      font-family: inherit; padding: 8px 11px; outline: none;
      box-sizing: border-box;
    }
    .ar-edit-row textarea { min-height: 70px; resize: vertical; }
    .ar-edit-actions { display: flex; gap: 8px; margin-top: 6px; }

    .ar-empty {
      text-align: center; padding: 48px 20px; color: var(--muted);
    }
    .ar-empty-icon { font-size: 32px; margin-bottom: 8px; opacity: 0.5; }
    .ar-empty p { font-size: 13px; line-height: 1.6; max-width: 300px; margin: 0 auto; }

    .ar-chevron {
      color: var(--muted); font-size: 11px; transition: transform 150ms ease;
      flex-shrink: 0;
    }
    .ar-card.open .ar-chevron { transform: rotate(180deg); }
  `;
  document.head.appendChild(s);
}

// -- State & entry point ------------------------------------------------------

let _data = [];

export async function render(container) {
  injectStyles();
  container.innerHTML = '<div class="ar-wrap"><div class="spinner-wrap"><div class="spinner"></div></div></div>';

  try {
    _data = await get('/autoresponses');
    container.innerHTML = buildPage();
    attach(container);
  } catch (e) {
    container.innerHTML = `<div class="ar-wrap"><div class="error-state">
      <div class="state-icon">&#9888;&#65039;</div>
      <p>Could not load autoresponses.</p>
      <p style="font-size:11px;color:var(--muted)">${esc(e.message || '')}</p>
    </div></div>`;
  }
}

// -- Build --------------------------------------------------------------------

function buildPage() {
  return `<div class="ar-wrap">
    <div class="ar-header">
      <div>
        <h2>Autoresponses</h2>
        <p>Define trigger words the bot listens for and automatic replies.</p>
      </div>
      <button class="btn btn-gold" id="ar-toggle-form">+ New Autoresponse</button>
    </div>

    ${buildForm()}
    ${buildList()}
  </div>`;
}

function buildForm() {
  return `<div class="ar-form-card" id="ar-form-card">
    <div class="ar-form-title">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      New Autoresponse
    </div>
    <div class="ar-form-body" id="ar-form-body" hidden>
      <div class="ar-field">
        <label>Trigger</label>
        <div class="hint">The word or phrase the bot will listen for (case-insensitive).</div>
        <input type="text" id="ar-trigger" placeholder="e.g. -lfg" />
      </div>
      <div class="ar-field">
        <label>Response</label>
        <div class="hint">The message the bot will send when the trigger is detected.</div>
        <textarea id="ar-response" placeholder="e.g. Please put any Looking For Group requests in the proper chats! #lfg-chat"></textarea>
      </div>
      <div class="ar-field">
        <label>Match Mode</label>
        <div class="hint">How the trigger should be matched against messages.</div>
        <select id="ar-match-mode">
          <option value="contains" selected>Contains -- trigger appears anywhere in the message</option>
          <option value="exact">Exact -- message is exactly the trigger text</option>
          <option value="startswith">Starts with -- message begins with the trigger</option>
        </select>
      </div>
      <div class="ar-form-actions">
        <button class="btn btn-gold" id="ar-save">Add Autoresponse</button>
        <button class="btn btn-ghost" id="ar-cancel">Cancel</button>
        <span class="ar-status" id="ar-form-status"></span>
      </div>
    </div>
  </div>`;
}

function buildList() {
  if (_data.length === 0) {
    return `<div class="ar-empty">
      <div class="ar-empty-icon">&#128172;</div>
      <p>No autoresponses yet. Click <strong>+ New Autoresponse</strong> above to create your first one.</p>
    </div>`;
  }

  const cards = _data.map((ar, i) => {
    const disabledClass = ar.enabled ? '' : ' disabled';
    const preview = ar.response.length > 80
      ? ar.response.substring(0, 80) + '...'
      : ar.response;
    const modeLabel = ar.match_mode === 'exact' ? 'exact'
      : ar.match_mode === 'startswith' ? 'starts with'
      : 'contains';

    return `<div class="ar-card${disabledClass}" data-id="${ar.id}" data-index="${i}">
      <div class="ar-card-header">
        <span class="ar-trigger">${esc(ar.trigger)}</span>
        <span class="ar-mode">${modeLabel}</span>
        <span class="ar-preview">${esc(preview)}</span>
        <div class="ar-actions">
          <button class="btn btn-sm btn-ghost ar-toggle-btn" data-id="${ar.id}" title="${ar.enabled ? 'Disable' : 'Enable'}">
            ${ar.enabled ? 'Disable' : 'Enable'}
          </button>
          <button class="btn btn-sm btn-danger ar-delete-btn" data-id="${ar.id}" title="Delete">Delete</button>
        </div>
        <span class="ar-chevron">&#9660;</span>
      </div>
      <div class="ar-expand">
        <div class="ar-response-text">${esc(ar.response)}</div>
        <div class="ar-expand-meta">
          Match mode: ${modeLabel} &middot;
          Created: ${ar.created_at ? new Date(ar.created_at).toLocaleDateString() : 'unknown'}
        </div>
        <div class="ar-edit-row" id="ar-edit-${ar.id}">
          <input type="text" value="${esc(ar.trigger)}" data-field="trigger" placeholder="Trigger" />
          <textarea data-field="response" placeholder="Response">${esc(ar.response)}</textarea>
          <select data-field="match_mode">
            <option value="contains"${ar.match_mode === 'contains' ? ' selected' : ''}>Contains</option>
            <option value="exact"${ar.match_mode === 'exact' ? ' selected' : ''}>Exact</option>
            <option value="startswith"${ar.match_mode === 'startswith' ? ' selected' : ''}>Starts with</option>
          </select>
          <div class="ar-edit-actions">
            <button class="btn btn-sm btn-gold ar-edit-save" data-id="${ar.id}">Save Changes</button>
            <span class="ar-status" id="ar-edit-status-${ar.id}"></span>
          </div>
        </div>
      </div>
    </div>`;
  }).join('');

  return `<div class="ar-list">${cards}</div>`;
}

// -- Interactions -------------------------------------------------------------

function attach(container) {
  // Toggle create form visibility
  const formBody = document.getElementById('ar-form-body');
  const toggleBtn = document.getElementById('ar-toggle-form');
  if (toggleBtn && formBody) {
    toggleBtn.addEventListener('click', () => {
      const hidden = formBody.hidden;
      formBody.hidden = !hidden;
      toggleBtn.textContent = hidden ? 'Cancel' : '+ New Autoresponse';
      if (!hidden) {
        // Reset form
        document.getElementById('ar-trigger').value = '';
        document.getElementById('ar-response').value = '';
        document.getElementById('ar-match-mode').value = 'contains';
        document.getElementById('ar-form-status').textContent = '';
      }
    });
  }

  // Cancel button
  document.getElementById('ar-cancel')?.addEventListener('click', () => {
    formBody.hidden = true;
    toggleBtn.textContent = '+ New Autoresponse';
  });

  // Save new autoresponse
  document.getElementById('ar-save')?.addEventListener('click', async () => {
    const trigger = document.getElementById('ar-trigger').value.trim();
    const response = document.getElementById('ar-response').value.trim();
    const mode = document.getElementById('ar-match-mode').value;
    const status = document.getElementById('ar-form-status');

    if (!trigger) { status.className = 'ar-status err'; status.textContent = 'Trigger is required.'; return; }
    if (!response) { status.className = 'ar-status err'; status.textContent = 'Response is required.'; return; }

    status.className = 'ar-status'; status.textContent = 'Saving...';
    try {
      await post('/autoresponses', { trigger, response, match_mode: mode });
      status.className = 'ar-status ok'; status.textContent = 'Created!';
      // Reload
      _data = await get('/autoresponses');
      container.innerHTML = buildPage();
      attach(container);
    } catch (e) {
      status.className = 'ar-status err';
      status.textContent = e.message || 'Failed to create.';
    }
  });

  // Card expand/collapse
  container.querySelectorAll('.ar-card-header').forEach(header => {
    header.addEventListener('click', (e) => {
      // Don't toggle if a button was clicked
      if (e.target.closest('.ar-actions')) return;
      header.closest('.ar-card').classList.toggle('open');
    });
  });

  // Toggle enable/disable
  container.querySelectorAll('.ar-toggle-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.id);
      const ar = _data.find(a => a.id === id);
      if (!ar) return;
      try {
        await put(`/autoresponses/${id}`, { enabled: !ar.enabled });
        _data = await get('/autoresponses');
        container.innerHTML = buildPage();
        attach(container);
      } catch (err) {
        alert('Failed: ' + (err.message || err));
      }
    });
  });

  // Delete
  container.querySelectorAll('.ar-delete-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = parseInt(btn.dataset.id);
      const ar = _data.find(a => a.id === id);
      if (!ar) return;
      if (!confirm(`Delete autoresponse for "${ar.trigger}"?`)) return;
      try {
        await del(`/autoresponses/${id}`);
        _data = await get('/autoresponses');
        container.innerHTML = buildPage();
        attach(container);
      } catch (err) {
        alert('Failed: ' + (err.message || err));
      }
    });
  });

  // Inline edit save
  container.querySelectorAll('.ar-edit-save').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = parseInt(btn.dataset.id);
      const editRow = document.getElementById(`ar-edit-${id}`);
      const status = document.getElementById(`ar-edit-status-${id}`);
      if (!editRow) return;

      const trigger = editRow.querySelector('[data-field="trigger"]').value.trim();
      const response = editRow.querySelector('[data-field="response"]').value.trim();
      const match_mode = editRow.querySelector('[data-field="match_mode"]').value;

      if (!trigger || !response) {
        if (status) { status.className = 'ar-status err'; status.textContent = 'Trigger and response required.'; }
        return;
      }

      if (status) { status.className = 'ar-status'; status.textContent = 'Saving...'; }
      try {
        await put(`/autoresponses/${id}`, { trigger, response, match_mode });
        if (status) { status.className = 'ar-status ok'; status.textContent = 'Saved!'; }
        _data = await get('/autoresponses');
        container.innerHTML = buildPage();
        attach(container);
      } catch (err) {
        if (status) { status.className = 'ar-status err'; status.textContent = err.message || 'Failed.'; }
      }
    });
  });
}

function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
