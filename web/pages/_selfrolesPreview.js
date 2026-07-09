/**
 * _selfrolesPreview.js -- Agent 4 (private module)
 * Not registered in the router. Imported only by selfroles.js.
 *
 * Exports:
 *   buildPreviewHTML(introText, roles, enforcement) → string  (safe HTML for pre.innerHTML)
 *   updatePreview(containerEl, introText, roles, enforcement) → void
 *
 * Discord mention format: <@&role_id>
 *   Existing-category roles  → rendered as <@&{role_id}> (exact Discord syntax)
 *   New-builder roles        → rendered as role name (no ID until bot processes the action)
 */

const INTRO_DEFAULTS = {
  single: 'Select one option. Choosing a new one will remove your current selection.',
  multi:  'Select any that apply. You can pick multiple.',
};

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * Returns an HTML string (safe to set via innerHTML on a <pre>).
 * Styles injected by selfroles.js under #sr-styles.
 */
export function buildPreviewHTML(introText, roles, enforcement) {
  const intro = (introText ?? '').trim() || INTRO_DEFAULTS[enforcement] || INTRO_DEFAULTS.single;

  const filled = (roles ?? []).filter(r => r.emoji || r.role_id || r.name);

  let roleLine;
  if (filled.length === 0) {
    roleLine = '<span class="srp-dim">(no roles added yet)</span>';
  } else {
    roleLine = filled.map(r => {
      const emoji = (r.emoji ?? '').trim() || '❓';
      const mention = r.role_id
        ? `<span class="srp-mention">&lt;@&amp;${esc(String(r.role_id))}&gt;</span>`
        : `<span class="srp-new">${esc(r.name || '(role name)')}</span>`;
      return `→ ${esc(emoji)} ${mention}`;
    }).join('  ');
  }

  return [
    esc(intro),
    roleLine,
    '<span class="srp-dim">Remove your reaction to unassign the role.</span>',
  ].join('\n');
}

/**
 * Mounts or updates the preview DOM inside containerEl.
 * Creates the label + pre on first call; updates pre.innerHTML on subsequent calls.
 */
export function updatePreview(containerEl, introText, roles, enforcement) {
  let pre = containerEl.querySelector('.sr-preview-pre');
  if (!pre) {
    containerEl.innerHTML = '';
    const lbl = document.createElement('p');
    lbl.className = 'sr-preview-label';
    lbl.textContent = 'Discord preview';
    pre = document.createElement('pre');
    pre.className = 'sr-preview-pre';
    containerEl.appendChild(lbl);
    containerEl.appendChild(pre);
  }
  pre.innerHTML = buildPreviewHTML(introText, roles, enforcement);
}
