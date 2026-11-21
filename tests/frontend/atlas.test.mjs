import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ATLAS_MAX_CELLS, atlasLabel, atlasTitle, layoutAtlas, planAtlas } from '../../frontend/js/atlas.js';

const SIZE = [3000, 4000];
const EPS = 1e-6;
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < EPS, `${msg ?? ''} ${a} vs ${b}`);

const inSheet = (sheet, p, [w, h] = SIZE) =>
    Math.abs(p[0] - sheet.center[0]) <= w / 2 + EPS && Math.abs(p[1] - sheet.center[1]) <= h / 2 + EPS;

// Even-odd point in polygon
function inRing(ring, [x, y]) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i];
        const [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y) && x < xj + (y - yj) * (xi - xj) / (yi - yj)) inside = !inside;
    }
    return inside;
}

// Points every `step` metres over the ring's bounding box that lie inside it
function samplesInside(ring, step) {
    const xs = ring.map(p => p[0]);
    const ys = ring.map(p => p[1]);
    const out = [];
    for (let x = Math.min(...xs) + step / 2; x < Math.max(...xs); x += step) {
        for (let y = Math.min(...ys) + step / 2; y < Math.max(...ys); y += step) {
            if (inRing(ring, [x, y])) out.push([x, y]);
        }
    }
    return out;
}

const parse = label => {
    const [, letters, col] = label.match(/^([A-Z]+)(\d+)$/);
    let row = 0;
    for (const ch of letters) row = row * 26 + (ch.charCodeAt(0) - 64);
    return [row - 1, Number(col) - 1];
};

test('an area exactly one sheet in size gives one sheet, A1', () => {
    const r = layoutAtlas([[0, 0], [3000, 0], [3000, 4000], [0, 4000]], { size: SIZE, overlapM: 300 });
    assert.deepEqual(r, { rows: 1, cols: 1, sheets: [{ center: [1500, 2000], label: 'A1' }] });
});

test('a rectangle at 10 %: hand-computed grid, centred, reading order', () => {
    const r = layoutAtlas([[0, 0], [8000, 0], [8000, 7000], [0, 7000]], { size: SIZE, overlapM: 300 });
    assert.equal(r.rows, 2);
    assert.equal(r.cols, 3);
    assert.deepEqual(r.sheets.map(s => s.label), ['A1', 'A2', 'A3', 'B1', 'B2', 'B3']);
    assert.deepEqual(r.sheets.map(s => s.center), [
        [1300, 5350], [4000, 5350], [6700, 5350], [1300, 1650], [4000, 1650], [6700, 1650]]);
});

test('a rectangle at 0 %: sheets meet edge to edge', () => {
    const r = layoutAtlas([[0, 0], [8000, 0], [8000, 7000], [0, 7000]], { size: SIZE, overlapM: 0 });
    assert.deepEqual(r.sheets.map(s => s.center), [
        [1000, 5500], [4000, 5500], [7000, 5500], [1000, 1500], [4000, 1500], [7000, 1500]]);
});

test('an L-shape leaves out the empty corner; a shared edge alone keeps nothing', () => {
    const L = [[0, 0], [3000, 0], [3000, 4000], [6000, 4000], [6000, 8000], [0, 8000]];
    const r = layoutAtlas(L, { size: SIZE, overlapM: 0 });
    assert.deepEqual(r.sheets.map(s => s.label), ['A1', 'A2', 'B1']);
});

test('a sliver under half the overlap keeps no sheet; just past it does', () => {
    // grid 2 × 2, extent 5700 × 7700 = the bbox; B2's sheet starts at x 2700, its top at y 4000
    const ring = x => [[0, 0], [x, 0], [x, 3900], [5700, 3900], [5700, 7700], [0, 7700]];
    const labels = x => layoutAtlas(ring(x), { size: SIZE, overlapM: 300 }).sheets.map(s => s.label);
    assert.deepEqual(labels(2800), ['A1', 'A2', 'B1']);         // 100 m < 150 m into B2
    assert.deepEqual(labels(2900), ['A1', 'A2', 'B1', 'B2']);   // 200 m > 150 m
});

test('every point inside the area is on a kept sheet', () => {
    const shapes = {
        diagonal: [[0, 0], [2000, 0], [20000, 15000], [18000, 15000]],
        triangle: [[0, 0], [14000, 0], [7000, 11000]],
        bowtie: [[0, 0], [12000, 9000], [12000, 0], [0, 9000]],   // self-crossing
    };
    for (const [name, ring] of Object.entries(shapes)) {
        for (const ov of [0, 300, 800]) {
            const { sheets } = layoutAtlas(ring, { size: SIZE, overlapM: ov });
            const pts = samplesInside(ring, 100);
            assert.ok(pts.length > 100, name);
            for (const p of pts) {
                assert.ok(sheets.some(s => inSheet(s, p)), `${name} ov ${ov}: ${p}`);
            }
        }
    }
});

test('the diagonal strip leaves cells out', () => {
    const ring = [[0, 0], [2000, 0], [20000, 15000], [18000, 15000]];
    const r = layoutAtlas(ring, { size: SIZE, overlapM: 300 });
    assert.ok(r.sheets.length < r.rows * r.cols);
});

test('labels tell the truth about neighbours', () => {
    const ring = [[0, 0], [2000, 0], [20000, 15000], [18000, 15000]];
    const { sheets } = layoutAtlas(ring, { size: SIZE, overlapM: 300 });
    const at = Object.fromEntries(sheets.map(s => [s.label, s.center]));
    let east = 0;
    let south = 0;
    for (const s of sheets) {
        const [row, col] = parse(s.label);
        const e = at[atlasLabel(row, col + 1)];
        if (e) { east++; near(e[0] - s.center[0], 2700); near(e[1], s.center[1]); }
        const so = at[atlasLabel(row + 1, col)];
        if (so) { south++; near(s.center[1] - so[1], 3700); near(so[0], s.center[0]); }
    }
    assert.ok(east > 0 && south > 0);
});

test('rows past Z continue AA, AB', () => {
    assert.equal(atlasLabel(0, 0), 'A1');
    assert.equal(atlasLabel(25, 0), 'Z1');
    assert.equal(atlasLabel(26, 2), 'AA3');
    assert.equal(atlasLabel(27, 9), 'AB10');
    const tall = [[0, 0], [10, 0], [10, 27 * 3700 + 300], [0, 27 * 3700 + 300]];
    const r = layoutAtlas(tall, { size: SIZE, overlapM: 300 });
    assert.equal(r.rows, 27);
    assert.equal(r.sheets.at(-1).label, 'AA1');
});

test('degenerate rings terminate with at least one sheet', () => {
    assert.equal(layoutAtlas([[5, 5], [5, 5], [5, 5]], { size: SIZE, overlapM: 300 }).sheets.length, 1);
    assert.ok(layoutAtlas([[0, 0], [5000, 0], [10000, 0]], { size: SIZE, overlapM: 300 }).sheets.length >= 1);
    // a zero-area ring lying on the shared edge of the shares
    assert.equal(layoutAtlas([[0, 0], [8000, 0], [0, 0]], { size: SIZE, overlapM: 0 }).sheets.length >= 1, true);
});

test('planAtlas uses the paper settings', () => {
    const r = planAtlas([[0, 0], [3920, 0], [3920, 5600], [0, 5600]],
        { paperSize: 'A4', orientation: 'portrait', margin: 7, scale: 20000, overlapPct: 10 });
    assert.equal(r.sheets.length, 1);   // A4 portrait 1:20 000 map area is 3920 × 5600 m
    const l = planAtlas([[0, 0], [3920, 0], [3920, 5600], [0, 5600]],
        { paperSize: 'A4', orientation: 'landscape', margin: 7, scale: 20000, overlapPct: 10 });
    assert.ok(l.sheets.length > 1);
});

test('a country-sized area at 1:10 000 lays out quickly when asked to', () => {
    // A4 portrait at 1:10 000 (half of 3920 × 5600), no cell limit
    const ring = [[0, 6600000], [600000, 6600000], [700000, 7300000], [300000, 7800000], [100000, 7400000]];
    const t0 = performance.now();
    const r = layoutAtlas(ring, { size: [1960, 2800], overlapM: 196 });
    assert.ok(performance.now() - t0 < 500, `${performance.now() - t0} ms`);
    assert.ok(r.sheets.length > 1000);
});

test('atlasTitle: label kept, long names cut, blank falls back', () => {
    assert.equal(atlasTitle('Kaldoaivi', 'B3', 'Atlas'), 'Kaldoaivi B3');
    assert.equal(atlasTitle('   ', 'B3', 'Atlas'), 'Atlas B3');
    const long = atlasTitle('x'.repeat(200), 'AA12', 'Atlas');
    assert.equal(long.length, 120);
    assert.ok(long.endsWith('… AA12'));
});

test('a huge grid is not laid out: at least max(rows, cols) maps, quickly', () => {
    // a whole-country box at 1:10 000: over a million candidate cells
    const ring = [[50000, 6600000], [750000, 6600000], [750000, 7800000], [50000, 7800000]];
    const t0 = performance.now();
    const r = planAtlas(ring, { paperSize: 'A4', orientation: 'portrait', margin: 7, scale: 10000, overlapPct: 10 });
    assert.ok(performance.now() - t0 < 50, `${performance.now() - t0} ms`);
    assert.ok(r.rows * r.cols > ATLAS_MAX_CELLS);
    assert.equal(r.sheets, null);
    assert.equal(r.atLeast, Math.max(r.rows, r.cols));
});

test('a grid at the cell limit is still laid out', () => {
    const r = layoutAtlas([[0, 0], [3000, 0], [3000, 4000], [0, 4000]], { size: [3000, 4000], overlapM: 0, maxCells: 1 });
    assert.equal(r.sheets.length, 1);
});
