// Request bodies for the PDF endpoints. Pure: features are duck-typed
// (anything with getGeometry() whose geometry has getType/getCoordinates).

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

// One map's request body.
// `shared` holds the settings common to all maps, as read from the form:
//   { dpi, zoomLevel, routes, gpxColor, gpxWidth, gpxOpacity }
// dpi / zoomLevel are '' for automatic; gpxWidth / gpxOpacity are strings.
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
    if (shared.routes?.length) {
        payload.gpx_routes = shared.routes;
        payload.gpx_color = shared.gpxColor;
        payload.gpx_width = parseInt(shared.gpxWidth, 10) || 5;
        payload.gpx_opacity = parseInt(shared.gpxOpacity, 10) / 100;
    }
    return payload;
}
