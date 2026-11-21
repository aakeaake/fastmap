import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatNumber } from '../../frontend/js/format.js';

const NBSP = ' ';

test('thousands are grouped with a no-break space in every language', () => {
    assert.equal(formatNumber(20000, 'en-GB'), `20${NBSP}000`);
    assert.equal(formatNumber(20000, 'fi-FI'), `20${NBSP}000`);
    assert.equal(formatNumber(1234567, 'en-GB'), `1${NBSP}234${NBSP}567`);
    assert.equal(formatNumber(999, 'en-GB'), '999');
});

test('the decimal mark still follows the language', () => {
    const opts = { minimumFractionDigits: 1, maximumFractionDigits: 1 };
    assert.equal(formatNumber(1234.5, 'en-GB', opts), `1${NBSP}234.5`);
    assert.equal(formatNumber(1234.5, 'fi-FI', opts), `1${NBSP}234,5`);
});
