import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    MODES, defaultSetSettings, readSavedLayout, sanitizeMode, sanitizeSetSettings, settingsChanged,
} from '../../frontend/js/modes.js';

test('three modes', () => {
    assert.deepEqual(MODES, ['maps', 'route', 'atlas']);
});

test('unknown modes become maps', () => {
    assert.equal(sanitizeMode('atlas'), 'atlas');
    for (const bad of [undefined, null, 'x', 3]) assert.equal(sanitizeMode(bad), 'maps');
});

test('set defaults', () => {
    assert.deepEqual(defaultSetSettings('route'), {
        paperSize: 'A4', orientation: 'auto', scale: 20000,
        layer: 'maastokartta', gridMode: 'off', gridSpacing: 1000, overlapPct: 10,
    });
    assert.equal(defaultSetSettings('atlas').orientation, 'portrait');
});

test('sanitizeSetSettings keeps good fields and repairs bad ones', () => {
    const s = sanitizeSetSettings('atlas', {
        paperSize: 'A3', orientation: 'auto', scale: 25000,
        layer: 'maastokartta_vektori', gridMode: 'full', gridSpacing: 333, overlapPct: 0,
    });
    assert.deepEqual(s, {
        paperSize: 'A3', orientation: 'portrait', scale: 25000,
        layer: 'maastokartta_vektori', gridMode: 'full', gridSpacing: 1000, overlapPct: 0,
    });
    assert.equal(sanitizeSetSettings('route', { overlapPct: 0 }).overlapPct, 10);   // route has no 0 %
    assert.equal(sanitizeSetSettings('route', { layer: 'maastokartta_vektori', scale: 20000 }).layer, 'maastokartta');
    assert.deepEqual(sanitizeSetSettings('route', null), defaultSetSettings('route'));
});

test('settingsChanged compares the block with what the sheets were made with', () => {
    const a = defaultSetSettings('route');
    assert.equal(settingsChanged(a, null), false);
    assert.equal(settingsChanged(a, { ...a }), false);
    for (const [k, v] of [['scale', 25000], ['layer', 'maastokartta_vektori'], ['gridMode', 'full'],
        ['gridSpacing', 2000], ['overlapPct', 20], ['paperSize', 'A3'], ['orientation', 'same']]) {
        assert.equal(settingsChanged({ ...a, [k]: v }, a), true, k);
    }
});

const ring = (cx, cy) => [[cx - 1, cy - 1], [cx + 1, cy - 1], [cx + 1, cy + 1], [cx - 1, cy + 1], [cx - 1, cy - 1]];
const map = (id, extra = {}) => ({
    id, paperSize: 'A4', orientation: 'portrait', scale: 20000,
    layer: 'maastokartta', margin: 7, coords: ring(0, 0), ...extra,
});

test('old saved data: every map is a Maps-mode map, margin from the selected map', () => {
    const r = readSavedLayout({ nextId: 4, activeId: 2, maps: [map(1, { margin: 5 }), map(2, { margin: 12 })] });
    assert.deepEqual(r.maps.map(m => m.settings.mode), ['maps', 'maps']);
    assert.deepEqual(r.activeIds, { maps: 2, route: null, atlas: null });
    assert.equal(r.margin, 12);
    assert.deepEqual(r.madeWith, { route: null, atlas: null });
    assert.equal(r.nextId, 4);
});

test('old saved data without a valid selection: margin 7', () => {
    assert.equal(readSavedLayout({ maps: [map(1, { margin: 5 })] }).margin, 7);
});

test('new saved data round-trips modes, selections, margin and made-with', () => {
    const made = { ...defaultSetSettings('atlas'), scale: 50000 };
    const r = readSavedLayout({
        nextId: 9, margin: 10, activeIds: { maps: 1, route: 3, atlas: 7 },
        madeWith: { route: defaultSetSettings('route'), atlas: made },
        maps: [map(1), map(3, { mode: 'route' }), map(7, { mode: 'atlas' })],
    });
    assert.deepEqual(r.maps.map(m => m.settings.mode), ['maps', 'route', 'atlas']);
    assert.deepEqual(r.activeIds, { maps: 1, route: 3, atlas: 7 });
    assert.equal(r.margin, 10);
    assert.deepEqual(r.madeWith.atlas, made);
});

test('selections must name a map of their own mode; made-with needs sheets', () => {
    const r = readSavedLayout({
        activeIds: { maps: 7, route: 99, atlas: 7 },
        madeWith: { route: defaultSetSettings('route'), atlas: 'junk' },
        maps: [map(1), map(7, { mode: 'atlas' })],
    });
    assert.deepEqual(r.activeIds, { maps: null, route: null, atlas: 7 });
    assert.deepEqual(r.madeWith, { route: null, atlas: defaultSetSettings('atlas') });
});

test('junk saved data gives null', () => {
    for (const bad of [null, 3, 'x', { maps: 'no' }]) assert.equal(readSavedLayout(bad), null);
});

test('a margin change since the sheets were made counts as a change', () => {
    const a = defaultSetSettings('atlas');
    const made = { ...a, margin: 7 };
    assert.equal(settingsChanged(a, made, 7), false);
    assert.equal(settingsChanged(a, made, 20), true);
    assert.equal(settingsChanged(a, { ...a }, 20), false);   // made before margins were recorded
});

test('made-with keeps its margin through a save and load', () => {
    const made = { ...defaultSetSettings('route'), margin: 12 };
    assert.equal(sanitizeSetSettings('route', made).margin, 12);
    assert.equal('margin' in sanitizeSetSettings('route', defaultSetSettings('route')), false);
    const r = readSavedLayout({ madeWith: { route: made }, maps: [map(3, { mode: 'route' })] });
    assert.equal(r.madeWith.route.margin, 12);
});
