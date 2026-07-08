import { apiFetch, post, put } from '../api.js';

let _notes = [], _search = '';

function injectStyles() {
  if (document.getElementById('s-notes')) return;
  const s = document.createElement('style');
  s.id = 's-notes';
  s.textContent = `
    .nt-wrap { padding: 24px; }
    .nt-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
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
    .note-uid { font-size: 11px; color: var(--muted); font-family: var(--font-mono); margin-top: 2px; }
    .note-meta { font-size: 11px; color: var(--muted); text-align: right; font-family: var(--font-mono); line-height: 1.7; flex-shrink: 0; }
    .note-body { font-size: 13px; color: var(--muted); line-height: 1.6; margin-bottom: 10px; white-space: pre-wrap; }
    .note-edit-ta {
      width: 100%; background: var(--card-2); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); font: inherit; font-size: 13px;
      padding: 8px 10px; box-sizing: border-box; outline: none; min-height: 60px;
      resize: vertical; margin-bottom: 10px;
    }
    .note-edit-ta:focus { border-color: var(--border-focus); }
    .note-foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .note-confirm { display: none; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); }
    .note-confirm.show { display: flex; }
    .note-status { font-size: 11.5px; margin-left: auto; }
    .note-status.ok  { color: var(--green); }
    .note-status.err { color: var(--red); }

    /* ─── Add-note modal (same shape as add-warn) ─── */
    .nt-modal-backdrop {
      position: fixed; inset: 0; background: rgba(0,0,0,.55);
      display: flex; align-items: center; justify-content: center;
      z-index: 1000; padding: 24px; opacity: 0; pointer-events: none;
      transition: opacity var(--transition);
    }
    .nt-modal-backdrop.open { opacity: 1; pointer-events: auto; }
    .nt-modal {
      background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 22px; max-width: 460px; width: 100%;
      box-shadow: 0 24px 60px -20px rgba(0,0,0,.7);
    }
    .nt-modal h3 { font-size: 15px; margin: 0 0 4px; color: var(--text); }
    .nt-modal-sub { font-size: 12px; color: var(--muted); margin-bottom: 18px; }
    .nt-modal label { display: block; font-size: 11.5px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; margin-bottom: 6px; }
    .nt-modal .field { margin-bottom: 14px; position: relative; }
    .nt-modal input, .nt-modal textarea {
      width: 100%; background: var(--card-2); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); font: inherit; font-size: 13px;
      padding: 9px 11px; box-sizing: border-box; outline: none;
      transition: border-color var(--fast);
    }
    .nt-modal input:focus, .nt-modal textarea:focus { border-color: var(--border-focus); }
    .nt-modal textarea { min-height: 68px; resize: vertical; }
    .nt-suggest {
      position: absolute; top: 100%; left: 0; right: 0; z-index: 10;
      background: var(--card-2); border: 1px solid var(--border-focus);
      border-radius: var(--radius); margin-top: 4px; max-height: 220px;
      overflow-y: auto; box-shadow: 0 8px 24px rgba(0,0,0,.4); display: none;
    }
    .nt-suggest.open { display: block; }
    .nt-suggest-item {
      display: flex; align-items: center; gap: 10px; padding: 8px 12px;
      cursor: pointer; font-size: 13px; transition: background var(--fast);
    }
    .nt-suggest-item:hover, .nt-suggest-item.hi { background: rgba(255,255,255,.04); }
    .nt-suggest-avatar { width: 24px; height: 24px; border-radius: 50%; background: var(--border); flex-shrink: 0; overflow: hidden; }
    .nt-suggest-avatar img { width: 100%; height: 100%; object-fit: cover; }
    .nt-suggest-name { color: var(--text); }
    .nt-suggest-handle { color: var(--muted); font-family: var(--font-mono); font-size: 11px; margin-left: auto; }
    .nt-modal-actions { display: flex; align-items: center; gap: 10px; margin-top: 18px; }
    .nt-modal-status { font-size: 12px; flex: 1; }
    .nt-modal-status.ok  { color: var(--green); }
    .nt-modal-status.err { color: var(--red); }
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
      <button class="btn btn-primary" id="nt-add-btn">+ Add note</button>
      <span style="font-size:12px;color:var(--muted);margin-left:auto" id="nt-count"></span>
    </div>
    <div id="nt-list"></div>
    ${addNoteModalHTML()}
  </div>`;
}

function addNoteModalHTML() {
  return `<div class="nt-modal-backdrop" id="nt-modal-back">
    <div class="nt-modal" role="dialog" aria-labelledby="nt-modal-title">
      <h3 id="nt-modal-title">Add a note</h3>
      <p class="nt-modal-sub">Private staff note. Never visible to the target.</p>
      <div class="field">
        <label>User</label>
        <input id="nt-user" type="text" placeholder="Start typing a username…" autocomplete="off">
        <div class="nt-suggest" id="nt-suggest"></div>
      </div>
      <div class="field">
        <label>Note</label>
        <textarea id="nt-content" placeholder="What should staff know about this user?"></textarea>
      </div>
      <div class="nt-modal-actions">
        <span class="nt-modal-status" id="nt-modal-status"></span>
        <button class="btn btn-ghost"    id="nt-modal-cancel">Cancel</button>
        <button class="btn btn-primary"  id="nt-modal-submit" disabled>Add note</button>
      </div>
    </div>
  </div>`;
}

function renderNotes(container) {
  const list  = document.getElementById('nt-list');
  const count = document.getElementById('nt-count');
  if (!list) return;

  const filtered = _search
    ? _notes.filter(n => (n.target_username || '').toLowerCase().includes(_search.toLowerCase()))
    : _notes;

  if (count) count.textContent = `${filtered.length} notes`;

  if (filtered.length === 0) {
    list.innerHTML = `<div class="empty-state"><div class="state-icon">🔖</div><p>No notes found</p></div>`;
    return;
  }

  list.innerHTML = filtered.map(n => noteCardHTML(n)).join('');

  attachNoteHandlers(list, container);
}

function noteCardHTML(n) {
  const id = n.note_id ?? n.id;
  const uname = n.target_username || `User ${n.target_id}`;
  const author = n.author_username || `User ${n.author_id}`;
  return `<div class="note-card" data-id="${esc(String(id))}">
    <div class="note-hd">
      <div>
        <div class="note-uname">${esc(uname)}</div>
        <div class="note-uid">${esc(n.target_id || '')}</div>
      </div>
      <div class="note-meta">#${id}<br>${esc(author)} · ${fmtDate(n.created_at)}</div>
    </div>
    <div class="note-body" data-role="body">${esc(n.content || '')}</div>
    <textarea class="note-edit-ta" data-role="editor" style="display:none">${esc(n.content || '')}</textarea>
    <div class="note-foot">
      <div data-role="view-actions">
        <button class="btn btn-ghost btn-sm edit-btn" data-id="${id}">Edit</button>
        <button class="btn btn-danger btn-sm del-btn" data-id="${id}">Delete</button>
      </div>
      <div data-role="edit-actions" style="display:none">
        <button class="btn btn-primary btn-sm save-btn" data-id="${id}">Save</button>
        <button class="btn btn-ghost btn-sm cancel-edit-btn" data-id="${id}">Cancel</button>
      </div>
      <div class="note-confirm" id="nc-${id}">
        Are you sure?
        <button class="btn btn-danger btn-sm confirm-yes" data-id="${id}">Yes, delete</button>
        <button class="btn btn-ghost  btn-sm confirm-no"  data-id="${id}">Cancel</button>
      </div>
      <span class="note-status" data-role="status"></span>
    </div>
  </div>`;
}

function attachNoteHandlers(list, container) {
  // Edit
  list.querySelectorAll('.edit-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.note-card');
      card.querySelector('[data-role="body"]').style.display = 'none';
      card.querySelector('[data-role="editor"]').style.display = 'block';
      card.querySelector('[data-role="view-actions"]').style.display = 'none';
      card.querySelector('[data-role="edit-actions"]').style.display = 'flex';
      card.querySelector('[data-role="editor"]').focus();
    });
  });
  list.querySelectorAll('.cancel-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.note-card');
      // Restore original content
      const original = _notes.find(n => String(n.id ?? n.note_id) === String(btn.dataset.id))?.content || '';
      card.querySelector('[data-role="editor"]').value = original;
      card.querySelector('[data-role="body"]').style.display = '';
      card.querySelector('[data-role="editor"]').style.display = 'none';
      card.querySelector('[data-role="view-actions"]').style.display = '';
      card.querySelector('[data-role="edit-actions"]').style.display = 'none';
      card.querySelector('[data-role="status"]').textContent = '';
    });
  });
  list.querySelectorAll('.save-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const card = btn.closest('.note-card');
      const ta = card.querySelector('[data-role="editor"]');
      const status = card.querySelector('[data-role="status"]');
      const newText = ta.value.trim();
      if (!newText) {
        status.className = 'note-status err';
        status.textContent = 'Note cannot be empty';
        return;
      }
      btn.disabled = true;
      status.className = 'note-status';
      status.textContent = 'Saving…';
      try {
        await put(`/notes/${id}`, { content: newText });
        // Update local state
        const n = _notes.find(x => String(x.id ?? x.note_id) === String(id));
        if (n) n.content = newText;
        // Update view
        card.querySelector('[data-role="body"]').textContent = newText;
        card.querySelector('[data-role="body"]').style.display = '';
        ta.style.display = 'none';
        card.querySelector('[data-role="view-actions"]').style.display = '';
        card.querySelector('[data-role="edit-actions"]').style.display = 'none';
        status.className = 'note-status ok';
        status.textContent = 'Saved';
        setTimeout(() => { status.textContent = ''; status.className = 'note-status'; }, 1500);
      } catch (e) {
        status.className = 'note-status err';
        status.textContent = 'Save failed';
      } finally {
        btn.disabled = false;
      }
    });
  });

  // Delete → confirm
  list.querySelectorAll('.del-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.note-card');
      card.querySelector('[data-role="view-actions"]').style.display = 'none';
      document.getElementById(`nc-${btn.dataset.id}`)?.classList.add('show');
    });
  });
  list.querySelectorAll('.confirm-no').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.note-card');
      document.getElementById(`nc-${btn.dataset.id}`)?.classList.remove('show');
      card.querySelector('[data-role="view-actions"]').style.display = '';
    });
  });
  list.querySelectorAll('.confirm-yes').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      btn.textContent = '…'; btn.disabled = true;
      try {
        await apiFetch(`/notes/${id}`, { method: 'DELETE' });
        _notes = _notes.filter(n => String(n.id ?? n.note_id) !== String(id));
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
  attachAddNoteModal(container);
}

// ── Add-note modal ──────────────────────────────────────────────────────────

function attachAddNoteModal(container) {
  const back    = document.getElementById('nt-modal-back');
  const openBtn = document.getElementById('nt-add-btn');
  const cancel  = document.getElementById('nt-modal-cancel');
  const submit  = document.getElementById('nt-modal-submit');
  const userIn  = document.getElementById('nt-user');
  const content = document.getElementById('nt-content');
  const status  = document.getElementById('nt-modal-status');
  const sug     = document.getElementById('nt-suggest');

  let picked = null;
  let sugIdx = -1;
  let sugItems = [];
  let sugTimer = null;

  const close = () => {
    back.classList.remove('open');
    userIn.value = ''; content.value = ''; status.textContent = '';
    picked = null; sug.classList.remove('open');
    submit.disabled = true;
  };
  openBtn?.addEventListener('click', () => { back.classList.add('open'); userIn.focus(); });
  cancel?.addEventListener('click', close);
  back?.addEventListener('click', e => { if (e.target === back) close(); });

  const canSubmit = () => picked && content.value.trim().length > 0;
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
            <div class="nt-suggest-item" data-i="${i}">
              <div class="nt-suggest-avatar">${u.avatar ? `<img src="${esc(u.avatar)}" alt="">` : ''}</div>
              <div class="nt-suggest-name">${esc(u.username)}</div>
              <div class="nt-suggest-handle">@${esc(u.handle)}</div>
            </div>
          `).join('');
          sug.querySelectorAll('.nt-suggest-item').forEach(el => {
            el.addEventListener('click', () => {
              picked = sugItems[Number(el.dataset.i)];
              userIn.value = picked.username;
              sug.classList.remove('open');
              refreshBtn();
              content.focus();
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
      content.focus();
    } else if (e.key === 'Escape') {
      sug.classList.remove('open');
    }
  });

  function highlight() {
    sug.querySelectorAll('.nt-suggest-item').forEach((el, i) =>
      el.classList.toggle('hi', i === sugIdx)
    );
  }

  content?.addEventListener('input', refreshBtn);

  submit?.addEventListener('click', async () => {
    if (!canSubmit()) return;
    submit.disabled = true;
    status.className = 'nt-modal-status';
    status.textContent = 'Saving…';
    try {
      await post('/notes', {
        target_id: picked.user_id,
        content:   content.value.trim(),
      });
      status.className = 'nt-modal-status ok';
      status.textContent = 'Note added.';
      setTimeout(async () => {
        close();
        try {
          const data = await apiFetch('/notes');
          _notes = Array.isArray(data) ? data : (data?.notes ?? []);
          renderNotes(document);
        } catch {}
      }, 900);
    } catch (e) {
      status.className = 'nt-modal-status err';
      status.textContent = 'Failed: ' + (e.message || e);
      submit.disabled = false;
    }
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
