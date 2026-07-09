import { apiFetch, get, post } from '../api.js';

let _tickets = [], _status = 'open', _search = '';
let _openTicketId = null;   // currently expanded ticket
let _transcripts  = new Map();  // ticket_id -> transcript payload

const ONE_HOUR = 3_600_000;

function injectStyles() {
  if (document.getElementById('s-tickets')) return;
  const s = document.createElement('style');
  s.id = 's-tickets';
  s.textContent = `
    .tk-wrap { padding: 24px; }
    .tk-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
    .filter-tabs {
      display: flex; gap: 3px; background: var(--card);
      padding: 3px; border-radius: 8px; border: 1px solid var(--border);
    }
    .ftab {
      padding: 5px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;
      color: var(--muted); background: none; border: none; cursor: pointer;
      transition: all var(--transition); font-family: var(--font);
    }
    .ftab.active { background: var(--gold-faint); color: var(--gold); }
    .ftab:hover:not(.active) { color: var(--text); }
    .tk-search {
      background: var(--card-2); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); font: inherit; font-size: 13px;
      padding: 7px 11px; outline: none; max-width: 240px;
      transition: border-color var(--fast);
    }
    .tk-search:focus { border-color: var(--border-focus); }

    .ticket-card {
      background: var(--card); border: 1px solid var(--border); border-radius: 10px;
      margin-bottom: 10px; overflow: hidden;
      transition: box-shadow var(--transition), border-color var(--transition);
    }
    .ticket-card:hover { box-shadow: 0 2px 14px rgba(0,0,0,.3); }
    .ticket-card.urgent { border-color: rgba(239,68,68,.28); }
    .ticket-card.open-expanded { border-color: var(--border-focus); }

    .tk-head-row {
      display: flex; align-items: flex-start; gap: 12px;
      padding: 14px 16px; cursor: pointer; user-select: none;
      transition: background var(--transition);
    }
    .tk-head-row:hover { background: rgba(255,255,255,.02); }
    .tk-ico {
      width: 36px; height: 36px; border-radius: 8px;
      background: rgba(96,165,250,.12); display: flex; align-items: center;
      justify-content: center; flex-shrink: 0; color: #60A5FA;
      overflow: hidden;
    }
    .tk-ico img { width: 100%; height: 100%; object-fit: cover; }
    .tk-body { flex: 1; min-width: 0; }
    .tk-head {
      display: flex; align-items: center; gap: 8px; margin-bottom: 5px; flex-wrap: wrap;
    }
    .tk-opener { font-size: 14px; font-weight: 600; }
    .tk-subject { font-size: 13px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
    .tk-meta { display: flex; align-items: center; gap: 12px; font-size: 11px; color: var(--muted); flex-wrap: wrap; }
    .tk-meta-item { display: flex; align-items: center; gap: 4px; }
    .tk-urgent-warn { color: #EF4444; font-weight: 600; }
    .tk-chevron { margin-left: auto; color: var(--muted); transition: transform var(--transition); flex-shrink: 0; }
    .ticket-card.open-expanded .tk-chevron { transform: rotate(180deg); }

    /* ─── Expanded ticket panel ─── */
    .tk-panel {
      display: none;
      border-top: 1px solid var(--border);
      background: rgba(255,255,255,.01);
    }
    .ticket-card.open-expanded .tk-panel { display: block; }

    .tk-transcript {
      max-height: 480px; overflow-y: auto; padding: 14px 16px;
      display: flex; flex-direction: column; gap: 8px;
      border-bottom: 1px solid var(--border);
    }
    .tk-transcript::-webkit-scrollbar { width: 3px; }
    .tk-transcript::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

    .tk-msg {
      display: flex; gap: 10px; padding: 6px 0;
    }
    .tk-msg-avatar {
      width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      font-size: 12px; font-weight: 600;
    }
    .tk-msg-avatar.in  { background: rgba(96,165,250,.14); color: #60A5FA; }
    .tk-msg-avatar.out { background: var(--gold-faint);    color: var(--gold); }
    .tk-msg-body { flex: 1; min-width: 0; }
    .tk-msg-head { display: flex; align-items: baseline; gap: 8px; font-size: 12px; margin-bottom: 2px; }
    .tk-msg-author { font-weight: 600; color: var(--text); }
    .tk-msg-author.staff { color: var(--gold); }
    .tk-msg-time { font-size: 11px; color: var(--muted); font-family: var(--font-mono); }
    .tk-msg-content { font-size: 13px; color: var(--text); line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }
    .tk-anon-badge {
      font-family: var(--font-mono); font-size: 10px; color: var(--muted);
      background: rgba(255,255,255,.04); padding: 1px 6px; border-radius: 4px;
    }

    /* Reply composer */
    .tk-composer {
      padding: 14px 16px; display: flex; flex-direction: column; gap: 10px;
    }
    .tk-composer-header {
      display: flex; align-items: center; justify-content: space-between; gap: 8px;
    }
    .tk-composer-label {
      font-size: 11px; font-weight: 600; color: var(--muted);
      text-transform: uppercase; letter-spacing: .07em;
    }
    .tk-anon-toggle {
      display: flex; align-items: center; gap: 7px;
      font-size: 12px; color: var(--muted); cursor: pointer;
    }
    .tk-anon-toggle input { accent-color: var(--gold); }
    .tk-reply-ta {
      width: 100%; background: var(--card-2); border: 1px solid var(--border);
      border-radius: var(--radius); color: var(--text); font: inherit; font-size: 13px;
      padding: 10px 12px; box-sizing: border-box; outline: none;
      resize: vertical; min-height: 68px;
      transition: border-color var(--fast);
    }
    .tk-reply-ta:focus { border-color: var(--border-focus); }
    .tk-composer-actions { display: flex; align-items: center; gap: 10px; }
    .tk-status { font-size: 12px; flex: 1; }
    .tk-status.ok  { color: var(--green); }
    .tk-status.err { color: var(--red); }

    .tk-closed-banner {
      padding: 12px 16px; background: rgba(255,255,255,.02);
      color: var(--muted); font-size: 12.5px; text-align: center;
      font-style: italic;
    }

    /* Skeleton for transcript */
    .tk-transcript-loading {
      display: flex; flex-direction: column; gap: 12px; padding: 14px 16px;
    }
    .tk-transcript-loading .skeleton { height: 28px; border-radius: 6px; }
  `;
  document.head.appendChild(s);
}

export async function render(container) {
  injectStyles();
  container.innerHTML = `<div class="tk-wrap">${Array(3).fill(`<div class="skeleton" style="height:84px;border-radius:10px;margin-bottom:10px"></div>`).join('')}</div>`;
  try {
    const data = await apiFetch('/tickets?status=all');
    _tickets = Array.isArray(data) ? data : (data?.tickets ?? []);
    _status = 'open'; _search = ''; _openTicketId = null; _transcripts.clear();
    container.innerHTML = buildPage();
    attach(container);
    renderTickets(container);
  } catch {
    container.innerHTML = errState();
  }
}

function buildPage() {
  return `<div class="tk-wrap">
    <div class="tk-toolbar">
      <div class="filter-tabs">
        <button class="ftab active" data-s="open">Open</button>
        <button class="ftab" data-s="closed">Closed</button>
        <button class="ftab" data-s="all">All</button>
      </div>
      <input type="text" class="tk-search" id="tk-search" placeholder="Search by user…" autocomplete="off">
      <span style="font-size:12px;color:var(--muted);margin-left:auto" id="tk-count"></span>
    </div>
    <div id="tk-list"></div>
  </div>`;
}

function isUrgent(t) {
  if ((t.status || 'open').toLowerCase() !== 'open') return false;
  const msgs = t.message_count ?? t.messages ?? 1;
  if (msgs > 1) return false;
  return Date.now() - new Date(t.opened_at || t.created_at).getTime() > ONE_HOUR;
}

function renderTickets(container) {
  const list  = document.getElementById('tk-list');
  const count = document.getElementById('tk-count');
  if (!list) return;

  let filtered = _tickets;
  if (_status !== 'all') filtered = filtered.filter(t => (t.status || 'open').toLowerCase() === _status);
  if (_search) {
    const q = _search.toLowerCase();
    filtered = filtered.filter(t =>
      (t.opener_username || t.username || t.user_name || '').toLowerCase().includes(q)
    );
  }

  if (count) count.textContent = `${filtered.length} ticket${filtered.length === 1 ? '' : 's'}`;

  if (filtered.length === 0) {
    const label = _status === 'all' ? '' : _status + ' ';
    list.innerHTML = `<div class="empty-state"><div class="state-icon">💬</div><p>No ${label}tickets</p></div>`;
    return;
  }

  list.innerHTML = filtered.map(t => ticketCardHTML(t)).join('');

  // Wire up card headers
  list.querySelectorAll('.tk-head-row').forEach(row => {
    row.addEventListener('click', async () => {
      const card = row.closest('.ticket-card');
      const ticketId = Number(card.dataset.id);
      const wasOpen = card.classList.contains('open-expanded');

      // Close any other open cards
      list.querySelectorAll('.ticket-card.open-expanded').forEach(c => c.classList.remove('open-expanded'));

      if (!wasOpen) {
        card.classList.add('open-expanded');
        _openTicketId = ticketId;
        await loadTranscript(ticketId, card);
        wireComposer(card, ticketId);
      } else {
        _openTicketId = null;
      }
    });
  });
}

function ticketCardHTML(t) {
  const id = t.ticket_id ?? t.id;
  const urgent = isUrgent(t);
  const statusKey = urgent ? 'urgent' : (t.status || 'open').toLowerCase();
  const msgCount = t.message_count ?? t.messages;
  const isOpen = (t.status || 'open').toLowerCase() === 'open';
  const opener = t.opener_username || t.username || t.user_name || `User ${t.opener_id ?? t.user_id}`;
  const avatar = t.opener_avatar;

  return `<div class="ticket-card${urgent ? ' urgent' : ''}" data-id="${id}">
    <div class="tk-head-row">
      <div class="tk-ico">
        ${avatar ? `<img src="${esc(avatar)}" alt="">` : `
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
          </svg>`}
      </div>
      <div class="tk-body">
        <div class="tk-head">
          <span class="tk-opener">${esc(opener)}</span>
          <span class="tk-subject">-- Ticket #${id}</span>
          <span class="badge badge-${statusKey}" style="flex-shrink:0">${urgent ? 'Urgent' : cap(t.status || 'open')}</span>
        </div>
        <div class="tk-meta">
          <span class="tk-meta-item">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
            Opened ${ago(t.opened_at || t.created_at)}
          </span>
          ${msgCount != null ? `<span class="tk-meta-item">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
            ${msgCount} messages
          </span>` : ''}
          ${urgent ? `<span class="tk-urgent-warn tk-meta-item">⚠ No response for 1h+</span>` : ''}
        </div>
      </div>
      <svg class="tk-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>
    </div>
    <div class="tk-panel" id="tk-panel-${id}">
      <div class="tk-transcript" id="tk-transcript-${id}">
        <div class="tk-transcript-loading">
          <div class="skeleton" style="height:40px"></div>
          <div class="skeleton" style="height:40px"></div>
        </div>
      </div>
      ${isOpen ? composerHTML(id) : `<div class="tk-closed-banner">This ticket is closed. Reopening from the web isn't supported yet.</div>`}
    </div>
  </div>`;
}

function composerHTML(id) {
  return `<div class="tk-composer">
    <div class="tk-composer-header">
      <span class="tk-composer-label">Reply as staff</span>
      <label class="tk-anon-toggle">
        <input type="checkbox" id="tk-anon-${id}"> Anonymous ("Staff")
      </label>
    </div>
    <textarea class="tk-reply-ta" id="tk-reply-${id}" placeholder="Type a reply -- the user will receive it as a DM…"></textarea>
    <div class="tk-composer-actions">
      <button class="btn btn-primary" id="tk-send-${id}" disabled>Send reply</button>
      <button class="btn btn-danger"  id="tk-close-${id}">Close ticket</button>
      <span class="tk-status" id="tk-status-${id}"></span>
    </div>
  </div>`;
}

async function loadTranscript(ticketId, card) {
  const box = document.getElementById(`tk-transcript-${ticketId}`);
  if (!box) return;

  try {
    let data = _transcripts.get(ticketId);
    if (!data) {
      data = await get(`/tickets/${ticketId}/transcript`);
      _transcripts.set(ticketId, data);
    }
    const msgs = data.messages || [];
    if (msgs.length === 0) {
      box.innerHTML = `<div class="empty-state" style="padding: 30px"><p style="color: var(--muted)">No messages yet.</p></div>`;
    } else {
      box.innerHTML = msgs.map(msgHTML).join('');
      // Scroll to bottom
      box.scrollTop = box.scrollHeight;
    }
  } catch (e) {
    box.innerHTML = `<div class="empty-state" style="padding: 30px"><p style="color: var(--red)">Failed to load transcript.</p></div>`;
  }
}

function msgHTML(m) {
  const cls = m.is_staff ? 'out' : 'in';
  const initial = (m.author || '?').charAt(0).toUpperCase();
  return `<div class="tk-msg">
    <div class="tk-msg-avatar ${cls}">${initial}</div>
    <div class="tk-msg-body">
      <div class="tk-msg-head">
        <span class="tk-msg-author${m.is_staff ? ' staff' : ''}">${esc(m.author)}</span>
        ${m.anonymous ? `<span class="tk-anon-badge">anon</span>` : ''}
        <span class="tk-msg-time">${fmtTime(m.timestamp)}</span>
      </div>
      <div class="tk-msg-content">${esc(m.content)}</div>
    </div>
  </div>`;
}

function wireComposer(card, ticketId) {
  const ta       = document.getElementById(`tk-reply-${ticketId}`);
  const sendBtn  = document.getElementById(`tk-send-${ticketId}`);
  const closeBtn = document.getElementById(`tk-close-${ticketId}`);
  const anonCbx  = document.getElementById(`tk-anon-${ticketId}`);
  const status   = document.getElementById(`tk-status-${ticketId}`);

  if (!ta || !sendBtn) return;  // ticket is closed, no composer

  ta.addEventListener('input', () => {
    sendBtn.disabled = !ta.value.trim();
  });

  sendBtn.addEventListener('click', async () => {
    const message = ta.value.trim();
    if (!message) return;
    sendBtn.disabled = true;
    status.className = 'tk-status';
    status.textContent = 'Sending…';
    try {
      const res = await post(`/tickets/${ticketId}/reply`, {
        message,
        anonymous: anonCbx?.checked || false,
      });
      status.className = 'tk-status ok';
      status.textContent = `Queued (action #${res.action_id}). DM will send within a few seconds.`;
      ta.value = '';
      // Invalidate transcript cache -- reload after a delay
      setTimeout(async () => {
        _transcripts.delete(ticketId);
        await loadTranscript(ticketId, card);
        status.textContent = '';
      }, 6000);
    } catch (e) {
      status.className = 'tk-status err';
      status.textContent = 'Failed: ' + (e.message || e);
      sendBtn.disabled = false;
    }
  });

  closeBtn?.addEventListener('click', async () => {
    if (!confirm(`Close ticket #${ticketId}? This will archive the transcript and delete the channel.`)) return;
    closeBtn.disabled = true;
    status.className = 'tk-status';
    status.textContent = 'Closing…';
    try {
      const res = await post(`/tickets/${ticketId}/close`, {});
      status.className = 'tk-status ok';
      status.textContent = `Queued (action #${res.action_id}). Closing…`;
      setTimeout(async () => {
        // Refresh the whole ticket list
        try {
          const data = await apiFetch('/tickets?status=all');
          _tickets = Array.isArray(data) ? data : (data?.tickets ?? []);
          _openTicketId = null;
          renderTickets(document);
        } catch {}
      }, 5000);
    } catch (e) {
      status.className = 'tk-status err';
      status.textContent = 'Failed: ' + (e.message || e);
      closeBtn.disabled = false;
    }
  });
}

function attach(container) {
  container.querySelectorAll('.ftab').forEach(tab => {
    tab.addEventListener('click', () => {
      container.querySelectorAll('.ftab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      _status = tab.dataset.s;
      _openTicketId = null;
      renderTickets(container);
    });
  });
  let searchTimer;
  container.querySelector('#tk-search')?.addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      _search = e.target.value.trim();
      renderTickets(container);
    }, 200);
  });
}

function errState() {
  return `<div class="tk-wrap"><div class="error-state">
    <div class="state-icon">⚠️</div>
    <p>Could not load tickets. Is the bot running?</p>
    <button class="btn btn-ghost" onclick="location.reload()">Retry</button>
  </div></div>`;
}

const cap = s => String(s).charAt(0).toUpperCase() + String(s).slice(1);
const esc = s => String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
function ago(d) {
  if (!d) return '--';
  const m = Math.floor((Date.now() - new Date(d).getTime()) / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
function fmtTime(d) {
  if (!d) return '';
  const dt = new Date(d);
  return dt.toLocaleDateString('en-US',{month:'short',day:'numeric'}) + ' · ' +
         dt.toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',hour12:false});
}
