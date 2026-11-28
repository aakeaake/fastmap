// The route: length, GPX export and saved data. Pure (no OpenLayers), so it
// runs in Node tests. A route is a list of lines; a line is a list of
// [x, y] points in EPSG:3067 metres.
import { COURSE_MAX_POINTS } from './course.js';
import { formatNumber } from './format.js';

export const ROUTE_KEY = 'fastmap.route.v1';

// Planar length in metres (EPSG:3067 is metric, exact enough for a hike)
export function routeLengthM(lines) {
    let m = 0;
    for (const line of lines) {
        for (let i = 1; i < line.length; i++) {
            m += Math.hypot(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1]);
        }
    }
    return m;
}

// A short fingerprint of the route (points rounded to the metre), so a set
// of sheets can tell whether the route changed since they were made
export function routeKey(lines) {
    const text = lines.map(line => line.map(p => `${Math.round(p[0])},${Math.round(p[1])}`).join(';')).join('|');
    let h = 0x811c9dc5;   // FNV-1a, 32 bit
    for (let i = 0; i < text.length; i++) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    return `${lines.length}-${h.toString(16)}`;
}

export function formatKm(m, locale) {
    return `${formatNumber(m / 1000, locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} km`;
}

const XML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };
const escapeXml = s => s.replace(/[&<>"']/g, c => XML_ESCAPES[c]);

const lonLat = (toLonLat, p) => {
    const [lon, lat] = toLonLat(p);
    return `lat="${lat.toFixed(6)}" lon="${lon.toFixed(6)}"`;
};

// Waypoints as <wpt>s, then the lines: one <rte> per line when `asRoute`
// (a course), else one <trk> named `name` with a <trkseg> per line.
// `toLonLat` turns an EPSG:3067 point into [lon, lat].
export function toGpx(name, lines, toLonLat, { asRoute = false, waypoints = [] } = {}) {
    const wpts = waypoints.map(w => (w.name
        ? `  <wpt ${lonLat(toLonLat, [w.x, w.y])}>\n    <name>${escapeXml(w.name)}</name>\n  </wpt>`
        : `  <wpt ${lonLat(toLonLat, [w.x, w.y])}/>`));
    let body;
    if (asRoute) {
        body = lines.map(line => [
            '  <rte>',
            `    <name>${escapeXml(name)}</name>`,
            ...line.map(p => `    <rtept ${lonLat(toLonLat, p)}/>`),
            '  </rte>',
        ].join('\n'));
    } else {
        const segs = lines.map(line => {
            const pts = line.map(p => `      <trkpt ${lonLat(toLonLat, p)}/>`);
            return `    <trkseg>\n${pts.join('\n')}\n    </trkseg>`;
        });
        body = ['  <trk>', `    <name>${escapeXml(name)}</name>`, ...segs, '  </trk>'];
    }
    return [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="FastMap" xmlns="http://www.topografix.com/GPX/1/1">',
        ...wpts,
        ...body,
        '</gpx>',
        '',
    ].join('\n');
}

export function serializeRoute({ name, lines, showOnPrint, source, waypoints }) {
    return { v: 1, name, lines, showOnPrint, source, waypoints };
}

const SOURCES = ['drawn', 'rte', 'wpt', 'trk'];
const MAX_WAYPOINTS = 500;

// Saved waypoints: each needs finite x, y; names up to 40 characters
function sanitizeWaypoints(list) {
    if (!Array.isArray(list)) return [];
    return list
        .filter(w => w && typeof w === 'object' && Number.isFinite(w.x) && Number.isFinite(w.y))
        .slice(0, MAX_WAYPOINTS)
        .map(w => ({ x: w.x, y: w.y, name: typeof w.name === 'string' ? w.name.slice(0, 40) : '' }));
}

const isPoint = p => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);

// Saved data back into a route, or null if it is not a usable route.
// A line with a bad point makes the whole route unusable; lines with fewer
// than two points are dropped.
export function sanitizeSavedRoute(data) {
    if (!data || typeof data !== 'object' || data.v !== 1 || !Array.isArray(data.lines)) return null;
    const lines = [];
    for (const line of data.lines) {
        if (!Array.isArray(line) || !line.every(isPoint)) return null;
        if (line.length >= 2) lines.push(line.map(p => [p[0], p[1]]));
    }
    if (!lines.length) return null;
    // Saved before routes knew their source: one short line was drawn
    const guess = lines.length === 1 && lines[0].length <= COURSE_MAX_POINTS ? 'drawn' : 'trk';
    return {
        name: typeof data.name === 'string' ? data.name : '',
        lines,
        showOnPrint: data.showOnPrint !== false,
        source: SOURCES.includes(data.source) ? data.source : guess,
        waypoints: sanitizeWaypoints(data.waypoints),
    };
}
