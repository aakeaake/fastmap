import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    atlasCountLabel, attributionLabel, createdLabel, deletedLabel, displayName, mapSummary, progressLabel, shortName,
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
    assert.equal(attributionLabel(line), '© Maanmittauslaitos, CC BY 4.0, 11/2026');
});

test('attributionLabel falls back to the given date', () => {
    assert.equal(attributionLabel('', new Date(2027, 0, 5)), '© Maanmittauslaitos, CC BY 4.0, 01/2027');
    assert.equal(attributionLabel(undefined, new Date(2027, 9, 5)), '© Maanmittauslaitos, CC BY 4.0, 10/2027');
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

test('atlasCountLabel: maps, rows and columns, singular and plural', () => {
    assert.equal(atlasCountLabel(12, 3, 5), '12 maps · 3 rows × 5 columns');
    assert.equal(atlasCountLabel(1, 1, 1), '1 map · 1 row × 1 column');
    assert.equal(atlasCountLabel(2, 2, 2, 'fi'), '2 karttaa · 2 riviä × 2 saraketta');
});

test('atlasCountLabel above 25 is the too-many warning', () => {
    assert.equal(atlasCountLabel(1234, 30, 50),
        '1,234 maps — an atlas holds at most 25. Choose a smaller scale, larger paper or a smaller area.');
    assert.equal(atlasCountLabel(25, 5, 5), '25 maps · 5 rows × 5 columns');
});

test('createdLabel for an atlas', () => {
    assert.equal(createdLabel(12, 'Atlas', 'en', 'atlas'), 'Created 12 maps for Atlas');
    assert.equal(createdLabel(1, 'Kartasto', 'fi', 'atlas'), '1 kartta luotu kartastoon Kartasto');
    assert.equal(createdLabel(3, 'Reitti', 'fi'), '3 karttaa luotu reitille Reitti');
});

test('atlasCountLabel for a grid too big to lay out', () => {
    assert.equal(atlasCountLabel(224, 224, 180, 'en', true),
        'At least 224 maps — an atlas holds at most 25. Choose a smaller scale, larger paper or a smaller area.');
    assert.equal(atlasCountLabel(224, 224, 180, 'fi', true),
        'Vähintään 224 karttaa — kartastossa voi olla enintään 25. Valitse pienempi mittakaava, isompi paperi tai pienempi alue.');
});
