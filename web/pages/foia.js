/**
 * foia.js -- FOIA request tracker
 *
 * Endpoints:
 *   GET    /foia                  -> list with computed deadline status
 *   POST   /foia                  -> file a new request
 *   PATCH  /foia/{id}             -> update status, notes, fee
 *   POST   /foia/{id}/extend      -> apply the 10-business-day extension
 *   DELETE /foia/{id}             -> remove
 */

import { get, post, patch, del } from '../api.js';

const STATUSES = [
  ['filed', 'Filed'], ['acknowledged', 'Acknowledged'], ['extended', 'Extended'],
  ['fee_quoted', 'Fee quoted'], ['granted', 'Granted'], ['partial', 'Partial'],
  ['denied', 'Denied'], ['appealed', 'Appealed'], ['closed', 'Closed'],
];

function injectStyles() {
  if (document.getElementById('foia-styles')) return;
  const s = document.createElement('style');
  s.id = 'foia-styles';
  s.textContent = `
    .fo-wrap { max-width: 1000px; padding: 24px; }
    .fo-head { display:flex; justify-content:space-between; align-items:flex-start;
      gap:12px; flex-wrap:wrap; margin-bottom:18px; }
    .fo-head h2 { font-size:20px; font-weight:600; letter-spacing:-0.02em; }
    .fo-head p { font-size:13px; color:var(--muted); margin-top:3px; max-width:560px; }

    .fo-stats { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:18px; }
    .fo-stat { background:var(--card); border:1px solid var(--border);
      border-radius:9px; padding:10px 14px; min-width:100px; }
    .fo-stat b { display:block; font-size:19px; font-family:var(--font-mono); }
    .fo-stat.bad b { color:#E06C6C; }
    .fo-stat.warn b { color:#D4A843; }
    .fo-stat span { font-size:11px; color:var(--muted); text-transform:uppercase;
      letter-spacing:0.05em; }

    .fo-new { background:var(--card); border:1px solid var(--border);
      border-radius:10px; padding:16px; margin-bottom:20px; display:none; }
    .fo-new.open { display:block; }
    .fo-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:9px; }
    .fo-row .input { flex:1 1 200px; }

    .fo-card { background:var(--card); border:1px solid var(--border);
      border-left:3px solid var(--border); border-radius:10px;
      padding:13px 16px; margin-bottom:9px; }
    .fo-card.overdue { border-left-color:#E06C6C; }
    .fo-card.soon    { border-left-color:#D4A843; }
    .fo-card.done    { border-left-color:#5FD98A; opacity:0.75; }

    .fo-top { display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }
    .fo-id { font-family:var(--font-mono); font-size:12px; color:var(--gold);
      background:var(--gold-faint); border-radius:5px; padding:2px 7px; }
    .fo-body-name { font-weight:600; font-size:14px; }
    .fo-due { margin-left:auto; font-size:12px; font-family:var(--font-mono); }
    .fo-due.overdue { color:#E06C6C; font-weight:600; }
    .fo-due.soon { color:#D4A843; }
    .fo-subject { font-size:13px; margin-top:6px; line-height:1.5; }
    .fo-meta { font-size:11.5px; color:var(--muted); margin-top:6px; }
    .fo-actions { display:flex; gap:6px; margin-top:10px; flex-wrap:wrap; align-items:center; }
    .fo-actions select.cfg-input { max-width:170px; }
    .fo-notes { margin-top:8px; padding-top:8px; border-top:1px solid var(--border);
      font-size:12px; color:var(--muted); white-space:pre-wrap; }
    .fo-empty { padding:44px; text-align:center; color:var(--muted); font-size:13px; }
    .fo-law { font-size:11.5px; color:var(--muted); margin-top:14px; line-height:1.6;
      border-top:1px solid var(--border); padding-top:12px; }
  `;
  document.head.appendChild(s);
}

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export async function render(root) {
  injectStyles();
  root.innerHTML = `<div class="fo-wrap">
    <div class="fo-head">
      <div>
        <h2>Records Requests</h2>
        <p>Deadlines are computed in business days, skipping weekends and the
           holiday calendar set under Configuration. Defaults match Michigan FOIA:
           5 business days plus one 10-day extension.</p>
      </div>
      <button class="btn btn-gold" id="fo-toggle">File request</button>
    </div>

    <div class="fo-stats" id="fo-stats"></div>

    <div class="fo-new" id="fo-new">
      <div class="fo-row">
        <input class="input" id="fo-body" placeholder="Public body the request went to">
        <input class="input" id="fo-filed" type="date" style="flex:0 1 170px">
      </div>
      <div class="fo-row">
        <input class="input" id="fo-subject" placeholder="What you asked for">
      </div>
      <div class="fo-row">
        <input class="input" id="fo-notes" placeholder="Notes (optional)">
        <button class="btn btn-gold" id="fo-create">Log it</button>
      </div>
    </div>

    <div id="fo-list"><div class="fo-empty">Loading…</div></div>

    <div class="fo-law">
      Response windows, extension length, and the holiday calendar are set under
      Configuration &rarr; Records Request Tracker. Defaults follow Michigan FOIA
      (MCL 15.235): 5 business days, one 10-business-day extension, and a missed
      deadline treated as a denial. Check your own jurisdiction before relying on
      these numbers.
    </div>
  </div>`;

  document.getElementById('fo-toggle').addEventListener('click', () => {
    document.getElementById('fo-new').classList.toggle('open');
  });
  document.getElementById('fo-create').addEventListener('click', createFoia);

  await load();
}

async function load() {
  const el = document.getElementById('fo-list');
  try {
    const rows = await get('/foia');
    renderStats(rows);
    if (!rows.length) {
      el.innerHTML = `<div class="fo-empty">No requests tracked yet.</div>`;
      return;
    }
    el.innerHTML = rows.map(cardHTML).join('');
    wire(el);
  } catch (err) {
    el.innerHTML = `<div class="fo-empty">Could not load: ${esc(err.message)}</div>`;
  }
}

function renderStats(rows) {
  const open = rows.filter(r => r.days_left !== null);
  const overdue = open.filter(r => r.overdue).length;
  const soon = open.filter(r => !r.overdue && r.days_left <= 2).length;
  document.getElementById('fo-stats').innerHTML = `
    <div class="fo-stat"><b>${rows.length}</b><span>Tracked</span></div>
    <div class="fo-stat"><b>${open.length}</b><span>Open</span></div>
    <div class="fo-stat ${soon ? 'warn' : ''}"><b>${soon}</b><span>Due soon</span></div>
    <div class="fo-stat ${overdue ? 'bad' : ''}"><b>${overdue}</b><span>Overdue</span></div>`;
}

function cardHTML(r) {
  let cls = '', dueText = r.status_label;
  if (r.days_left === null) {
    cls = 'done';
  } else if (r.overdue) {
    cls = 'overdue';
    dueText = `OVERDUE by ${Math.abs(r.days_left)} business day(s)`;
  } else if (r.days_left === 0) {
    cls = 'soon'; dueText = 'DUE TODAY';
  } else if (r.days_left <= 2) {
    cls = 'soon'; dueText = `${r.days_left} business day(s) left`;
  } else {
    dueText = `${r.days_left} business day(s) left`;
  }

  const opts = STATUSES.map(([v, l]) =>
    `<option value="${v}" ${v === r.status ? 'selected' : ''}>${l}</option>`).join('');

  return `<div class="fo-card ${cls}" data-id="${r.id}">
    <div class="fo-top">
      <span class="fo-id">#${r.id}</span>
      <span class="fo-body-name">${esc(r.body)}</span>
      <span class="fo-due ${cls}">${esc(dueText)}</span>
    </div>
    <div class="fo-subject">${esc(r.subject)}</div>
    <div class="fo-meta">
      Filed ${esc(r.filed_date)} · due ${esc(r.effective_due)}
      ${r.extended_due ? ' (extended)' : ''}
      ${r.fee_quoted ? ` · fee $${Number(r.fee_quoted).toLocaleString()}` : ''}
      ${r.filed_by ? ` · by ${esc(r.filed_by)}` : ''}
    </div>
    <div class="fo-actions">
      <select class="cfg-input" data-act="status">${opts}</select>
      ${r.extended_due ? '' : `<button class="btn" data-act="extend">Log extension</button>`}
      <button class="btn" data-act="note">Add note</button>
      <button class="btn" data-act="delete" style="color:#E06C6C">Delete</button>
    </div>
    ${r.notes ? `<div class="fo-notes">${esc(r.notes)}</div>` : ''}
  </div>`;
}

function wire(el) {
  el.querySelectorAll('.fo-card').forEach(card => {
    const id = card.dataset.id;
    card.querySelector('[data-act="status"]').addEventListener('change', async e => {
      await patch(`/foia/${id}`, { status: e.target.value });
      await load();
    });
    card.querySelector('[data-act="extend"]')?.addEventListener('click', async () => {
      const r = await post(`/foia/${id}/extend`, {});
      alert(`Extended. New deadline ${r.extended_due}.\nA second extension is not permitted.`);
      await load();
    });
    card.querySelector('[data-act="note"]').addEventListener('click', async () => {
      const note = prompt('Add a note:');
      if (!note) return;
      await patch(`/foia/${id}`, { notes: note });
      await load();
    });
    card.querySelector('[data-act="delete"]').addEventListener('click', async () => {
      if (!confirm(`Delete FOIA #${id}?`)) return;
      await del(`/foia/${id}`);
      await load();
    });
  });
}

async function createFoia() {
  const body = document.getElementById('fo-body').value.trim();
  const subject = document.getElementById('fo-subject').value.trim();
  if (!body || !subject) return alert('Public body and subject are both required.');
  try {
    const r = await post('/foia', {
      body, subject,
      filed_date: document.getElementById('fo-filed').value || '',
      notes: document.getElementById('fo-notes').value.trim(),
    });
    ['fo-body', 'fo-subject', 'fo-notes'].forEach(i =>
      document.getElementById(i).value = '');
    document.getElementById('fo-new').classList.remove('open');
    alert(`Logged as #${r.id}. Response due ${r.response_due}.`);
    await load();
  } catch (err) {
    alert(`Could not file: ${err.message}`);
  }
}
