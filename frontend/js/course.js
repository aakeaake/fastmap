// Orienteering course geometry, the same rules as the PDF's
// src/fastmap/services/course_geometry.py. Pure (no OpenLayers), so it runs
// in Node tests. Points are [x, y] in any one unit (map units on screen).

// A course is one line of at most this many points (the API checks it too)
export const COURSE_MAX_POINTS = 100;

// Symbol sizes on screen in px; they stay the same at every zoom
export const SCREEN = { controlD: 22, startSide: 26, finishD: [18, 26], gap: 1, numberPx: 14, namePx: 12, dotMin: 3 };

const unit = (dx, dy) => {
    const n = Math.hypot(dx, dy);
    return n > 1e-12 ? [dx / n, dy / n] : [0, 0];
};

// The leg a→b with ra cut from its start and rb from its end; null when
// nothing is left
export function shortenLeg(a, b, ra, rb) {
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (d <= ra + rb) return null;
    const ux = (b[0] - a[0]) / d;
    const uy = (b[1] - a[1]) / d;
    return [[a[0] + ux * ra, a[1] + uy * ra], [b[0] - ux * rb, b[1] - uy * rb]];
}

// Legs between consecutive points, each end stopped at its symbol + gap
export function courseLegs(points, { start, control, finish, gap }) {
    const last = points.length - 1;
    const radius = i => (i === 0 ? start : i === last ? finish : control) + gap;
    const legs = [];
    for (let i = 0; i < last; i++) {
        const leg = shortenLeg(points[i], points[i + 1], radius(i), radius(i + 1));
        if (leg) legs.push(leg);
    }
    return legs;
}

// Unit vector from p away from both of its legs (where its number goes)
export function numberDirection(prev, p, next) {
    const a = unit(prev[0] - p[0], prev[1] - p[1]);
    const b = unit(next[0] - p[0], next[1] - p[1]);
    const ux = a[0] + b[0];
    const uy = a[1] + b[1];
    if (Math.hypot(ux, uy) < 1e-9) {
        const [tx, ty] = unit(next[0] - prev[0], next[1] - prev[1]);
        if (tx === 0 && ty === 0) return [0, 1];
        return [-ty, tx];   // left of the direction of travel
    }
    return unit(-ux, -uy);
}

// Equilateral triangle centred on p, its first corner pointing at `toward`
export function startTriangle(p, toward, side) {
    const r = side / Math.sqrt(3);
    const dx = toward[0] - p[0];
    const dy = toward[1] - p[1];
    const theta = Math.hypot(dx, dy) > 1e-12 ? Math.atan2(dy, dx) : Math.PI / 2;
    return [0, 120, -120].map(k => {
        const a = theta + (k * Math.PI) / 180;
        return [p[0] + r * Math.cos(a), p[1] + r * Math.sin(a)];
    });
}

// Can this route ({ source, lines }) be drawn as a course?
export function courseable({ source, lines }) {
    return source !== 'trk' && lines.length === 1
        && lines[0].length >= 2 && lines[0].length <= COURSE_MAX_POINTS;
}

// The look the route is drawn with: the chosen one, or line when it cannot
// be a course
export const effectiveLook = (look, route) => (look === 'course' && courseable(route) ? 'course' : 'line');
