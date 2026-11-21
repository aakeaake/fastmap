import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMargin, sanitizeSavedMap } from '../../frontend/js/saved.js';

const coords = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]];
const good = {
    id: 3, title: 'Nuuksio', paperSize: 'A3', orientation: 'landscape', scale: 25000,
    layer: 'maastokartta', margin: 5, gridMode: 'full', gridSpacing: 2000, colorIdx: 0, coords,
};

test('parseMargin: numbers are clamped, junk falls back to the default', () => {
    assert.equal(parseMargin('12'), 12);
    assert.equal(parseMargin(12.5), 12.5);
    assert.equal(parseMargin('-3'), 0);
    assert.equal(parseMargin('99'), 30);
    assert.equal(parseMargin('abc'), 7);
    assert.equal(parseMargin(''), 7);
});

test('a valid saved map keeps its settings', () => {
    const { settings, coords: c } = sanitizeSavedMap(good);
    assert.deepEqual(settings, {
        id: 3, title: 'Nuuksio', paperSize: 'A3', orientation: 'landscape', scale: 25000,
        layer: 'maastokartta', margin: 5, gridMode: 'full', gridSpacing: 2000, mode: 'maps',
    });
    assert.equal(c, coords);
});

test('optional fields fall back to defaults', () => {
    const { settings } = sanitizeSavedMap({
        ...good, id: 'x', title: 42, margin: 'wide', gridMode: 'tartan', gridSpacing: 750,
    });
    assert.equal('id' in settings, false);
    assert.equal(settings.title, '');
    assert.equal(settings.margin, 7);
    assert.equal(settings.gridMode, 'off');
    assert.equal(settings.gridSpacing, 1000);
    assert.equal(sanitizeSavedMap({ ...good, margin: 80 }).settings.margin, 30);
});

test('maps that cannot be trusted are rejected', () => {
    for (const bad of [
        null,
        'map',
        { ...good, coords: coords.slice(0, 4) },
        { ...good, coords: [...coords.slice(0, 4), [0, NaN]] },
        { ...good, paperSize: 'A5' },
        { ...good, orientation: 'diagonal' },
        { ...good, layer: 'satellite' },
        { ...good, scale: 50 },
        { ...good, scale: 3e6 },
        { ...good, scale: '20000' },
    ]) {
        assert.equal(sanitizeSavedMap(bad), null, JSON.stringify(bad));
    }
});

test('a saved vector map at an unsupported scale loads as raster', () => {
    const { settings } = sanitizeSavedMap({ ...good, layer: 'maastokartta_vektori', scale: 15000 });
    assert.equal(settings.layer, 'maastokartta');
});

test('a saved vector map at a supported scale keeps the vector layer', () => {
    const { settings } = sanitizeSavedMap({ ...good, layer: 'maastokartta_vektori', scale: 50000 });
    assert.equal(settings.layer, 'maastokartta_vektori');
});

test('sanitizeSavedMap keeps the mode; missing or unknown is maps', () => {
    assert.equal(sanitizeSavedMap({ ...good, mode: 'route' }).settings.mode, 'route');
    assert.equal(sanitizeSavedMap(good).settings.mode, 'maps');
    assert.equal(sanitizeSavedMap({ ...good, mode: 'x' }).settings.mode, 'maps');
});
