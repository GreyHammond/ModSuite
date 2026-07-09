/* ============================================================
   ModSuite v3.0 -- GitHub Pages site
   Interactive: live activity console + command search
   ============================================================ */

// ============ LIVE CONSOLE (signature element) ============
const consoleFeed = [
  {
    type: "good",
    title: "Ticket opened",
    body: "New ModMail ticket from <strong>@sable</strong> -- <strong>#ticket-sable</strong> created, staff notified.",
  },
  {
    type: "warn",
    title: "Violation -- spam",
    body: "<strong>@newcomer42</strong> sent 6 messages in 8s. Deleted. Violation #3/5 in 60m.",
  },
  {
    type: "warn",
    title: "Violation -- link",
    body: "Blocked link to <strong>grabify.link</strong> in <strong>#lounge</strong>. Violation recorded.",
  },
  {
    type: "danger",
    title: "RAID LOCKDOWN ACTIVATED",
    body: "12 joins in 8s. All channels locked. Profile switched from <strong>normal</strong> to <strong>raid</strong>. Auto-unlock in 5m.",
  },
  {
    type: "danger",
    title: "Raid -- new joiner banned",
    body: "<strong>skibidi_bot_9182</strong> banned on join (lockdown active). Logged to mod_logs.",
  },
  {
    type: "warn",
    title: "Violation -- phishing",
    body: "Phishing domain detected: <strong>disc0rd-nitro.gift</strong>. Message deleted. Violation recorded.",
  },
  {
    type: "good",
    title: "Lockdown lifted",
    body: "Cooldown reached (5 min). Channels restored. Profile restored to <strong>normal</strong>.",
  },
  {
    type: "warn",
    title: "Auto-Jail -- threshold reached",
    body: "<strong>@jaybone</strong> hit 5 violations in 60m. Auto-jailed for 1d.",
  },
  {
    type: "good",
    title: "Ticket closed",
    body: "<strong>#ticket-sable</strong> closed. Transcript zipped to <strong>#closed-tickets</strong>.",
  },
  {
    type: "warn",
    title: "Violation -- allcaps",
    body: "<strong>@CAPSLOCKER</strong> 92% uppercase (threshold 70%). Message deleted.",
  },
  {
    type: "danger",
    title: "Name filter triggered",
    body: "<strong>n1tr0_fr33_g1ft</strong> matched blocked pattern 'nitro'. Kicked on join.",
  },
  {
    type: "good",
    title: "Member verified",
    body: "<strong>@newmember</strong> reacted to verification message. Gate role granted.",
  },
  {
    type: "warn",
    title: "Violation -- word_filter",
    body: "Matched '<strong>slur</strong>' in list '<strong>hate_speech</strong>'. Message deleted.",
  },
  {
    type: "good",
    title: "Roles restored on rejoin",
    body: "<strong>@returning_user</strong> rejoined. 4 roles restored from role persistence.",
  },
  {
    type: "warn",
    title: "Violation -- slowmode",
    body: "<strong>@fasttyper</strong> posting too fast in <strong>#general</strong> (5s cooldown). Deleted.",
  },
  {
    type: "good",
    title: "Profile switched",
    body: "AutoMod profile switched from <strong>normal</strong> to <strong>strict</strong> by <strong>@admin</strong>.",
  },
  {
    type: "warn",
    title: "Tempban expired",
    body: "<strong>@troublemaker</strong> auto-unbanned after 7d tempban. Fresh start (no roles).",
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

  const shuffled = [...consoleFeed].sort(() => Math.random() - 0.5);
  let idx = 0;

  const addOne = () => {
    const entry = makeEntry(shuffled[idx % shuffled.length]);
    box.appendChild(entry);
    idx++;
    while (box.children.length > 4) {
      box.removeChild(box.firstChild);
    }
  };

  addOne();
  setTimeout(addOne, 800);
  setTimeout(addOne, 1800);

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
  { name: "/close",             cat: "modmail",    desc: "Close a ModMail ticket. Builds transcript, zips, archives to #closed-tickets." },

  // Moderation
  { name: "/kick",              cat: "moderation", desc: "Kick a member from the server. Reason logged to #mod-log." },
  { name: "/ban",               cat: "moderation", desc: "Ban a member. Optional message-history purge in days." },
  { name: "/unban",             cat: "moderation", desc: "Unban a user by ID." },
  { name: "/tempban",           cat: "moderation", desc: "Temporarily ban a member with automatic unban. Duration: 1h, 1d, 7d, 30d." },
  { name: "/softban",           cat: "moderation", desc: "Ban then unban to wipe recent messages. Roles restored on rejoin." },
  { name: "/mute",              cat: "moderation", desc: "Timeout a member. Flexible duration (10m, 2h30m, 1d12h). Default 30 days." },
  { name: "/unmute",            cat: "moderation", desc: "Remove a member's timeout." },
  { name: "/purge",             cat: "moderation", desc: "Bulk-delete messages with filters: user, contains, bots_only, max_age. Up to 200 messages." },

  // Warns
  { name: "/warn",              cat: "warns",      desc: "Warn a member. Thresholds can trigger automatic jail or ban." },
  { name: "/unwarn",            cat: "warns",      desc: "Remove a specific warning by ID." },
  { name: "/history",           cat: "warns",      desc: "View a member's full moderation history (16 action types with icons)." },

  // Jail
  { name: "/jail",              cat: "jail",       desc: "Strip a member's roles and drop them in a private jail channel." },
  { name: "/unjail",            cat: "jail",       desc: "Release a member from jail and restore their previous roles." },
  { name: "/tempjail",          cat: "jail",       desc: "Jail a member for a time-boxed duration." },
  { name: "/setautojail",       cat: "jail",       desc: "Configure automatic jail thresholds." },

  // Notes
  { name: "/note",              cat: "notes",      desc: "Add a private staff note. Never shown to the subject." },
  { name: "/notes",             cat: "notes",      desc: "List all active staff notes for a user." },
  { name: "/delnote",           cat: "notes",      desc: "Soft-delete a note by ID." },

  // Violations (v2.6)
  { name: "/violations check",       cat: "violations", desc: "Check a user's active violation count and recent history." },
  { name: "/violations clear",       cat: "violations", desc: "Clear all violations for a user." },
  { name: "/violations threshold",   cat: "violations", desc: "Set violation-to-jail threshold (count and window)." },
  { name: "/violations duration",    cat: "violations", desc: "Set auto-jail duration from violations." },

  // AutoMod
  { name: "/automod status",           cat: "automod", desc: "Show all current AutoMod settings in one embed." },
  { name: "/automod spam",             cat: "automod", desc: "Turn spam detection on or off." },
  { name: "/automod spam_threshold",   cat: "automod", desc: "Set spam velocity: N messages allowed in S seconds." },
  { name: "/automod spam_action",      cat: "automod", desc: "Delete / mute / kick / ban on spam trigger." },
  { name: "/automod links",            cat: "automod", desc: "Turn link filtering on or off." },
  { name: "/automod link_mode",        cat: "automod", desc: "Switch between whitelist (strict) and blacklist (permissive) mode." },
  { name: "/automod link_add",         cat: "automod", desc: "Add a domain to the whitelist or blacklist." },
  { name: "/automod link_remove",      cat: "automod", desc: "Remove a domain from the whitelist or blacklist." },
  { name: "/automod link_list",        cat: "automod", desc: "Show every domain on the whitelist and blacklist." },
  { name: "/automod link_action",      cat: "automod", desc: "Delete / mute / kick / ban on disallowed link." },
  { name: "/automod link_bypass_channel", cat: "automod", desc: "Toggle a channel as bypassing the link filter." },
  { name: "/automod link_bypass_role", cat: "automod", desc: "Toggle a role as bypassing the link filter." },
  { name: "/automod invites",          cat: "automod", desc: "Turn Discord invite filtering on or off." },
  { name: "/automod invite_action",    cat: "automod", desc: "Delete / mute / kick / ban on Discord invite." },
  { name: "/automod antiphish",        cat: "automod", desc: "Turn anti-phishing link scanning on or off." },
  { name: "/automod max_length",       cat: "automod", desc: "Set max message length (0 to disable)." },
  { name: "/automod min_length",       cat: "automod", desc: "Set min message length (0 to disable)." },
  { name: "/automod allcaps",          cat: "automod", desc: "Turn all-caps message filtering on or off." },
  { name: "/automod allcaps_threshold",cat: "automod", desc: "Set the % of uppercase characters and min length that triggers the filter." },
  { name: "/automod slowmode",         cat: "automod", desc: "Turn bot-enforced per-channel slowmode on or off." },
  { name: "/automod slowmode_interval",cat: "automod", desc: "Set slowmode interval in seconds per user per channel." },
  { name: "/automod slowmode_channel", cat: "automod", desc: "Toggle a channel for bot-enforced slowmode." },
  { name: "/immune",                   cat: "automod", desc: "Toggle a role as immune to all AutoMod filters." },

  // Word Lists
  { name: "/wordlist toggle",          cat: "wordlist",  desc: "Turn word list filtering on or off." },
  { name: "/wordlist add",             cat: "wordlist",  desc: "Add words to a word list (creates the list if new)." },
  { name: "/wordlist remove",          cat: "wordlist",  desc: "Remove words from a word list." },
  { name: "/wordlist view",            cat: "wordlist",  desc: "View all word lists and their contents." },
  { name: "/wordlist delete",          cat: "wordlist",  desc: "Delete an entire word list." },

  // Profiles (v2.9)
  { name: "/profile switch",           cat: "profiles",  desc: "Activate a severity profile (normal, strict, raid, or custom)." },
  { name: "/profile list",             cat: "profiles",  desc: "View all available profiles with override previews." },
  { name: "/profile view",             cat: "profiles",  desc: "See full override details for a specific profile." },
  { name: "/profile create",           cat: "profiles",  desc: "Snapshot current settings into a new custom profile." },
  { name: "/profile delete",           cat: "profiles",  desc: "Delete a custom profile (built-ins cannot be deleted)." },

  // Name Filter (v3.0)
  { name: "/namefilter toggle",        cat: "namefilter", desc: "Turn username/nickname filtering on or off." },
  { name: "/namefilter action",        cat: "namefilter", desc: "Set what happens when a blocked name is detected (log, kick, ban)." },
  { name: "/namefilter confusables",   cat: "namefilter", desc: "Toggle Unicode confusable character normalization." },
  { name: "/namefilter add",           cat: "namefilter", desc: "Add words to the blocked name list." },
  { name: "/namefilter remove",        cat: "namefilter", desc: "Remove words from the blocked name list." },
  { name: "/namefilter list",          cat: "namefilter", desc: "View all blocked name words and filter status." },

  // Verification Gate (v3.0)
  { name: "/verifygate toggle",        cat: "verifygate", desc: "Turn the verification gate on or off." },
  { name: "/verifygate role",          cat: "verifygate", desc: "Set the role granted when a member verifies." },
  { name: "/verifygate channel",       cat: "verifygate", desc: "Set the channel where the verification message lives." },
  { name: "/verifygate post",          cat: "verifygate", desc: "Post the verification message in the configured channel." },
  { name: "/verifygate status",        cat: "verifygate", desc: "View verification gate settings." },

  // Raid
  { name: "/lockdown",                 cat: "raid",    desc: "Manually lock all text channels. Auto-switches to raid profile." },
  { name: "/unlock",                   cat: "raid",    desc: "Lift lockdown, restore channels and previous profile." },
  { name: "/autorole",                 cat: "raid",    desc: "Set (or clear) a role to auto-assign to new members on join." },
  { name: "/raidcfg threshold",        cat: "raid",    desc: "Set raid detection: N joins in S seconds triggers auto-lockdown." },
  { name: "/raidcfg account_age",      cat: "raid",    desc: "Flag joins from accounts younger than N days. 0 disables." },
  { name: "/raidcfg action",           cat: "raid",    desc: "During active raid, kick or ban new joiners (default: ban)." },
  { name: "/raidcfg auto_verification",cat: "raid",    desc: "Auto-raise server verification level during lockdown." },
  { name: "/raidcfg cooldown",         cat: "raid",    desc: "Auto-unlock lockdown after N minutes. 0 = manual only." },

  // Honeypot
  { name: "/honeypot add",             cat: "honeypot",  desc: "Designate a channel as a honeypot (auto-ban on any post)." },
  { name: "/honeypot remove",          cat: "honeypot",  desc: "Remove a channel from the honeypot list." },
  { name: "/honeypot list",            cat: "honeypot",  desc: "List all active honeypot channels." },

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
  { name: "/panel",                    cat: "panels",    desc: "Post the persistent Mod Panel (10 buttons including TempBan)." },
  { name: "/mod",                      cat: "panels",    desc: "Open the ephemeral context-aware Mod Panel on demand." },
  { name: "/userinfo",                 cat: "panels",    desc: "View information about a user." },
  { name: "/serverinfo",               cat: "panels",    desc: "View information about this server." },

  // Threads
  { name: "/delete",                   cat: "threads",   desc: "Forum thread owner deletes their own thread. Two-step confirmation." },

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
  violations: "Violations",
  automod:    "AutoMod",
  wordlist:   "Word Lists",
  profiles:   "Profiles",
  namefilter: "Name Filter",
  verifygate: "Verify Gate",
  raid:       "Raid",
  honeypot:   "Honeypot",
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
  const counter = document.getElementById("cmd-count");
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
  if (counter) counter.textContent = `${filtered.length} command${filtered.length !== 1 ? 's' : ''}`;
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
      } catch (e) { /* clipboard blocked */ }
    });
  });
}

// ============ INIT ============
document.addEventListener("DOMContentLoaded", () => {
  initConsole();
  initCommands();
  initCopyable();
});
