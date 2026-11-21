// The atlas area: its size and saved data. Pure (no OpenLayers), so it runs
// in Node tests. An area is one ring of [x, y] points in EPSG:3067 metres,
// not closed (the first point is not repeated at the end).
import { formatNumber } from './format.js';

export const AREA_KEY = 'fastmap.area.v1';

const NAME_MAX = 100;

// Absolute area in square metres (shoelace formula)
export function ringAreaM2(ring) {
    let twice = 0;
    for (let i = 0; i < ring.length; i++) {
        const [x1, y1] = ring[i];
        const [x2, y2] = ring[(i + 1) % ring.length];
        twice += x1 * y2 - x2 * y1;
    }
    return Math.abs(twice) / 2;
}

// "12.3 km²" under 100 km², "412 km²" from 100 up
export function formatKm2(m2, locale) {
    const km2 = m2 / 1e6;
    const digits = km2 < 100 ? 1 : 0;
    return `${formatNumber(km2, locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })} km²`;
}

export function serializeArea({ name, ring }) {
    return { v: 1, name, ring };
}

const isPoint = p => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);

// Saved data back into an area, or null if it is not a usable area
export function sanitizeSavedArea(data) {
    if (!data || typeof data !== 'object' || data.v !== 1 || !Array.isArray(data.ring)) return null;
    if (!data.ring.every(isPoint)) return null;
    const ring = data.ring.map(p => [p[0], p[1]]);
    const [first, last] = [ring[0], ring[ring.length - 1]];
    if (ring.length > 1 && first[0] === last[0] && first[1] === last[1]) ring.pop();
    if (ring.length < 3) return null;
    return {
        name: typeof data.name === 'string' ? data.name.slice(0, NAME_MAX) : '',
        ring,
    };
}
