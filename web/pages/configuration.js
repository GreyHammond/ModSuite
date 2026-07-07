/**
 * configuration.js — Agent 4
 * Panel A: Bot Messages  (GET /bot-messages, PUT /bot-messages/{slot}, DELETE /bot-messages/{slot})
 * Panel B: Post as Bot   (GET /channels, POST /post-as-bot)
 */

import { get, post, put, del } from '../api.js';

// ── Slot metadata ─────────────────────────────────────────────────────────────

const SLOT_META = {
  warn_dm:         { label: 'Warn DM',         vars: ['{user}', '{reason}'] },
  jail_dm:         { label: 'Jail DM',         vars: ['{user}', '{reason}', '{duration}'] },
  unjail_dm:       { label: 'Unjail DM',       vars: ['{user}'] },
  mute_dm:         { label: 'Mute DM',         vars: ['{user}', '{reason}', '{duration}'] },
  ban_dm:          { label: 'Ban DM',          vars: ['{user}', '{reason}'] },
  join_message:    { label: 'Join Message',    vars: ['{user}'] },
  welcome_message: { label: 'Welcome Message', vars: ['{user}'] },
};

// ── Styles ────────────────────────────────────────────────────────────────────

function injectStyles() {
  if (document.getElementById('cfg-styles')) return;
  const s = document.createElement('style');
  s.id = 'cfg-styles';
  s.textContent = `
    .cfg-wrap   { display:flex; flex-direction:column; gap:20px; max-width:800px; }

    /* Section title row inside a .card */
    .cfg-panel-title {
      font-size:13px; font-weight:600; color:var(--text);
      margin:0 0 18px; padding-bottom:14px;
      border-bottom:1px solid var(--border);
      letter-spacing:.03em;
    }

    /* Individual message slot */
    .cfg-slot { padding:16px 0; border-bottom:1px solid var(--border); }
    .cfg-slot:first-of-type { padding-top:0; }
    .cfg-slot:last-of-type  { border-bottom:none; padding-bottom:0; }

    .cfg-slot-header {
      display:flex; align-items:center; gap:8px;
      margin-bottom:8px; flex-wrap:wrap;
    }
    .cfg-slot-label { font-size:13px; font-weight:600; color:var(--text); }

    .cfg-vars { display:flex; gap:4px; flex-wrap:wrap; }
    .cfg-chip {
      font-family:var(--font-mono); font-size:11px;
      color:var(--gold); background:var(--gold-faint);
      border:1px solid rgba(212,168,67,.25);
      border-radius:var(--radius-sm); padding:1px 6px;
    }

    .cfg-reset-link {
      margin-left:auto; font-size:11.5px; color:var(--muted);
      background:none; border:none; padding:0;
      text-decoration:underline; text-underline-offset:2px;
      cursor:pointer; transition:color var(--fast);
    }
    .cfg-reset-link:hover { color:var(--text); }
    .cfg-reset-link[hidden] { display:none; }

    /* Textarea */
    .cfg-ta {
      width:100%; min-height:68px;
      background:var(--card-2); border:1px solid var(--border);
      border-radius:var(--radius); color:var(--text);
      font-size:13px; font-family:inherit; line-height:1.55;
      padding:9px 12px; resize:vertical; box-sizing:border-box;
      transition:border-color var(--fast); outline:none;
    }
    .cfg-ta:focus { border-color:var(--border-focus); }
    .cfg-ta.dirty { border-color:rgba(212,168,67,.3); }

    /* Save row */
    .cfg-save-row {
      display:flex; align-items:center; gap:12px;
      margin-top:20px; padding-top:16px;
      border-top:1px solid var(--border);
    }
    .cfg-status { font-size:12.5px; }
    .cfg-status.ok  { color:var(--green); }
    .cfg-status.err { color:var(--red); }

    /* Post as Bot fields */
    .cfg-field { margin-bottom:14px; }
    .cfg-field:last-child { margin-bottom:0; }
    .cfg-field-label {
      display:block; font-size:11.5px; font-weight:600;
      color:var(--muted); text-transform:uppercase;
      letter-spacing:.07em; margin-bottom:6px;
    }
    .cfg-select {
      width:100%; background:var(--card-2);
      border:1px solid var(--border); border-radius:var(--radius);
      color:var(--text); font-size:13px; font-family:inherit;
      padding:9px 32px 9px 12px; appearance:none; outline:none;
      background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%238888A0' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
      background-repeat:no-repeat; background-position:right 11px center;
      transition:border-color var(--fast); cursor:pointer;
    }
    .cfg-select:focus { border-color:var(--border-focus); }
    .cfg-ta-msg {
      width:100%; min-height:100px;
      background:var(--card-2); border:1px solid var(--border);
      border-radius:var(--radius); color:var(--text);
      font-size:13px; font-family:inherit; line-height:1.55;
      padding:9px 12px; resize:vertical; box-sizing:border-box;
      transition:border-color var(--fast); outline:none;
    }
    .cfg-ta-msg:focus { border-color:var(--border-focus); }
  `;
  document.head.appendChild(s);
}

// ── Utilities ─────────────────────────────────────────────────────────────────

const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function flash(el, text, type, ms = 3500) {
  el.textContent = text;
  el.className = `cfg-status ${type}`;
  clearTimeout(el._t);
  if (ms > 0) el._t = setTimeout(() => { el.textContent = ''; el.className = 'cfg-status'; }, ms);
}

// ── Panel A: Bot Messages ──────────────────────────────────────────────────────

async function renderBotMessages(wrap) {
  wrap.innerHTML = '<div class="cfg-panel-title">Bot Messages</div><div class="page-loading"><div class="spinner"></div></div>';

  let slots;
  try {
    slots = await get('/bot-messages');
  } catch (err) {
    wrap.innerHTML = `
      <div class="cfg-panel-title">Bot Messages</div>
      <div class="page-error">
        <span class="error-icon">⚠️</span>
        <p>Could not load messages. Is the bot running?</p>
        <button class="btn btn-ghost btn-sm" id="bm-retry">Retry</button>
      </div>`;
    wrap.querySelector('#bm-retry').onclick = () => renderBotMessages(wrap);
    return;
  }

  // Track original content for dirty-checking
  const original  = {};
  const defaults  = {};
  slots.forEach(m => { original[m.slot] = m.content; defaults[m.slot] = m.default; });

  const rowsHtml = slots.map(m => {
    const meta      = SLOT_META[m.slot] || { label: m.slot, vars: [] };
    const chips     = meta.vars.map(v => `<span class="cfg-chip">${esc(v)}</span>`).join('');
    const isCustom  = m.content !== m.default;
    return `
      <div class="cfg-slot" data-slot-row="${esc(m.slot)}">
        <div class="cfg-slot-header">
          <span class="cfg-slot-label">${esc(meta.label)}</span>
          <span class="cfg-vars">${chips}</span>
          <button class="cfg-reset-link" data-reset="${esc(m.slot)}"
            ${isCustom ? '' : 'hidden'}>Reset to default</button>
        </div>
        <textarea class="cfg-ta" data-slot="${esc(m.slot)}"
          spellcheck="false">${esc(m.content)}</textarea>
      </div>`;
  }).join('');

  wrap.innerHTML = `
    <div class="cfg-panel-title">Bot Messages</div>
    <div class="cfg-slots">${rowsHtml}</div>
    <div class="cfg-save-row">
      <button class="btn btn-gold" id="bm-save">Save changes</button>
      <span class="cfg-status" id="bm-msg"></span>
    </div>`;

  const saveBtn = wrap.querySelector('#bm-save');
  const saveMsg = wrap.querySelector('#bm-msg');

  // Mark textarea dirty on input
  wrap.querySelectorAll('.cfg-ta[data-slot]').forEach(ta => {
    ta.addEventListener('input', () =>
      ta.classList.toggle('dirty', ta.value !== original[ta.dataset.slot])
    );
  });

  // Reset to default
  wrap.addEventListener('click', async e => {
    const btn = e.target.closest('[data-reset]');
    if (!btn || btn.hidden) return;
    const slot = btn.dataset.reset;
    btn.disabled = true;
    btn.textContent = 'Resetting…';
    try {
      const res = await del(`/bot-messages/${slot}`);
      const ta  = wrap.querySelector(`.cfg-ta[data-slot="${slot}"]`);
      if (ta) {
        ta.value = res.default ?? defaults[slot] ?? '';
        original[slot] = ta.value;
        ta.classList.remove('dirty');
      }
      btn.hidden = true;
      btn.disabled = false;
      btn.textContent = 'Reset to default';
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Reset to default';
      flash(saveMsg, `Reset failed: ${err.message}`, 'err', 6000);
    }
  });

  // Save all dirty slots
  saveBtn.addEventListener('click', async () => {
    const dirty = [...wrap.querySelectorAll('.cfg-ta.dirty')].map(ta => ({
      slot: ta.dataset.slot, content: ta.value, ta,
    }));
    if (!dirty.length) { flash(saveMsg, 'No changes to save.', 'err', 2000); return; }

    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    saveMsg.textContent = '';
    const failed = [];

    for (const { slot, content, ta } of dirty) {
      try {
        await put(`/bot-messages/${slot}`, { content });
        original[slot] = content;
        ta.classList.remove('dirty');
        // Show/hide reset link
        const row = wrap.querySelector(`[data-slot-row="${slot}"]`);
        const resetBtn = row?.querySelector('[data-reset]');
        if (resetBtn) resetBtn.hidden = content === defaults[slot];
      } catch { failed.push(slot); }
    }

    saveBtn.disabled = false;
    saveBtn.textContent = 'Save changes';
    if (failed.length === 0) {
      flash(saveMsg, `✓ Saved ${dirty.length} message${dirty.length > 1 ? 's' : ''}`, 'ok');
    } else {
      flash(saveMsg, `Saved some. Failed: ${failed.join(', ')}`, 'err', 6000);
    }
  });
}

// ── Panel B: Post as Bot ──────────────────────────────────────────────────────

async function renderPostAsBot(wrap) {
  wrap.innerHTML = '<div class="cfg-panel-title">Post as Bot</div><div class="page-loading"><div class="spinner"></div></div>';

  let channels;
  try {
    channels = await get('/channels');
  } catch (err) {
    wrap.innerHTML = `
      <div class="cfg-panel-title">Post as Bot</div>
      <div class="page-error">
        <span class="error-icon">⚠️</span>
        <p>Could not load channels. Is the bot running?</p>
        <button class="btn btn-ghost btn-sm" id="pab-retry">Retry</button>
      </div>`;
    wrap.querySelector('#pab-retry').onclick = () => renderPostAsBot(wrap);
    return;
  }

  // Group channels by Discord category
  const groups = {};
  channels.forEach(ch => {
    const cat = ch.category || 'Uncategorised';
    (groups[cat] = groups[cat] || []).push(ch);
  });
  const optgroupsHtml = Object.entries(groups).map(([cat, chs]) =>
    `<optgroup label="${esc(cat)}">${
      chs.map(ch => `<option value="${esc(ch.channel_id)}">#${esc(ch.name)}</option>`).join('')
    }</optgroup>`
  ).join('');

  wrap.innerHTML = `
    <div class="cfg-panel-title">Post as Bot</div>
    <div class="cfg-field">
      <label class="cfg-field-label" for="pab-ch">Channel</label>
      <select class="cfg-select" id="pab-ch">
        <option value="" disabled selected>Select a channel…</option>
        ${optgroupsHtml}
      </select>
    </div>
    <div class="cfg-field">
      <label class="cfg-field-label" for="pab-msg">Message</label>
      <textarea class="cfg-ta-msg" id="pab-msg" placeholder="Type your message…"></textarea>
    </div>
    <div class="cfg-save-row">
      <button class="btn btn-gold" id="pab-send">Send</button>
      <span class="cfg-status" id="pab-msg-status"></span>
    </div>`;

  const chSel   = wrap.querySelector('#pab-ch');
  const msgTA   = wrap.querySelector('#pab-msg');
  const sendBtn = wrap.querySelector('#pab-send');
  const status  = wrap.querySelector('#pab-msg-status');

  sendBtn.addEventListener('click', async () => {
    if (!chSel.value)        { flash(status, 'Select a channel.', 'err', 0); return; }
    if (!msgTA.value.trim()) { flash(status, 'Message cannot be empty.', 'err', 0); return; }

    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending…';
    status.textContent = '';

    try {
      await post('/post-as-bot', { guild_id: '', channel_id: chSel.value, content: msgTA.value });
      msgTA.value = '';
      chSel.value = '';
      flash(status, '✓ Message sent', 'ok');
    } catch (err) {
      flash(status, `Error: ${err.message}`, 'err', 6000);
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    }
  });

  // Clear validation messages on interaction
  chSel.addEventListener('change', () => { status.textContent = ''; status.className = 'cfg-status'; });
  msgTA.addEventListener('input',  () => { status.textContent = ''; status.className = 'cfg-status'; });
}

// ── Router contract ───────────────────────────────────────────────────────────

export async function render(el) {
  injectStyles();
  el.innerHTML = `
    <div class="page-header">
      <h2>Configuration</h2>
    </div>
    <div class="cfg-wrap">
      <div class="card" id="cfg-bm-panel"></div>
      <div class="card" id="cfg-pab-panel"></div>
    </div>`;

  await Promise.all([
    renderBotMessages(el.querySelector('#cfg-bm-panel')),
    renderPostAsBot(el.querySelector('#cfg-pab-panel')),
  ]);
}
