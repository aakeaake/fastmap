import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bboxOf, buildPayload, gpxRoutes, readRouteFeatures } from '../../frontend/js/payload.js';

// Minimal stand-ins for OpenLayers features
const feature = (type, coordinates, props = {}) => ({
    getGeometry: () => ({ getType: () => type, getCoordinates: () => coordinates }),
    get: k => props[k],
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
const auto = { dpi: '', zoomLevel: '', routes: [], gpxColor: '#ff00ff', gpxWidthMm: '1.1', gpxOpacity: '60' };

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
        { ...auto, dpi: '200', zoomLevel: '12', routes: [[[0, 0], [1, 1]]], gpxWidthMm: 'x', gpxOpacity: '35' });
    assert.equal(p.title, 'Nuuksio');
    assert.equal(p.dpi, 200);
    assert.equal(p.zoom_level, 12);
    assert.deepEqual(p.gpx_routes, [[[0, 0], [1, 1]]]);
    assert.equal(p.gpx_color, '#ff00ff');
    assert.equal(p.gpx_width, 3.12);   // non-numeric width falls back to 1.1 mm
    assert.equal(p.gpx_opacity, 0.35);
});

test('buildPayload sends the width in mm as points', () => {
    const p = buildPayload(entry, [0, 0, 1, 1], { ...auto, routes: [[[0, 0], [1, 1]]], gpxWidthMm: 2, gpxOpacity: 60 });
    assert.equal(p.gpx_width, 5.67);
    assert.equal(p.gpx_opacity, 0.6);
});

test('buildPayload leaves the route out when it is not to be printed', () => {
    const shared = { ...auto, routes: [[[1, 2], [3, 4]]], showRoute: false };
    const p = buildPayload(entry, [0, 0, 10, 10], shared);
    assert.equal('gpx_routes' in p, false);
    assert.equal('gpx_color' in p, false);
    assert.deepEqual(buildPayload(entry, [0, 0, 10, 10], { ...shared, showRoute: true }).gpx_routes, [[[1, 2], [3, 4]]]);
});

// --- Reading a GPX file: route, track, waypoints --------------------------------
const rte = feature('LineString', [[1, 1, 5], [2, 2, 5], [3, 3, 5]]);
const trk = feature('MultiLineString', [[[10, 10], [11, 11]]]);
const wpt = (x, y, name) => feature('Point', [x, y, 7], name === undefined ? {} : { name });

test('readRouteFeatures: a route with waypoints', () => {
    assert.deepEqual(readRouteFeatures([wpt(5, 6, ' Kota '), rte]), {
        source: 'rte', lines: [[[1, 1], [2, 2], [3, 3]]], waypoints: [{ x: 5, y: 6, name: 'Kota' }],
    });
});

test('readRouteFeatures: a track with a waypoint', () => {
    assert.deepEqual(readRouteFeatures([trk, wpt(5, 6, 'A')]), {
        source: 'trk', lines: [[[10, 10], [11, 11]]], waypoints: [{ x: 5, y: 6, name: 'A' }],
    });
});

test('readRouteFeatures: a route wins over a track', () => {
    const r = readRouteFeatures([trk, rte]);
    assert.equal(r.source, 'rte');
    assert.deepEqual(r.lines, [[[1, 1], [2, 2], [3, 3]]]);
});

test('readRouteFeatures: waypoints only become the line, in file order', () => {
    assert.deepEqual(readRouteFeatures([wpt(1, 2, 'a'), wpt(3, 4, 'b'), wpt(5, 6)]), {
        source: 'wpt', lines: [[[1, 2], [3, 4], [5, 6]]], waypoints: [],
    });
});

test('readRouteFeatures: one waypoint alone is no route', () => {
    assert.equal(readRouteFeatures([wpt(1, 2, 'a')]), null);
    assert.equal(readRouteFeatures([]), null);
});

test('readRouteFeatures: waypoint names are trimmed to 40, missing is empty, max 500', () => {
    const r = readRouteFeatures([rte, wpt(1, 2, 'x'.repeat(60)), wpt(3, 4)]);
    assert.deepEqual(r.waypoints, [{ x: 1, y: 2, name: 'x'.repeat(40) }, { x: 3, y: 4, name: '' }]);
    const many = Array.from({ length: 600 }, (_, i) => wpt(i, i, ''));
    assert.equal(readRouteFeatures([rte, ...many]).waypoints.length, 500);
});

test('buildPayload sends the look and waypoints with the route', () => {
    const p = buildPayload(entry, [0, 0, 1, 1],
        { ...auto, routes: [[[0, 0], [1, 1]]], look: 'course', waypoints: [{ x: 1, y: 2, name: 'A' }] });
    assert.equal(p.gpx_look, 'course');
    assert.deepEqual(p.gpx_waypoints, [{ x: 1, y: 2, name: 'A' }]);
    const plain = buildPayload(entry, [0, 0, 1, 1], { ...auto, routes: [[[0, 0], [1, 1]]] });
    assert.equal(plain.gpx_look, 'line');
    assert.equal('gpx_waypoints' in plain, false);
});
