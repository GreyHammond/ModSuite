/* ============================================================
   ModSuite — GitHub Pages site
   Interactive: live activity console + command search
   ============================================================ */

// ============ LIVE CONSOLE (signature element) ============
const consoleFeed = [
  {
    type: "good",
    title: "Ticket opened",
    body: "New ModMail ticket from <strong>@sable</strong> — <strong>#ticket-sable</strong> created, staff notified.",
  },
  {
    type: "warn",
    title: "AutoMod — Message velocity",
    body: "<strong>@newcomer42</strong> sent 6 messages in 8s. Deleted + muted 10m.",
  },
  {
    type: "warn",
    title: "AutoMod — Link filter (whitelist)",
    body: "Blocked link to <strong>grabify.link</strong> in <strong>#lounge</strong>. Deleted + muted.",
  },
  {
    type: "danger",
    title: "RAID LOCKDOWN ACTIVATED",
    body: "12 joins in 8s exceeded threshold. Verification raised to highest. Auto-unlock in 5m.",
  },
  {
    type: "warn",
    title: "Raid — new joiner blocked",
    body: "<strong>skibidi_bot_9182</strong> kicked on join (lockdown active).",
  },
  {
    type: "good",
    title: "Thread deleted by owner",
    body: "<strong>@toasty_kris</strong> deleted their thread <strong>“Sunsets and sunrises”</strong>.",
  },
  {
    type: "warn",
    title: "AutoMod — Duplicate spam",
    body: "<strong>@spammer</strong> sent same message ×3. Deleted + muted 10m.",
  },
  {
    type: "good",
    title: "Lockdown lifted",
    body: "Cooldown reached (5 min). Channels restored. Verification level rolled back.",
  },
  {
    type: "warn",
    title: "Warn threshold reached",
    body: "<strong>@jaybone</strong> hit warn #3 → auto-mute 24h applied by policy.",
  },
  {
    type: "good",
    title: "Ticket closed",
    body: "<strong>#ticket-sable</strong> closed. Transcript zipped → <strong>#closed-tickets</strong>.",
  },
  {
    type: "warn",
    title: "AutoMod — Mention flood",
    body: "<strong>@pinger</strong> pinged 7 members in one message. Deleted + muted.",
  },
  {
    type: "warn",
    title: "Suspicious join — young account",
    body: "<strong>new_user_004</strong> account is 2d old (min: 7d). Flagged in log.",
  },
];

function fmtTime() {
  const d = new Date();
  return d.toTimeString().slice(0, 8);
}

function makeEntry({ type, title, body }) {
  const el = document.createElement("div");
  el.className = `log-entry ${type}`;
  el.innerHTML = `
    <div class="log-head">
      <span class="log-time">${fmtTime()}</span>
      <span class="log-title ${type}">${title}</span>
    </div>
    <div class="log-body">${body}</div>
  `;
  return el;
}

function initConsole() {
  const box = document.getElementById("console-log");
  if (!box) return;

  // Seed with a couple of entries so it's never empty
  const shuffled = [...consoleFeed].sort(() => Math.random() - 0.5);
  let idx = 0;

  const addOne = () => {
    const entry = makeEntry(shuffled[idx % shuffled.length]);
    box.appendChild(entry);
    idx++;

    // Keep console at a sensible size
    while (box.children.length > 4) {
      box.removeChild(box.firstChild);
    }
  };

  addOne();
  setTimeout(addOne, 800);
  setTimeout(addOne, 1800);

  // Respect reduced motion
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  setInterval(addOne, 3200);
}

// ============ COMMAND REFERENCE ============
const commands = [
  // Setup
  { name: "/setup",             cat: "setup",      desc: "Guided server setup wizard. Creates roles, categories, channels, and the react-role message. Administrator only." },
  { name: "/setmessage",        cat: "setup",      desc: "Set the text for a customisable bot message (welcome, ModMail greeting, etc.)." },
  { name: "/viewmessages",      cat: "setup",      desc: "List all current customised bot message templates." },
  { name: "/resetmessage",      cat: "setup",      desc: "Reset a message template to its default." },
  { name: "/presence",          cat: "setup",      desc: "Change the bot's Discord activity (Playing / Watching / Listening / Streaming) at runtime." },
  { name: "/say",               cat: "setup",      desc: "Post a message as the bot in a channel." },

  // ModMail
  { name: "/reply",             cat: "modmail",    desc: "Reply to a ModMail ticket. Anonymous mode sends as \"Staff\"." },
  { name: "/close",             cat: "modmail",    desc: "Close a ModMail ticket. Builds a transcript, zips it, archives to #closed-tickets, and deletes the ticket channel." },

  // Moderation
  { name: "/kick",              cat: "moderation", desc: "Kick a member from the server. Reason logged to #mod-log." },
  { name: "/ban",               cat: "moderation", desc: "Ban a member. Optional message-history purge in days." },
  { name: "/unban",             cat: "moderation", desc: "Unban a user by ID." },
  { name: "/softban",           cat: "moderation", desc: "Ban then unban to wipe recent messages. Roles restored on rejoin." },
  { name: "/mute",              cat: "moderation", desc: "Timeout a member. Flexible duration (10m, 2h30m, 1d12h). Default 30 days." },
  { name: "/unmute",            cat: "moderation", desc: "Remove a member's timeout." },
  { name: "/purge",             cat: "moderation", desc: "Bulk-delete N messages from the current channel." },

  // Warns
  { name: "/warn",              cat: "warns",      desc: "Warn a member. Thresholds can trigger automatic mute or ban." },
  { name: "/unwarn",            cat: "warns",      desc: "Remove a specific warning by ID." },
  { name: "/history",           cat: "warns",      desc: "View a member's full moderation history." },

  // Jail
  { name: "/jail",              cat: "jail",       desc: "Strip a member's roles and drop them in the jail channel." },
  { name: "/unjail",            cat: "jail",       desc: "Release a member from jail and restore their previous roles." },
  { name: "/tempjail",          cat: "jail",       desc: "Jail a member for a time-boxed duration." },
  { name: "/setautojail",       cat: "jail",       desc: "Configure automatic jail thresholds." },

  // Notes
  { name: "/note",              cat: "notes",      desc: "Add a private staff note. Never shown to the subject." },
  { name: "/notes",             cat: "notes",      desc: "List all active staff notes for a user." },
  { name: "/delnote",           cat: "notes",      desc: "Soft-delete a note by ID." },

  // AutoMod (v2.2)
  { name: "/automod status",           cat: "automod", desc: "Show all current AutoMod settings in one embed. Staff only." },
  { name: "/automod spam",             cat: "automod", desc: "Turn spam detection on or off." },
  { name: "/automod spam_threshold",   cat: "automod", desc: "Set spam velocity: N messages allowed in S seconds." },
  { name: "/automod spam_action",      cat: "automod", desc: "Delete / mute / kick / ban on spam trigger." },
  { name: "/automod links",            cat: "automod", desc: "Turn link filtering on or off." },
  { name: "/automod link_mode",        cat: "automod", desc: "Switch between whitelist (strict) and blacklist (permissive) mode." },
  { name: "/automod link_add",         cat: "automod", desc: "Add a domain to the whitelist or blacklist." },
  { name: "/automod link_remove",      cat: "automod", desc: "Remove a domain from the whitelist or blacklist." },
  { name: "/automod link_action",      cat: "automod", desc: "Delete / mute / kick / ban on disallowed link." },
  { name: "/automod link_bypass_channel", cat: "automod", desc: "Toggle a channel as bypassing the link filter." },
  { name: "/automod link_bypass_role", cat: "automod", desc: "Toggle a role as bypassing the link filter." },
  { name: "/automod invites",          cat: "automod", desc: "Turn Discord invite filtering on or off." },
  { name: "/automod invite_action",    cat: "automod", desc: "Delete / mute / kick / ban on Discord invite." },
  { name: "/automod immune",           cat: "automod", desc: "Toggle a role as immune to all AutoMod filters." },

  // Raid
  { name: "/lockdown",                 cat: "raid",    desc: "Manually lock all text channels. Blocks send permissions for @everyone." },
  { name: "/unlock",                   cat: "raid",    desc: "Lift lockdown and restore channel access." },
  { name: "/autorole",                 cat: "raid",    desc: "Set (or clear) a role to auto-assign to new members on join." },
  { name: "/raidcfg threshold",        cat: "raid",    desc: "Set raid detection: N joins in S seconds triggers auto-lockdown." },
  { name: "/raidcfg account_age",      cat: "raid",    desc: "Flag joins from accounts younger than N days. 0 disables." },
  { name: "/raidcfg action",           cat: "raid",    desc: "During active raid, kick or ban new joiners." },
  { name: "/raidcfg auto_verification",cat: "raid",    desc: "Auto-raise server verification level during lockdown." },
  { name: "/raidcfg cooldown",         cat: "raid",    desc: "Auto-unlock lockdown after N minutes. 0 = manual only." },

  // React Roles
  { name: "/createreactmessage",       cat: "reactrole", desc: "Start building a new react-role message." },
  { name: "/setreactmessage",          cat: "reactrole", desc: "Set the body of the in-progress react-role message." },
  { name: "/addrole",                  cat: "reactrole", desc: "Add a role option to the message being built." },
  { name: "/editrole",                 cat: "reactrole", desc: "Edit a role option on the message being built." },
  { name: "/deleterole",               cat: "reactrole", desc: "Remove a role option from the message being built." },
  { name: "/editreactmessage",         cat: "reactrole", desc: "Edit a published react-role message." },
  { name: "/publishreactmessage",      cat: "reactrole", desc: "Publish the react-role message to a channel." },
  { name: "/cancelreactmessage",       cat: "reactrole", desc: "Cancel an in-progress react-role message draft." },

  // Starboard
  { name: "/starboard create",         cat: "starboard", desc: "Create a new starboard in a channel." },
  { name: "/starboard delete",         cat: "starboard", desc: "Delete a starboard." },
  { name: "/starboard threshold",      cat: "starboard", desc: "Set the reaction threshold for a starboard." },
  { name: "/starboard addemoji",       cat: "starboard", desc: "Add a reaction emoji that counts for this starboard." },
  { name: "/starboard removeemoji",    cat: "starboard", desc: "Remove a reaction emoji from this starboard." },
  { name: "/starboard list",           cat: "starboard", desc: "List all starboards in the server." },

  // Streamer
  { name: "/streamer add",             cat: "streamer",  desc: "Track a new streamer for go-live alerts." },
  { name: "/streamer remove",          cat: "streamer",  desc: "Stop tracking a streamer." },
  { name: "/streamer edit",            cat: "streamer",  desc: "Edit a tracked streamer's settings." },
  { name: "/links add",                cat: "streamer",  desc: "Add a supplementary link to a streamer's alert message." },
  { name: "/links remove",             cat: "streamer",  desc: "Remove a supplementary link from a streamer." },
  { name: "/links list",               cat: "streamer",  desc: "List all supplementary links for a streamer." },

  // Reminders
  { name: "/timezone",                 cat: "reminders", desc: "Set your personal timezone. Used by /remindme." },
  { name: "/remindme",                 cat: "reminders", desc: "Schedule a reminder in human time (2h, tomorrow 9am, etc.)." },
  { name: "/reminders",                cat: "reminders", desc: "List your scheduled reminders." },

  // Panels
  { name: "/panel",                    cat: "panels",    desc: "Post the persistent Mod Panel in this channel." },
  { name: "/mod",                      cat: "panels",    desc: "Open the ephemeral Mod Panel on demand." },
  { name: "/userinfo",                 cat: "panels",    desc: "View information about a user." },
  { name: "/serverinfo",               cat: "panels",    desc: "View information about this server." },

  // Threads (v2.1)
  { name: "/delete",                   cat: "threads",   desc: "Forum thread owner deletes their own thread. Two-step confirmation, logged to #mod-log." },

  // Misc
  { name: "/verify",                   cat: "misc",      desc: "Verify a member (grant access to gated content)." },
  { name: "/unverify",                 cat: "misc",      desc: "Reverse a member's verification." },
  { name: "/move",                     cat: "misc",      desc: "Move a conversation to a different channel." },
];

const catLabels = {
  setup:      "Setup",
  modmail:    "ModMail",
  moderation: "Moderation",
  warns:      "Warns",
  jail:       "Jail",
  notes:      "Notes",
  automod:    "AutoMod",
  raid:       "Raid",
  reactrole:  "React Roles",
  starboard:  "Starboard",
  streamer:   "Streamer",
  reminders:  "Reminders",
  panels:     "Panels & Info",
  threads:    "Threads",
  misc:       "Misc",
};

let activeCat = "all";
let activeQuery = "";

function renderCommands() {
  const list = document.getElementById("commands-list");
  const empty = document.getElementById("commands-empty");
  if (!list) return;

  const q = activeQuery.trim().toLowerCase();
  const filtered = commands.filter(c => {
    const catOk = activeCat === "all" || c.cat === activeCat;
    if (!catOk) return false;
    if (!q) return true;
    return (
      c.name.toLowerCase().includes(q) ||
      c.desc.toLowerCase().includes(q) ||
      (catLabels[c.cat] || "").toLowerCase().includes(q)
    );
  });

  list.innerHTML = filtered.map(c => `
    <div class="cmd">
      <div>
        <span class="cmd-cat">${catLabels[c.cat] || c.cat}</span><br>
        <span class="cmd-name">${c.name}</span>
      </div>
      <div class="cmd-desc">${c.desc}</div>
    </div>
  `).join("");

  if (empty) empty.hidden = filtered.length !== 0;
}

function initCommands() {
  const search = document.getElementById("cmd-search");
  const chips = document.querySelectorAll("#cmd-filters .chip");

  if (search) {
    search.addEventListener("input", (e) => {
      activeQuery = e.target.value;
      renderCommands();
    });
  }

  chips.forEach(chip => {
    chip.addEventListener("click", () => {
      chips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      activeCat = chip.dataset.cat;
      renderCommands();
    });
  });

  renderCommands();
}

// ============ COPY CODE BLOCKS ============
function initCopyable() {
  document.querySelectorAll("pre.code[data-copy]").forEach(pre => {
    pre.style.cursor = "copy";
    pre.title = "Click to copy";
    pre.addEventListener("click", async () => {
      const text = pre.textContent.trim();
      try {
        await navigator.clipboard.writeText(text);
        const original = pre.style.borderColor;
        pre.style.borderColor = "var(--mint)";
        setTimeout(() => { pre.style.borderColor = original; }, 800);
      } catch (e) { /* clipboard blocked — silent fail */ }
    });
  });
}

// ============ INIT ============
document.addEventListener("DOMContentLoaded", () => {
  initConsole();
  initCommands();
  initCopyable();
});
