import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AREA_KEY, formatKm2, ringAreaM2, sanitizeSavedArea, serializeArea } from '../../frontend/js/area.js';

test('the saved area has its own storage key', () => {
    assert.equal(AREA_KEY, 'fastmap.area.v1');
});

test('ringAreaM2 is the absolute polygon area', () => {
    assert.equal(ringAreaM2([[0, 0], [1000, 0], [1000, 2000], [0, 2000]]), 2e6);
    assert.equal(ringAreaM2([[0, 0], [0, 2000], [1000, 2000], [1000, 0]]), 2e6);   // clockwise
    assert.equal(ringAreaM2([[0, 0], [5, 5], [10, 10]]), 0);
});

test('formatKm2: one decimal under 100 km², none above', () => {
    assert.equal(formatKm2(2e6, 'en'), '2.0 km²');
    assert.equal(formatKm2(412.3e6, 'en'), '412 km²');
    assert.equal(formatKm2(12.34e6, 'fi'), '12,3 km²');
});

test('a saved area round-trips', () => {
    const area = { name: 'Kaldoaivi', ring: [[0, 0], [1000, 0], [500, 800]] };
    assert.deepEqual(sanitizeSavedArea(JSON.parse(JSON.stringify(serializeArea(area)))), area);
});

test('a closing point equal to the first is dropped', () => {
    const s = sanitizeSavedArea({ v: 1, name: 'x', ring: [[0, 0], [1, 0], [1, 1], [0, 0]] });
    assert.deepEqual(s.ring, [[0, 0], [1, 0], [1, 1]]);
});

test('duplicate points are kept and still load', () => {
    const s = sanitizeSavedArea({ v: 1, name: 'x', ring: [[0, 0], [0, 0], [1, 0], [1, 1]] });
    assert.equal(s.ring.length, 4);
});

test('junk gives null', () => {
    for (const bad of [null, 7, {}, { v: 2, name: '', ring: [[0, 0], [1, 0], [1, 1]] },
        { v: 1, name: '', ring: [[0, 0], [1, 0]] },
        { v: 1, name: '', ring: [[0, 0], [1, 0], [0, 0]] },
        { v: 1, name: '', ring: [[0, 0], [1, 'x'], [1, 1]] },
        { v: 1, name: '', ring: 'no' }]) {
        assert.equal(sanitizeSavedArea(bad), null, JSON.stringify(bad));
    }
});

test('a bad name becomes empty, a long one is cut to 100', () => {
    assert.equal(sanitizeSavedArea({ v: 1, name: 5, ring: [[0, 0], [1, 0], [1, 1]] }).name, '');
    assert.equal(sanitizeSavedArea({ v: 1, name: 'x'.repeat(150), ring: [[0, 0], [1, 0], [1, 1]] }).name.length, 100);
});
