import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fitColumns, indexLayout, moveInIndex, nudgeCenter, sheetLabel } from '../../frontend/js/sheet-index.js';

test('labels come from the title suffix', () => {
    assert.deepEqual(sheetLabel('Kilpisjärvi – Halti 3/25'), { n: 3 });
    assert.deepEqual(sheetLabel('Atlas B3'), { row: 1, col: 2, label: 'B3' });
    assert.deepEqual(sheetLabel('Kartasto AA12'), { row: 26, col: 11, label: 'AA12' });
    assert.deepEqual(sheetLabel('Long name cut… 12/25'), { n: 12 });
    for (const t of ['', 'Map 1', 'Nuuksio', 'Atlas b3', undefined]) assert.equal(sheetLabel(t), null, String(t));
});

test('route strip in walking order, gaps keep printed numbers', () => {
    const s = [5, 1, 2, 4].map(n => ({ id: n, title: `R ${n}/5` }));
    const L = indexLayout('route', s, { maxCols: 3 });
    assert.equal(L.kind, 'strip');
    assert.equal(L.cols, 3);
    assert.deepEqual(L.cells.map(c => [c.label, c.row, c.col]), [['1', 0, 0], ['2', 0, 1], ['4', 0, 2], ['5', 1, 0]]);
});

test('atlas grid keeps gaps and shrinks to the remaining labels', () => {
    const s = ['A2', 'A3', 'B2', 'C3'].map((l, i) => ({ id: i, title: `Atlas ${l}` }));
    const L = indexLayout('atlas', s, { maxCols: 8 });
    assert.equal(L.kind, 'grid');
    assert.equal(L.cols, 2);
    assert.deepEqual(L.cells.map(c => [c.label, c.row, c.col]), [['A2', 0, 0], ['A3', 0, 1], ['B2', 1, 0], ['C3', 2, 1]]);
});

test('a wide atlas falls back to a strip in reading order', () => {
    const s = Array.from({ length: 9 }, (_, i) => ({ id: i, title: `Atlas A${i + 1}` }));
    const L = indexLayout('atlas', s, { maxCols: 8 });
    assert.equal(L.kind, 'strip');
    assert.deepEqual(L.cells.at(-1), { id: 8, label: 'A9', row: 1, col: 0 });
});

test('sheets without a label go last in a strip', () => {
    const L = indexLayout('route', [{ id: 1, title: 'R 2/3' }, { id: 2, title: 'odd' }], { maxCols: 8 });
    assert.deepEqual(L.cells.map(c => [c.id, c.label]), [[1, '2'], [2, '2']]);
});

test('moving skips gaps and stops at edges', () => {
    const s = ['A1', 'A3', 'B1', 'B2', 'B3'].map(l => ({ id: l, title: `Atlas ${l}` }));
    const L = indexLayout('atlas', s, { maxCols: 8 });
    assert.equal(moveInIndex(L, 'A1', 'ArrowRight'), 'A3');   // A2 is a gap
    assert.equal(moveInIndex(L, 'A3', 'ArrowRight'), 'A3');
    assert.equal(moveInIndex(L, 'B2', 'ArrowUp'), 'A1');      // A2 gap: the nearest above
    assert.equal(moveInIndex(L, 'A1', 'ArrowDown'), 'B1');
    assert.equal(moveInIndex(L, 'B2', 'End'), 'B3');
    assert.equal(moveInIndex(L, 'B2', 'Home'), 'A1');
    const R = indexLayout('route', [1, 2, 3, 4, 5].map(n => ({ id: n, title: `R ${n}/5` })), { maxCols: 2 });
    assert.equal(moveInIndex(R, 1, 'ArrowDown'), 3);
    assert.equal(moveInIndex(R, 5, 'ArrowDown'), 5);
    assert.equal(moveInIndex(R, 2, 'ArrowRight'), 3);
    assert.equal(moveInIndex(R, 99, 'ArrowRight'), 1);        // unknown id: the first sheet
});

test('new maps are nudged off each other', () => {
    assert.deepEqual(nudgeCenter([0, 0], [], [4000, 3000]), [0, 0]);
    assert.deepEqual(nudgeCenter([0, 0], [[0, 0]], [4000, 3000]), [1000, -750]);
    assert.deepEqual(nudgeCenter([0, 0], [[0, 0], [1000, -750]], [4000, 3000]), [2000, -1500]);
    assert.deepEqual(nudgeCenter([0, 0], [[5, 5]], [4000, 3000]), [0, 0]);   // 7 m away: free
});

test('a cell alone in its row and column is still reachable by arrows', () => {
    const L = indexLayout('atlas', ['A1', 'B2', 'C3'].map(l => ({ id: l, title: `Atlas ${l}` })), { maxCols: 8 });
    assert.equal(moveInIndex(L, 'A1', 'ArrowDown'), 'B2');
    assert.equal(moveInIndex(L, 'A1', 'ArrowRight'), 'B2');
    assert.equal(moveInIndex(L, 'C3', 'ArrowUp'), 'B2');
    assert.equal(moveInIndex(L, 'C3', 'ArrowLeft'), 'B2');
    assert.equal(moveInIndex(L, 'C3', 'ArrowDown'), 'C3');   // nothing below
});

test('the index shows as many columns as fit', () => {
    assert.equal(fitColumns(246, 30, 4), 7);    // desktop panel with a scrollbar
    assert.equal(fitColumns(256, 30, 4), 7);
    assert.equal(fitColumns(270, 30, 4), 8);
    assert.equal(fitColumns(328, 44, 4), 6);    // 360 px phone
    assert.equal(fitColumns(343, 44, 4), 7);    // 375 px phone
    assert.equal(fitColumns(0, 30, 4), 1);      // not laid out yet
});
