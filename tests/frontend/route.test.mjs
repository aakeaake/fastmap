import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    ROUTE_KEY, formatKm, routeLengthM, sanitizeSavedRoute, serializeRoute, toGpx,
} from '../../frontend/js/route.js';

test('the saved route has its own storage key', () => {
    assert.equal(ROUTE_KEY, 'fastmap.route.v1');
});

test('routeLengthM sums every segment of every line', () => {
    assert.equal(routeLengthM([[[0, 0], [3, 4]], [[10, 0], [10, 6], [18, 6]]]), 5 + 6 + 8);
    assert.equal(routeLengthM([]), 0);
});

test('formatKm uses the locale decimal separator', () => {
    assert.equal(formatKm(12400, 'fi-FI'), '12,4 km');
    assert.equal(formatKm(12400, 'en-GB'), '12.4 km');
    assert.equal(formatKm(40, 'en-GB'), '0.0 km');
});

test('toGpx writes one trk with a trkseg per line, 6 decimals', () => {
    const gpx = toGpx('Kierros', [[[1, 2], [3, 4]], [[5, 6], [7, 8]]], ([x, y]) => [x + 0.1234567, y]);
    assert.match(gpx, /^<\?xml version="1.0" encoding="UTF-8"\?>/);
    assert.match(gpx, /<gpx version="1.1" creator="FastMap" xmlns="http:\/\/www.topografix.com\/GPX\/1\/1">/);
    assert.equal((gpx.match(/<trk>/g) || []).length, 1);
    assert.equal((gpx.match(/<trkseg>/g) || []).length, 2);
    assert.equal((gpx.match(/<trkpt /g) || []).length, 4);
    assert.match(gpx, /<trkpt lat="2.000000" lon="1.123457"\/>/);
    assert.match(gpx, /<name>Kierros<\/name>/);
});

test('toGpx escapes XML in the name', () => {
    assert.match(toGpx('A & B <"x">', [[[0, 0], [1, 1]]], p => p), /<name>A &amp; B &lt;&quot;x&quot;&gt;<\/name>/);
});

test('sanitizeSavedRoute round-trips and rejects junk', () => {
    const r = { name: 'Oma reitti', lines: [[[1, 2], [3, 4]]], showOnPrint: false };
    assert.deepEqual(serializeRoute(r), { v: 1, ...r });
    assert.deepEqual(sanitizeSavedRoute(serializeRoute(r)), r);
    for (const bad of [null, 42, 'x', [], {}, { v: 1, name: 'x', lines: 'no' },
                       { v: 1, name: 'x', lines: [[[1, NaN], [2, 3]]] },
                       { v: 1, name: 'x', lines: [[[1, 2], 'p']] },
                       { v: 2, name: 'x', lines: [[[1, 2], [3, 4]]] }]) {
        assert.equal(sanitizeSavedRoute(bad), null);
    }
    // lines shorter than 2 points are dropped; nothing left -> null
    assert.equal(sanitizeSavedRoute({ v: 1, name: 'x', lines: [[[1, 2]]], showOnPrint: true }), null);
    // missing showOnPrint defaults to true, non-string name to ''
    assert.deepEqual(sanitizeSavedRoute({ v: 1, name: 5, lines: [[[1, 2], [3, 4]]] }),
                     { name: '', lines: [[[1, 2], [3, 4]]], showOnPrint: true });
});
