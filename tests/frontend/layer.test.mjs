import { test } from 'node:test';
import assert from 'node:assert/strict';
import { effectiveLayer } from '../../frontend/js/layer.js';

test('vector layer at an unsupported scale falls back to raster', () => {
    assert.equal(effectiveLayer('maastokartta_vektori', 20000), 'maastokartta');
});

test('vector layer at 25 000 and 50 000 is unchanged', () => {
    assert.equal(effectiveLayer('maastokartta_vektori', 25000), 'maastokartta_vektori');
    assert.equal(effectiveLayer('maastokartta_vektori', 50000), 'maastokartta_vektori');
});

test('other layers are unchanged at any scale', () => {
    assert.equal(effectiveLayer('maastokartta', 20000), 'maastokartta');
    assert.equal(effectiveLayer('ortokuva', 15000), 'ortokuva');
});
