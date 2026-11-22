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
    for (const id of ['modeMaps', 'modeRoute', 'modeAtlas', 'advanced', 'railModes']) {
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

test('route and atlas both have a name field', () => {
    const route = html.slice(html.indexOf('id="modeRoute"'), html.indexOf('id="modeAtlas"'));
    assert.match(route, /<input id="routeName" type="text" maxlength="100"/);
    assert.match(html, /<input id="atlasName" type="text" maxlength="100"/);
});

test('a drawn route is called Route / Reitti', () => {
    assert.equal(STRINGS.en['gpx.myRoute'], 'Route');
    assert.equal(STRINGS.fi['gpx.myRoute'], 'Reitti');
});

test('route and atlas show their sheets as a compact index, not a list', () => {
    for (const p of ['route', 'atlas']) {
        assert.match(html, new RegExp(`id="${p}Index"[^>]*role="radiogroup"`), p);
        for (const id of [`${p}Set`, `${p}Summary`, `${p}Selected`, `${p}SelDl`, `${p}SelDel`]) {
            assert.ok(html.includes(`id="${id}"`), id);
        }
        assert.ok(!html.includes(`id="${p}List"`), `${p}List gone`);
    }
});

test('Maps fold and the click-to-select tip have their words', () => {
    assert.equal(STRINGS.en['maps.showAll'], 'Show all {count} maps');
    assert.equal(STRINGS.fi['maps.showAll'], 'Näytä kaikki {count} karttaa');
    assert.equal(STRINGS.en['maps.showLess'], 'Show fewer');
    assert.equal(STRINGS.fi['maps.showLess'], 'Näytä vähemmän');
    assert.match(STRINGS.en['hint.after'], /click a sheet to select it/);
    assert.match(STRINGS.fi['hint.after'], /valitse karttalehti klikkaamalla/);
    assert.ok(html.includes('id="mapsShowAll"'));
});
