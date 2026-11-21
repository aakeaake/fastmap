// An atlas: a regular grid of north-up sheets over a drawn area, labelled by
// row (A, B, … from the north) and column (1, 2, … from the west). Pure (no
// DOM or OpenLayers), so it runs in Node tests. Points are [x, y] in
// EPSG:3067 metres; the area is one ring, not closed.
import { fitTitle } from './cover.js';
import { contentMeters } from './geometry.js';

export const ATLAS_OVERLAP_OPTIONS = [0, 5, 10, 20];
export const ATLAS_DEFAULT_OVERLAP = 10;
export const ATLAS_MAX = 25;   // the server's batch limit, so "Download all" works
// Grids with more candidate cells are not laid out (the live count would
// stall the page); they hold at least max(rows, cols) maps, far over ATLAS_MAX
export const ATLAS_MAX_CELLS = 50000;

const EPS = 1e-6;

// 0-based row and column -> "A1"; rows past Z go on AA, AB, …
export function atlasLabel(row, col) {
    let letters = '';
    for (let n = row + 1; n > 0; n = Math.floor((n - 1) / 26)) {
        letters = String.fromCharCode(65 + ((n - 1) % 26)) + letters;
    }
    return `${letters}${col + 1}`;
}

// Does the segment a–b touch the closed rectangle [x0, y0, x1, y1]?
// (Liang–Barsky clipping)
function segmentHitsRect([ax, ay], [bx, by], [x0, y0, x1, y1]) {
    let t0 = 0;
    let t1 = 1;
    const dx = bx - ax;
    const dy = by - ay;
    for (const [p, q] of [[-dx, ax - x0], [dx, x1 - ax], [-dy, ay - y0], [dy, y1 - ay]]) {
        if (p === 0) {
            if (q < 0) return false;
        } else {
            const t = q / p;
            if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; }
            else { if (t < t0) return false; if (t < t1) t1 = t; }
        }
    }
    return true;
}

// Even-odd point in polygon, over the given edges
function inside(edges, [x, y]) {
    let odd = false;
    for (const [[xi, yi], [xj, yj]] of edges) {
        if ((yi > y) !== (yj > y) && x < xj + (y - yj) * (xi - xj) / (yi - yj)) odd = !odd;
    }
    return odd;
}

// The grid over `ring` for sheets of `size` = [w, h] ground metres sharing
// `overlapM` with each neighbour. Cells are kept where the area reaches into
// the cell's own share of the grid (its sheet minus half the overlap on each
// side with a neighbour), so no sheet is printed for a sliver its neighbour
// already holds. Returns { rows, cols, sheets: [{ center, label }] } in
// reading order (north row first, west to east).
// Above `maxCells` candidate cells, returns { rows, cols, sheets: null,
// atLeast } instead: the area is one connected shape spanning every row and
// column, so it keeps at least one sheet in each of them.
export function layoutAtlas(ring, { size: [w, h], overlapM, maxCells = Infinity }) {
    const ov = Math.max(0, Math.min(overlapM, w / 2, h / 2));
    const [sx, sy] = [w - ov, h - ov];
    const xs = ring.map(p => p[0]);
    const ys = ring.map(p => p[1]);
    const [minx, maxx, miny, maxy] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const cols = Math.max(1, Math.ceil((maxx - minx - ov) / sx - EPS));
    const rows = Math.max(1, Math.ceil((maxy - miny - ov) / sy - EPS));
    if (rows * cols > maxCells) return { rows, cols, sheets: null, atLeast: Math.max(rows, cols) };
    const x0 = (minx + maxx) / 2 - (cols * sx + ov) / 2;
    const ytop = (miny + maxy) / 2 + (rows * sy + ov) / 2;
    const edges = ring.map((p, i) => [p, ring[(i + 1) % ring.length]]);
    const center = (r, c) => [x0 + c * sx + w / 2, ytop - r * sy - h / 2];

    const sheets = [];
    for (let r = 0; r < rows; r++) {
        const top = ytop - r * sy - (r > 0 ? ov / 2 : 0) - EPS;
        const bottom = ytop - r * sy - h + (r < rows - 1 ? ov / 2 : 0) + EPS;
        // Only the edges that reach this row's band matter for its cells
        const band = edges.filter(([a, b]) => Math.max(a[1], b[1]) >= bottom && Math.min(a[1], b[1]) <= top);
        if (!band.length) continue;
        const bx0 = Math.min(...band.map(([a, b]) => Math.min(a[0], b[0])));
        const bx1 = Math.max(...band.map(([a, b]) => Math.max(a[0], b[0])));
        const c0 = Math.max(0, Math.floor((bx0 - x0 - w) / sx));
        const c1 = Math.min(cols - 1, Math.ceil((bx1 - x0) / sx));
        for (let c = c0; c <= c1; c++) {
            const share = [
                x0 + c * sx + (c > 0 ? ov / 2 : 0) + EPS, bottom,
                x0 + c * sx + w - (c < cols - 1 ? ov / 2 : 0) - EPS, top,
            ];
            // Either an edge touches the share, or the share is wholly
            // inside or outside the area: its centre tells which
            const hit = band.some(([a, b]) => segmentHitsRect(a, b, share))
                || inside(band, [(share[0] + share[2]) / 2, (share[1] + share[3]) / 2]);
            if (hit) sheets.push({ center: center(r, c), label: atlasLabel(r, c) });
        }
    }
    if (!sheets.length) {
        // A zero-area ring lying on the shares' edges: the sheet under its first point
        const c = Math.min(cols - 1, Math.max(0, Math.floor((ring[0][0] - x0) / sx)));
        const r = Math.min(rows - 1, Math.max(0, Math.floor((ytop - ring[0][1]) / sy)));
        sheets.push({ center: center(r, c), label: atlasLabel(r, c) });
    }
    return { rows, cols, sheets };
}

// The atlas for the section's paper settings
export function planAtlas(ring, { paperSize, orientation, margin, scale, overlapPct }) {
    const size = contentMeters({ paperSize, orientation, margin, scale });
    return layoutAtlas(ring, { size, overlapM: overlapPct / 100 * Math.min(...size), maxCells: ATLAS_MAX_CELLS });
}

// "<name> B3", a blank name replaced by `fallback`, cut to the server's limit
export function atlasTitle(name, label, fallback) {
    return fitTitle(name.trim() || fallback, ` ${label}`);
}
