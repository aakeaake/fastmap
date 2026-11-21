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
import { defaults } from 'ol/interaction/defaults.js';
import GPX from 'ol/format/GPX.js';
import proj4 from 'proj4';
import { register } from 'ol/proj/proj4.js';
import {
    ACTIVE_COLOR, CASING, DEF_CENTER, LOCKED_COLOR, MAX_EXTENT, PROJ, PROJ_DEF, RESOLUTIONS, TILE_ORIGIN,
} from './constants.js';

proj4.defs(PROJ, PROJ_DEF);
register(proj4);

export function makeBaseSource(layer) {
    return new TileImage({
        projection: PROJ,
        tileGrid: new TileGrid({ origin: TILE_ORIGIN, resolutions: RESOLUTIONS, tileSize: 256 }),
        tileUrlFunction: ([z, x, y]) => `/api/nls-tiles/${z}/${x}/${y}.png?layer=${layer}`,
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
