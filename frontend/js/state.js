// The list of maps and which one is selected. Each entry holds its settings
// plus its OpenLayers features: { id, title, paperSize, orientation, scale,
// layer, margin, gridMode, gridSpacing, feature, labelFeature }.
import { DEFAULTS } from './constants.js';
import { contentMeters, extentCenter, ring, ringCenter } from './geometry.js';
import { makeFeatures } from './map.js';
import { sanitizeSavedMap } from './saved.js';

export const state = { maps: [], activeId: null, nextId: 1 };

export const getEntry = id => state.maps.find(m => m.id === id);
export const active = () => getEntry(state.activeId);
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
    const entry = { ...DEFAULTS, title: '', ...settings };
    // Keep a restored id (so undo brings back the same map), else allocate
    entry.id = Number.isInteger(settings.id) && settings.id > 0 && !getEntry(settings.id)
        ? settings.id : state.nextId++;
    state.nextId = Math.max(state.nextId, entry.id + 1);
    const [w, h] = contentMeters(entry);
    Object.assign(entry, makeFeatures(entry.id, coords ?? ring(center[0], center[1], w, h)));
    state.maps.push(entry);
    return entry;
}

export function serialize() {
    return {
        nextId: state.nextId,
        activeId: state.activeId,
        maps: state.maps.map(e => ({
            id: e.id,
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
// (empty when nothing in it was valid).
export function restoreFrom(data) {
    if (!data || !Array.isArray(data.maps)) return [];
    const created = [];
    for (const m of data.maps) {
        const saved = sanitizeSavedMap(m);
        // Rebuild the rectangle from its saved centre with the current
        // contentMeters(), rather than reusing the saved corners: maps
        // saved before a layout change (e.g. the PDF footer band) would
        // otherwise keep a size that no longer matches the print.
        if (saved) created.push(createEntry(ringCenter(saved.coords), saved.settings));
    }
    if (created.length && Number.isFinite(data.nextId)) {
        state.nextId = Math.max(state.nextId, data.nextId, 1);
    }
    return created;
}
