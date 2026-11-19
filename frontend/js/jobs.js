// Async PDF jobs: submit, poll, fetch the file. No DOM; `fetch` and `sleep`
// can be injected for tests.

const defaultFetch = (...args) => globalThis.fetch(...args);
const defaultSleep = ms => new Promise(r => setTimeout(r, ms));

// A failure the UI can translate: `key` and `params` name a string in
// strings.js. Server-provided text (FastAPI `detail`, a job's error) is
// passed through as is, with no key.
export class JobError extends Error {
    constructor(message, key = null, params = {}) {
        super(message);
        this.name = 'JobError';
        this.key = key;
        this.params = params;
    }
}

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
// { blob, filename }; rejects with a JobError.
export async function runJob(url, body, { fetch = defaultFetch, sleep = defaultSleep } = {}) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!resp.ok) throw new JobError(await errorDetail(resp));
    const { job_id } = await resp.json();

    let result;
    for (let attempt = 0; ; attempt++) {
        await sleep(pollDelay(attempt));
        const sr = await fetch(`/map-status/${job_id}`);
        if (!sr.ok) {
            throw new JobError(`Checking the status failed (HTTP ${sr.status})`, 'job.statusFailed', { status: sr.status });
        }
        result = await sr.json();
        if (result.status === 'done') break;
        if (result.status === 'error') {
            throw result.error
                ? new JobError(result.error)
                : new JobError('Creating the file failed', 'job.failed');
        }
    }

    const dr = await fetch(result.download_url);
    if (!dr.ok) throw new JobError(`Downloading failed (HTTP ${dr.status})`, 'job.fetchFailed', { status: dr.status });
    return { blob: await dr.blob(), filename: result.filename || 'fastmap.pdf' };
}
