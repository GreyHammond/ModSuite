import { apiFetch, post } from '../api.js';

let _warns = [], _search = '', _activeOnly = true;

function injectStyles() {
  if (document.getElementById('s-warns')) return;
  const s = document.createElement('style');
  s.id = 's-warns';
  s.textContent = `
    .wn-wrap { padding: 24px; }
    .wn-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
    .warn-card {
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid; border-radius: 10px; margin-bottom: 10px; overflow: hidden;
      transition: box-shadow var(--transition);
    }
    .warn-card:hover { box-shadow: 0 2px 14px rgba(0,0,0,.3); }
    .warn-card.sev-low  { border-left-color: #F59E0B; }
    .warn-card.sev-high { border-left-color: #EF4444; }
    .warn-card-hd {
      display: flex; align-items: center; gap: 10px; padding: 12px 14px;
      cursor: pointer; user-select: none; transition: background var(--transition);
    }
    .warn-card-hd:hover { background: rgba(255,255,255,.02); }
    .warn-uname { font-size: 14px; font-weight: 600; color: var(--text); }
    .warn-last  { font-size: 12px; color: var(--muted); margin-top: 2px; }
    .warn-chevron { margin-left: auto; color: var(--muted); transition: transform var(--transition); flex-shrink:0; }
    .warn-card.open .warn-chevron { transform: rotate(180deg); }
    .warn-history { display: none; border-top: 1px solid var(--border); padding: 10px 14px; }
    .warn-card.open .warn-history { display: block; }
    .warn-entry {
      display: flex; align-items: flex-start; gap: 10px;
      padding: 8px 0; border-bottom: 1px solid var(--border);
    }
    .warn-entry:last-child { border-bottom: none; padding-bottom: 0; }
    .we-body { flex: 1; min-width: 0; }
    .we-reason { font-size: 13px; color: var(--text); }
    .we-meta { font-size: 11px; color: var(--muted); margin-top: 3px; font-family: var(--font-mono); }
    .we-actions { flex-shrink: 0; display: flex; align-items: center; gap: 6px; }

    /* ─── Add-warn modal ─── */
    .wn-modal-backdrop {
      position: fixed; inset: 0; background: rgba(0,0,0,.55);
      display: flex; align-items: center; justify-content: center;
      z-index: 1000; padding: 24px;
      opacity: 0; pointer-events: none;
      transition: opacity var(--transition);
    }
    .wn-modal-backdrop.open { opacity: 1; pointer-events: auto; }
    .wn-modal {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 22px; max-width: 460px; width: 100%;
      box-shadow: 0 24px 60px -20px rgba(0,0,0,.7);
    }
    .wn-modal h3 {
      font-size: 15px; margin: 0 0 4px; color: var(--text);
    }
    .wn-modal-sub { font-size: 12px; color: var(--muted); margin-bottom: 18px; }
    .wn-modal label { display: block; font-size: 11.5px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; margin-bottom: 6px; }
    .wn-modal .field { margin-bottom: 14px; position: relative; }
    .wn-modal input, .wn-modal textarea {
      width: 100%; background: var(--card-2); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); font: inherit; font-size: 13px;
      padding: 9px 11px; box-sizing: border-box; outline: none;
      transition: border-color var(--fast);
    }
    .wn-modal input:focus, .wn-modal textarea:focus { border-color: var(--border-focus); }
    .wn-modal textarea { min-height: 68px; resize: vertical; }
    .wn-suggest {
      position: absolute; top: 100%; left: 0; right: 0; z-index: 10;
      background: var(--card-2); border: 1px solid var(--border-focus);
      border-radius: var(--radius); margin-top: 4px; max-height: 220px;
      overflow-y: auto; box-shadow: 0 8px 24px rgba(0,0,0,.4);
      display: none;
    }
    .wn-suggest.open { display: block; }
    .wn-suggest-item {
      display: flex; align-items: center; gap: 10px; padding: 8px 12px;
      cursor: pointer; font-size: 13px; transition: background var(--fast);
    }
    .wn-suggest-item:hover, .wn-suggest-item.hi { background: rgba(255,255,255,.04); }
    .wn-suggest-avatar {
      width: 24px; height: 24px; border-radius: 50%; background: var(--border);
      flex-shrink: 0; overflow: hidden;
    }
    .wn-suggest-avatar img { width: 100%; height: 100%; object-fit: cover; }
    .wn-suggest-name { color: var(--text); }
    .wn-suggest-handle { color: var(--muted); font-family: var(--font-mono); font-size: 11px; margin-left: auto; }
    .wn-modal-actions { display: flex; align-items: center; gap: 10px; margin-top: 18px; }
    .wn-modal-status { font-size: 12px; flex: 1; }
    .wn-modal-status.ok  { color: var(--green); }
    .wn-modal-status.err { color: var(--red); }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="wn-wrap">${Array(3).fill(`<div class="skeleton" style="height:76px;border-radius:10px;margin-bottom:10px"></div>`).join('')}</div>`;
  try {
    const data = await apiFetch('/warns');
    _warns = Array.isArray(data) ? data : (data?.warns ?? []);
    _search = ''; _activeOnly = true;
    container.innerHTML = buildPage();
    attach(container);
    renderList(container);
  } catch {
    container.innerHTML = errState();
  }
}

function buildPage() {
  return `<div class="wn-wrap">
    <div class="wn-toolbar">
      <input type="text" class="input" id="wn-search" placeholder="Search by username…" style="max-width:260px">
      <label class="toggle-wrap">
        <input type="checkbox" id="wn-active" checked>
        <div class="toggle-pill"></div>
        Active only
      </label>
      <button class="btn btn-primary" id="wn-add-btn">+ Add warn</button>
      <span style="font-size:12px;color:var(--muted);margin-left:auto" id="wn-count"></span>
    </div>
    <div id="wn-list"></div>
    ${addWarnModalHTML()}
  </div>`;
}

function addWarnModalHTML() {
  return `<div class="wn-modal-backdrop" id="wn-modal-back">
    <div class="wn-modal" role="dialog" aria-labelledby="wn-modal-title">
      <h3 id="wn-modal-title">Add a warn</h3>
      <p class="wn-modal-sub">The bot will DM the user and log to <code style="color:var(--gold)">#mod-log</code>.</p>
      <div class="field">
        <label>User</label>
        <input id="wn-user" type="text" placeholder="Start typing a username…" autocomplete="off">
        <div class="wn-suggest" id="wn-suggest"></div>
      </div>
      <div class="field">
        <label>Reason</label>
        <textarea id="wn-reason" placeholder="Reason for the warn…"></textarea>
      </div>
      <div class="wn-modal-actions">
        <span class="wn-modal-status" id="wn-modal-status"></span>
        <button class="btn btn-ghost"    id="wn-modal-cancel">Cancel</button>
        <button class="btn btn-primary"  id="wn-modal-submit" disabled>Add warn</button>
      </div>
    </div>
  </div>`;
}

function byUser(warns) {
  const map = {};
  for (const w of warns) {
    const k = w.user_id || w.username || 'unknown';
    if (!map[k]) map[k] = { name: w.username || w.user_name || `User ${w.user_id}`, warns: [] };
    map[k].warns.push(w);
  }
  return Object.values(map);
}

function renderList(container) {
  const list  = document.getElementById('wn-list');
  const count = document.getElementById('wn-count');
  if (!list) return;

  let filtered = _warns;
  if (_activeOnly) filtered = filtered.filter(w => w.active !== false && !w.pardoned);
  if (_search) filtered = filtered.filter(w =>
    (w.username || w.user_name || '').toLowerCase().includes(_search.toLowerCase())
  );

  const groups = byUser(filtered);
  if (count) count.textContent = `${groups.length} users`;

  if (groups.length === 0) {
    list.innerHTML = `<div class="empty-state"><div class="state-icon">✅</div><p>No warns found</p></div>`;
    return;
  }

  list.innerHTML = groups.map(u => {
    const active = u.warns.filter(w => w.active !== false && !w.pardoned).length;
    const sev    = active >= 4 ? 'sev-high' : 'sev-low';
    return `<div class="warn-card ${sev}">
      <div class="warn-card-hd" onclick="this.closest('.warn-card').classList.toggle('open')">
        <div>
          <div class="warn-uname">${esc(u.name)}</div>
          <div class="warn-last">${esc(u.warns.at(-1)?.reason || 'No reason')}</div>
        </div>
        <span class="badge badge-warn" style="margin-left:8px">${active} active</span>
        <svg class="warn-chevron" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
      </div>
      <div class="warn-history">${u.warns.map(entryHTML).join('')}</div>
    </div>`;
  }).join('');

  list.querySelectorAll('.pardon-btn').forEach(btn => {
    btn.addEventListener('click', async e => {
      e.stopPropagation();
      const id = btn.dataset.warnId;
      btn.textContent = '…'; btn.disabled = true;
      try {
        await apiFetch(`/warns/${id}`, { method: 'DELETE' });
        const w = _warns.find(x => String(x.id) === String(id));
        if (w) { w.active = false; w.pardoned = true; }
        renderList(container);
      } catch {
        btn.textContent = 'Pardon'; btn.disabled = false;
      }
    });
  });
}

function entryHTML(w) {
  const pardoned = w.active === false || w.pardoned;
  return `<div class="warn-entry">
    <div class="we-body">
      <div class="we-reason">${esc(w.reason || 'No reason')}</div>
      <div class="we-meta">ID: ${w.id} · by ${esc(w.mod_name || w.by || '?')} · ${fmtDate(w.created_at)}</div>
    </div>
    <div class="we-actions">
      ${pardoned
        ? `<span class="badge badge-success">Pardoned</span>`
        : `<button class="btn btn-ghost btn-sm pardon-btn" data-warn-id="${w.id}">Pardon</button>`}
    </div>
  </div>`;
}

function attach(container) {
  container.querySelector('#wn-search')?.addEventListener('input', e => {
    _search = e.target.value; renderList(container);
  });
  container.querySelector('#wn-active')?.addEventListener('change', e => {
    _activeOnly = e.target.checked; renderList(container);
  });
  attachAddWarnModal(container);
}

// ── Add-warn modal ───────────────────────────────────────────────────────────

function attachAddWarnModal(container) {
  const back    = document.getElementById('wn-modal-back');
  const openBtn = document.getElementById('wn-add-btn');
  const cancel  = document.getElementById('wn-modal-cancel');
  const submit  = document.getElementById('wn-modal-submit');
  const userIn  = document.getElementById('wn-user');
  const reason  = document.getElementById('wn-reason');
  const status  = document.getElementById('wn-modal-status');
  const sug     = document.getElementById('wn-suggest');

  let picked = null;         // { user_id, username }
  let sugIdx = -1;
  let sugItems = [];
  let sugTimer = null;

  const close = () => {
    back.classList.remove('open');
    userIn.value = ''; reason.value = ''; status.textContent = '';
    picked = null; sug.classList.remove('open');
    submit.disabled = true;
  };
  openBtn?.addEventListener('click', () => { back.classList.add('open'); userIn.focus(); });
  cancel?.addEventListener('click', close);
  back?.addEventListener('click', e => { if (e.target === back) close(); });

  const canSubmit = () => picked && reason.value.trim().length > 0;
  const refreshBtn = () => { submit.disabled = !canSubmit(); };

  userIn?.addEventListener('input', () => {
    picked = null;
    refreshBtn();
    const q = userIn.value.trim();
    clearTimeout(sugTimer);
    if (q.length < 1) { sug.classList.remove('open'); sug.innerHTML = ''; return; }
    sugTimer = setTimeout(async () => {
      try {
        const users = await apiFetch(`/users/search?q=${encodeURIComponent(q)}&limit=10`);
        sugItems = Array.isArray(users) ? users : [];
        sugIdx = -1;
        if (sugItems.length === 0) {
          sug.innerHTML = `<div style="padding:10px 12px;color:var(--muted);font-size:12px">No matches</div>`;
        } else {
          sug.innerHTML = sugItems.map((u, i) => `
            <div class="wn-suggest-item" data-i="${i}">
              <div class="wn-suggest-avatar">${u.avatar ? `<img src="${esc(u.avatar)}" alt="">` : ''}</div>
              <div class="wn-suggest-name">${esc(u.username)}</div>
              <div class="wn-suggest-handle">@${esc(u.handle)}</div>
            </div>
          `).join('');
          sug.querySelectorAll('.wn-suggest-item').forEach(el => {
            el.addEventListener('click', () => {
              const i = Number(el.dataset.i);
              picked = sugItems[i];
              userIn.value = picked.username;
              sug.classList.remove('open');
              refreshBtn();
              reason.focus();
            });
          });
        }
        sug.classList.add('open');
      } catch {
        sug.innerHTML = `<div style="padding:10px 12px;color:var(--red);font-size:12px">Lookup failed</div>`;
        sug.classList.add('open');
      }
    }, 180);
  });

  userIn?.addEventListener('keydown', e => {
    if (!sug.classList.contains('open') || sugItems.length === 0) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); sugIdx = Math.min(sugIdx + 1, sugItems.length - 1); highlight(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sugIdx = Math.max(sugIdx - 1, 0); highlight(); }
    else if (e.key === 'Enter' && sugIdx >= 0) {
      e.preventDefault();
      picked = sugItems[sugIdx];
      userIn.value = picked.username;
      sug.classList.remove('open');
      refreshBtn();
      reason.focus();
    } else if (e.key === 'Escape') {
      sug.classList.remove('open');
    }
  });

  function highlight() {
    sug.querySelectorAll('.wn-suggest-item').forEach((el, i) =>
      el.classList.toggle('hi', i === sugIdx)
    );
  }

  reason?.addEventListener('input', refreshBtn);

  submit?.addEventListener('click', async () => {
    if (!canSubmit()) return;
    submit.disabled = true;
    status.className = 'wn-modal-status';
    status.textContent = 'Queuing…';
    try {
      const res = await post('/warns', {
        user_id: picked.user_id,
        reason:  reason.value.trim(),
      });
      status.className = 'wn-modal-status ok';
      status.textContent = `Queued (action #${res.action_id}). Will apply within a few seconds.`;
      setTimeout(async () => {
        close();
        // Refresh the warns list to show the new one
        try {
          const data = await apiFetch('/warns');
          _warns = Array.isArray(data) ? data : (data?.warns ?? []);
          renderList(document);
        } catch {}
      }, 1500);
    } catch (e) {
      status.className = 'wn-modal-status err';
      status.textContent = 'Failed: ' + (e.message || e);
      submit.disabled = false;
    }
  });
}

function errState() {
  return `<div class="wn-wrap"><div class="error-state">
    <div class="state-icon">⚠️</div>
    <p>Could not load warns. Is the bot running?</p>
    <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
  </div></div>`;
}

const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmtDate = d => !d ? '—' : new Date(d).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'2-digit'});
