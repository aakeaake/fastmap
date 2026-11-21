// Validation of saved / undo snapshot data and of form input. Pure.
import {
    DEFAULTS, GRID_MODES, GRID_SPACINGS, LAYERS, MARGIN_MAX_MM, ORIENTATIONS, PAPER_MM,
} from './constants.js';
import { effectiveLayer } from './layer.js';

// Margin in mm from any input: non-numbers fall back to the default,
// numbers are clamped to 0..MARGIN_MAX_MM.
export function parseMargin(value) {
    const m = typeof value === 'number' ? value : parseFloat(value);
    if (!Number.isFinite(m)) return DEFAULTS.margin;
    return Math.min(Math.max(m, 0), MARGIN_MAX_MM);
}

function isRing(c) {
    return Array.isArray(c) && c.length === 5 && c.every(
        p => Array.isArray(p) && p.length === 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]));
}

// One saved map -> { settings, coords }, or null when it cannot be trusted.
// Optional fields fall back to defaults; required ones reject the map.
export function sanitizeSavedMap(m) {
    if (!m || typeof m !== 'object') return null;
    if (!isRing(m.coords)) return null;
    if (!PAPER_MM[m.paperSize] || !ORIENTATIONS.includes(m.orientation)) return null;
    if (!LAYERS.includes(m.layer)) return null;
    if (!Number.isFinite(m.scale) || m.scale < 100 || m.scale > 2000000) return null;
    return {
        settings: {
            ...(Number.isInteger(m.id) && m.id > 0 ? { id: m.id } : {}),
            title: typeof m.title === 'string' ? m.title : '',
            paperSize: m.paperSize,
            orientation: m.orientation,
            scale: m.scale,
            layer: effectiveLayer(m.layer, m.scale),
            margin: Number.isFinite(m.margin) ? parseMargin(m.margin) : DEFAULTS.margin,
            gridMode: GRID_MODES.includes(m.gridMode) ? m.gridMode : 'off',
            gridSpacing: GRID_SPACINGS.includes(m.gridSpacing) ? m.gridSpacing : 1000,
        },
        coords: m.coords,
    };
}
