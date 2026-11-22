// Left column (desktop): collapse the settings into the rail, and remember
// which mode (Maps, Route, Atlas) was open.
import { MODES, UI_KEY } from './constants.js';

const el = id => document.getElementById(id);

export function createPanes({ phone, onNewMap, onDownloadAll, onLayout = () => {} }) {
    const ui = (() => { try { return JSON.parse(localStorage.getItem(UI_KEY)) || {}; } catch { return {}; } })();
    delete ui.shared;   // the second pane is gone
    const saveUi = () => { try { localStorage.setItem(UI_KEY, JSON.stringify(ui)); } catch { /* ignore */ } };

    let tempFolded = false;   // folded for drawing, not by the user

    // `save` false: a temporary fold, not the user's preference
    function setCollapsed(collapsed, { focus = false, save = true } = {}) {
        if (save) {
            ui.collapsed = collapsed;
            saveUi();
            tempFolded = false;   // the user's own choice stands
        }
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

    // Desktop: give the map the width while a route or area is drawn or
    // edited; the panel comes back after, unless the user had folded it
    function foldWhileDrawing(on) {
        if (on) {
            if (phone.matches || ui.collapsed || tempFolded) return;
            setCollapsed(true, { save: false });
            tempFolded = true;
        } else if (tempFolded) {
            tempFolded = false;
            setCollapsed(false, { save: false });
        }
    }
    el('railNew').addEventListener('click', onNewMap);
    el('railDownload').addEventListener('click', onDownloadAll);

    // Restore the last layout before any map is placed: placement uses it
    setCollapsed(!!ui.collapsed);

    return {
        setCollapsed,
        coveredLeft,
        foldWhileDrawing,
        getMode: () => (MODES.includes(ui.mode) ? ui.mode : 'maps'),
        setModePref: mode => { ui.mode = mode; saveUi(); },
    };
}
