import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bboxOf, buildPayload, gpxRoutes } from '../../frontend/js/payload.js';

// Minimal stand-ins for OpenLayers features
const feature = (type, coordinates) => ({
    getGeometry: () => ({ getType: () => type, getCoordinates: () => coordinates }),
});

test('gpxRoutes keeps lines, drops waypoints, strips elevation and time', () => {
    const routes = gpxRoutes([
        feature('Point', [1, 2, 30]),
        feature('LineString', [[1, 2, 30, 1700000000], [3, 4, 31, 1700000060]]),
        feature('MultiLineString', [[[5, 6], [7, 8]], [[9, 10]]]),   // 2nd segment too short
        { getGeometry: () => null },
    ]);
    assert.deepEqual(routes, [[[1, 2], [3, 4]], [[5, 6], [7, 8]]]);
});

const entry = {
    title: '', scale: 20000, paperSize: 'A4', orientation: 'portrait', layer: 'maastokartta',
    margin: 7, gridMode: 'off', gridSpacing: 1000,
};
const auto = { dpi: '', zoomLevel: '', routes: [], gpxColor: '#ff00ff', gpxWidth: '5', gpxOpacity: '60' };

test('bboxOf', () => {
    assert.deepEqual(bboxOf([1, 2, 3, 4]), { minx: 1, miny: 2, maxx: 3, maxy: 4 });
});

test('buildPayload: automatic settings send only the map', () => {
    assert.deepEqual(buildPayload(entry, [0, 0, 10, 20], auto), {
        bbox: { minx: 0, miny: 0, maxx: 10, maxy: 20 },
        scale: 20000, paper_size: 'A4', orientation: 'portrait', layer: 'maastokartta',
        margin_mm: 7, grid_mode: 'off', grid_spacing_m: 1000,
    });
});

test('buildPayload: title, precision and GPX style when set', () => {
    const p = buildPayload({ ...entry, title: 'Nuuksio' }, [0, 0, 1, 1],
        { ...auto, dpi: '200', zoomLevel: '12', routes: [[[0, 0], [1, 1]]], gpxWidth: 'x', gpxOpacity: '35' });
    assert.equal(p.title, 'Nuuksio');
    assert.equal(p.dpi, 200);
    assert.equal(p.zoom_level, 12);
    assert.deepEqual(p.gpx_routes, [[[0, 0], [1, 1]]]);
    assert.equal(p.gpx_color, '#ff00ff');
    assert.equal(p.gpx_width, 5);   // non-numeric width falls back to 5
    assert.equal(p.gpx_opacity, 0.35);
});
