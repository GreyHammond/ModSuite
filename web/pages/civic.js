/**
 * civic.js -- Feeds, meeting reminders, and the Round Table roster.
 *
 * Grouped into one page with tabs rather than three sidebar entries, since
 * they are all "things the server publishes on a schedule" and each is small.
 */

import { get, post, put, patch, del } from '../api.js';

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
let _tab = 'feeds';

function injectStyles() {
  if (document.getElementById('civ-styles')) return;
  const s = document.createElement('style');
  s.id = 'civ-styles';
  s.textContent = `
    .civ-wrap { max-width:1000px; padding:24px; }
    .civ-head h2 { font-size:20px; font-weight:600; letter-spacing:-0.02em; }
    .civ-head p { font-size:13px; color:var(--muted); margin-top:3px; max-width:620px; }
    .civ-tabs { display:flex; gap:4px; margin:18px 0 16px;
      border-bottom:1px solid var(--border); }
    .civ-tab { padding:8px 15px; font-size:13px; cursor:pointer; color:var(--muted);
      border-bottom:2px solid transparent; margin-bottom:-1px; }
    .civ-tab:hover { color:var(--text); }
    .civ-tab.active { color:var(--gold); border-bottom-color:var(--gold); font-weight:600; }

    .civ-card { background:var(--card); border:1px solid var(--border);
      border-left:3px solid var(--gold); border-radius:10px;
      padding:13px 16px; margin-bottom:9px; }
    .civ-card.off { border-left-color:var(--border); opacity:0.65; }
    .civ-card.warn { border-left-color:#D4A843; }
    .civ-top { display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }
    .civ-name { font-weight:600; font-size:14px; }
    .civ-id { font-family:var(--font-mono); font-size:11.5px; color:var(--gold);
      background:var(--gold-faint); border-radius:5px; padding:2px 7px; }
    .civ-meta { font-size:11.5px; color:var(--muted); margin-top:5px; line-height:1.6; }
    .civ-err { color:#E06C6C; font-size:11.5px; margin-top:5px; }
    .civ-actions { display:flex; gap:6px; margin-top:10px; flex-wrap:wrap; }
    .civ-new { background:var(--card); border:1px solid var(--border);
      border-radius:10px; padding:16px; margin-bottom:18px; }
    .civ-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:9px; }
    .civ-row .input, .civ-row .cfg-input { flex:1 1 180px; }
    .civ-empty { padding:40px; text-align:center; color:var(--muted); font-size:13px; }
    .civ-note { font-size:11.5px; color:var(--muted); margin-top:14px;
      border-top:1px solid var(--border); padding-top:12px; line-height:1.6; }
    .civ-pill { font-size:10px; text-transform:uppercase; letter-spacing:0.05em;
      border-radius:4px; padding:1px 6px; border:1px solid var(--border); color:var(--muted); }
    .civ-pill.bad { color:#E06C6C; border-color:rgba(224,108,108,0.35); }
  `;
  document.head.appendChild(s);
}

const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export async function render(root) {
  injectStyles();
  root.innerHTML = `<div class="civ-wrap">
    <div class="civ-head">
      <h2>Feeds &amp; Events</h2>
      <p>RSS feeds, recurring event reminders, and the published membership roster.</p>
    </div>
    <div class="civ-tabs">
      <div class="civ-tab" data-tab="feeds">Feeds</div>
      <div class="civ-tab" data-tab="meetings">Meetings</div>
      <div class="civ-tab" data-tab="roster">Roster</div>
    </div>
    <div id="civ-body"></div>
  </div>`;
  root.querySelectorAll('.civ-tab').forEach(t =>
    t.addEventListener('click', () => { _tab = t.dataset.tab; paint(root); }));
  paint(root);
}

function paint(root) {
  root.querySelectorAll('.civ-tab').forEach(t =>
    t.classList.toggle('active', t.dataset.tab === _tab));
  if (_tab === 'feeds') return renderFeeds();
  if (_tab === 'meetings') return renderMeetings();
  return renderRoster();
}

// ── Feeds ───────────────────────────────────────────────────────────────────

async function renderFeeds() {
  const el = document.getElementById('civ-body');
  el.innerHTML = `
    <div class="civ-new">
      <div class="civ-row">
        <input class="input" id="f-name" placeholder="Label, e.g. Company Blog">
        <input class="input" id="f-url" placeholder="https://example.com/feed">
      </div>
      <div class="civ-row">
        <input class="input" id="f-ch" placeholder="Channel ID">
        <label class="toggle-wrap"><input type="checkbox" id="f-th" checked>
          <span class="toggle-pill"></span> Open a thread per item</label>
        <button class="btn btn-gold" id="f-add">Watch feed</button>
      </div>
    </div>
    <div id="f-list"><div class="civ-empty">Loading…</div></div>
    <div class="civ-note">
      Polled every 15 minutes. On first add, existing items are marked as seen
      rather than posted, so adding a feed never dumps the back catalogue into
      a channel. Any RSS or Atom feed works, including YouTube channel feeds.
    </div>`;
  document.getElementById('f-add').addEventListener('click', addFeed);
  await loadFeeds();
}

async function loadFeeds() {
  const el = document.getElementById('f-list');
  try {
    const rows = await get('/feeds');
    if (!rows.length) { el.innerHTML = `<div class="civ-empty">No feeds yet.</div>`; return; }
    el.innerHTML = rows.map(f => `
      <div class="civ-card ${f.enabled ? (f.last_error ? 'warn' : '') : 'off'}">
        <div class="civ-top">
          <span class="civ-id">#${f.id}</span>
          <span class="civ-name">${esc(f.name)}</span>
          ${f.make_threads ? '<span class="civ-pill">threads</span>' : ''}
          ${f.enabled ? '' : '<span class="civ-pill">off</span>'}
        </div>
        <div class="civ-meta">${esc(f.url)}<br>→ channel ${esc(f.channel_id)}
          ${f.last_checked ? ` · checked ${esc(f.last_checked)}` : ''}</div>
        ${f.last_error ? `<div class="civ-err">⚠ ${esc(f.last_error)}</div>` : ''}
        <div class="civ-actions">
          <button class="btn" data-check="${f.id}">Check now</button>
          <button class="btn" data-toggle="${f.id}" data-en="${f.enabled ? 0 : 1}">
            ${f.enabled ? 'Disable' : 'Enable'}</button>
          <button class="btn" data-del="${f.id}" style="color:#E06C6C">Delete</button>
        </div>
      </div>`).join('');
    el.querySelectorAll('[data-check]').forEach(b => b.addEventListener('click', async () => {
      b.disabled = true; b.textContent = 'Checking…';
      try { const r = await post(`/feeds/${b.dataset.check}/check`, {});
        alert(r.posted ? `Posted ${r.posted} new item(s).` : 'Nothing new.'); }
      catch (e) { alert(`Failed: ${e.message}`); }
      loadFeeds();
    }));
    el.querySelectorAll('[data-toggle]').forEach(b => b.addEventListener('click', async () => {
      await patch(`/feeds/${b.dataset.toggle}`, { enabled: Number(b.dataset.en) });
      loadFeeds();
    }));
    el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
      if (!confirm('Delete this feed?')) return;
      await del(`/feeds/${b.dataset.del}`); loadFeeds();
    }));
  } catch (e) {
    el.innerHTML = `<div class="civ-empty">Could not load: ${esc(e.message)}</div>`;
  }
}

async function addFeed() {
  const name = document.getElementById('f-name').value.trim();
  const url = document.getElementById('f-url').value.trim();
  const ch = document.getElementById('f-ch').value.trim();
  if (!name || !url || !ch) return alert('Name, URL, and channel ID are all required.');
  try {
    await post('/feeds', { name, url, channel_id: ch,
      make_threads: document.getElementById('f-th').checked });
    ['f-name', 'f-url', 'f-ch'].forEach(i => document.getElementById(i).value = '');
    await loadFeeds();
  } catch (e) { alert(`Could not add: ${e.message}`); }
}

// ── Meetings ────────────────────────────────────────────────────────────────

async function renderMeetings() {
  const el = document.getElementById('civ-body');
  el.innerHTML = `
    <div class="civ-new">
      <div class="civ-row">
        <input class="input" id="m-name" placeholder="e.g. Monthly Board Meeting">
        <input class="input" id="m-ch" placeholder="Channel ID">
      </div>
      <div class="civ-row">
        <select class="cfg-input" id="m-wd">
          ${WEEKDAYS.map((d, i) => `<option value="${i}">${d}</option>`).join('')}
        </select>
        <input class="input" id="m-pos" placeholder="Weeks: 2,4 (blank = weekly, -1 = last)">
        <input class="input" id="m-time" value="19:00" style="flex:0 1 100px">
      </div>
      <div class="civ-row">
        <input class="input" id="m-loc" placeholder="Location (optional)">
        <input class="input" id="m-url" placeholder="Agenda URL (optional)">
        <button class="btn btn-gold" id="m-add">Add meeting</button>
      </div>
    </div>
    <div id="m-list"><div class="civ-empty">Loading…</div></div>
    <div class="civ-note">
      Two reminders per meeting: the morning of, and one hour before. Both ping
      the configured role rather than everyone.
    </div>`;
  document.getElementById('m-add').addEventListener('click', addMeeting);
  await loadMeetings();
}

async function loadMeetings() {
  const el = document.getElementById('m-list');
  try {
    const rows = await get('/meetings');
    if (!rows.length) { el.innerHTML = `<div class="civ-empty">No meetings scheduled.</div>`; return; }
    el.innerHTML = rows.map(m => `
      <div class="civ-card ${m.enabled ? '' : 'off'}">
        <div class="civ-top">
          <span class="civ-id">#${m.id}</span>
          <span class="civ-name">${esc(m.name)}</span>
        </div>
        <div class="civ-meta">${esc(m.description)}
          ${m.next ? `<br>Next: ${esc(String(m.next).replace('T', ' ').slice(0, 16))}` : '<br>No upcoming date'}
          ${m.location ? `<br>${esc(m.location)}` : ''}
          ${m.agenda_url ? `<br><a href="${esc(m.agenda_url)}" target="_blank" rel="noopener">Agenda</a>` : ''}
        </div>
        <div class="civ-actions">
          <button class="btn" data-agenda="${m.id}">Set agenda link</button>
          <button class="btn" data-del="${m.id}" style="color:#E06C6C">Delete</button>
        </div>
      </div>`).join('');
    el.querySelectorAll('[data-agenda]').forEach(b => b.addEventListener('click', async () => {
      const url = prompt('Agenda or packet URL:');
      if (!url) return;
      await patch(`/meetings/${b.dataset.agenda}`, { agenda_url: url });
      loadMeetings();
    }));
    el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
      if (!confirm('Delete this meeting?')) return;
      await del(`/meetings/${b.dataset.del}`); loadMeetings();
    }));
  } catch (e) {
    el.innerHTML = `<div class="civ-empty">Could not load: ${esc(e.message)}</div>`;
  }
}

async function addMeeting() {
  const name = document.getElementById('m-name').value.trim();
  const ch = document.getElementById('m-ch').value.trim();
  if (!name || !ch) return alert('Name and channel ID are required.');
  const wd = Number(document.getElementById('m-wd').value);
  const posRaw = document.getElementById('m-pos').value.trim();
  let schedule;
  if (posRaw) {
    const pos = posRaw.split(',').map(p => parseInt(p.trim(), 10)).filter(n => !isNaN(n));
    if (!pos.length) return alert('Weeks must be numbers, e.g. 2,4 or -1.');
    schedule = { type: 'monthly_nth', weekday: wd, positions: pos };
  } else {
    schedule = { type: 'weekly', weekday: wd };
  }
  try {
    await post('/meetings', {
      name, channel_id: ch, schedule,
      meeting_time: document.getElementById('m-time').value.trim() || '19:00',
      location: document.getElementById('m-loc').value.trim(),
      agenda_url: document.getElementById('m-url').value.trim(),
    });
    ['m-name', 'm-ch', 'm-pos', 'm-loc', 'm-url'].forEach(i =>
      document.getElementById(i).value = '');
    await loadMeetings();
  } catch (e) { alert(`Could not add: ${e.message}`); }
}

// ── Roster ──────────────────────────────────────────────────────────────────

async function renderRoster() {
  const el = document.getElementById('civ-body');
  el.innerHTML = `
    <div class="civ-row" style="margin-bottom:16px">
      <button class="btn btn-gold" id="r-pub">Publish roster</button>
    </div>
    <div id="r-list"><div class="civ-empty">Loading…</div></div>
    <div class="civ-note">
      Generated from who holds the configured roster role and republished
      automatically when the role is granted or removed. Members with no
      organization recorded appear as unlisted, so gaps are visible rather than
      silent. Change the role and channel under Configuration &rarr; Roster.
    </div>`;
  document.getElementById('r-pub').addEventListener('click', async () => {
    try {
      const r = await post('/roster/publish', {});
      let msg = `Published: ${r.members} member(s).`;
      if (r.missing_org?.length) msg += `\n\nNo organization recorded for: ${r.missing_org.join(', ')}`;
      alert(msg);
    } catch (e) { alert(`Publish failed: ${e.message}`); }
  });
  await loadRoster();
}

async function loadRoster() {
  const el = document.getElementById('r-list');
  try {
    const rows = await get('/roster');
    if (!rows.length) { el.innerHTML = `<div class="civ-empty">Nobody holds the roster role yet.</div>`; return; }
    el.innerHTML = rows.map(r => `
      <div class="civ-card ${r.holds_role ? (r.needs_org ? 'warn' : '') : 'off'}">
        <div class="civ-top">
          <span class="civ-name">${esc(r.display_name || r.user_id)}</span>
          ${r.holds_role ? '' : '<span class="civ-pill bad">no longer holds role</span>'}
          ${r.needs_org ? '<span class="civ-pill bad">no organization</span>' : ''}
        </div>
        <div class="civ-meta">
          ${esc(r.organization || 'Organization not listed')}
          ${r.role_title ? ` · ${esc(r.role_title)}` : ''}<br>${esc(r.user_id)}
        </div>
        <div class="civ-actions">
          <button class="btn" data-edit="${esc(r.user_id)}"
            data-name="${esc(r.display_name || '')}">Set organization</button>
          <button class="btn" data-del="${esc(r.user_id)}" style="color:#E06C6C">Clear record</button>
        </div>
      </div>`).join('');
    el.querySelectorAll('[data-edit]').forEach(b => b.addEventListener('click', async () => {
      const org = prompt('Organization:');
      if (org === null) return;
      const title = prompt('Their role there (optional):') || '';
      await put('/roster', { user_id: b.dataset.edit, display_name: b.dataset.name,
        organization: org, role_title: title });
      loadRoster();
    }));
    el.querySelectorAll('[data-del]').forEach(b => b.addEventListener('click', async () => {
      if (!confirm('Clear this roster record?')) return;
      await del(`/roster/${b.dataset.del}`); loadRoster();
    }));
  } catch (e) {
    el.innerHTML = `<div class="civ-empty">Could not load: ${esc(e.message)}</div>`;
  }
}
