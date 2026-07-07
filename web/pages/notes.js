import { apiFetch } from '../api.js';

let _notes = [], _search = '';

function injectStyles() {
  if (document.getElementById('s-notes')) return;
  const s = document.createElement('style');
  s.id = 's-notes';
  s.textContent = `
    .nt-wrap { padding: 24px; }
    .nt-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
    .note-card {
      background: var(--card); border: 1px solid var(--border);
      border-left: 3px solid var(--gold); border-radius: 10px;
      padding: 14px 16px; margin-bottom: 10px;
      transition: box-shadow var(--transition);
    }
    .note-card:hover { box-shadow: 0 2px 14px rgba(0,0,0,.3); }
    .note-card.removing { opacity: 0; transform: translateY(-4px); transition: opacity 180ms, transform 180ms; }
    .note-hd { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 8px; }
    .note-uname { font-size: 14px; font-weight: 600; flex: 1; }
    .note-meta { font-size: 11px; color: var(--muted); text-align: right; font-family: var(--font-mono); line-height: 1.7; flex-shrink: 0; }
    .note-body { font-size: 13px; color: var(--muted); line-height: 1.6; margin-bottom: 10px; }
    .note-foot { display: flex; align-items: center; gap: 8px; }
    .note-confirm { display: none; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); }
    .note-confirm.show { display: flex; }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="nt-wrap">${Array(4).fill(`<div class="skeleton" style="height:100px;border-radius:10px;margin-bottom:10px"></div>`).join('')}</div>`;
  try {
    const data = await apiFetch('/notes');
    _notes = Array.isArray(data) ? data : (data?.notes ?? []);
    _search = '';
    container.innerHTML = buildPage();
    attach(container);
    renderNotes(container);
  } catch {
    container.innerHTML = errState();
  }
}

function buildPage() {
  return `<div class="nt-wrap">
    <div class="nt-toolbar">
      <input type="text" class="input" id="nt-search" placeholder="Search by username…" style="max-width:260px">
      <span style="font-size:12px;color:var(--muted);margin-left:auto" id="nt-count"></span>
    </div>
    <div id="nt-list"></div>
  </div>`;
}

function renderNotes(container) {
  const list  = document.getElementById('nt-list');
  const count = document.getElementById('nt-count');
  if (!list) return;

  const filtered = _search
    ? _notes.filter(n => (n.username || n.user_name || '').toLowerCase().includes(_search.toLowerCase()))
    : _notes;

  if (count) count.textContent = `${filtered.length} notes`;

  if (filtered.length === 0) {
    list.innerHTML = `<div class="empty-state"><div class="state-icon">🔖</div><p>No notes found</p></div>`;
    return;
  }

  list.innerHTML = filtered.map(n => `
    <div class="note-card" data-id="${esc(String(n.id))}">
      <div class="note-hd">
        <div class="note-uname">${esc(n.username || n.user_name || `User ${n.user_id}`)}</div>
        <div class="note-meta">#${n.id}<br>${esc(n.author || n.mod_name || '?')} · ${fmtDate(n.created_at)}</div>
      </div>
      <div class="note-body">${esc(n.content || n.note || '')}</div>
      <div class="note-foot">
        <button class="btn btn-danger btn-sm del-btn" data-id="${n.id}">Delete</button>
        <div class="note-confirm" id="nc-${n.id}">
          Are you sure?
          <button class="btn btn-danger btn-sm confirm-yes" data-id="${n.id}">Yes, delete</button>
          <button class="btn btn-ghost  btn-sm confirm-no"  data-id="${n.id}">Cancel</button>
        </div>
      </div>
    </div>`).join('');

  // Delete → show inline confirm
  list.querySelectorAll('.del-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.style.display = 'none';
      document.getElementById(`nc-${btn.dataset.id}`)?.classList.add('show');
    });
  });

  // Cancel
  list.querySelectorAll('.confirm-no').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById(`nc-${btn.dataset.id}`)?.classList.remove('show');
      list.querySelector(`.del-btn[data-id="${btn.dataset.id}"]`).style.display = '';
    });
  });

  // Confirm delete
  list.querySelectorAll('.confirm-yes').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      btn.textContent = '…'; btn.disabled = true;
      try {
        await apiFetch(`/notes/${id}`, { method: 'DELETE' });
        _notes = _notes.filter(n => String(n.id) !== String(id));
        const card = list.querySelector(`.note-card[data-id="${id}"]`);
        if (card) {
          card.classList.add('removing');
          setTimeout(() => renderNotes(container), 190);
        }
      } catch {
        btn.textContent = 'Yes, delete'; btn.disabled = false;
      }
    });
  });
}

function attach(container) {
  container.querySelector('#nt-search')?.addEventListener('input', e => {
    _search = e.target.value; renderNotes(container);
  });
}

function errState() {
  return `<div class="nt-wrap"><div class="error-state">
    <div class="state-icon">⚠️</div>
    <p>Could not load notes. Is the bot running?</p>
    <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
  </div></div>`;
}

const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmtDate = d => !d ? '—' : new Date(d).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'2-digit'});
