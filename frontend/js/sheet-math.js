// Bottom-sheet heights and snapping. Pure.

export const SHEET_ORDER = ['peek', 'half', 'full'];
export const SHEET_NEXT = { peek: 'half', half: 'full', full: 'peek' };
export const FLICK_SPEED = 0.5;   // px/ms

// Snap heights for a viewport. Peek shows the header and download footer;
// full leaves a 72px strip of map above the sheet.
export function sheetHeights(viewportH, headH, footerH) {
    const peek = headH + footerH;
    return {
        peek,
        half: Math.max(peek, Math.round(viewportH * 0.5)),
        full: Math.max(peek, viewportH - 72),
    };
}

// Where a drag released at height `h` with vertical speed `v` (px/ms,
// negative = upwards) should settle: the nearest height, or for a flick
// one step further in the flick's direction.
export function snapTarget(heights, h, v) {
    if (Math.abs(v) > FLICK_SPEED) {
        return v < 0
            ? (SHEET_ORDER.find(s => heights[s] > h + 1) ?? 'full')
            : ([...SHEET_ORDER].reverse().find(s => heights[s] < h - 1) ?? 'peek');
    }
    return SHEET_ORDER.reduce((a, b) => (Math.abs(heights[b] - h) < Math.abs(heights[a] - h) ? b : a));
}
