// Bottom sheet (phones): three heights, peek (title + download), half and
// full. Drag the header, flick it, or tap it to step through. Wider screens
// keep the floating panel and ignore all of this.
import { SHEET_NEXT, sheetHeights, snapTarget } from './sheet-math.js';

export function createSheet({ panel, head, footer, grabber, stack }) {
    const phone = matchMedia('(max-width: 640px)');
    let current = 'peek';
    let drag = null;
    let suppressClick = false;

    const heights = () => sheetHeights(window.innerHeight, head.offsetHeight, footer.offsetHeight);
    const applyHeight = h => document.documentElement.style.setProperty('--sheet-h', `${Math.round(h)}px`);

    function setSheet(next) {
        current = next;
        if (!phone.matches) {
            panel.removeAttribute('data-sheet');
            document.documentElement.style.removeProperty('--sheet-h');
            grabber.setAttribute('aria-expanded', 'true');
            return;
        }
        panel.dataset.sheet = next;
        grabber.setAttribute('aria-expanded', String(next !== 'peek'));
        applyHeight(heights()[next]);
    }

    // Pixel height of map hidden behind the sheet (0 on wider screens)
    const coveredBottom = () => (phone.matches ? panel.getBoundingClientRect().height : 0);

    // Controls in the header (the mode switch) keep their own taps and drags;
    // the rest of the header (title, summary, grab handle) moves the sheet
    const onControl = target => {
        const c = target instanceof Element && target.closest('button, a, input, select, [role="radio"]');
        return !!c && c !== grabber;
    };

    head.addEventListener('pointerdown', ev => {
        if (!phone.matches || ev.button > 0 || onControl(ev.target)) return;
        suppressClick = false;
        // Measure once per gesture: reading layout on every move would force
        // a reflow right after the previous move changed --sheet-h
        const { peek, full } = heights();
        drag = { id: ev.pointerId, y: ev.clientY, h: panel.offsetHeight, peek, full,
                 lastY: ev.clientY, lastT: ev.timeStamp, v: 0, moved: false };
        try { head.setPointerCapture(ev.pointerId); } catch { /* pointer already gone */ }
    });
    head.addEventListener('pointermove', ev => {
        if (!drag || ev.pointerId !== drag.id) return;
        const dy = ev.clientY - drag.y;
        if (!drag.moved) {
            if (Math.abs(dy) < 6) return;
            drag.moved = true;
            panel.classList.add('dragging');
            stack.classList.add('dragging');
            panel.dataset.sheet = 'drag';
        }
        const dt = ev.timeStamp - drag.lastT;
        if (dt > 0) drag.v = (ev.clientY - drag.lastY) / dt;
        drag.lastY = ev.clientY;
        drag.lastT = ev.timeStamp;
        applyHeight(Math.min(drag.full, Math.max(drag.peek, drag.h - dy)));
    });
    function endDrag(ev) {
        if (!drag || ev.pointerId !== drag.id) return;
        const d = drag;
        drag = null;
        panel.classList.remove('dragging');
        stack.classList.remove('dragging');
        if (!d.moved) return;           // a tap: the click handler steps the sheet
        suppressClick = true;
        setSheet(snapTarget(heights(), panel.offsetHeight, d.v));
    }
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
        head.addEventListener(type, endDrag);
    }
    head.addEventListener('click', ev => {
        if (suppressClick) { suppressClick = false; return; }
        if (onControl(ev.target)) return;
        if (phone.matches) setSheet(SHEET_NEXT[current]);
    });
    // Keyboard path: in peek the body is visibility:hidden (not focusable),
    // so Tab reaches the grabber button, whose click opens the sheet.
    phone.addEventListener('change', () => setSheet(phone.matches ? 'peek' : current));
    window.addEventListener('resize', () => { if (!drag) setSheet(current); });
    // Peek is header + footer; if the footer's height changes (text zoom,
    // touch sizing), peek follows it
    new ResizeObserver(() => { if (!drag && phone.matches) setSheet(current); }).observe(footer);

    return { phone, setSheet, coveredBottom, get state() { return current; } };
}
