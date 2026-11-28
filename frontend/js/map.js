// OpenLayers setup: projection, base tiles, layers, rectangle styles, GPX.
import Map from 'ol/Map.js';
import View from 'ol/View.js';
import TileLayer from 'ol/layer/Tile.js';
import VectorLayer from 'ol/layer/Vector.js';
import TileImage from 'ol/source/TileImage.js';
import VectorSource from 'ol/source/Vector.js';
import Feature from 'ol/Feature.js';
import Polygon from 'ol/geom/Polygon.js';
import Point from 'ol/geom/Point.js';
import MultiLineString from 'ol/geom/MultiLineString.js';
import { toLonLat } from 'ol/proj.js';
import Style from 'ol/style/Style.js';
import Stroke from 'ol/style/Stroke.js';
import Fill from 'ol/style/Fill.js';
import Text from 'ol/style/Text.js';
import TileGrid from 'ol/tilegrid/TileGrid.js';
import Translate from 'ol/interaction/Translate.js';
import Draw from 'ol/interaction/Draw.js';
import Modify from 'ol/interaction/Modify.js';
import MultiPoint from 'ol/geom/MultiPoint.js';
import CircleStyle from 'ol/style/Circle.js';
import { altKeyOnly, doubleClick, never, singleClick } from 'ol/events/condition.js';
import { defaults } from 'ol/interaction/defaults.js';
import { defaults as defaultControls } from 'ol/control/defaults.js';
import GPX from 'ol/format/GPX.js';
import proj4 from 'proj4';
import { register } from 'ol/proj/proj4.js';
import { drawKeysIgnored } from './draw-keys.js';
import { previewTileLayer } from './layer.js';
import { DEFAULT_STYLE, rgba, screenWidthPx } from './route-style.js';
import { SCREEN, courseLegs, finishOuterRadius, numberDirection, startTriangle } from './course.js';
import {
    ACTIVE_COLOR, CASING, DEF_CENTER, LOCKED_COLOR, MAX_EXTENT, PROJ, PROJ_DEF, RESOLUTIONS, TILE_ORIGIN,
} from './constants.js';

proj4.defs(PROJ, PROJ_DEF);
register(proj4);

export function makeBaseSource(layer) {
    return new TileImage({
        projection: PROJ,
        tileGrid: new TileGrid({ origin: TILE_ORIGIN, resolutions: RESOLUTIONS, tileSize: 256 }),
        tileUrlFunction: ([z, x, y]) => `/api/nls-tiles/${z}/${x}/${y}.png?layer=${previewTileLayer(layer)}`,
    });
}

// --- Rectangles ------------------------------------------------------------
const ACTIVE_STYLE = [
    new Style({
        stroke: new Stroke({ color: CASING, width: 7 }),
        fill: new Fill({ color: 'rgba(0, 80, 230, 0.14)' }),
    }),
    new Style({ stroke: new Stroke({ color: ACTIVE_COLOR, width: 3 }) }),
];
const LOCKED_STYLE = [
    new Style({
        stroke: new Stroke({ color: CASING, width: 5 }),
        fill: new Fill({ color: 'rgba(255, 255, 255, 0.22)' }),
    }),
    new Style({ stroke: new Stroke({ color: LOCKED_COLOR, width: 2, lineDash: [7, 5] }) }),
];

function labelStyle(text, color) {
    return new Style({
        text: new Text({
            text,
            font: 'bold 12px system-ui, sans-serif',
            fill: new Fill({ color }),
            stroke: new Stroke({ color: '#ffffff', width: 3 }),
            offsetX: -5,
            offsetY: 5,
            textAlign: 'right',
            textBaseline: 'top',
        }),
    });
}

// A map's rectangle plus its name label (anchored at the top-right corner)
export function makeFeatures(id, coords) {
    const feature = new Feature(new Polygon([coords]));
    feature.set('mapId', id);
    const [, , maxx, maxy] = feature.getGeometry().getExtent();
    const labelFeature = new Feature(new Point([maxx, maxy]));
    labelFeature.set('mapId', id);
    labelFeature.set('label', true);
    return { feature, labelFeature };
}

// The route on the map: its print colour (rgba, with the opacity) and a
// screen width that roughly follows the print width (route-style.js)
export function routeLayerStyle(color, widthPx, look = 'line') {
    const line = new Style({ stroke: new Stroke({ color, width: widthPx }) });
    if (look !== 'course') return line;
    return (feature, resolution) => {
        const geom = feature.getGeometry();
        const lines = geom?.getType() === 'MultiLineString' ? geom.getCoordinates() : [];
        if (lines.length !== 1 || lines[0].length < 2) return line;
        return courseStyles(lines[0].map(p => [p[0], p[1]]), color, widthPx, resolution);
    };
}

const haloStroke = new Stroke({ color: 'rgba(255, 255, 255, 0.9)', width: 3 });

// The course look on screen: legs stopped at the symbols, start triangle,
// numbered control circles, finish double circle and a dot on every point.
// Sizes are SCREEN px, turned into map units with the current resolution.
function courseStyles(pts, color, widthPx, resolution) {
    const u = px => px * resolution;
    const stroke = new Stroke({ color, width: widthPx });
    const fill = new Fill({ color });
    const [innerR, outerR] = SCREEN.finishD.map(d => d / 2);
    const finishR = [innerR, finishOuterRadius(innerR, outerR, widthPx, SCREEN.finishClear)];
    const legs = courseLegs(pts, {
        start: u(SCREEN.startSide / Math.sqrt(3)),
        control: u(SCREEN.controlD / 2),
        finish: u(finishR[1]),
        // clear of the symbol's stroke and the leg's round cap, however thick
        gap: u(SCREEN.gap + widthPx),
    });
    const tri = startTriangle(pts[0], pts[1], u(SCREEN.startSide));
    const controls = pts.slice(1, -1);
    const finish = pts[pts.length - 1];
    const styles = [
        new Style({ geometry: new MultiLineString(legs), stroke }),
        new Style({ geometry: new Polygon([[...tri, tri[0]]]), stroke }),
        ...finishR.map(radius => new Style({
            geometry: new Point(finish), image: new CircleStyle({ radius, stroke }),
        })),
        new Style({ geometry: new MultiPoint(pts), image: new CircleStyle({ radius: Math.max(SCREEN.dotMin, widthPx) / 2, fill }) }),
    ];
    if (controls.length) {
        styles.push(new Style({
            geometry: new MultiPoint(controls), image: new CircleStyle({ radius: SCREEN.controlD / 2, stroke }),
        }));
    }
    const offset = u(SCREEN.controlD / 2 + 8);
    controls.forEach((p, i) => {
        const [dx, dy] = numberDirection(pts[i], p, pts[i + 2]);
        styles.push(new Style({
            geometry: new Point([p[0] + dx * offset, p[1] + dy * offset]),
            text: new Text({ text: String(i + 1), font: `bold ${SCREEN.numberPx}px sans-serif`, fill, stroke: haloStroke }),
        }));
    });
    return styles;
}

// Waypoints: a circle with a dot in the middle and the name to the right
export function waypointLayerStyle(color, widthPx) {
    const stroke = new Stroke({ color, width: widthPx });
    const fill = new Fill({ color });
    const ring = new Style({ image: new CircleStyle({ radius: SCREEN.controlD / 2, stroke }) });
    const dot = new Style({ image: new CircleStyle({ radius: Math.max(SCREEN.dotMin, widthPx) / 2, fill }) });
    return feature => {
        const name = feature.get('name');
        if (!name) return [ring, dot];
        return [ring, dot, new Style({
            text: new Text({
                text: name, font: `${SCREEN.namePx}px sans-serif`, textAlign: 'left',
                offsetX: SCREEN.controlD / 2 + 4, fill, stroke: haloStroke,
            }),
        })];
    };
}

// Waypoints [{ x, y, name }] as Point features for the waypoint layer
export function waypointFeatures(waypoints) {
    return waypoints.map(w => new Feature({ geometry: new Point([w.x, w.y]), name: w.name }));
}

// --- Map --------------------------------------------------------------------
// `isActive(mapId)` decides which style a rectangle and its label get.
export function createMap(target, { isActive }) {
    const styleFor = feature => {
        const act = isActive(feature.get('mapId'));
        if (feature.get('label')) {
            return labelStyle(feature.get('labelText') || '', act ? ACTIVE_COLOR : LOCKED_COLOR);
        }
        return act ? ACTIVE_STYLE : LOCKED_STYLE;
    };
    const baseLayer = new TileLayer({ source: makeBaseSource('maastokartta') });
    const gpxLayer = new VectorLayer({
        source: new VectorSource(),
        style: routeLayerStyle(rgba(DEFAULT_STYLE.color, DEFAULT_STYLE.opacity), screenWidthPx(DEFAULT_STYLE.widthMm)),
    });
    // GPX waypoints, on their own layer so the route tools never pick one
    const waypointLayer = new VectorLayer({
        source: new VectorSource(),
        style: waypointLayerStyle(rgba(DEFAULT_STYLE.color, DEFAULT_STYLE.opacity), screenWidthPx(DEFAULT_STYLE.widthMm)),
    });
    // The atlas area: thin orange outline, light fill, under the route and sheets
    const areaLayer = new VectorLayer({
        source: new VectorSource(),
        style: new Style({
            stroke: new Stroke({ color: '#e07000', width: 2 }),
            fill: new Fill({ color: 'rgba(224, 112, 0, 0.08)' }),
        }),
    });
    const lockedLayer = new VectorLayer({ source: new VectorSource(), style: styleFor });
    const activeLayer = new VectorLayer({ source: new VectorSource(), style: styleFor });
    // North up always: the PDFs are north-up, so the map never rotates
    const view = new View({
        projection: PROJ, center: DEF_CENTER, resolution: 128, extent: MAX_EXTENT, enableRotation: false,
    });
    const map = new Map({
        target,
        layers: [baseLayer, areaLayer, gpxLayer, waypointLayer, lockedLayer, activeLayer],
        view,
        interactions: defaults({ doubleClickZoom: false, altShiftDragRotate: false, pinchRotate: false }),
        controls: defaultControls({ rotate: false }),
    });
    return { map, view, baseLayer, areaLayer, gpxLayer, waypointLayer, lockedLayer, activeLayer };
}

// Drag rectangles on `layer`. Labels ride along; callbacks get the map ids.
export function addTranslate(map, layer, { onMove, onEnd }) {
    const translate = new Translate({ layers: [layer], filter: f => !f.get('label') });
    const ids = ev => ev.features.getArray().filter(f => !f.get('label')).map(f => f.get('mapId'));
    translate.on('translating', ev => onMove(ids(ev)));
    translate.on('translateend', ev => onEnd(ids(ev)));
    map.addInteraction(translate);
    return translate;
}

// --- Route and area drawing and editing ---------------------------------------------
// Drawing mode: a quick click adds a point, a drag pans, wheel/pinch zooms
// (OpenLayers Draw defaults). The layer is not touched; the caller gets the
// result.
// Editing mode: the shape's points are shown on `layer`; drag a point to
// move it, drag a segment to add one, Alt-click (double-tap on touch)
// deletes one. Cancel puts the shape back as it was.
// `type` 'LineString' (the route: shapes are lists of lines) or 'Polygon'
// (the area: shapes are one ring, not closed).
//   onChange(shape)       the points so far (for the live length / area)
//   onDone(mode, shape)   Finish (or double-click when drawing)
//   onModeChange(mode)    'draw' | 'edit' | null
const KEYS = { Enter: 'finish', Backspace: 'removeLast', Escape: 'cancel' };

const VERTEX_STYLE = new Style({
    image: new CircleStyle({
        radius: 5, fill: new Fill({ color: '#ffffff' }), stroke: new Stroke({ color: '#c000c0', width: 2 }),
    }),
    geometry: f => new MultiPoint(f.getGeometry().getCoordinates().flat()),
});

// The sketch while drawing, in `color` and fully opaque: lines with a white
// casing and white-ringed points, like the OpenLayers default sketch
function sketchStyle(color) {
    const casing = new Style({ stroke: new Stroke({ color: '#ffffff', width: 5 }) });
    const line = new Style({ stroke: new Stroke({ color, width: 3 }) });
    const point = new Style({
        image: new CircleStyle({
            radius: 6, fill: new Fill({ color }), stroke: new Stroke({ color: '#ffffff', width: 1.5 }),
        }),
    });
    const fill = new Style({ fill: new Fill({ color: 'rgba(255, 255, 255, 0.5)' }) });
    return feature => {
        const t = feature.getGeometry().getType();
        if (t === 'Point') return point;
        return t === 'Polygon' ? [fill, casing, line] : [casing, line];
    };
}

const xy = p => [p[0], p[1]];
const xyLines = geom => geom.getCoordinates().map(line => line.map(xy));

// The area as one feature (the ring closed), and back (the closing point dropped)
export const areaFeature = ring => new Feature(new Polygon([[...ring, ring[0]]]));
export const featureRing = feature => feature.getGeometry().getCoordinates()[0].slice(0, -1).map(xy);

export function createRouteTools(map, routeLayer, opts) {
    return createShapeTools(map, routeLayer, { ...opts, type: 'LineString' });
}

// `sketchColor` (optional): () => '#rrggbb', the colour to draw in
export function createShapeTools(map, layer, { type, onChange, onDone, onModeChange, sketchColor }) {
    const polygon = type === 'Polygon';
    const minPoints = polygon ? 3 : 2;
    // The layer's feature: a Polygon (area) or a MultiLineString (route)
    const shapeOf = feature => (polygon ? featureRing(feature) : xyLines(feature.getGeometry()));
    // The finished sketch: a Polygon, or a single LineString
    const drawnShape = feature => (polygon ? featureRing(feature) : [feature.getGeometry().getCoordinates().map(xy)]);
    let mode = null;
    let interaction = null;
    let editEnd = null;     // undoes what startEdit() set up
    let edited = null;      // the feature while editing
    let before = null;      // its geometry when editing started (for Cancel)
    let points = [];        // placed points while drawing
    let quietUntil = 0;     // the double-click that finished drawing must not centre a sheet

    function onKey(ev) {
        const action = KEYS[ev.key];
        if (!action || !mode || drawKeysIgnored(ev.target)) return;
        ev.preventDefault();
        ev.stopPropagation();
        api[action]();
    }

    function enter(next, inter) {
        if (mode) api.cancel();
        mode = next;
        interaction = inter;
        map.addInteraction(inter);
        window.addEventListener('keydown', onKey, true);
        onModeChange(mode);
    }

    function exit() {
        editEnd?.();
        editEnd = null;
        edited = null;
        map.removeInteraction(interaction);
        window.removeEventListener('keydown', onKey, true);
        interaction = null;
        mode = null;
        points = [];
        quietUntil = performance.now() + 500;
        onModeChange(null);
    }

    const drawn = () => (polygon ? points : points.length ? [points] : []);

    function startDraw() {
        // A drag always pans: no dragging the new point after a long press
        // (dragVertexDelay; finite so setTimeout does not overflow) and no
        // Shift-drag freehand drawing
        const draw = new Draw({
            type, dragVertexDelay: 1e9, freehandCondition: never,
            ...(sketchColor && { style: sketchStyle(sketchColor()) }),
        });
        // The sketch's last point follows the pointer; the rest are placed.
        // A polygon sketch's ring also ends with the closing point.
        draw.on('drawstart', ev => {
            const geom = ev.feature.getGeometry();
            const update = () => {
                const coords = polygon ? geom.getCoordinates()[0].slice(0, -2) : geom.getCoordinates().slice(0, -1);
                const next = coords.map(xy);
                if (next.length === points.length) return;
                points = next;
                onChange(drawn());
            };
            geom.on('change', update);
            update();
        });
        draw.on('drawabort', () => { points = []; onChange([]); });
        draw.on('drawend', ev => {
            const shape = drawnShape(ev.feature);
            exit();
            if (polygon ? shape.length >= 3 : shape[0].length >= 2) onDone('draw', shape);
        });
        points = [];
        enter('draw', draw);
        onChange([]);
    }

    // The shape is the layer's one feature (see routeFeature, areaFeature)
    function startEdit() {
        if (mode) api.cancel();
        const feature = layer.getSource().getFeatures()[0];
        if (!feature) return;
        edited = feature;
        before = feature.getGeometry().clone();
        const modify = new Modify({
            source: layer.getSource(),
            deleteCondition: e => (altKeyOnly(e) && singleClick(e))
                || (e.originalEvent.pointerType === 'touch' && doubleClick(e)),
        });
        const vertices = new VectorLayer({ source: layer.getSource(), style: VERTEX_STYLE });
        const changed = () => onChange(shapeOf(feature));
        feature.on('change', changed);
        enter('edit', modify);
        map.addLayer(vertices);
        editEnd = () => {
            feature.un('change', changed);
            map.removeLayer(vertices);
        };
        changed();
    }

    const api = {
        startDraw,
        startEdit,
        finish() {
            if (mode === 'draw' && points.length >= minPoints) interaction.finishDrawing();
            if (mode === 'edit') {
                const shape = shapeOf(edited);
                exit();
                onDone('edit', shape);
            }
        },
        removeLast() {
            if (mode === 'draw') interaction.removeLastPoint();
        },
        cancel() {
            if (!mode) return;
            if (mode === 'draw') interaction.abortDrawing();
            // Put the shape back before closing, so what re-renders on
            // close (counts, buttons) sees the restored shape
            if (mode === 'edit') edited.setGeometry(before);
            exit();
        },
        active: () => mode,
        // Map clicks belong to the route tools (also just after they close)
        paused: () => mode !== null || performance.now() < quietUntil,
    };
    return api;
}

export function readGpx(text) {
    return new GPX().readFeatures(text, { dataProjection: 'EPSG:4326', featureProjection: PROJ });
}

// The route as one feature on the route layer (one line per GPX segment)
export function routeFeature(lines) {
    return new Feature(new MultiLineString(lines));
}

// EPSG:3067 point -> [lon, lat]
export const toWgs84 = xy => toLonLat(xy, PROJ);
