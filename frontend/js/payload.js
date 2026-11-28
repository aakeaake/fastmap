// Request bodies for the PDF endpoints. Pure: features are duck-typed
// (anything with getGeometry() whose geometry has getType/getCoordinates).
import { mmToPt, parseWidthMm } from './route-style.js';

export function bboxOf([minx, miny, maxx, maxy]) {
    return { minx, miny, maxx, maxy };
}

// GPX tracks (<trk>) read as MultiLineString (one line per <trkseg>),
// routes (<rte>) as LineString; waypoints are Points and are skipped.
// Points carry [x, y, elevation, time] - send x, y only.
export function gpxRoutes(features) {
    const lines = [];
    for (const f of features) {
        const g = f.getGeometry();
        if (!g) continue;
        const type = g.getType();
        if (type === 'LineString') lines.push(g.getCoordinates());
        else if (type === 'MultiLineString') lines.push(...g.getCoordinates());
    }
    return lines
        .map(line => line.map(p => [p[0], p[1]]))
        .filter(line => line.length >= 2);
}

const MAX_WAYPOINTS = 500;
const NAME_MAX = 40;
const typeOf = f => f.getGeometry()?.getType();

// What a GPX file holds, as the route: { source, lines, waypoints }, or null
// when there is no route. Routes (<rte>) win over tracks (<trk>); a file with
// waypoints only makes them the line, in file order. Waypoints beside a route
// or track keep their names (trimmed to 40 characters, at most 500).
export function readRouteFeatures(features) {
    const routes = features.filter(f => typeOf(f) === 'LineString');
    const tracks = features.filter(f => typeOf(f) === 'MultiLineString');
    const points = features.filter(f => typeOf(f) === 'Point');
    const xy = f => f.getGeometry().getCoordinates().slice(0, 2);
    if (!routes.length && !tracks.length) {
        if (points.length < 2) return null;
        return { source: 'wpt', lines: [points.map(xy)], waypoints: [] };
    }
    const source = routes.length ? 'rte' : 'trk';
    const lines = gpxRoutes(routes.length ? routes : tracks);
    if (!lines.length) return null;
    const waypoints = points.slice(0, MAX_WAYPOINTS).map(f => {
        const [x, y] = xy(f);
        const name = f.get('name');
        return { x, y, name: typeof name === 'string' ? name.trim().slice(0, NAME_MAX) : '' };
    });
    return { source, lines, waypoints };
}

// One map's request body.
// `shared` holds the settings common to all maps, as read from the form:
//   { dpi, zoomLevel, routes, showRoute, gpxColor, gpxWidthMm, gpxOpacity,
//     look, waypoints }
// look is the look the route is drawn with ('line' when it cannot be a course).
// showRoute false leaves the route off the printout.
// dpi / zoomLevel are '' for automatic; gpxWidthMm is the width in mm and
// gpxOpacity a percent (numbers or strings). The API takes points.
export function buildPayload(entry, extent, shared) {
    const payload = {
        bbox: bboxOf(extent),
        scale: entry.scale,
        paper_size: entry.paperSize,
        orientation: entry.orientation,
        layer: entry.layer,
        margin_mm: entry.margin,
        grid_mode: entry.gridMode,
        grid_spacing_m: entry.gridSpacing,
    };
    if (shared.dpi) payload.dpi = parseInt(shared.dpi, 10);
    if (shared.zoomLevel) payload.zoom_level = parseInt(shared.zoomLevel, 10);
    if (entry.title) payload.title = entry.title;
    if (shared.showRoute !== false && shared.routes?.length) {
        payload.gpx_routes = shared.routes;
        payload.gpx_color = shared.gpxColor;
        payload.gpx_width = mmToPt(parseWidthMm(shared.gpxWidthMm));
        payload.gpx_opacity = parseInt(shared.gpxOpacity, 10) / 100;
        payload.gpx_look = shared.look ?? 'line';
        if (shared.waypoints?.length) payload.gpx_waypoints = shared.waypoints;
    }
    return payload;
}
