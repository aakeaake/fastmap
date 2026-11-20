// Pop-up notices in the bottom-right stack (above the sheet on phones),
// styled like the usage hint.
//   progress  a running download; updated in place
//   success   closes itself after a few seconds
//   error     stays until closed
// A notice with an id replaces the previous one with that id. Text is given
// as a function so it can be redrawn in a new language.
//
// Screen readers: the cards themselves carry no live role. Many screen
// readers skip text that is already present when a live element appears,
// so announcements go through two fixed, visually hidden live regions that
// stay in the page (polite for start / done, assertive for errors).
import { icon } from './icons.js';

const ICONS = { progress: 'loader', success: 'check', error: 'alert' };
const SUCCESS_MS = 6000;

export function createNotices(container, { closeLabel, politeRegion, alertRegion }) {
    const open = new Map();   // id -> { node, text, timer }

    // Clear, then write on the next task: a repeated identical message is
    // still a change, so it is announced again.
    function announce(text, { urgent = false } = {}) {
        const region = urgent ? alertRegion : politeRegion;
        region.textContent = '';
        setTimeout(() => { region.textContent = text; }, 60);
    }

    function close(id) {
        const n = open.get(id);
        if (!n) return;
        clearTimeout(n.timer);
        n.node.remove();
        open.delete(id);
    }

    function render(n) {
        n.node.querySelector('.notice-text').textContent = n.text();
        n.node.querySelector('.notice-close')?.setAttribute('aria-label', closeLabel());
    }

    // `announcement` (a string, already in the current language) is read out
    // once the card is on screen; success and error default to the card text.
    function show(id, kind, text, { announcement } = {}) {
        close(id);
        const node = document.createElement('div');
        node.className = `notice notice-${kind}`;
        // Progress has no close button: closing it would not stop the download
        node.innerHTML = `${icon(ICONS[kind])}<span class="notice-text"></span>`
            + (kind === 'progress' ? '' : `<button type="button" class="icon-btn notice-close">${icon('x')}</button>`);
        const n = { node, text, timer: null };
        node.querySelector('.notice-close')?.addEventListener('click', () => close(id));
        if (kind === 'success') n.timer = setTimeout(() => close(id), SUCCESS_MS);
        open.set(id, n);
        render(n);
        container.append(node);
        const said = announcement ?? (kind === 'progress' ? null : text());
        if (said) announce(said, { urgent: kind === 'error' });
    }

    // Redraw text in place (progress ticks, language changes)
    function refresh(id) {
        if (id) { const n = open.get(id); if (n) render(n); return; }
        open.forEach(render);
    }

    return { show, close, refresh, announce };
}
