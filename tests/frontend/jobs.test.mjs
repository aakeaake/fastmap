import { test } from 'node:test';
import assert from 'node:assert/strict';
import { errorDetail, JobError, pollDelay, runJob, stripPeriod } from '../../frontend/js/jobs.js';

const response = (status, body, blob, headers = {}) => ({
    ok: status >= 200 && status < 300,
    status,
    headers: { get: name => headers[name] ?? null },
    json: async () => { if (body === undefined) throw new SyntaxError('not JSON'); return body; },
    blob: async () => blob,
});

// fetch stand-in that answers each URL from a queue
function fakeFetch(routes) {
    const calls = [];
    const fetch = async (url, init) => {
        calls.push([url, init?.method ?? 'GET']);
        const queue = routes[url];
        assert.ok(queue?.length, `unexpected request ${url}`);
        return queue.length > 1 ? queue.shift() : queue[0];
    };
    return { fetch, calls };
}

test('pollDelay ramps 1 s, 2 s, then stays at 3 s', () => {
    assert.deepEqual([0, 1, 2, 3, 10].map(pollDelay), [1000, 2000, 3000, 3000, 3000]);
});

test('runJob submits, polls until done and fetches the file', async () => {
    const { fetch, calls } = fakeFetch({
        '/generate-map-async': [response(200, { job_id: 'j1' })],
        '/map-status/j1': [response(200, { status: 'pending' }),
            response(200, { status: 'done', download_url: '/map-download/j1', filename: 'a.pdf' })],
        '/map-download/j1': [response(200, {}, 'PDFBYTES')],
    });
    const waits = [];
    const result = await runJob('/generate-map-async', { scale: 1 }, { fetch, sleep: async ms => waits.push(ms) });
    assert.deepEqual(result, { blob: 'PDFBYTES', filename: 'a.pdf' });
    assert.deepEqual(waits, [1000, 2000]);
    assert.deepEqual(calls.map(c => c.join(' ')), [
        '/generate-map-async POST', '/map-status/j1 GET', '/map-status/j1 GET', '/map-download/j1 GET',
    ]);
});

test('runJob defaults the filename', async () => {
    const { fetch } = fakeFetch({
        '/x': [response(200, { job_id: 'j' })],
        '/map-status/j': [response(200, { status: 'done', download_url: '/d' })],
        '/d': [response(200, {}, 'b')],
    });
    const { filename } = await runJob('/x', {}, { fetch, sleep: async () => {} });
    assert.equal(filename, 'fastmap.pdf');
});

test('runJob reports the server detail when submitting fails', async () => {
    const { fetch } = fakeFetch({ '/x': [response(422, { detail: 'Alue on Suomen ulkopuolella' })] });
    await assert.rejects(runJob('/x', {}, { fetch, sleep: async () => {} }), /Alue on Suomen ulkopuolella/);
});

test('runJob reports a failed job', async () => {
    const { fetch } = fakeFetch({
        '/x': [response(200, { job_id: 'j' })],
        '/map-status/j': [response(200, { status: 'error', error: 'Tile fetch failed' })],
    });
    await assert.rejects(runJob('/x', {}, { fetch, sleep: async () => {} }), /Tile fetch failed/);
});

// Errors the app words itself carry a translation key; server text does not
async function caught(promise) {
    try { await promise; } catch (e) { return e; }
    throw new Error('did not reject');
}

test('runJob errors carry translation keys', async () => {
    const statusFail = fakeFetch({ '/x': [response(200, { job_id: 'j' })], '/map-status/j': [response(503)] });
    const e1 = await caught(runJob('/x', {}, { fetch: statusFail.fetch, sleep: async () => {} }));
    assert.ok(e1 instanceof JobError);
    assert.equal(e1.key, 'job.statusFailed');
    assert.deepEqual(e1.params, { status: 503 });

    const silentFail = fakeFetch({
        '/x': [response(200, { job_id: 'j' })],
        '/map-status/j': [response(200, { status: 'error' })],
    });
    assert.equal((await caught(runJob('/x', {}, { fetch: silentFail.fetch, sleep: async () => {} }))).key, 'job.failed');

    const serverDetail = fakeFetch({ '/x': [response(422, { detail: 'Alue on Suomen ulkopuolella' })] });
    assert.equal((await caught(runJob('/x', {}, { fetch: serverDetail.fetch, sleep: async () => {} }))).key, null);
});

test('errorDetail: string, structured and non-JSON bodies', async () => {
    assert.equal(await errorDetail(response(400, { detail: 'bad' })), 'bad');
    assert.equal(await errorDetail(response(422, { detail: [{ loc: ['scale'] }] })), '[{"loc":["scale"]}]');
    assert.equal(await errorDetail(response(502)), 'HTTP 502');
});

test('a busy server (503 + Retry-After) gives a translatable error', async () => {
    const busy = fakeFetch({
        '/x': [response(503, { detail: 'Palvelu on ruuhkautunut, yritä hetken kuluttua uudelleen.' },
            undefined, { 'Retry-After': '30' })],
    });
    const e = await caught(runJob('/x', {}, { fetch: busy.fetch, sleep: async () => {} }));
    assert.equal(e.key, 'job.busy');
});

test('a 503 without Retry-After keeps the server text', async () => {
    const config = fakeFetch({ '/x': [response(503, { detail: 'Server is missing MML_API_KEY configuration.' })] });
    const e = await caught(runJob('/x', {}, { fetch: config.fetch, sleep: async () => {} }));
    assert.equal(e.key, null);
    assert.equal(e.message, 'Server is missing MML_API_KEY configuration');
});

test('server messages lose their final full stop', async () => {
    assert.equal(stripPeriod('Alue on Suomen ulkopuolella.'), 'Alue on Suomen ulkopuolella');
    assert.equal(stripPeriod('Done...  '), 'Done');
    assert.equal(stripPeriod('No stop'), 'No stop');
    const failed = fakeFetch({
        '/x': [response(200, { job_id: 'j' })],
        '/map-status/j': [response(200, { status: 'error', error: 'Tile fetch failed.' })],
    });
    const e = await caught(runJob('/x', {}, { fetch: failed.fetch, sleep: async () => {} }));
    assert.equal(e.message, 'Tile fetch failed');
});
