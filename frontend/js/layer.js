// Which map layer a map really uses. Pure: no DOM, safe in Node tests.
import { VECTOR_LAYER, VECTOR_SCALES } from './constants.js';

// The vector map exists only at some scales; elsewhere use the raster map.
export function effectiveLayer(layer, scale) {
    return layer === VECTOR_LAYER && !VECTOR_SCALES.includes(scale) ? 'maastokartta' : layer;
}
