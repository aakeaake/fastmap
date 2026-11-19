import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    centerToShow, containsExtent, contentMeters, extentCenter, ring, visibleCenter, visibleExtent,
} from '../../frontend/js/geometry.js';

const a4 = { paperSize: 'A4', orientation: 'portrait', margin: 7, scale: 20000 };

// mm -> m conversions are floating point: compare to the micrometre
function assertClose(actual, expected) {
    assert.equal(actual.length, expected.length);
    actual.forEach((v, i) => assert.ok(Math.abs(v - expected[i]) < 1e-6, `${actual} != ${expected}`));
}

test('contentMeters: A4 portrait minus margins, in metres', () => {
    // (210 - 2*7) mm and (297 - 2*7) mm at 1:20 000
    assertClose(contentMeters(a4), [3920, 5660]);
});

test('contentMeters: landscape swaps the sides', () => {
    assertClose(contentMeters({ ...a4, orientation: 'landscape' }), [5660, 3920]);
});

test('contentMeters: A3 and scale', () => {
    assertClose(contentMeters({ ...a4, paperSize: 'A3', scale: 10000 }), [2830, 4060]);
});

test('contentMeters: margin is capped so content never vanishes', () => {
    // half the short side minus 0.5 mm leaves 1 mm of content
    const [w] = contentMeters({ ...a4, margin: 500 });
    assertClose([w], [20]);
    assert.deepEqual(contentMeters({ ...a4, margin: -5 }), contentMeters({ ...a4, margin: 0 }));
});

test('contentMeters: unknown paper falls back to A4', () => {
    assert.deepEqual(contentMeters({ ...a4, paperSize: 'B5' }), contentMeters(a4));
});

test('ring is a closed rectangle around the centre', () => {
    const r = ring(100, 200, 20, 10);
    assert.equal(r.length, 5);
    assert.deepEqual(r[0], r[4]);
    assert.deepEqual(r[0], [90, 195]);
    assert.deepEqual(r[2], [110, 205]);
    assert.deepEqual(extentCenter([90, 195, 110, 205]), [100, 200]);
});

test('containsExtent', () => {
    assert.ok(containsExtent([0, 0, 10, 10], [1, 1, 9, 9]));
    assert.ok(containsExtent([0, 0, 10, 10], [0, 0, 10, 10]));
    assert.ok(!containsExtent([0, 0, 10, 10], [5, 5, 11, 9]));
});

test('visible centre shifts right for left panes and up for the sheet', () => {
    // 300 px of panes, 200 px of sheet, 2 m/px
    assert.deepEqual(visibleCenter([1000, 5000], 2, { left: 300, bottom: 200 }), [1300, 5200]);
    assert.deepEqual(visibleCenter([1000, 5000], 2), [1000, 5000]);
});

test('visible extent excludes the covered strips', () => {
    // 1000 x 800 px viewport at 1 m/px centred on (0, 0)
    assert.deepEqual(visibleExtent([0, 0], 1, [1000, 800], { left: 300, bottom: 200 }),
        [-200, -200, 500, 400]);
});

test('centerToShow puts the target at the visible centre', () => {
    const covered = { left: 300, bottom: 200 };
    const target = [12345, 67890];
    const view = centerToShow(target, 4, covered);
    assert.deepEqual(visibleCenter(view, 4, covered), target);
});
