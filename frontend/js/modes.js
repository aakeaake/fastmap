// The three ways to make sheets (maps by hand, along a route, an atlas of an
// area) and the rules for each set: its print settings, whether they changed
// since its sheets were made, and reading saved layouts. Pure, so it runs in
// Node tests.
import { DEFAULTS, GRID_MODES, GRID_SPACINGS, LAYERS, MODES, ORIENTATIONS, PAPER_MM } from './constants.js';
import { ATLAS_OVERLAP_OPTIONS } from './atlas.js';
import { DEFAULT_OVERLAP, OVERLAP_OPTIONS } from './cover.js';
import { effectiveLayer } from './layer.js';
import { parseMargin, sanitizeMode, sanitizeSavedMap } from './saved.js';

export { MODES, sanitizeMode };

// Route orientation: best per sheet, or the same for every sheet
export const ROUTE_ORIENTATIONS = ['auto', 'same'];

const SET_FIELDS = ['paperSize', 'orientation', 'scale', 'layer', 'gridMode', 'gridSpacing', 'overlapPct'];
const orientationsOf = mode => (mode === 'route' ? ROUTE_ORIENTATIONS : ORIENTATIONS);
const overlapsOf = mode => (mode === 'route' ? OVERLAP_OPTIONS : ATLAS_OVERLAP_OPTIONS);

// The print settings a new route or atlas set starts with
export function defaultSetSettings(mode) {
    return {
        paperSize: DEFAULTS.paperSize,
        orientation: orientationsOf(mode)[0],
        scale: DEFAULTS.scale,
        layer: DEFAULTS.layer,
        gridMode: DEFAULTS.gridMode,
        gridSpacing: DEFAULTS.gridSpacing,
        overlapPct: DEFAULT_OVERLAP,
    };
}

// Saved or typed set settings, each bad field replaced by its default
export function sanitizeSetSettings(mode, data) {
    const d = defaultSetSettings(mode);
    if (!data || typeof data !== 'object') return d;
    const scale = Number.isFinite(data.scale) && data.scale >= 100 && data.scale <= 2000000 ? data.scale : d.scale;
    return {
        paperSize: PAPER_MM[data.paperSize] ? data.paperSize : d.paperSize,
        orientation: orientationsOf(mode).includes(data.orientation) ? data.orientation : d.orientation,
        scale,
        layer: effectiveLayer(LAYERS.includes(data.layer) ? data.layer : d.layer, scale),
        gridMode: GRID_MODES.includes(data.gridMode) ? data.gridMode : d.gridMode,
        gridSpacing: GRID_SPACINGS.includes(data.gridSpacing) ? data.gridSpacing : d.gridSpacing,
        overlapPct: overlapsOf(mode).includes(data.overlapPct) ? data.overlapPct : d.overlapPct,
    };
}

// Does the block differ from the settings the set's sheets were made with?
// (No sheets, nothing made: no change to report.)
export function settingsChanged(block, madeWith) {
    if (!madeWith) return false;
    return SET_FIELDS.some(k => block[k] !== madeWith[k]);
}

// Saved maps data -> { maps: [{ settings, coords }], activeIds, margin,
// madeWith, nextId }, or null when it is not a saved layout. Data saved
// before the modes existed loads as hand-placed maps.
export function readSavedLayout(data) {
    if (!data || typeof data !== 'object' || !Array.isArray(data.maps)) return null;
    const maps = data.maps.map(sanitizeSavedMap).filter(Boolean);
    const ids = data.activeIds && typeof data.activeIds === 'object' ? data.activeIds : { maps: data.activeId };
    const activeIds = {};
    for (const mode of MODES) {
        const id = ids[mode];
        activeIds[mode] = maps.some(m => m.settings.id === id && m.settings.mode === mode) ? id : null;
    }
    const selected = maps.find(m => m.settings.id === activeIds.maps);
    const margin = Number.isFinite(data.margin) ? parseMargin(data.margin)
        : selected ? selected.settings.margin : DEFAULTS.margin;
    const madeWith = {};
    for (const mode of ['route', 'atlas']) {
        madeWith[mode] = maps.some(m => m.settings.mode === mode)
            ? sanitizeSetSettings(mode, data.madeWith?.[mode]) : null;
    }
    return { maps, activeIds, margin, madeWith, nextId: Number.isFinite(data.nextId) ? data.nextId : null };
}
