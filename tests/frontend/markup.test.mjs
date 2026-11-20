import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { LANGS, STRINGS } from '../../frontend/js/strings.js';

const html = readFileSync(new URL('../../frontend/index.html', import.meta.url), 'utf8');

// Every translation key the markup names: data-i18n="key" and
// data-i18n-attr="attr:key;attr:key"
function markupKeys() {
    const keys = [...html.matchAll(/data-i18n="([^"]+)"/g)].map(m => m[1]);
    for (const [, spec] of html.matchAll(/data-i18n-attr="([^"]+)"/g)) {
        for (const pair of spec.split(';')) keys.push(pair.split(':')[1].trim());
    }
    return keys;
}

test('the markup names translation keys', () => {
    assert.ok(markupKeys().length > 40);
});

test('every key in index.html exists in the English table', () => {
    const missing = markupKeys().filter(k => !(k in STRINGS.en));
    assert.deepEqual(missing, []);
});

test('the language menu offers every language', () => {
    const offered = [...html.matchAll(/role="menuitemradio" data-lang="(\w+)"/g)].map(m => m[1]).sort();
    assert.deepEqual(offered, [...LANGS].sort());
});
