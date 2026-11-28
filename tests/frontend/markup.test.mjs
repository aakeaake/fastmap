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
    const card = html.slice(html.indexOf('id="routeCard"'), html.indexOf('<!-- end routeCard -->'));
    assert.match(card, /<input id="routeName" type="text" maxlength="100"/);
    assert.match(html, /<input id="atlasName" type="text" maxlength="100"/);
});

test('the route lives in its own card, opened from a map button', () => {
    assert.match(html, /id="routeToolBtn"[^>]*aria-controls="routeCard"/);
    assert.match(html, /id="routeCard"[^>]*role="dialog"/);
    const route = html.slice(html.indexOf('id="modeRoute"'), html.indexOf('id="modeAtlas"'));
    for (const id of ['gpxBtn', 'drawBtn', 'routeName', 'gpxColor', 'gpxWidth', 'routeStyle']) {
        assert.ok(!route.includes(`id="${id}"`), `${id} not in Route mode`);
    }
    for (const id of ['routeNone', 'openRouteToolBtn', 'routeLine', 'routeToolLink']) assert.ok(route.includes(`id="${id}"`), id);
    // Text, not number: a number field drops or mangles a decimal comma
    // ("1,5" -> "15" in some browsers) before parseWidthMm can read it
    assert.match(html, /<input id="gpxWidth" type="text" inputmode="decimal"[^>]*value="1.1"/);
    assert.equal(STRINGS.en['gpx.width'], 'Width (mm)');
    assert.equal(STRINGS.fi['gpx.width'], 'Leveys (mm)');
});

test('every mode can clear all its sheets', () => {
    for (const id of ['clearAllBtn', 'routeClearAll', 'atlasClearAll']) {
        assert.match(html, new RegExp(`id="${id}"[^>]*data-i18n="maps.clearAll"`), id);
    }
});

test('the route button looks pressed while its card is open', () => {
    const css = readFileSync(new URL('../../frontend/styles.css', import.meta.url), 'utf8');
    assert.match(css, /#routeToolBtn\[aria-expanded="true"\]\s*\{[^}]*background/);
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

test('the info button opens a modal dialog', () => {
    assert.match(html, /<button id="infoBtn"[^>]*aria-haspopup="dialog"[^>]*aria-controls="infoDialog"/);
    assert.match(html, /<dialog id="infoDialog"[^>]*aria-labelledby="infoTitle"/);
});

test('the info dialog closes through a dialog form and keeps its sections closed', () => {
    const dlg = html.slice(html.indexOf('<dialog id="infoDialog"'), html.indexOf('</dialog>'));
    assert.match(dlg, /<form method="dialog"/);
    const details = [...dlg.matchAll(/<details\b[^>]*>/g)].map(m => m[0]);
    assert.equal(details.length, 3);
    for (const d of details) assert.ok(!/\bopen\b/.test(d), d);
    for (const key of ['mode.maps', 'mode.route', 'mode.atlas', 'routeTool.button', 'info.intro']) {
        assert.ok(dlg.includes(`data-i18n="${key}"`), key);
    }
});

test('every grid block has magnetic north lines with their own spacing', () => {
    for (const p of ['', 'cover', 'atlas']) {
        const box = p ? `${p}Magnetic` : 'magnetic';
        const spacing = p ? `${p}MagneticSpacing` : 'magneticSpacing';
        assert.match(html, new RegExp(`<input id="${box}" type="checkbox"`), box);
        assert.match(html, new RegExp(`<select id="${spacing}"[^>]*>\\s*<option value="250">`), spacing);
    }
});
