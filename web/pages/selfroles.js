/**
 * selfroles.js -- Agent 4
 * Self Roles page: category list, intro text editor, new-category builder.
 *
 * GET    /selfroles/categories
 * POST   /selfroles/categories
 * PUT    /selfroles/categories/{id}
 * DELETE /selfroles/categories/{id}
 *
 * Live preview via _selfrolesPreview.js -- renders <@&role_id> (exact Discord format).
 * role_id is a string confirmed present in the API response.
 */

import { get, post, put, del } from '../api.js';
import { buildPreviewHTML, updatePreview } from './_selfrolesPreview.js';

// ── Styles ────────────────────────────────────────────────────────────────────

function injectStyles() {
  if (document.getElementById('sr-styles')) return;
  const s = document.createElement('style');
  s.id = 'sr-styles';
  s.textContent = `
    .sr-wrap { display:flex; flex-direction:column; gap:20px; max-width:800px; }

    /* Top action bar */
    .sr-top-bar { display:flex; justify-content:flex-end; }

    /* Category list card */
    .sr-list-card { padding:0; overflow:hidden; }

    .sr-list-empty {
      padding:40px 20px; text-align:center;
      color:var(--muted); font-size:13.5px;
    }

    /* Category row */
    .sr-cat-row { border-bottom:1px solid var(--border); }
    .sr-cat-row:last-child { border-bottom:none; }

    .sr-cat-header {
      display:flex; align-items:center; gap:12px;
      padding:14px 18px;
    }

    .sr-cat-info { flex:1; min-width:0; }
    .sr-cat-name  { font-size:13.5px; font-weight:600; color:var(--text); }
    .sr-cat-meta  { font-size:11.5px; color:var(--muted); margin-top:2px; }

    .sr-cat-actions { display:flex; align-items:center; gap:8px; flex-shrink:0; }

    /* Inline expand editor */
    .sr-expand {
      display:none; padding:0 18px 18px;
      border-top:1px solid var(--border);
      background:rgba(255,255,255,.015);
    }
    .sr-expand.open { display:block; }

    .sr-expand-label {
      display:block; font-size:11.5px; font-weight:600;
      color:var(--muted); text-transform:uppercase;
      letter-spacing:.07em; margin:16px 0 7px;
    }

    .sr-ta {
      width:100%; min-height:68px;
      background:var(--card-2); border:1px solid var(--border);
      border-radius:var(--radius); color:var(--text);
      font-size:13px; font-family:inherit; line-height:1.55;
      padding:9px 12px; resize:vertical; box-sizing:border-box;
      transition:border-color var(--fast); outline:none;
    }
    .sr-ta:focus { border-color:var(--border-focus); }

    .sr-expand-actions {
      display:flex; align-items:center; gap:10px; margin-top:10px;
    }

    .sr-inline-msg { font-size:12.5px; }
    .sr-inline-msg.ok  { color:var(--green); }
    .sr-inline-msg.err { color:var(--red); }

    /* Delete confirmation strip */
    .sr-del-confirm {
      display:none; align-items:center; gap:10px;
      padding:10px 18px;
      background:rgba(224,85,85,.06);
      border-top:1px solid rgba(224,85,85,.15);
      font-size:12.5px; color:var(--text);
    }
    .sr-del-confirm.open { display:flex; }
    .sr-del-text  { flex:1; }

    /* Preview box */
    .sr-preview-label {
      font-size:11px; font-weight:600; color:var(--muted);
      text-transform:uppercase; letter-spacing:.07em;
      margin:14px 0 6px;
    }
    .sr-preview-pre {
      background:#0E0E14; border:1px solid var(--border);
      border-radius:var(--radius); padding:12px 14px;
      font-family:var(--font-mono); font-size:12.5px;
      color:var(--text); white-space:pre-wrap;
      word-break:break-word; line-height:1.6; margin:0;
    }
    .srp-mention  { color:var(--gold); }
    .srp-new      { color:var(--muted); font-style:italic; }
    .srp-dim      { color:var(--muted-2); }

    /* New category form */
    .sr-new-form {
      border:1px solid rgba(212,168,67,.25);
      border-radius:var(--radius-lg); padding:22px;
      background:var(--card);
    }
    .sr-new-form-title {
      font-size:14px; font-weight:700; color:var(--text);
      margin:0 0 20px;
    }

    .sr-field { margin-bottom:16px; }
    .sr-field:last-child { margin-bottom:0; }
    .sr-field-label {
      display:block; font-size:11.5px; font-weight:600;
      color:var(--muted); text-transform:uppercase;
      letter-spacing:.07em; margin-bottom:6px;
    }
    .sr-field-label .opt {
      font-weight:400; text-transform:none; font-size:11px; margin-left:5px;
    }

    .sr-input {
      width:100%; background:var(--card-2);
      border:1px solid var(--border); border-radius:var(--radius);
      color:var(--text); font-size:13px; font-family:inherit;
      padding:9px 12px; box-sizing:border-box;
      transition:border-color var(--fast); outline:none;
    }
    .sr-input:focus   { border-color:var(--border-focus); }
    .sr-input.invalid { border-color:rgba(224,85,85,.5); }

    .sr-field-error {
      font-size:11.5px; color:var(--red);
      margin-top:5px; display:none;
    }
    .sr-field-error.show { display:block; }

    /* Enforcement toggle */
    .sr-enf-row { display:flex; gap:10px; }
    .sr-enf-btn {
      flex:1; padding:12px; border-radius:var(--radius);
      border:2px solid var(--border); background:var(--card-2);
      color:var(--muted); cursor:pointer; text-align:left;
      transition:all var(--fast);
    }
    .sr-enf-btn:hover { border-color:rgba(255,255,255,.15); color:var(--text); }
    .sr-enf-btn.active {
      border-color:var(--gold); background:var(--gold-faint); color:var(--text);
    }
    .sr-enf-title { display:block; font-size:13px; font-weight:600; margin-bottom:2px; }
    .sr-enf-desc  { display:block; font-size:11.5px; opacity:.7; }

    /* Role entry rows */
    .sr-roles-list { display:flex; flex-direction:column; gap:8px; margin-bottom:8px; }
    .sr-role-row   { display:flex; align-items:center; gap:8px; }

    .sr-emoji-input {
      width:50px; text-align:center; font-size:18px;
      background:var(--card-2); border:1px solid var(--border);
      border-radius:var(--radius); color:var(--text);
      padding:7px 4px; outline:none; flex-shrink:0;
      transition:border-color var(--fast);
    }
    .sr-emoji-input:focus { border-color:var(--border-focus); }

    .sr-role-name-input {
      flex:1; background:var(--card-2); border:1px solid var(--border);
      border-radius:var(--radius); color:var(--text);
      font-size:13px; font-family:inherit;
      padding:9px 12px; outline:none;
      transition:border-color var(--fast);
    }
    .sr-role-name-input:focus { border-color:var(--border-focus); }

    .sr-remove-role {
      background:none; border:none; color:var(--muted-2);
      font-size:18px; line-height:1; padding:0 4px;
      cursor:pointer; flex-shrink:0; transition:color var(--fast);
    }
    .sr-remove-role:hover { color:var(--red); }

    .sr-add-role-btn {
      background:none; border:none; color:var(--gold);
      font-size:12.5px; font-weight:600; cursor:pointer;
      padding:4px 0; letter-spacing:.02em;
      transition:opacity var(--fast);
    }
    .sr-add-role-btn:hover { opacity:.75; }

    /* Form action row */
    .sr-form-actions {
      display:flex; align-items:center; gap:12px;
      margin-top:20px; padding-top:18px;
      border-top:1px solid var(--border);
    }
    .sr-form-err { font-size:12.5px; color:var(--red); }

    .sr-cancel-link {
      background:none; border:none; color:var(--muted);
      font-size:12.5px; cursor:pointer; padding:0;
      text-decoration:underline; text-underline-offset:2px;
      transition:color var(--fast);
    }
    .sr-cancel-link:hover { color:var(--text); }
  `;
  document.head.appendChild(s);
}

// ── Utilities ─────────────────────────────────────────────────────────────────

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function flash(el, text, type, ms = 3000) {
  el.textContent = text;
  el.className = `sr-inline-msg ${type}`;
  clearTimeout(el._t);
  if (ms > 0) el._t = setTimeout(() => { el.textContent = ''; el.className = 'sr-inline-msg'; }, ms);
}

// ── Category row builder ──────────────────────────────────────────────────────

function buildCategoryRow(cat, listEl, onDelete) {
  const isBuiltin  = !!cat.is_builtin;
  const roleCount  = cat.roles?.length ?? 0;
  const enfLabel   = cat.enforcement === 'single' ? 'Single-select' : 'Multi-select';

  const badgeHtml = isBuiltin
    ? `<span class="badge" style="background:var(--gold-faint);color:var(--gold);border:1px solid rgba(212,168,67,.2);font-size:10px">Built-in</span>`
    : `<span class="badge" style="background:rgba(76,175,130,.12);color:var(--green);border:1px solid rgba(76,175,130,.2);font-size:10px">Custom</span>`;

  const deleteBtn = isBuiltin
    ? ''
    : `<button class="btn btn-ghost btn-sm sr-delete-btn">Delete</button>`;

  const rowEl = document.createElement('div');
  rowEl.className = 'sr-cat-row';
  rowEl.dataset.catId = cat.category_id;

  rowEl.innerHTML = `
    <div class="sr-cat-header">
      <div class="sr-cat-info">
        <div class="sr-cat-name">${esc(cat.name)}</div>
        <div class="sr-cat-meta">${roleCount} role${roleCount !== 1 ? 's' : ''} · ${enfLabel}</div>
      </div>
      <div class="sr-cat-actions">
        ${badgeHtml}
        <button class="btn btn-ghost btn-sm sr-edit-btn">Edit intro</button>
        ${deleteBtn}
      </div>
    </div>

    <!-- Inline intro editor -->
    <div class="sr-expand" id="sr-exp-${cat.category_id}">
      <label class="sr-expand-label">Intro text</label>
      <textarea class="sr-ta" id="sr-ta-${cat.category_id}" rows="3"
        placeholder="${isBuiltin
          ? (cat.enforcement === 'single'
              ? 'Select one option. Choosing a new one will remove your current selection.'
              : 'Select any that apply. You can pick multiple.')
          : 'Optional intro message…'
        }">${esc(cat.intro_text ?? '')}</textarea>
      <div class="sr-expand-actions">
        <button class="btn btn-gold btn-sm sr-save-intro-btn">Save</button>
        <button class="sr-cancel-link sr-close-btn">Cancel</button>
        <span class="sr-inline-msg" id="sr-msg-${cat.category_id}"></span>
      </div>
      <div id="sr-preview-${cat.category_id}"></div>
    </div>

    <!-- Delete confirmation (custom only) -->
    ${!isBuiltin ? `
    <div class="sr-del-confirm" id="sr-del-${cat.category_id}">
      <span class="sr-del-text">Are you sure? This will remove the message from Discord.</span>
      <button class="btn btn-danger btn-sm sr-confirm-yes">Confirm</button>
      <button class="btn btn-ghost btn-sm sr-confirm-no">Cancel</button>
    </div>` : ''}
  `;

  // References
  const expandEl   = rowEl.querySelector(`#sr-exp-${cat.category_id}`);
  const ta         = rowEl.querySelector(`#sr-ta-${cat.category_id}`);
  const msgEl      = rowEl.querySelector(`#sr-msg-${cat.category_id}`);
  const previewEl  = rowEl.querySelector(`#sr-preview-${cat.category_id}`);
  const editBtn    = rowEl.querySelector('.sr-edit-btn');
  const saveBtn    = rowEl.querySelector('.sr-save-intro-btn');
  const closeBtn   = rowEl.querySelector('.sr-close-btn');

  // Mount live preview
  updatePreview(previewEl, ta.value, cat.roles ?? [], cat.enforcement);
  ta.addEventListener('input', () =>
    updatePreview(previewEl, ta.value, cat.roles ?? [], cat.enforcement)
  );

  // Toggle editor
  editBtn.addEventListener('click', () => {
    const isOpen = expandEl.classList.contains('open');
    expandEl.classList.toggle('open', !isOpen);
    editBtn.textContent = isOpen ? 'Edit intro' : 'Close';
  });

  closeBtn.addEventListener('click', () => {
    expandEl.classList.remove('open');
    editBtn.textContent = 'Edit intro';
    ta.value = cat.intro_text ?? '';
    updatePreview(previewEl, ta.value, cat.roles ?? [], cat.enforcement);
  });

  // Save intro
  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    try {
      await put(`/selfroles/categories/${cat.category_id}`,
        { intro_text: ta.value.trim() || null });
      cat.intro_text = ta.value.trim() || null;
      flash(msgEl, '✓ Saved', 'ok');
    } catch (err) {
      flash(msgEl, `Error: ${err.message}`, 'err', 5000);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  });

  // Delete flow (custom only)
  if (!isBuiltin) {
    const delConfirm = rowEl.querySelector(`#sr-del-${cat.category_id}`);
    const deleteBtn  = rowEl.querySelector('.sr-delete-btn');
    const confirmYes = rowEl.querySelector('.sr-confirm-yes');
    const confirmNo  = rowEl.querySelector('.sr-confirm-no');

    deleteBtn.addEventListener('click', () => {
      delConfirm.classList.add('open');
      deleteBtn.style.display = 'none';
    });

    confirmNo.addEventListener('click', () => {
      delConfirm.classList.remove('open');
      deleteBtn.style.display = '';
    });

    confirmYes.addEventListener('click', async () => {
      confirmYes.disabled = true;
      confirmYes.textContent = 'Deleting…';
      try {
        await del(`/selfroles/categories/${cat.category_id}`);
        rowEl.remove();
        if (!listEl.querySelector('.sr-cat-row')) {
          listEl.innerHTML = '<div class="sr-list-empty">No custom categories yet.</div>';
        }
        onDelete?.();
      } catch (err) {
        confirmYes.disabled = false;
        confirmYes.textContent = 'Confirm';
        delConfirm.classList.remove('open');
        deleteBtn.style.display = '';
        // Inline error near the row
        const errEl = document.createElement('div');
        errEl.style.cssText = 'font-size:12px;color:var(--red);padding:6px 18px';
        errEl.textContent = `Delete failed: ${err.message}`;
        rowEl.appendChild(errEl);
        setTimeout(() => errEl.remove(), 5000);
      }
    });
  }

  return rowEl;
}

// ── New category form ─────────────────────────────────────────────────────────

function mountNewCategoryForm(containerEl, onSuccess) {
  let enforcement = 'single';
  let roleRows    = [];
  let nextId      = 0;

  containerEl.innerHTML = '';
  const formEl = document.createElement('div');
  formEl.className = 'sr-new-form';
  containerEl.appendChild(formEl);

  // Collect current role state from DOM for preview
  function getRolesForPreview() {
    return roleRows.map(r => ({
      emoji: r.emojiEl?.value?.trim() || '❓',
      name:  r.nameEl?.value?.trim()  || '(role name)',
      role_id: null,
    }));
  }

  function refreshPreview() {
    const introEl = formEl.querySelector('#sr-new-intro');
    updatePreview(
      formEl.querySelector('#sr-new-preview'),
      introEl ? introEl.value : '',
      getRolesForPreview(),
      enforcement
    );
  }

  function renderRoleList() {
    const listEl = formEl.querySelector('#sr-role-list');
    if (!listEl) return;
    listEl.innerHTML = '';
    roleRows.forEach(r => {
      const rowEl = document.createElement('div');
      rowEl.className = 'sr-role-row';
      rowEl.innerHTML = `
        <input class="sr-emoji-input" type="text" placeholder="🎮"
          maxlength="4" value="${esc(r.emoji)}" title="Emoji">
        <input class="sr-role-name-input" type="text"
          placeholder="Role name (e.g. PC)" value="${esc(r.name)}">
        <button class="sr-remove-role" title="Remove">×</button>`;

      const emojiEl = rowEl.querySelector('.sr-emoji-input');
      const nameEl  = rowEl.querySelector('.sr-role-name-input');
      r.emojiEl = emojiEl;
      r.nameEl  = nameEl;

      emojiEl.addEventListener('input', () => {
        // Keep first grapheme cluster only
        const glyphs = [...emojiEl.value];
        if (glyphs.length > 1) emojiEl.value = glyphs[0];
        r.emoji = emojiEl.value;
        refreshPreview();
      });
      nameEl.addEventListener('input', () => { r.name = nameEl.value; refreshPreview(); });

      rowEl.querySelector('.sr-remove-role').addEventListener('click', () => {
        roleRows = roleRows.filter(x => x.id !== r.id);
        renderRoleList();
        refreshPreview();
      });

      listEl.appendChild(rowEl);
    });
  }

  formEl.innerHTML = `
    <p class="sr-new-form-title">New category</p>

    <div class="sr-field">
      <label class="sr-field-label" for="sr-new-name">Category name</label>
      <input class="sr-input" type="text" id="sr-new-name"
        placeholder="e.g. Gaming Platforms" maxlength="60">
      <div class="sr-field-error" id="sr-name-err">Name is required.</div>
    </div>

    <div class="sr-field">
      <label class="sr-field-label" for="sr-new-intro">
        Intro text <span class="opt">(optional)</span>
      </label>
      <textarea class="sr-ta" id="sr-new-intro" rows="3"
        placeholder="Leave blank to use the default for this enforcement type…"></textarea>
    </div>

    <div class="sr-field">
      <label class="sr-field-label">Enforcement</label>
      <div class="sr-enf-row">
        <button class="sr-enf-btn ${enforcement === 'single' ? 'active' : ''}"
                data-enf="single">
          <span class="sr-enf-title">One (single-select)</span>
          <span class="sr-enf-desc">Members can hold only one role at a time.</span>
        </button>
        <button class="sr-enf-btn ${enforcement === 'multi' ? 'active' : ''}"
                data-enf="multi">
          <span class="sr-enf-title">Any (multi-select)</span>
          <span class="sr-enf-desc">Members can hold multiple roles simultaneously.</span>
        </button>
      </div>
    </div>

    <div class="sr-field">
      <label class="sr-field-label">Roles</label>
      <div class="sr-roles-list" id="sr-role-list"></div>
      <button class="sr-add-role-btn" id="sr-add-role">+ Add role</button>
      <div class="sr-field-error" id="sr-roles-err">At least one role is required.</div>
    </div>

    <div id="sr-new-preview"></div>

    <div class="sr-form-actions">
      <button class="btn btn-gold" id="sr-create-btn">Create category</button>
      <button class="sr-cancel-link" id="sr-cancel-btn">Cancel</button>
      <span class="sr-form-err" id="sr-form-err"></span>
    </div>`;

  // Enforcement toggles
  formEl.querySelectorAll('.sr-enf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      enforcement = btn.dataset.enf;
      formEl.querySelectorAll('.sr-enf-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.enf === enforcement)
      );
      refreshPreview();
    });
  });

  // Live preview on intro text
  formEl.querySelector('#sr-new-intro').addEventListener('input', refreshPreview);

  // Add role button
  formEl.querySelector('#sr-add-role').addEventListener('click', () => {
    roleRows.push({ id: nextId++, emoji: '', name: '', emojiEl: null, nameEl: null });
    renderRoleList();
    refreshPreview();
    // Focus new emoji input
    const inputs = formEl.querySelectorAll('.sr-emoji-input');
    if (inputs.length) inputs[inputs.length - 1].focus();
  });

  // Seed one empty row
  roleRows.push({ id: nextId++, emoji: '', name: '', emojiEl: null, nameEl: null });
  renderRoleList();
  refreshPreview();

  // Cancel
  formEl.querySelector('#sr-cancel-btn').addEventListener('click', () => {
    containerEl.innerHTML = '';
    roleRows = [];
    nextId = 0;
    enforcement = 'single';
  });

  // Create
  formEl.querySelector('#sr-create-btn').addEventListener('click', async () => {
    const nameInput   = formEl.querySelector('#sr-new-name');
    const introInput  = formEl.querySelector('#sr-new-intro');
    const nameErr     = formEl.querySelector('#sr-name-err');
    const rolesErr    = formEl.querySelector('#sr-roles-err');
    const formErr     = formEl.querySelector('#sr-form-err');
    const createBtn   = formEl.querySelector('#sr-create-btn');

    // Clear previous errors
    nameInput.classList.remove('invalid');
    nameErr.classList.remove('show');
    rolesErr.classList.remove('show');
    formErr.textContent = '';

    let valid = true;
    if (!nameInput.value.trim()) {
      nameInput.classList.add('invalid');
      nameErr.classList.add('show');
      valid = false;
    }
    const filledRoles = roleRows.filter(r => r.nameEl?.value?.trim());
    if (!filledRoles.length) {
      rolesErr.classList.add('show');
      valid = false;
    }
    if (!valid) return;

    createBtn.disabled = true;
    createBtn.textContent = 'Creating…';

    try {
      await post('/selfroles/categories', {
        guild_id:    '',
        name:        nameInput.value.trim(),
        enforcement,
        intro_text:  introInput.value.trim() || null,
        roles: filledRoles.map(r => ({
          name:  r.nameEl.value.trim(),
          emoji: (r.emojiEl.value.trim()) || '❓',
        })),
      });

      containerEl.innerHTML = '';
      roleRows = [];
      nextId = 0;
      enforcement = 'single';
      onSuccess();
    } catch (err) {
      formErr.textContent = `Error: ${err.message}`;
      createBtn.disabled = false;
      createBtn.textContent = 'Create category';
    }
  });
}

// ── Main render ───────────────────────────────────────────────────────────────

async function renderContent(pageEl) {
  pageEl.innerHTML = '<div class="page-loading"><div class="spinner"></div></div>';

  let categories;
  try {
    categories = await get('/selfroles/categories');
  } catch (err) {
    pageEl.innerHTML = `
      <div class="page-error">
        <span class="error-icon">⚠️</span>
        <p>Could not load categories. Is the bot running?</p>
        <button class="btn btn-ghost btn-sm" id="sr-retry">Retry</button>
      </div>`;
    pageEl.querySelector('#sr-retry').onclick = () => renderContent(pageEl);
    return;
  }

  pageEl.innerHTML = `
    <div class="sr-wrap">
      <div class="sr-top-bar">
        <button class="btn btn-gold" id="sr-new-btn">+ New category</button>
      </div>
      <div class="card sr-list-card" id="sr-list"></div>
      <div id="sr-new-form-container"></div>
    </div>`;

  const listEl         = pageEl.querySelector('#sr-list');
  const newFormCont    = pageEl.querySelector('#sr-new-form-container');
  const newBtn         = pageEl.querySelector('#sr-new-btn');

  // Populate list
  function populateList(cats) {
    listEl.innerHTML = '';
    if (!cats?.length) {
      listEl.innerHTML = '<div class="sr-list-empty">No categories yet. Create your first one above.</div>';
      return;
    }
    cats.forEach(cat => listEl.appendChild(buildCategoryRow(cat, listEl, reload)));
  }

  async function reload() {
    try {
      categories = await get('/selfroles/categories');
      populateList(categories);
    } catch { /* non-critical */ }
  }

  populateList(categories);

  // New category form toggle
  newBtn.addEventListener('click', () => {
    if (newFormCont.children.length) {
      newFormCont.innerHTML = '';
      return;
    }
    mountNewCategoryForm(newFormCont, reload);
    setTimeout(() => newFormCont.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  });
}

// ── Router contract ───────────────────────────────────────────────────────────

export async function render(el) {
  injectStyles();
  el.innerHTML = `
    <div class="page-header">
      <h2>Self Roles</h2>
    </div>
    <div id="sr-content"></div>`;
  await renderContent(el.querySelector('#sr-content'));
}
