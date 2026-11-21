// The list of maps and which one is selected in each mode. Each entry holds
// its settings plus its OpenLayers features: { id, mode, title, paperSize,
// orientation, scale, layer, margin, gridMode, gridSpacing, feature,
// labelFeature }. `mode` is the set it belongs to: 'maps' (placed by hand),
// 'route' or 'atlas'.
import { DEFAULTS, MODES } from './constants.js';
import { contentMeters, extentCenter, ring, ringCenter } from './geometry.js';
import { makeFeatures } from './map.js';
import { readSavedLayout } from './modes.js';

export const state = {
    maps: [],
    nextId: 1,
    mode: 'maps',                                       // the mode on screen
    activeIds: { maps: null, route: null, atlas: null }, // selected map per mode
    margin: DEFAULTS.margin,                            // one margin for all maps
    madeWith: { route: null, atlas: null },             // settings each set was made with
};

export const getEntry = id => state.maps.find(m => m.id === id);
// The current mode's selected map
export const active = () => getEntry(state.activeIds[state.mode]);
export const setActiveId = id => { state.activeIds[state.mode] = id; };
// The maps of a mode, in list order
export const modeMaps = (mode = state.mode) => state.maps.filter(m => m.mode === mode);
export const entryExtent = e => e.feature.getGeometry().getExtent();
export const entryCenter = e => extentCenter(entryExtent(e));

// Keep the label on the rectangle's top-right corner
export function syncLabel(e) {
    const [, , maxx, maxy] = entryExtent(e);
    e.labelFeature.getGeometry().setCoordinates([maxx, maxy]);
}

// Redraw the rectangle for the entry's settings, centred on `center`
export function placeEntry(e, center = entryCenter(e)) {
    const [w, h] = contentMeters(e);
    e.feature.getGeometry().setCoordinates([ring(center[0], center[1], w, h)]);
    syncLabel(e);
}

export function createEntry(center, settings = {}, coords = null) {
    const entry = { ...DEFAULTS, title: '', mode: 'maps', ...settings };
    // Keep a restored id (so undo brings back the same map), else allocate
    entry.id = Number.isInteger(settings.id) && settings.id > 0 && !getEntry(settings.id)
        ? settings.id : state.nextId++;
    state.nextId = Math.max(state.nextId, entry.id + 1);
    const [w, h] = contentMeters(entry);
    Object.assign(entry, makeFeatures(entry.id, coords ?? ring(center[0], center[1], w, h)));
    state.maps.push(entry);
    return entry;
}

// Everything, or with `mode` only that mode's maps (an undo snapshot of one set)
export function serialize({ mode } = {}) {
    return {
        nextId: state.nextId,
        margin: state.margin,
        activeIds: { ...state.activeIds },
        madeWith: { ...state.madeWith },
        maps: (mode ? modeMaps(mode) : state.maps).map(e => ({
            id: e.id,
            mode: e.mode,
            title: e.title,
            paperSize: e.paperSize,
            orientation: e.orientation,
            scale: e.scale,
            layer: e.layer,
            margin: e.margin,
            colorIdx: 0,   // kept for older saved data; there is one colour now
            gridMode: e.gridMode,
            gridSpacing: e.gridSpacing,
            coords: e.feature.getGeometry().getCoordinates()[0],
        })),
    };
}

// Rebuild maps from a serialize() snapshot; returns the entries created
// (empty when nothing in it was valid). With `mode`, only that mode's maps,
// selection and made-with settings are taken (undo of one set); otherwise
// the whole layout, including the margin.
export function restoreFrom(data, { mode } = {}) {
    const layout = readSavedLayout(data);
    if (!layout) return [];
    const created = [];
    for (const saved of layout.maps) {
        if (mode && saved.settings.mode !== mode) continue;
        // Rebuild the rectangle from its saved centre with the current
        // contentMeters(), rather than reusing the saved corners: maps
        // saved before a layout change (e.g. the PDF footer band) would
        // otherwise keep a size that no longer matches the print.
        created.push(createEntry(ringCenter(saved.coords), saved.settings));
    }
    for (const m of mode ? [mode] : MODES) {
        state.activeIds[m] = getEntry(layout.activeIds[m])?.mode === m ? layout.activeIds[m] : null;
        if (m !== 'maps') state.madeWith[m] = layout.madeWith[m];
    }
    if (!mode) state.margin = layout.margin;
    if (Number.isFinite(layout.nextId)) state.nextId = Math.max(state.nextId, layout.nextId, 1);
    return created;
}
