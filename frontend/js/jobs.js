// Async PDF jobs: submit, poll, fetch the file. No DOM; `fetch` and `sleep`
// can be injected for tests.

const defaultFetch = (...args) => globalThis.fetch(...args);
const defaultSleep = ms => new Promise(r => setTimeout(r, ms));

// Poll quickly at first (small maps finish in seconds), then back off
export function pollDelay(attempt) {
    return Math.min(1000 * (attempt + 1), 3000);
}

// Best error text from a failed response: FastAPI's `detail`, else the status
export async function errorDetail(resp) {
    try {
        const err = await resp.json();
        if (err.detail) return typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail);
    } catch { /* not JSON */ }
    return `HTTP ${resp.status}`;
}

// Submit a job, wait for it, download the result. Resolves to
// { blob, filename }; rejects with a user-facing message.
export async function runJob(url, body, { fetch = defaultFetch, sleep = defaultSleep } = {}) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await errorDetail(resp));
    const { job_id } = await resp.json();

    let result;
    for (let attempt = 0; ; attempt++) {
        await sleep(pollDelay(attempt));
        const sr = await fetch(`/map-status/${job_id}`);
        if (!sr.ok) throw new Error(`Tilan haku epäonnistui (HTTP ${sr.status})`);
        result = await sr.json();
        if (result.status === 'done') break;
        if (result.status === 'error') throw new Error(result.error || 'Luonti epäonnistui');
    }

    const dr = await fetch(result.download_url);
    if (!dr.ok) throw new Error(`Lataus epäonnistui (HTTP ${dr.status})`);
    return { blob: await dr.blob(), filename: result.filename || 'fastmap.pdf' };
}
