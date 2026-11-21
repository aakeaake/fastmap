import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    attributionLabel, createdLabel, deletedLabel, displayName, mapSummary, progressLabel, shortName,
} from '../../frontend/js/text.js';

test('displayName: title, else a numbered default in the language', () => {
    assert.equal(displayName({ title: 'Nuuksio' }, 0, 'fi'), 'Nuuksio');
    assert.equal(displayName({ title: '' }, 2), 'Map 3');
    assert.equal(displayName({ title: '' }, 2, 'fi'), 'Kartta 3');
});

test('shortName trims to 16 characters', () => {
    assert.equal(shortName('Kilpisjärvi itä'), 'Kilpisjärvi itä');
    assert.equal(shortName('1234567890123456'), '1234567890123456');
    assert.equal(shortName('12345678901234567'), '123456789012345…');
});

test('mapSummary groups digits for the language', () => {
    assert.equal(mapSummary({ paperSize: 'A4', scale: 20000 }), 'A4 · 1:20,000');
    // fi-FI groups with a no-break space
    assert.match(mapSummary({ paperSize: 'A4', scale: 20000 }, 'fi'), /^A4 · 1:20\s000$/);
});

test('deletedLabel', () => {
    assert.equal(deletedLabel(1), 'Map deleted');
    assert.equal(deletedLabel(3), '3 maps deleted');
    assert.equal(deletedLabel(1, 'fi'), 'Kartta poistettu');
    assert.equal(deletedLabel(3, 'fi'), '3 karttaa poistettu');
});

test('attributionLabel takes the month from the server line', () => {
    const line = '© Maanmittauslaitos, CC BY 4.0 — Maastotietokanta 11/2026';
    assert.equal(attributionLabel(line), '© Maanmittauslaitos 11/2026');
});

test('attributionLabel falls back to the given date', () => {
    assert.equal(attributionLabel('', new Date(2027, 0, 5)), '© Maanmittauslaitos 01/2027');
    assert.equal(attributionLabel(undefined, new Date(2027, 9, 5)), '© Maanmittauslaitos 10/2027');
});

test('progressLabel', () => {
    assert.equal(progressLabel(1, 4), 'Creating PDF… 4 s');
    assert.equal(progressLabel(2, 12), 'Creating 2 files… 12 s');
    assert.equal(progressLabel(1, 4, 'fi'), 'Luodaan PDF:ää… 4 s');
    assert.equal(progressLabel(2, 12, 'fi'), 'Luodaan 2 tiedostoa… 12 s');
});

test('createdLabel: singular and plural, both languages', () => {
    assert.equal(createdLabel(1, 'Reitti'), 'Created 1 map for Reitti');
    assert.equal(createdLabel(7, 'Reitti'), 'Created 7 maps for Reitti');
    assert.equal(createdLabel(1, 'Reitti', 'fi'), '1 kartta luotu reitille Reitti');
    assert.equal(createdLabel(7, 'Reitti', 'fi'), '7 karttaa luotu reitille Reitti');
});
