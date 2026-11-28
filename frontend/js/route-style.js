// How the route prints (and shows on the map): show on printouts, colour,
// width in mm and opacity in %. Pure (no DOM or OpenLayers), so it runs in
// Node tests. Saved on its own, so it outlives the route it was set for.

export const ROUTE_STYLE_KEY = 'fastmap.routeStyle.v1';

// The width field. 0.4–7 mm is 1.13–19.8 pt, inside the API's 1–20 pt.
export const WIDTH_MM = { min: 0.4, max: 7, step: 0.1, def: 1.1 };   // 1.1 mm ≈ 3 pt

// A course is drawn thin, like orienteering course lines: 0.4 mm is 1.13 pt,
// the API's thinnest
export const COURSE_WIDTH_MM = WIDTH_MM.min;

// look: 'line', or 'course' (start triangle, numbered controls, finish) when
// the route can be one; see course.js. Each look keeps its own width.
export const DEFAULT_STYLE = {
    show: true, color: '#ff00ff', widthMm: WIDTH_MM.def, opacity: 60, look: 'line', courseWidthMm: COURSE_WIDTH_MM,
};

// The width (mm) the route is drawn with in `look`
export const lookWidthMm = (style, look) => (look === 'course' ? style.courseWidthMm : style.widthMm);

const OPACITY = { min: 10, max: 100 };
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// A typed width ("1,5" or "1.5") in mm, clamped and rounded to the field's
// 0.1 mm step; anything unreadable is the default
export function parseWidthMm(value) {
    const text = typeof value === 'number' ? null : String(value ?? '').trim().replace(',', '.');
    const n = text === null ? value : text === '' ? NaN : Number(text);
    if (!Number.isFinite(n)) return WIDTH_MM.def;
    return Math.round(clamp(n, WIDTH_MM.min, WIDTH_MM.max) * 10) / 10;
}

// Millimetres to PDF points (1 pt = 1/72 inch), 2 decimals
export const mmToPt = mm => Math.round((mm * 72 / 25.4) * 100) / 100;

// Saved data back into a style; each bad field takes its default. `show`
// falls back to `fallbackShow` (a 0.2.x route saved its show choice itself).
export function sanitizeRouteStyle(data, fallbackShow = true) {
    const d = data && typeof data === 'object' ? data : {};
    const opacity = Number(d.opacity);
    return {
        show: typeof d.show === 'boolean' ? d.show : fallbackShow,
        color: typeof d.color === 'string' && /^#[0-9a-f]{6}$/i.test(d.color) ? d.color.toLowerCase() : DEFAULT_STYLE.color,
        widthMm: parseWidthMm(typeof d.widthMm === 'number' ? d.widthMm : NaN),
        opacity: Number.isFinite(opacity) ? Math.round(clamp(opacity, OPACITY.min, OPACITY.max)) : DEFAULT_STYLE.opacity,
        look: d.look === 'course' ? 'course' : 'line',
        courseWidthMm: typeof d.courseWidthMm === 'number' && Number.isFinite(d.courseWidthMm)
            ? parseWidthMm(d.courseWidthMm) : COURSE_WIDTH_MM,
    };
}

// On-screen stroke: roughly follows the print width, kept visible and modest
export const screenWidthPx = mm => Math.min(14, Math.max(2, Math.round(mm * 3.6)));

// '#rrggbb' + opacity % -> 'rgba(r, g, b, a)'
export function rgba(hex, opacityPct) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${opacityPct / 100})`;
}
