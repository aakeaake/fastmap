// Paper footprints and visible-area maths. Pure functions, map units in
// metres (EPSG:3067), screen sizes in CSS pixels.
import { FOOTER_MM, PAPER_MM } from './constants.js';

// Printable content size in metres for a map's settings.
// Mirrors the backend's content_area_mm(): paper minus equal margins,
// minus the footer band.
export function contentMeters({ paperSize, orientation, margin, scale }) {
    let [wmm, hmm] = PAPER_MM[paperSize] || PAPER_MM.A4;
    if (orientation === 'landscape') [wmm, hmm] = [hmm, wmm];
    const m = Math.max(0, Math.min(margin, Math.min(wmm, hmm) / 2 - 0.5));
    return [(wmm - 2 * m) / 1000 * scale, (hmm - 2 * m - FOOTER_MM) / 1000 * scale];
}

// Closed rectangle ring centred on (cx, cy)
export function ring(cx, cy, w, h) {
    return [
        [cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2],
        [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2],
        [cx - w / 2, cy - h / 2],
    ];
}

export function extentCenter([minx, miny, maxx, maxy]) {
    return [(minx + maxx) / 2, (miny + maxy) / 2];
}

// Centre of a ring's bounding box
export function ringCenter(coords) {
    const xs = coords.map(p => p[0]);
    const ys = coords.map(p => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
}

export function containsExtent(outer, inner) {
    return outer[0] <= inner[0] && inner[2] <= outer[2]
        && outer[1] <= inner[1] && inner[3] <= outer[3];
}

// The visible map is the viewport minus the panes on the left (desktop) and
// the bottom sheet (phones). `covered` gives those widths in pixels.

// Centre of the visible area, for a view centred at `center`
export function visibleCenter(center, res, { left = 0, bottom = 0 } = {}) {
    return [center[0] + (left / 2) * res, center[1] + (bottom / 2) * res];
}

// Visible area as an extent [minx, miny, maxx, maxy]
export function visibleExtent(center, res, [w, h], { left = 0, bottom = 0 } = {}) {
    return [
        center[0] - (w / 2 - left) * res, center[1] - (h / 2 - bottom) * res,
        center[0] + (w / 2) * res, center[1] + (h / 2) * res,
    ];
}

// View centre that puts `target` in the middle of the visible area
export function centerToShow(target, res, { left = 0, bottom = 0 } = {}) {
    return [target[0] - (left / 2) * res, target[1] - (bottom / 2) * res];
}
