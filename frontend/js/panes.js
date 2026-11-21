// Left column (desktop): collapse the settings into the rail, and remember
// which mode (Maps, Route, Atlas) was open.
import { MODES, UI_KEY } from './constants.js';

const el = id => document.getElementById(id);

export function createPanes({ phone, onNewMap, onDownloadAll, onLayout = () => {} }) {
    const ui = (() => { try { return JSON.parse(localStorage.getItem(UI_KEY)) || {}; } catch { return {}; } })();
    delete ui.shared;   // the second pane is gone
    const saveUi = () => { try { localStorage.setItem(UI_KEY, JSON.stringify(ui)); } catch { /* ignore */ } };

    function setCollapsed(collapsed, { focus = false } = {}) {
        ui.collapsed = collapsed;
        saveUi();
        el('leftCol').toggleAttribute('data-collapsed', collapsed);
        el('rail').hidden = !collapsed;
        el('collapseBtn').setAttribute('aria-expanded', String(!collapsed));
        el('expandBtn').setAttribute('aria-expanded', String(!collapsed));
        if (focus) el(collapsed ? 'expandBtn' : 'collapseBtn').focus();
        onLayout(coveredLeft());
    }

    // Pixel width of map hidden behind the left column (0 on phones)
    function coveredLeft() {
        if (phone.matches) return 0;
        let right = 0;
        for (const id of ['panel', 'rail']) {
            const p = el(id);
            if (p.offsetParent !== null) right = Math.max(right, p.getBoundingClientRect().right);
        }
        return right;
    }

    el('collapseBtn').addEventListener('click', () => setCollapsed(true, { focus: true }));
    el('expandBtn').addEventListener('click', () => setCollapsed(false, { focus: true }));
    el('railNew').addEventListener('click', onNewMap);
    el('railDownload').addEventListener('click', onDownloadAll);

    // Restore the last layout before any map is placed: placement uses it
    setCollapsed(!!ui.collapsed);

    return {
        setCollapsed,
        coveredLeft,
        getMode: () => (MODES.includes(ui.mode) ? ui.mode : 'maps'),
        setModePref: mode => { ui.mode = mode; saveUi(); },
    };
}
