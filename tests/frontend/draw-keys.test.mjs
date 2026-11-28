import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drawKeysIgnored } from '../../frontend/js/draw-keys.js';

// Element stand-ins: closest() answers for an open dialog around them
const el = (tagName, { inDialog = false, isContentEditable = false } = {}) => ({
    tagName, isContentEditable, closest: sel => (sel === 'dialog[open]' && inDialog ? {} : null),
});

test('drawing keys are left alone while typing in a field', () => {
    for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) assert.equal(drawKeysIgnored(el(tag)), true, tag);
    assert.equal(drawKeysIgnored(el('DIV', { isContentEditable: true })), true);
});

test('drawing keys are left alone inside an open dialog (the info popup)', () => {
    assert.equal(drawKeysIgnored(el('BUTTON', { inDialog: true })), true);
    assert.equal(drawKeysIgnored(el('SUMMARY', { inDialog: true })), true);
});

test('drawing keys work on the map and its buttons', () => {
    assert.equal(drawKeysIgnored(el('DIV')), false);
    assert.equal(drawKeysIgnored(el('BUTTON')), false);
    assert.equal(drawKeysIgnored(null), false);
});
