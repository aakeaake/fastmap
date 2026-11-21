// Cover a route with print sheets: walk along the route and place north-up
// sheets one by one, in walking order. Pure (no DOM or OpenLayers), so it
// runs in Node tests. Points are [x, y] in EPSG:3067 metres.
import { contentMeters } from './geometry.js';

export const OVERLAP_OPTIONS = [5, 10, 20];
export const DEFAULT_OVERLAP = 10;
export const MAX_BATCH = 25;   // the server's batch limit (BatchMapRequest)

const TITLE_MAX = 120;         // the server's title limit
const CLEARANCE_MM = 10;       // route kept this far from the sheet edges, on paper
const REVISIT = 0.25;          // share of a sheet's shorter inner side that counts as a revisit
const DENSIFY = 20;            // points per shorter inner side
const EPS = 1e-6;
const ORIENTATIONS = ['portrait', 'landscape'];

// Points at most `step` apart, with their distance along the line
function densify(line, step) {
    const P = [line[0]];
    const S = [0];
    for (let i = 1; i < line.length; i++) {
        const [a, b] = [line[i - 1], line[i]];
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len === 0) continue;
        const n = Math.ceil(len / step);
        const s0 = S[S.length - 1];
        for (let k = 1; k <= n; k++) {
            const t = k / n;
            P.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
            S.push(s0 + len * t);
        }
    }
    return { P, S };
}

// Sheets as [{ center, orientation }] covering every line of the route.
// `sizes` = { portrait: [w, h], landscape: [w, h] } map area on the ground;
// the route stays `clearanceM` inside the edges; consecutive sheets share at
// least `overlapM` of route.
export function coverRoute(lines, { sizes, clearanceM, overlapM, orientation = 'auto' }) {
    const candidates = ORIENTATIONS.includes(orientation) ? [orientation] : ORIENTATIONS;
    const shortest = Math.min(...candidates.flatMap(o => sizes[o]));
    const c = Math.max(0, Math.min(clearanceM, shortest / 4));
    const inner = o => [sizes[o][0] - 2 * c, sizes[o][1] - 2 * c];
    const step = Math.min(...candidates.map(o => Math.min(...inner(o)))) / DENSIFY;
    const inside = (sheet, p) => {
        const [w, h] = inner(sheet.orientation);
        return Math.abs(p[0] - sheet.center[0]) <= w / 2 + EPS
            && Math.abs(p[1] - sheet.center[1]) <= h / 2 + EPS;
    };

    const sheets = [];
    for (const line of lines) {
        if (!line.length) continue;
        const { P, S } = densify(line, step);
        const last = P.length - 1;
        // Last point at or before distance `s` (searching from `from`), so a
        // handover never shares less route than asked
        const startAt = (from, s) => {
            let k = from;
            while (k < last && S[k + 1] <= s + EPS) k++;
            return k;
        };
        let i = 0;
        let from = null;   // the sheet the walk hands over from
        lineLoop: for (;;) {
            // A real revisit of an earlier sheet: skip the stretch it already holds
            let best = null;
            for (const sheet of sheets) {
                if (sheet === from || !inside(sheet, P[i])) continue;
                let j = i;
                while (j < last && inside(sheet, P[j + 1])) j++;
                if (!best || S[j] > S[best.j]) best = { sheet, j };
            }
            if (best) {
                const { sheet, j } = best;
                if (j === last) break;
                const long = S[j] - S[i] >= REVISIT * Math.min(...inner(sheet.orientation));
                const next = startAt(i, S[j] - overlapM);
                if (long && next > i) {
                    i = next;
                    from = sheet;
                    continue;
                }
            }

            // Place a sheet that reaches as far along the route as possible
            // A tie keeps the orientation of the sheet before, else portrait
            const order = from && candidates.includes(from.orientation)
                ? [from.orientation, ...candidates.filter(o => o !== from.orientation)] : candidates;
            let pick = null;
            for (const o of order) {
                const [w, h] = inner(o);
                let [minx, miny, maxx, maxy] = [P[i][0], P[i][1], P[i][0], P[i][1]];
                let r = i;
                while (r < last) {
                    const [x, y] = P[r + 1];
                    const nx = [Math.min(minx, x), Math.min(miny, y), Math.max(maxx, x), Math.max(maxy, y)];
                    if (nx[2] - nx[0] > w + EPS || nx[3] - nx[1] > h + EPS) break;
                    [minx, miny, maxx, maxy] = nx;
                    r++;
                }
                if (!pick || r > pick.r) pick = { o, r, box: [minx, miny, maxx, maxy] };
            }
            const [minx, miny, maxx, maxy] = pick.box;
            const sheet = { center: [(minx + maxx) / 2, (miny + maxy) / 2], orientation: pick.o };
            sheets.push(sheet);
            if (pick.r === last) break lineLoop;
            const next = startAt(i, S[pick.r] - overlapM);
            i = next > i ? next : i + 1;
            from = sheet;
        }
    }
    return sheets;
}

// Paper settings -> ground metres for coverRoute()
export function coverParams({ paperSize, scale, margin, overlapPct }) {
    const sizes = Object.fromEntries(ORIENTATIONS.map(o =>
        [o, contentMeters({ paperSize, orientation: o, margin, scale })]));
    const shorter = Math.min(...sizes.portrait, ...sizes.landscape);
    return { sizes, clearanceM: CLEARANCE_MM / 1000 * scale, overlapM: overlapPct / 100 * shorter };
}

// The sheets for the route block's settings. `orientation` 'auto' picks the
// best orientation per sheet; 'same' gives every sheet the orientation that
// needs fewer sheets (a tie goes to portrait).
export function planCover(lines, { paperSize, scale, margin, overlapPct, orientation = 'auto' }) {
    const params = coverParams({ paperSize, scale, margin, overlapPct });
    if (orientation !== 'same') return coverRoute(lines, params);
    const [p, l] = ORIENTATIONS.map(o => coverRoute(lines, { ...params, orientation: o }));
    return l.length < p.length ? l : p;
}

// `name` + `suffix`, the name cut with "…" so the title fits the server's limit
export function fitTitle(name, suffix) {
    if (name.length + suffix.length <= TITLE_MAX) return `${name}${suffix}`;
    return `${name.slice(0, TITLE_MAX - suffix.length - 1)}…${suffix}`;
}

// "<name> i/n"
export const coverTitle = (name, i, n) => fitTitle(name, ` ${i}/${n}`);
