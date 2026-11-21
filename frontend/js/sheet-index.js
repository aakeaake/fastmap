// The compact index of a route or atlas set: each sheet's printed label (read
// from its title), the index layout (an atlas grid or a wrapping strip),
// keyboard moves, and nudging new maps off each other. Pure, so it runs in
// Node tests.

// The label printed on a sheet, from the end of its title: " 3/25" (route)
// -> { n: 3 }; " B3" (atlas) -> { row: 1, col: 2, label: 'B3' }; else null
export function sheetLabel(title) {
    if (typeof title !== 'string') return null;
    const route = title.match(/\s(\d+)\/\d+$/);
    if (route) return { n: Number(route[1]) };
    const atlas = title.match(/\s([A-Z]{1,2})(\d{1,3})$/);
    if (!atlas) return null;
    let row = 0;
    for (const ch of atlas[1]) row = row * 26 + (ch.charCodeAt(0) - 64);
    return { row: row - 1, col: Number(atlas[2]) - 1, label: `${atlas[1]}${atlas[2]}` };
}

// Cells in order, wrapped `maxCols` to a row
function strip(items, maxCols) {
    const cols = Math.max(1, Math.min(maxCols, items.length));
    return {
        kind: 'strip',
        cols,
        cells: items.map(({ id, label }, i) => ({ id, label, row: Math.floor(i / cols), col: i % cols })),
    };
}

// The index for a set's sheets ([{ id, title }]). A route is a strip in
// walking order; an atlas is its grid (only the rows and columns its sheets
// use, gaps left empty), or a strip in reading order when the grid is wider
// than `maxCols`. Sheets without a label go last.
export function indexLayout(mode, sheets, { maxCols }) {
    const read = sheets.map(s => ({ id: s.id, l: sheetLabel(s.title) }));
    if (mode === 'route') {
        const labelled = read.filter(r => r.l && 'n' in r.l).sort((a, b) => a.l.n - b.l.n);
        const rest = read.filter(r => !(r.l && 'n' in r.l));
        return strip([...labelled, ...rest].map((r, i) => ({ id: r.id, label: r.l && 'n' in r.l ? String(r.l.n) : String(i + 1) })), maxCols);
    }
    const labelled = read.filter(r => r.l && 'row' in r.l)
        .sort((a, b) => a.l.row - b.l.row || a.l.col - b.l.col);
    const rest = read.filter(r => !(r.l && 'row' in r.l));
    const items = [...labelled, ...rest].map((r, i) => ({ id: r.id, label: r.l && 'row' in r.l ? r.l.label : String(i + 1) }));
    if (!labelled.length || rest.length) return strip(items, maxCols);
    const rows = labelled.map(r => r.l.row);
    const cols = labelled.map(r => r.l.col);
    const [r0, c0] = [Math.min(...rows), Math.min(...cols)];
    const width = Math.max(...cols) - c0 + 1;
    if (width > maxCols) return strip(items, maxCols);
    return {
        kind: 'grid',
        cols: width,
        cells: labelled.map(r => ({ id: r.id, label: r.l.label, row: r.l.row - r0, col: r.l.col - c0 })),
    };
}

const STEPS = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] };

// The sheet a key moves the selection to (the same one at an edge).
// Grid: steps over empty slots; strip: ←/→ along the order, ↑/↓ a row.
export function moveInIndex(layout, id, key) {
    const { cells } = layout;
    if (!cells.length) return id;
    const i = cells.findIndex(c => c.id === id);
    if (i === -1) return cells[0].id;
    if (key === 'Home') return cells[0].id;
    if (key === 'End') return cells[cells.length - 1].id;
    const step = STEPS[key];
    if (!step) return id;
    if (layout.kind === 'strip') {
        const j = i + (step[0] ? step[0] * layout.cols : step[1]);
        return j >= 0 && j < cells.length ? cells[j].id : id;
    }
    const maxRow = Math.max(...cells.map(c => c.row));
    const cur = cells[i];
    let { row, col } = cur;
    for (;;) {
        row += step[0];
        col += step[1];
        if (row < 0 || row > maxRow || col < 0 || col >= layout.cols) break;
        const hit = cells.find(c => c.row === row && c.col === col);
        if (hit) return hit.id;
    }
    // Nothing straight ahead: the nearest cell in that direction, so no
    // sheet is out of the keyboard's reach
    const ahead = c => (step[0] ? (c.row - cur.row) * step[0] : (c.col - cur.col) * step[1]);
    const aside = c => (step[0] ? Math.abs(c.col - cur.col) : Math.abs(c.row - cur.row));
    let best = null;
    for (const c of cells) {
        if (ahead(c) <= 0) continue;
        if (!best || ahead(c) < ahead(best) || (ahead(c) === ahead(best) && aside(c) < aside(best))) best = c;
    }
    return best ? best.id : id;
}

// How many cells of `cell` px with `gap` px between fit in `width` px
export function fitColumns(width, cell, gap) {
    return Math.max(1, Math.floor((width + gap) / (cell + gap)));
}

// A new map's centre, moved a quarter sheet right and down while another
// map's centre is within a metre of it
export function nudgeCenter(center, others, [w, h]) {
    let [x, y] = center;
    for (let k = 0; k < 50 && others.some(o => Math.hypot(o[0] - x, o[1] - y) < 1); k++) {
        x += w / 4;
        y -= h / 4;
    }
    return [x, y];
}
