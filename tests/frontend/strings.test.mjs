import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_LANG, LANGS, LOCALES, STRINGS, translate } from '../../frontend/js/strings.js';

const placeholders = s => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort();

test('English is the default and every language has a locale', () => {
    assert.equal(DEFAULT_LANG, 'en');
    for (const lang of LANGS) assert.ok(LOCALES[lang], lang);
});

test('every language has exactly the same keys', () => {
    const en = Object.keys(STRINGS.en).sort();
    for (const lang of LANGS) {
        assert.deepEqual(Object.keys(STRINGS[lang]).sort(), en, `${lang} keys differ from en`);
    }
});

test('translations use the same placeholders as English', () => {
    for (const lang of LANGS) {
        for (const [key, text] of Object.entries(STRINGS[lang])) {
            assert.deepEqual(placeholders(text), placeholders(STRINGS.en[key]), `${lang}.${key}`);
        }
    }
});

test('no translation is empty', () => {
    for (const lang of LANGS) {
        for (const [key, text] of Object.entries(STRINGS[lang])) assert.ok(text.length, `${lang}.${key}`);
    }
});

test('translate fills placeholders and falls back to English, then the key', () => {
    assert.equal(translate('fi', 'map.default', { n: 2 }), 'Kartta 2');
    assert.equal(translate('en', 'map.default', { n: 2 }), 'Map 2');
    assert.equal(translate('sv', 'maps.new'), 'New map');
    assert.equal(translate('fi', 'no.such.key'), 'no.such.key');
    assert.equal(translate('en', 'map.default'), 'Map {n}');   // missing params stay visible
});
