import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    DEFAULT_STYLE, ROUTE_STYLE_KEY, WIDTH_MM, mmToPt, parseWidthMm, rgba, sanitizeRouteStyle, screenWidthPx,
} from '../../frontend/js/route-style.js';

test('the style has its own storage key and defaults', () => {
    assert.equal(ROUTE_STYLE_KEY, 'fastmap.routeStyle.v1');
    assert.deepEqual(DEFAULT_STYLE, { show: true, color: '#ff00ff', widthMm: 1.1, opacity: 60 });
    assert.deepEqual(WIDTH_MM, { min: 0.4, max: 7, step: 0.1, def: 1.1 });
});

test('parseWidthMm reads both decimal marks, clamps and rounds', () => {
    assert.equal(parseWidthMm('1,5'), 1.5);
    assert.equal(parseWidthMm('1.06'), 1.1);
    assert.equal(parseWidthMm(''), 1.1);
    assert.equal(parseWidthMm('x'), 1.1);
    assert.equal(parseWidthMm(null), 1.1);
    assert.equal(parseWidthMm('0.1'), 0.4);
    assert.equal(parseWidthMm(12), 7);
    assert.equal(parseWidthMm(2), 2);
});

test('mmToPt: 1.1 mm is about 3 pt, the field range fits the API 1–20 pt', () => {
    assert.equal(mmToPt(1.1), 3.12);
    assert.equal(mmToPt(2), 5.67);
    assert.ok(mmToPt(0.4) >= 1 && mmToPt(7) <= 20);
});

test('sanitizeRouteStyle keeps good fields, defaults bad ones', () => {
    assert.deepEqual(sanitizeRouteStyle({ show: false, color: '#00AA00', widthMm: 2, opacity: 80 }),
                     { show: false, color: '#00aa00', widthMm: 2, opacity: 80 });
    assert.deepEqual(sanitizeRouteStyle(null), DEFAULT_STYLE);
    assert.deepEqual(sanitizeRouteStyle('junk'), DEFAULT_STYLE);
    assert.deepEqual(sanitizeRouteStyle({ color: 'red', widthMm: 'x', opacity: 3 }), { ...DEFAULT_STYLE, opacity: 10 });
    assert.equal(sanitizeRouteStyle({ widthMm: 9 }).widthMm, 7);
    assert.equal(sanitizeRouteStyle({ opacity: 150 }).opacity, 100);
});

test('a 0.2.x saved route\'s show choice is the fallback when no style is saved', () => {
    assert.equal(sanitizeRouteStyle(null, false).show, false);
    assert.equal(sanitizeRouteStyle({ show: true }, false).show, true);
});

test('screen width and rgba', () => {
    assert.equal(screenWidthPx(1.1), 4);
    assert.equal(screenWidthPx(0.4), 2);
    assert.equal(screenWidthPx(7), 14);
    assert.equal(rgba('#ff00ff', 60), 'rgba(255, 0, 255, 0.6)');
    assert.equal(rgba('#00AA10', 100), 'rgba(0, 170, 16, 1)');
});
