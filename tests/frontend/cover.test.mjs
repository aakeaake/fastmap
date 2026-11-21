import { test } from 'node:test';
import assert from 'node:assert/strict';
import { coverParams, coverRoute, coverTitle, planCover } from '../../frontend/js/cover.js';

const SIZES = { portrait: [3000, 4000], landscape: [4000, 3000] };
const C = 250;
const OV = 500;
const OPTS = { sizes: SIZES, clearanceM: C, overlapM: OV };

const EPS = 1e-6;
function inInner(sheet, p, sizes = SIZES, c = C) {
    const [w, h] = sizes[sheet.orientation];
    return Math.abs(p[0] - sheet.center[0]) <= w / 2 - c + EPS
        && Math.abs(p[1] - sheet.center[1]) <= h / 2 - c + EPS;
}

// Points every `step` metres along a line, with their distance along it
function densify(line, step = 50) {
    const out = [{ p: line[0], s: 0 }];
    let s = 0;
    for (let i = 1; i < line.length; i++) {
        const [a, b] = [line[i - 1], line[i]];
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        const n = Math.max(1, Math.ceil(len / step));
        for (let k = 1; k <= n; k++) {
            const t = k / n;
            out.push({ p: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], s: s + len * t });
        }
        s += len;
    }
    return out;
}

function assertCovered(lines, sheets, sizes, c) {
    for (const line of lines) {
        for (const { p } of densify(line)) {
            assert.ok(sheets.some(sh => inInner(sh, p, sizes, c)), `point ${p} not covered`);
        }
    }
}

const EW = [[[0, 0], [10000, 0]]];

test('a straight east–west route gets landscape sheets, hand-computed count', () => {
    const s = coverRoute(EW, OPTS);
    assert.equal(s.length, 4);   // [0,3500] [3000,6500] [6000,9500] [9000,10000]
    assert.ok(s.every(x => x.orientation === 'landscape'));
});

test('a straight north–south route gets portrait sheets', () => {
    const s = coverRoute([[[0, 0], [0, 10000]]], OPTS);
    assert.equal(s.length, 4);
    assert.ok(s.every(x => x.orientation === 'portrait'));
});

test('every route point lies in some sheet\'s inner box', () => {
    const zigzag = [[[0, 0], [3000, 2000], [0, 4000], [3000, 6000], [0, 8000]]];
    const loop = [[[0, 0], [6000, 0], [6000, 6000], [0, 6000], [0, 0]]];
    for (const lines of [zigzag, loop]) assertCovered(lines, coverRoute(lines, OPTS));
});

test('consecutive sheets share at least the overlap of route', () => {
    const s = coverRoute(EW, OPTS);
    const pts = densify(EW[0]);
    for (let k = 0; k + 1 < s.length; k++) {
        // where the route leaves sheet k
        const end = Math.max(...pts.filter(q => inInner(s[k], q.p)).map(q => q.s));
        const shared = pts.filter(q => q.s >= end - OV && q.s <= end);
        assert.ok(shared.length > 0);
        assert.ok(shared.every(q => inInner(s[k], q.p) && inInner(s[k + 1], q.p)), `handover ${k}`);
    }
});

test('out-and-back: the return leg adds no sheets', () => {
    const back = [[[0, 0], [10000, 0], [10000, 100], [0, 100]]];
    const s = coverRoute(back, OPTS);
    assert.equal(s.length, coverRoute(EW, OPTS).length);
    assertCovered(back, s);
});

test('a route smaller than one inner box gives one sheet', () => {
    assert.equal(coverRoute([[[0, 0], [500, 300]]], OPTS).length, 1);
});

test('fixed orientation gives only that orientation', () => {
    const s = coverRoute(EW, { ...OPTS, orientation: 'portrait' });
    assert.ok(s.length > 0);
    assert.ok(s.every(x => x.orientation === 'portrait'));
    assertCovered(EW, s);
});

test('multi-line: sheets for every line, in line order', () => {
    const lines = [[[0, 0], [10000, 0]], [[0, 20000], [0, 30000]]];
    const s = coverRoute(lines, OPTS);
    assert.ok(s.slice(0, 4).every(x => x.orientation === 'landscape'));
    assert.ok(s.length > 4);
    assert.ok(s.slice(4).every(x => x.orientation === 'portrait'));
    assertCovered(lines, s);
});

test('a brief crossing of an earlier sheet is not skipped', () => {
    // line 2 starts 500 m inside sheet 1 (< 0.25 × 2500): it gets a sheet of its own from its start
    const lines = [[[0, 0], [10000, 0]], [[1000, 750], [1000, 10000]]];
    const opts = { ...OPTS, overlapM: 300 };
    const n1 = coverRoute([lines[0]], opts).length;
    const s = coverRoute(lines, opts);
    assert.ok(s.length > n1);
    assert.ok(inInner(s[n1], [1000, 750]));
});

test('degenerate input terminates', () => {
    assert.equal(coverRoute([[[5, 5], [5, 5]]], OPTS).length, 1);
    const dup = [[[0, 0], [0, 0], [2000, 0], [2000, 0]]];
    const s = coverRoute(dup, OPTS);
    assert.ok(s.length >= 1);
    assertCovered(dup, s);
});

test('a 500 km zig-zag at 1:10 000 finishes quickly', () => {
    const line = [];
    for (let i = 0; i <= 100; i++) line.push([i * 3000, (i % 2) * 4000]);   // 100 legs of 5 km
    const settings = { paperSize: 'A4', scale: 10000, margin: 7, overlapPct: 10, sameOrientation: false };
    const t0 = performance.now();
    const s = planCover([line], settings);
    assert.ok(performance.now() - t0 < 500);
    const { sizes, clearanceM } = coverParams(settings);
    assertCovered([line], s, sizes, clearanceM);
});

test('coverParams turns paper settings into ground metres', () => {
    const p = coverParams({ paperSize: 'A4', scale: 20000, margin: 7, overlapPct: 10 });
    const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-6, `${a} vs ${b}`);
    near(p.sizes.portrait[0], 3920); near(p.sizes.portrait[1], 5600);
    near(p.sizes.landscape[0], 5660); near(p.sizes.landscape[1], 3860);
    near(p.clearanceM, 200);
    near(p.overlapM, 386);
});

test('same orientation for all picks the run with fewer sheets', () => {
    const lines = [[[0, 0], [0, 20000]]];
    const base = { paperSize: 'A4', scale: 20000, margin: 7, overlapPct: 10 };
    const s = planCover(lines, { ...base, sameOrientation: true });
    assert.equal(new Set(s.map(x => x.orientation)).size, 1);
    const p = coverParams(base);
    const fixed = o => coverRoute(lines, { ...p, orientation: o }).length;
    assert.equal(s.length, Math.min(fixed('portrait'), fixed('landscape')));
});

test('coverTitle numbers and cuts long names', () => {
    assert.equal(coverTitle('Kaldoaivi', 3, 12), 'Kaldoaivi 3/12');
    const long = coverTitle('x'.repeat(200), 3, 12);
    assert.equal(long.length, 120);
    assert.ok(long.endsWith('… 3/12'));
});

// Wherever the route leaves a sheet, another sheet must already have held
// the last `overlapM` of route before that point (the hiker's handover).
function assertHandovers(lines, sheets, { sizes, clearanceM, overlapM }) {
    for (const line of lines) {
        const pts = densify(line, 5).map(q => ({ ...q, in: sheets.map(sh => inInner(sh, q.p, sizes, clearanceM)) }));
        for (let i = 1; i < pts.length; i++) {
            for (let a = 0; a < sheets.length; a++) {
                if (!(pts[i - 1].in[a] && !pts[i].in[a])) continue;
                const exit = pts[i].s;
                const ok = sheets.some((_, b) => b !== a && pts[i].in[b]
                    && pts.every(q => q.s < exit - overlapM + 10 || q.s > exit || q.in[b]));
                assert.ok(ok, `leaving sheet ${a} at ${Math.round(exit)} m without ${Math.round(overlapM)} m handover`);
            }
        }
    }
}

test('every handover shares at least the chosen overlap, also on diagonals and revisits', () => {
    for (const overlapPct of [5, 20]) {
    const settings = { paperSize: 'A4', scale: 20000, margin: 7, overlapPct, sameOrientation: false };
    const params = coverParams(settings);
    const diagonal = [[[0, 0], [7000, 5300], [15000, 6100], [21000, 13000]]];
    const outAndBack = [[[0, 0], [9000, 6800], [17000, 7700], [17150, 7900], [9150, 7000], [150, 200]]];
    for (const lines of [diagonal, outAndBack]) assertHandovers(lines, planCover(lines, settings), params);
    }
});
