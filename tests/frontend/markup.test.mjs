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

test('one panel with three modes, no second pane', () => {
    assert.ok(!html.includes('id="sharedPane"'));
    assert.match(html, /id="modeTabs"[^>]*role="radiogroup"/);
    const modes = [...html.matchAll(/role="radio"[^>]*data-mode="(\w+)"/g)].map(m => m[1]);
    assert.deepEqual(modes, ['maps', 'route', 'atlas']);
    for (const id of ['modeMaps', 'modeRoute', 'modeAtlas', 'advanced', 'routeList', 'atlasList', 'railModes']) {
        assert.ok(html.includes(`id="${id}"`), id);
    }
});

test('margin lives in Advanced, map type next to scale', () => {
    const adv = html.slice(html.indexOf('id="advanced"'));
    assert.ok(adv.indexOf('id="margin"') > 0 && adv.indexOf('id="margin"') < adv.indexOf('</details>'));
    const maps = html.slice(html.indexOf('id="modeMaps"'), html.indexOf('id="modeRoute"'));
    assert.ok(maps.includes('id="mapType"') && !maps.includes('id="margin"'));
});

test('hidden always hides, even on elements whose class sets display', () => {
    const css = readFileSync(new URL('../../frontend/styles.css', import.meta.url), 'utf8');
    assert.match(css, /\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}/);
});
