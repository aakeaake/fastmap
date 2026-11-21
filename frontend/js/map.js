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
import GPX from 'ol/format/GPX.js';
import proj4 from 'proj4';
import { register } from 'ol/proj/proj4.js';
import { previewTileLayer } from './layer.js';
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
        style: new Style({ stroke: new Stroke({ color: 'rgba(255, 0, 255, 0.6)', width: 5 }) }),
    });
    const lockedLayer = new VectorLayer({ source: new VectorSource(), style: styleFor });
    const activeLayer = new VectorLayer({ source: new VectorSource(), style: styleFor });
    const view = new View({ projection: PROJ, center: DEF_CENTER, resolution: 128, extent: MAX_EXTENT });
    const map = new Map({
        target,
        layers: [baseLayer, gpxLayer, lockedLayer, activeLayer],
        view,
        interactions: defaults({ doubleClickZoom: false }),
    });
    return { map, view, baseLayer, gpxLayer, lockedLayer, activeLayer };
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

// --- Route drawing and editing -----------------------------------------------------
// Drawing mode: a quick click adds a point, a drag pans, wheel/pinch zooms
// (OpenLayers Draw defaults). The route layer is not touched; the caller
// gets the result.
// Editing mode: the route's points are shown on `routeLayer`; drag a point
// to move it, drag a segment to add one, Alt-click (double-tap on touch)
// deletes one. Cancel puts the route back as it was.
//   onChange(lines)       the points so far (for the live length)
//   onDone(mode, lines)   Finish (or double-click when drawing)
//   onModeChange(mode)    'draw' | 'edit' | null
const KEYS = { Enter: 'finish', Backspace: 'removeLast', Escape: 'cancel' };
const typing = t => t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));

const VERTEX_STYLE = new Style({
    image: new CircleStyle({
        radius: 5, fill: new Fill({ color: '#ffffff' }), stroke: new Stroke({ color: '#c000c0', width: 2 }),
    }),
    geometry: f => new MultiPoint(f.getGeometry().getCoordinates().flat()),
});

const xyLines = geom => geom.getCoordinates().map(line => line.map(p => [p[0], p[1]]));

export function createRouteTools(map, routeLayer, { onChange, onDone, onModeChange }) {
    let mode = null;
    let interaction = null;
    let editEnd = null;     // undoes what startEdit() set up
    let edited = null;      // the route feature while editing
    let before = null;      // its geometry when editing started (for Cancel)
    let points = [];        // placed points while drawing
    let quietUntil = 0;     // the double-click that finished drawing must not centre a sheet

    function onKey(ev) {
        const action = KEYS[ev.key];
        if (!action || !mode || typing(ev.target)) return;
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

    const drawnLines = () => (points.length ? [points] : []);

    function startDraw() {
        // A drag always pans: no dragging the new point after a long press
        // (dragVertexDelay; finite so setTimeout does not overflow) and no
        // Shift-drag freehand drawing
        const draw = new Draw({ type: 'LineString', dragVertexDelay: 1e9, freehandCondition: never });
        // The sketch's last point follows the pointer; the rest are placed
        draw.on('drawstart', ev => {
            const geom = ev.feature.getGeometry();
            const update = () => {
                const next = geom.getCoordinates().slice(0, -1).map(p => [p[0], p[1]]);
                if (next.length === points.length) return;
                points = next;
                onChange(drawnLines());
            };
            geom.on('change', update);
            update();
        });
        draw.on('drawabort', () => { points = []; onChange([]); });
        draw.on('drawend', ev => {
            const line = ev.feature.getGeometry().getCoordinates().map(p => [p[0], p[1]]);
            exit();
            if (line.length >= 2) onDone('draw', [line]);
        });
        points = [];
        enter('draw', draw);
        onChange([]);
    }

    // The route is one MultiLineString feature (see routeFeature)
    function startEdit() {
        if (mode) api.cancel();
        const feature = routeLayer.getSource().getFeatures()[0];
        if (!feature) return;
        edited = feature;
        before = feature.getGeometry().clone();
        const modify = new Modify({
            source: routeLayer.getSource(),
            deleteCondition: e => (altKeyOnly(e) && singleClick(e))
                || (e.originalEvent.pointerType === 'touch' && doubleClick(e)),
        });
        const vertices = new VectorLayer({ source: routeLayer.getSource(), style: VERTEX_STYLE });
        const changed = () => onChange(xyLines(feature.getGeometry()));
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
            if (mode === 'draw' && points.length >= 2) interaction.finishDrawing();
            if (mode === 'edit') {
                const lines = xyLines(edited.getGeometry());
                exit();
                onDone('edit', lines);
            }
        },
        removeLast() {
            if (mode === 'draw') interaction.removeLastPoint();
        },
        cancel() {
            if (!mode) return;
            if (mode === 'draw') interaction.abortDrawing();
            const [feature, geometry] = mode === 'edit' ? [edited, before] : [];
            exit();
            feature?.setGeometry(geometry);
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
