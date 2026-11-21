// The route: length, GPX export and saved data. Pure (no OpenLayers), so it
// runs in Node tests. A route is a list of lines; a line is a list of
// [x, y] points in EPSG:3067 metres.

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

export function formatKm(m, locale) {
    const n = new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    return `${n.format(m / 1000)} km`;
}

const XML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' };
const escapeXml = s => s.replace(/[&<>"']/g, c => XML_ESCAPES[c]);

// One <trk> named `name`, one <trkseg> per line. `toLonLat` turns an
// EPSG:3067 point into [lon, lat].
export function toGpx(name, lines, toLonLat) {
    const segs = lines.map(line => {
        const pts = line.map(p => {
            const [lon, lat] = toLonLat(p);
            return `      <trkpt lat="${lat.toFixed(6)}" lon="${lon.toFixed(6)}"/>`;
        });
        return `    <trkseg>\n${pts.join('\n')}\n    </trkseg>`;
    });
    return [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="FastMap" xmlns="http://www.topografix.com/GPX/1/1">',
        '  <trk>',
        `    <name>${escapeXml(name)}</name>`,
        ...segs,
        '  </trk>',
        '</gpx>',
        '',
    ].join('\n');
}

export function serializeRoute({ name, lines, showOnPrint }) {
    return { v: 1, name, lines, showOnPrint };
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
    return {
        name: typeof data.name === 'string' ? data.name : '',
        lines,
        showOnPrint: data.showOnPrint !== false,
    };
}
