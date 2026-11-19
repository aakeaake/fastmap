import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sheetHeights, snapTarget } from '../../frontend/js/sheet-math.js';

// 812 px tall phone, 70 px header + 65 px download footer
const hs = sheetHeights(812, 70, 65);

test('sheetHeights: peek fits header and footer, full leaves a map strip', () => {
    assert.deepEqual(hs, { peek: 135, half: 406, full: 740 });
});

test('sheetHeights never goes below peek on a tiny screen', () => {
    assert.deepEqual(sheetHeights(200, 70, 65), { peek: 135, half: 135, full: 135 });
});

test('a slow release snaps to the nearest height', () => {
    assert.equal(snapTarget(hs, 150, 0), 'peek');
    assert.equal(snapTarget(hs, 435, -0.2), 'half');
    assert.equal(snapTarget(hs, 700, 0.3), 'full');
});

test('a flick moves one step in its direction', () => {
    assert.equal(snapTarget(hs, 300, -0.8), 'half');   // up from between peek and half
    assert.equal(snapTarget(hs, 435, -0.8), 'full');   // up past half
    assert.equal(snapTarget(hs, 406, 0.8), 'peek');    // down from half
    assert.equal(snapTarget(hs, 740, -0.8), 'full');   // already at the top
    assert.equal(snapTarget(hs, 135, 0.8), 'peek');    // already at the bottom
});
