// Shared constants. No DOM or OpenLayers imports: safe to load in Node tests.

// --- Projection and tiles: EPSG:3067 (ETRS-TM35FIN) -------------------------
export const PROJ = 'EPSG:3067';
export const PROJ_DEF = '+proj=utm +zone=35 +ellps=GRS80 +towgs84=0,0,0 +units=m +no_defs';
export const MAX_EXTENT = [-548576, 6291456, 1548576, 8388608];
export const DEF_CENTER = [379667, 6673891];   // Otaniemi / Espoo
export const TILE_ORIGIN = [-548576, 8388608];
// NLS ETRS-TM35FIN tile matrix set: res = 8192 / 2^z, origin top-left.
// The open-data service offers levels 0-13 for this matrix set.
export const RESOLUTIONS = Array.from({ length: 14 }, (_, z) => 8192 / 2 ** z);

// --- Map settings -------------------------------------------------------------
export const PAPER_MM = { A4: [210, 297], A3: [297, 420] };
export const ORIENTATIONS = ['portrait', 'landscape'];
export const LAYERS = ['maastokartta', 'taustakartta', 'selkokartta', 'ortokuva'];
export const GRID_MODES = ['off', 'vertical', 'vertical_coords', 'full', 'full_coords'];
export const GRID_SPACINGS = [500, 1000, 2000, 5000];
export const MARGIN_MAX_MM = 30;
// Mirrors FOOTER_MM in print_layout.py: space under the map for the PDF
// footer line. The map keeps its width (and scale), loses this height.
export const FOOTER_MM = 3;
export const DEFAULTS = {
    paperSize: 'A4',
    orientation: 'portrait',
    scale: 20000,
    layer: 'maastokartta',
    margin: 7,
    gridMode: 'off',
    gridSpacing: 1000,
};

// --- Browser storage keys -----------------------------------------------------
export const STORAGE_KEY = 'fastmap.maps.v1';
export const HINT_KEY = 'fastmap.hintHidden';
export const UI_KEY = 'fastmap.ui.v1';

// --- Rectangle colours --------------------------------------------------------
// The topographic map is full of red roads, pink built-up areas and grey
// detail, so the selected map is a vivid blue and the others are dark ink;
// both sit on a white casing that keeps them visible over any background.
// ACTIVE_COLOR matches --active in styles.css.
export const ACTIVE_COLOR = '#0050e6';
export const LOCKED_COLOR = '#1d2329';
export const CASING = 'rgba(255, 255, 255, 0.95)';
