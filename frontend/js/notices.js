// Pop-up notices in the bottom-right stack (above the sheet on phones),
// styled like the usage hint.
//   progress  a running download; updated in place, no announcements per tick
//   success   closes itself after a few seconds
//   error     stays until closed; announced at once (role="alert")
// A notice with an id replaces the previous one with that id. Text is given
// as a function so it can be redrawn in a new language.
import { icon } from './icons.js';

const ICONS = { progress: 'loader', success: 'check', error: 'alert' };
const SUCCESS_MS = 6000;

export function createNotices(container, { closeLabel }) {
    const open = new Map();   // id -> { node, text, timer }

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

    function show(id, kind, text) {
        close(id);
        const node = document.createElement('div');
        node.className = `notice notice-${kind}`;
        if (kind === 'error') node.setAttribute('role', 'alert');
        else if (kind === 'success') node.setAttribute('role', 'status');
        // Progress has no close button: closing it would not stop the download
        node.innerHTML = `${icon(ICONS[kind])}<span class="notice-text"></span>`
            + (kind === 'progress' ? '' : `<button type="button" class="icon-btn notice-close">${icon('x')}</button>`);
        const n = { node, text, timer: null };
        node.querySelector('.notice-close')?.addEventListener('click', () => close(id));
        if (kind === 'success') n.timer = setTimeout(() => close(id), SUCCESS_MS);
        open.set(id, n);
        render(n);
        container.append(node);
    }

    // Redraw text in place (progress ticks, language changes)
    function refresh(id) {
        if (id) { const n = open.get(id); if (n) render(n); return; }
        open.forEach(render);
    }

    return { show, close, refresh };
}
