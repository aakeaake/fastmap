// Left column (desktop): collapse the settings into the rail, and the
// "Reitti ja tarkkuus" pane. On phones the pane opens as its own sheet.
import { UI_KEY } from './constants.js';

const el = id => document.getElementById(id);

export function createPanes({ phone, onNewMap, onDownloadAll }) {
    const ui = (() => { try { return JSON.parse(localStorage.getItem(UI_KEY)) || {}; } catch { return {}; } })();
    const saveUi = () => { try { localStorage.setItem(UI_KEY, JSON.stringify(ui)); } catch { /* ignore */ } };

    function setCollapsed(collapsed, { focus = false } = {}) {
        ui.collapsed = collapsed;
        saveUi();
        el('leftCol').toggleAttribute('data-collapsed', collapsed);
        el('rail').hidden = !collapsed;
        el('collapseBtn').setAttribute('aria-expanded', String(!collapsed));
        el('expandBtn').setAttribute('aria-expanded', String(!collapsed));
        if (focus) el(collapsed ? 'expandBtn' : 'collapseBtn').focus();
    }

    let opener = null;
    function setShared(open, { focus = false } = {}) {
        const pane = el('sharedPane');
        if (open && !pane.hidden) return;
        if (!phone.matches) { ui.shared = open; saveUi(); }
        pane.hidden = !open;
        for (const id of ['sharedBtn', 'railShared']) el(id).setAttribute('aria-expanded', String(open));
        if (open) {
            opener = document.activeElement;
            if (focus) el('sharedClose').focus();
        } else if (focus) {
            (opener && opener.offsetParent !== null ? opener : el('sharedBtn')).focus();
        }
    }

    // Pixel width of map hidden behind the left column's panes (0 on phones)
    function coveredLeft() {
        if (phone.matches) return 0;
        let right = 0;
        for (const id of ['panel', 'rail', 'sharedPane']) {
            const p = el(id);
            if (p.offsetParent !== null) right = Math.max(right, p.getBoundingClientRect().right);
        }
        return right;
    }

    el('collapseBtn').addEventListener('click', () => setCollapsed(true, { focus: true }));
    el('expandBtn').addEventListener('click', () => setCollapsed(false, { focus: true }));
    el('railNew').addEventListener('click', onNewMap);
    el('railDownload').addEventListener('click', onDownloadAll);
    for (const id of ['sharedBtn', 'railShared']) {
        el(id).addEventListener('click', () => setShared(el('sharedPane').hidden, { focus: true }));
    }
    el('sharedClose').addEventListener('click', () => setShared(false, { focus: true }));
    el('sharedPane').addEventListener('keydown', ev => {
        if (ev.key === 'Escape') setShared(false, { focus: true });
    });

    // Restore the last layout before any map is placed: placement uses it
    setCollapsed(!!ui.collapsed);
    if (ui.shared && !phone.matches) setShared(true);

    return { setCollapsed, setShared, coveredLeft };
}
