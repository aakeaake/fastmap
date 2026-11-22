// FastMap UI: wires the map, the map list, the panes and PDF downloads.
import {
    DEFAULTS, GRID_MODES, HINT_KEY, PAPER_MM, STORAGE_KEY, VECTOR_LAYER, VECTOR_SCALES,
} from './constants.js';
import { centerToShow, containsExtent, contentMeters, visibleCenter as visibleCenterOf, visibleExtent } from './geometry.js';
import { applyTranslations, getLang, locale, onLangChange, setLang, t } from './i18n.js';
import { hydrateIcons, icon, setButton } from './icons.js';
import { JobError, runJob } from './jobs.js';
import {
    addTranslate, areaFeature, createMap, createRouteTools, createShapeTools, featureRing, makeBaseSource, readGpx,
    routeFeature, toWgs84,
} from './map.js';
import { AREA_KEY, formatKm2, ringAreaM2, sanitizeSavedArea, serializeArea } from './area.js';
import { ATLAS_MAX, atlasTitle, planAtlas } from './atlas.js';
import { effectiveLayer } from './layer.js';
import { createLangMenu } from './lang-menu.js';
import { createNotices } from './notices.js';
import { createPanes } from './panes.js';
import { MAX_BATCH, coverTitle, planCover } from './cover.js';
import { sanitizeSetSettings, settingsChanged } from './modes.js';
import { buildPayload, gpxRoutes } from './payload.js';
import { ROUTE_KEY, formatKm, routeLengthM, sanitizeSavedRoute, serializeRoute, toGpx } from './route.js';
import { parseMargin } from './saved.js';
import { formatNumber } from './format.js';
import { createSheet } from './sheet.js';
import {
    active, createEntry, entryCenter, entryExtent, getEntry, modeMaps, placeEntry, restoreFrom, serialize, setActiveId, state,
    syncLabel,
} from './state.js';
import { fitColumns, indexLayout, moveInIndex, nudgeCenter, sheetLabel } from './sheet-index.js';
import { atlasCountLabel, attributionLabel, createdLabel, deletedLabel, displayName, mapSummary, progressLabel, setSummaryLabel, shortName, splitSetLabel } from './text.js';

const el = id => document.getElementById(id);
hydrateIcons();
applyTranslations();

const { map, view, baseLayer, areaLayer, gpxLayer, lockedLayer, activeLayer } =
    createMap('map', { isActive: id => id === active()?.id });

const generatingIds = new Set();
let downloadAllBusy = false;      // Download all is running
let mapsExpanded = false;         // phones: the long Maps list unfolded
let revealedId = null;            // the Maps row last scrolled into view
const downloadedIds = new Set();   // downloaded and unchanged since

const nameOf = e => displayName(e, modeMaps(e.mode).indexOf(e), getLang());
const summaryOf = e => mapSummary(e, getLang());

// --- Selection and the map layers -------------------------------------------
// The selected map lives on its own layer so only it can be dragged.
function moveFeature(entry, layer) {
    if (!entry) return;
    for (const f of [entry.feature, entry.labelFeature]) {
        if (lockedLayer.getSource().hasFeature(f)) lockedLayer.getSource().removeFeature(f);
        if (activeLayer.getSource().hasFeature(f)) activeLayer.getSource().removeFeature(f);
        if (layer) layer.getSource().addFeature(f);
    }
}

// Only the current mode's maps are on the map
function showMode() {
    for (const e of state.maps) moveFeature(e, null);
    for (const e of modeMaps()) moveFeature(e, e === active() ? activeLayer : lockedLayer);
}

function setActive(id) {
    const cur = active();
    if (cur && cur.id !== id) moveFeature(cur, lockedLayer);
    setActiveId(id);
    moveFeature(active(), activeLayer);
    syncPanel();
    renderList();
    persist();
}

function selectAndReveal(e) {
    setActive(e.id);
    revealEntry(e);
}

// The area of a map changed: its last PDF is stale
function areaChanged(e) {
    downloadedIds.delete(e.id);
    renderList();
    persist();
}

function newMap() {
    if (state.mode !== 'maps') return;   // only Maps mode places sheets by hand
    // inherit the active map's settings so consecutive maps stay consistent
    const cur = active();
    const settings = cur ? {
        paperSize: cur.paperSize,
        orientation: cur.orientation,
        scale: cur.scale,
        layer: cur.layer,
        gridMode: cur.gridMode,
        gridSpacing: cur.gridSpacing,
    } : {};
    const full = { ...DEFAULTS, ...settings, margin: state.margin, mode: 'maps' };
    // not exactly on top of another map (it would hide under it)
    const center = nudgeCenter(visibleCenter(), modeMaps('maps').map(entryCenter), contentMeters(full));
    setActive(createEntry(center, full).id);
}

// An undo snapshot of one mode's maps
const snapshotOf = (mode = state.mode) => ({ mode, data: serialize({ mode }) });

function deleteEntry(id) {
    const list = modeMaps();
    const i = list.findIndex(m => m.id === id);
    if (i === -1) return;
    const snapshot = snapshotOf();
    const gone = list[i];
    moveFeature(gone, null);
    state.maps.splice(state.maps.indexOf(gone), 1);
    const rest = modeMaps();
    if (!active()) {   // the selected map went
        if (rest.length) setActive(rest[Math.max(0, i - 1)].id);
        else if (state.mode === 'maps') newMap();
        else { setActiveId(null); renderList(); persist(); }
    } else {
        renderList();
        persist();
    }
    // Name it in whatever language is showing when the message is drawn
    offerUndo(() => t('map.deleted', { name: displayName(gone, i, getLang()) }), snapshot);
}

// Remove every map of one mode (the others stay)
function removeMode(mode) {
    for (const e of modeMaps(mode)) moveFeature(e, null);
    state.maps = state.maps.filter(e => e.mode !== mode);
    state.activeIds[mode] = null;
}

// Clear the current mode's maps (Maps mode starts again with one new map)
function clearAll() {
    const snapshot = snapshotOf();
    const count = modeMaps().length;
    removeMode(state.mode);
    if (state.mode === 'maps') newMap();
    else { renderList(); persist(); }
    offerUndo(() => deletedLabel(count, getLang()), snapshot);
}

// Select the mode's saved selection, else its last map
function selectInMode() {
    const list = modeMaps();
    const id = active()?.id ?? list[list.length - 1]?.id ?? null;
    if (id === null) { setActiveId(null); renderList(); persist(); return; }
    setActive(id);
}

// Load the saved layout at start; false if nothing in it was valid
function loadSnapshot(data) {
    const created = restoreFrom(data);
    showMode();
    if (!created.length) return false;
    selectInMode();
    return modeMaps().length > 0 || state.mode !== 'maps';
}

// --- Undo -------------------------------------------------------------------
let undoSnapshot = null;
let toastTimer = null;
let toastText = () => '';   // re-run on a language change

function offerUndo(text, snapshot) {
    undoSnapshot = snapshot;
    toastText = text;
    el('toastMsg').textContent = text();
    el('toast').hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 8000);
}

function hideToast() {
    el('toast').hidden = true;
    undoSnapshot = null;
}

// Put back the snapshot's mode only; other modes keep any later changes
function undo() {
    if (!undoSnapshot) return;
    const { mode, data } = undoSnapshot;
    hideToast();
    revealedId = null;
    removeMode(mode);
    // The sheets come back at today's margin (one margin for all maps); a
    // route or atlas then says its settings changed if the margin did
    for (const e of restoreFrom(data, { mode })) {
        if (e.margin !== state.margin) { e.margin = state.margin; placeEntry(e); }
    }
    if (mode !== state.mode) {
        setMode(mode);   // show the set that came back
    } else {
        showMode();
        if (!modeMaps().length && mode === 'maps') newMap();
        else selectInMode();
    }
    renderCover();
    renderAtlas();
    persist();
    if (state.mode === 'maps') el('mapList').querySelector(`[data-key="select-${active()?.id}"]`)?.focus();
    else {
        const btn = el(state.mode === 'route' ? 'coverBtn' : 'atlasBtn');
        (el(`${state.mode}Index`).querySelector('[tabindex="0"]')
            ?? (btn.offsetParent !== null ? btn : el('modeTabs').querySelector(`[data-mode="${state.mode}"]`)))?.focus();
    }
}

// --- Settings form <-> selected map -------------------------------------------
function syncPanel() {
    if (state.mode !== 'maps') {     // route and atlas sheets have no form of their own
        const { layer, scale } = readBlock(state.mode);
        baseLayer.setSource(makeBaseSource(effectiveLayer(layer, scale)));
        return;
    }
    const e = active();
    if (!e) return;
    baseLayer.setSource(makeBaseSource(e.layer));
    el('paperSize').value = e.paperSize;
    el('orientation').value = e.orientation;
    el('scale').value = e.scale;
    el('mapType').value = e.layer === VECTOR_LAYER ? 'vector' : 'raster';
    updateMapTypeOption(e.scale);
    el('title').value = e.title;
    el('gridMode').value = e.gridMode;
    el('gridSpacing').value = e.gridSpacing;
    el('gridSpacing').disabled = e.gridMode === 'off';
}

// The vector option exists only at the scales the vector map supports
function updateMapTypeOption(scale) {
    const ok = VECTOR_SCALES.includes(scale);
    el('mapTypeVector').disabled = !ok;
    el('mapTypeHint').hidden = ok;
}

function panelChanged() {
    const e = active();
    if (!e) return;
    downloadedIds.delete(e.id);
    e.paperSize = PAPER_MM[el('paperSize').value] ? el('paperSize').value : 'A4';
    e.orientation = el('orientation').value === 'landscape' ? 'landscape' : 'portrait';
    e.scale = parseInt(el('scale').value, 10) || 20000;
    const prevLayer = e.layer;
    e.layer = effectiveLayer(el('mapType').value === 'vector' ? VECTOR_LAYER : 'maastokartta', e.scale);
    el('mapType').value = e.layer === VECTOR_LAYER ? 'vector' : 'raster';
    updateMapTypeOption(e.scale);
    if (e.layer !== prevLayer) baseLayer.setSource(makeBaseSource(e.layer));
    e.title = el('title').value.trim();
    e.gridMode = GRID_MODES.includes(el('gridMode').value) ? el('gridMode').value : 'off';
    e.gridSpacing = parseInt(el('gridSpacing').value, 10) || 1000;
    el('gridSpacing').disabled = e.gridMode === 'off';
    placeEntry(e);
    renderList();
    persist();
}

// --- Map list, rail and labels ------------------------------------------------
function refreshLabels() {
    for (const e of state.maps) {
        e.labelFeature.set('labelText', shortName(nameOf(e)));
        syncLabel(e);
    }
    lockedLayer.changed();
    activeLayer.changed();
}

// Collapsed rail: one numbered tile per map, same order as the list
function renderRail(focusKey) {
    const ul = el('railMaps');
    ul.innerHTML = '';
    modeMaps().forEach((e, i) => {
        const li = document.createElement('li');
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'rail-map';
        b.dataset.key = `rail-${e.id}`;
        b.textContent = tileLabel(e, i);
        if (generatingIds.has(e.id)) b.classList.add('generating');
        else if (downloadedIds.has(e.id)) b.classList.add('done');
        const label = `${nameOf(e)} · ${summaryOf(e)}`;
        b.setAttribute('aria-label', label);
        b.title = label;
        b.setAttribute('aria-pressed', String(e.id === active()?.id));
        b.addEventListener('click', () => selectAndReveal(e));
        li.append(b);
        ul.append(li);
    });
    if (focusKey) ul.querySelector(`[data-key="${focusKey}"]`)?.focus();
}

// Route and atlas sheets show their printed label ("3", "B3"); maps 1…N
function tileLabel(e, i) {
    const l = e.mode === 'maps' ? null : sheetLabel(e.title);
    return l ? ('n' in l ? String(l.n) : l.label) : String(i + 1);
}

// A download button for one sheet, with its generating / done state
function setDownloadButton(btn, e) {
    const name = nameOf(e);
    btn.classList.remove('generating', 'done');
    btn.removeAttribute('aria-disabled');
    if (generatingIds.has(e.id)) {
        btn.classList.add('generating');
        btn.innerHTML = icon('loader');
        btn.setAttribute('aria-label', t('map.generating', { name }));
        btn.setAttribute('aria-disabled', 'true');
    } else if (downloadedIds.has(e.id)) {
        btn.classList.add('done');
        btn.innerHTML = icon('check');
        btn.setAttribute('aria-label', t('map.downloadAgain', { name }));
    } else {
        btn.innerHTML = icon('download');
        btn.setAttribute('aria-label', t('map.download', { name }));
    }
    btn.title = btn.getAttribute('aria-label');
}

function listRow(e) {
    const isActive = e.id === active()?.id;
    const name = nameOf(e);
    const li = document.createElement('li');
    li.dataset.id = e.id;
    if (isActive) li.classList.add('active');

    const select = document.createElement('button');
    select.type = 'button';
    select.className = 'm-select';
    select.dataset.key = `select-${e.id}`;
    select.setAttribute('aria-pressed', String(isActive));
    select.addEventListener('click', () => selectAndReveal(e));

    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.classList.toggle('chip-active', isActive);

    const nameEl = document.createElement('span');
    nameEl.className = 'm-name';
    nameEl.textContent = name;

    const sum = document.createElement('span');
    sum.className = 'm-sum';
    sum.textContent = summaryOf(e);

    select.append(chip, nameEl, sum);

    const dlBtn = document.createElement('button');
    dlBtn.type = 'button';
    dlBtn.className = 'icon-btn dl-btn';
    dlBtn.dataset.key = `dl-${e.id}`;
    setDownloadButton(dlBtn, e);
    dlBtn.addEventListener('click', () => downloadSingle(e));

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'icon-btn del';
    del.dataset.key = `del-${e.id}`;
    del.innerHTML = icon('x');
    del.setAttribute('aria-label', t('map.delete', { name }));
    del.title = t('map.deleteShort');
    del.addEventListener('click', () => deleteEntry(e.id));

    li.append(select, dlBtn, del);
    return li;
}

// Rebuilt on every change; keyboard focus is carried over by data-key
function renderList() {
    const focused = document.activeElement;
    const railFocus = el('railMaps').contains(focused) ? focused.dataset.key : null;
    if (state.mode === 'maps') {
        const ul = el('mapList');
        const listFocus = ul.contains(focused) ? focused.dataset.key : null;
        // Phones: a long list folds to the selected map, so its settings
        // stay close; "Show all" unfolds it
        const maps = modeMaps();
        const fold = sheet.phone.matches && maps.length > MAPS_FOLD;
        const shown = fold && !mapsExpanded ? maps.filter(e => e === active()) : maps;
        ul.replaceChildren(...shown.map(listRow));
        const more = el('mapsShowAll');
        more.hidden = !fold;
        more.textContent = mapsExpanded ? t('maps.showLess') : t('maps.showAll', { count: maps.length });
        more.setAttribute('aria-expanded', String(fold && mapsExpanded));
        if (listFocus) {
            (ul.querySelector(`[data-key="${listFocus}"]`)
                ?? ul.querySelector(`[data-key="select-${active()?.id}"]`))?.focus();
        }
        // Scroll to the selected row only when the selection changed, not on
        // every edit (that would carry the field being typed in out of view)
        if (active() && active().id !== revealedId) {
            ul.querySelector('li.active')?.scrollIntoView({ block: 'nearest' });
            revealedId = active().id;
        }
    } else {
        renderIndex(state.mode);
    }
    renderRail(railFocus);

    const cur = active();
    el('activeName').textContent = cur ? nameOf(cur) : '';
    const summary = el('sheetSummary');
    summary.textContent = '';
    if (cur) {
        const [base, label] = splitSetLabel(nameOf(cur));
        const b = document.createElement('b');
        const baseEl = document.createElement('span');
        baseEl.className = 'sum-base';
        baseEl.textContent = base;
        b.append(baseEl, label);
        const rest = document.createElement('span');
        rest.className = 'sum-rest';
        rest.textContent = ` · ${summaryOf(cur)}`;
        summary.append(b, rest);
    }
    const count = modeMaps().length;
    el('downloadAllBtn').textContent = count > 1 ? t('download.allCount', { count }) : t('download.one');
    if (!downloadAllBusy) el('downloadAllBtn').disabled = count === 0;
    refreshLabels();
}

const MAPS_FOLD = 5;   // phones fold the Maps list above this many maps
el('mapsShowAll').addEventListener('click', () => { mapsExpanded = !mapsExpanded; renderList(); });

// --- Route and Atlas: the sheet index ------------------------------------------
// The set as its shape (atlas grid, route strip) with one summary line and
// one line for the selected sheet. Cells show the printed labels.
const indexLayouts = { route: null, atlas: null };

function renderIndex(mode) {
    const sheets = modeMaps(mode);
    el(`${mode}Set`).hidden = !sheets.length;
    if (!sheets.length) {
        indexLayouts[mode] = null;
        el(`${mode}Index`).replaceChildren();   // no stale cells to focus
        return;
    }
    const idx = el(`${mode}Index`);
    const focusIn = idx.contains(document.activeElement);
    const layout = indexLayout(mode, sheets, { maxCols: indexColumns(idx) });
    indexLayouts[mode] = { ...layout, maxCols: indexColumns(idx) };
    el(`${mode}Summary`).textContent = setSummaryLabel(sheets.length, sheets[0], getLang());

    const cur = state.mode === mode ? active() : null;
    const focusId = cur?.id ?? layout.cells[0].id;
    idx.style.gridTemplateColumns = `repeat(${layout.cols}, var(--cell))`;
    // The same cells as before: update them in place, so a screen reader
    // doesn't announce the focused cell again on every download tick
    const old = [...idx.children];
    const same = old.length === layout.cells.length && layout.cells.every((c, i) =>
        old[i].dataset.id === String(c.id) && old[i].textContent === c.label
        && old[i].style.gridRow === String(c.row + 1) && old[i].style.gridColumn === String(c.col + 1));
    const cells = layout.cells.map((c, i) => {
        const b = same ? old[i] : document.createElement('button');
        if (!same) {
            b.type = 'button';
            b.className = 'index-cell';
            b.setAttribute('role', 'radio');
            b.textContent = c.label;
            b.style.gridRow = String(c.row + 1);
            b.style.gridColumn = String(c.col + 1);
            b.dataset.id = c.id;
        }
        const e = getEntry(c.id);
        b.tabIndex = c.id === focusId ? 0 : -1;
        b.setAttribute('aria-checked', String(c.id === cur?.id));
        b.setAttribute('aria-label', `${nameOf(e)} · ${summaryOf(e)}`);
        b.classList.toggle('generating', generatingIds.has(c.id));
        b.classList.toggle('done', !generatingIds.has(c.id) && downloadedIds.has(c.id));
        return b;
    });
    if (!same) idx.replaceChildren(...cells);
    if (focusIn) idx.querySelector('[tabindex="0"]')?.focus();

    el(`${mode}Selected`).hidden = !cur;
    if (!cur) return;
    const name = el(`${mode}SelName`);
    name.replaceChildren();
    const b = document.createElement('b');
    b.textContent = nameOf(cur);
    const small = document.createElement('small');
    small.textContent = summaryOf(cur);
    name.append(b, ' ', small);
    setDownloadButton(el(`${mode}SelDl`), cur);
    el(`${mode}SelDel`).setAttribute('aria-label', t('map.delete', { name: nameOf(cur) }));
    el(`${mode}SelDel`).title = t('map.deleteShort');
}

// As many columns as fit the panel (cells are 30 px, 44 px on touch)
function indexColumns(idx) {
    const cell = parseFloat(getComputedStyle(idx).getPropertyValue('--cell')) || 30;
    return fitColumns(idx.clientWidth, cell, INDEX_GAP);
}
const INDEX_GAP = 4;

// Re-lay the index when its width changes (scrollbar, rotation, resize), and
// the Maps fold when the layout switches between phone and desktop
function refitIndex() {
    const mode = state.mode;
    if (mode === 'maps' || !indexLayouts[mode]) return;
    if (indexColumns(el(`${mode}Index`)) !== indexLayouts[mode].maxCols) renderList();
}
const indexWidth = new ResizeObserver(refitIndex);
window.addEventListener('resize', refitIndex);   // also where observers are throttled

for (const mode of ['route', 'atlas']) {
    const idx = el(`${mode}Index`);
    indexWidth.observe(idx);
    idx.addEventListener('click', ev => {
        const b = ev.target.closest('.index-cell');
        const e = b && getEntry(Number(b.dataset.id));
        if (e) selectAndReveal(e);
    });
    // One tab stop; arrows move the selection (over gaps), Home / End
    idx.addEventListener('keydown', ev => {
        const layout = indexLayouts[mode];
        if (!layout || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(ev.key)) return;
        ev.preventDefault();
        const from = Number(ev.target.closest('.index-cell')?.dataset.id ?? active()?.id);
        const e = getEntry(moveInIndex(layout, from, ev.key));
        if (e) selectAndReveal(e);
    });
    el(`${mode}SelDl`).addEventListener('click', () => { const e = active(); if (e) downloadSingle(e); });
    el(`${mode}SelDel`).addEventListener('click', () => { const e = active(); if (e) deleteEntry(e.id); });
}

// The id prefix of the Route and Atlas print blocks (saved under SETS_KEY)
const BLOCK_PREFIX = { route: 'cover', atlas: 'atlas' };
const SETS_KEY = 'fastmap.sets.v1';

// --- Persistence ----------------------------------------------------------------
function persist() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(serialize())); }
    catch { /* storage may be unavailable - ignore */ }
}

function savedSnapshot() {
    try { return JSON.parse(localStorage.getItem(STORAGE_KEY)); } catch { return null; }
}

// --- Layout: sheet, panes, visible area -------------------------------------
const sheet = createSheet({
    panel: el('panel'),
    head: el('sheetHead'),
    footer: el('panel').querySelector('.download'),
    grabber: el('grabber'),
    stack: document.querySelector('.stack'),
});
const panes = createPanes({
    phone: sheet.phone,
    onNewMap: newMap,
    onDownloadAll: () => el('downloadAllBtn').click(),
    onLayout: setCoveredLeft,   // runs once before `panes` is assigned
});
const covered = () => ({ left: panes.coveredLeft(), bottom: sheet.coveredBottom() });
// Phone <-> desktop: the Maps fold and the index columns follow
sheet.phone.addEventListener('change', () => renderList());

// Centre of the part of the map the user can actually see
// (from the view, so it works before the first frame has rendered)
function visibleCenter() {
    return visibleCenterOf(view.getCenter(), view.getResolution(), covered());
}

// Pixel width of map hidden behind the right-hand controls (zoom, centre)
function coveredRight() {
    const tool = el('centerBtn');
    if (tool.offsetParent === null) return 0;   // hidden (phone sheet fully open)
    return Math.max(0, window.innerWidth - tool.getBoundingClientRect().left);
}

// Zoom to `entries`, clear of the panel, the sheet and the map controls
function fitTo(entries, duration = 300) {
    const ext = entries.map(entryExtent).reduce((a, b) => [
        Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3]),
    ]);
    const c = covered();
    view.fit(ext, { padding: [40, 40 + coveredRight(), 40 + c.bottom, 40 + c.left], duration });
}

// When none of the mode's maps is in view, zoom to them (after a mode
// switch or a reload); otherwise leave the view alone
function fitModeIfHidden(duration = 300) {
    const maps = modeMaps();
    const size = map.getSize();
    if (!maps.length || !size) return;
    const [x0, y0, x1, y1] = visibleExtent(view.getCenter(), view.getResolution(), size, covered());
    const seen = maps.some(e => {
        const [a0, b0, a1, b1] = entryExtent(e);
        return a0 < x1 && a1 > x0 && b0 < y1 && b1 > y0;
    });
    if (!seen) fitTo(maps, duration);
}

// Where the left column ends: the bottom-right stack keeps clear of it
function setCoveredLeft(px) {
    document.documentElement.style.setProperty('--covered-left', `${Math.round(px)}px`);
}
const updateCoveredLeft = () => setCoveredLeft(panes.coveredLeft());
window.addEventListener('resize', updateCoveredLeft);

// Pan so the entry sits in the visible area, if it is not there already
function revealEntry(e) {
    const size = map.getSize() ?? [0, 0];
    const c = covered();
    if (size[1] - c.bottom < 120 || size[0] - c.left < 120) return;
    const res = view.getResolution();
    if (containsExtent(visibleExtent(view.getCenter(), res, size, c), entryExtent(e))) return;
    view.animate({ center: centerToShow(entryCenter(e), res, c), duration: 300 });
}

// --- Map interactions ------------------------------------------------------------
const translate = addTranslate(map, activeLayer, {
    onMove: ids => ids.forEach(id => { const e = getEntry(id); if (e) syncLabel(e); }),
    onEnd: ids => {
        ids.forEach(id => downloadedIds.delete(id));
        persist();
        renderList();
    },
});

// Double-click centres the selected rectangle there (no zoom)
map.on('dblclick', ev => {
    if (routeTools.paused() || areaTools.paused()) return;
    const cur = active();
    if (!cur) return;
    placeEntry(cur, ev.coordinate);
    areaChanged(cur);
});

// A click on a sheet of the current mode selects it (the topmost one); it
// does not move the view. Drawing tools keep their clicks.
const sheetLayers = l => l === activeLayer || l === lockedLayer;
map.on('singleclick', ev => {
    if (routeTools.paused() || areaTools.paused()) return;
    let id = null;
    map.forEachFeatureAtPixel(ev.pixel, f => {
        if (f.get('label') || f.get('mapId') == null) return false;
        id = f.get('mapId');
        return true;
    }, { layerFilter: sheetLayers, hitTolerance: 2 });
    const e = id === null ? null : getEntry(id);
    if (e && e.mode === state.mode && e.id !== active()?.id) setActive(e.id);
});
// A hand over sheets that a click would select
map.on('pointermove', ev => {
    if (ev.dragging || sheet.phone.matches) return;
    if (routeTools.paused() || areaTools.paused()) {   // a click adds a point
        map.getTargetElement().style.cursor = '';
        return;
    }
    const over = map.hasFeatureAtPixel(ev.pixel, { layerFilter: l => l === lockedLayer, hitTolerance: 2 });
    map.getTargetElement().style.cursor = over ? 'pointer' : '';
});

// Move-here button: put the selected map in the centre of the visible map
el('centerBtn').addEventListener('click', () => {
    const cur = active();
    if (!cur) return;
    placeEntry(cur, visibleCenter());
    areaChanged(cur);
});

// --- Start -------------------------------------------------------------------------
// Size the sheet first: newMap() places the first map in the visible area
sheet.setSheet(sheet.state);
state.mode = panes.getMode();
loadBlocks();
if (!loadSnapshot(savedSnapshot()) && state.mode === 'maps') newMap();
el('margin').value = state.margin;

for (const id of ['paperSize', 'orientation', 'scale', 'mapType', 'gridMode', 'gridSpacing']) {
    el(id).addEventListener('change', panelChanged);
    el(id).addEventListener('input', panelChanged);
}
el('title').addEventListener('input', () => {
    const e = active();
    if (!e) return;
    e.title = el('title').value.trim();
    renderList();
    persist();
});
el('newBtn').addEventListener('click', newMap);

// One margin for every map (Advanced): re-size every sheet in every mode
function marginChanged() {
    state.margin = parseMargin(el('margin').value);
    for (const e of state.maps) {
        if (e.margin === state.margin) continue;
        e.margin = state.margin;
        placeEntry(e);
        downloadedIds.delete(e.id);
    }
    renderList();
    renderCover();
    renderAtlas();
    persist();
}
el('margin').addEventListener('input', marginChanged);
el('margin').addEventListener('change', () => {
    marginChanged();
    el('margin').value = state.margin;   // show the value in use (clamped to 0–30)
});

// --- Modes: Maps, Route, Atlas ----------------------------------------------------
// Each mode keeps its own maps; only the current mode's are on the map, in
// its list and in Download all.
function renderModeUi() {
    const mode = state.mode;
    for (const m of ['maps', 'route', 'atlas']) {
        el(`mode${m[0].toUpperCase()}${m.slice(1)}`).hidden = m !== mode;
    }
    for (const b of el('modeTabs').querySelectorAll('[data-mode]')) {
        const on = b.dataset.mode === mode;
        b.setAttribute('aria-checked', String(on));
        b.tabIndex = on ? 0 : -1;
    }
    for (const b of el('railModes').querySelectorAll('[data-mode]')) {
        b.setAttribute('aria-pressed', String(b.dataset.mode === mode));
    }
    el('railNew').hidden = mode !== 'maps';
    areaLayer.setVisible(mode === 'atlas');
}

function setMode(mode) {
    if (mode === state.mode) return;
    routeTools.cancel();
    areaTools.cancel();
    state.mode = mode;
    revealedId = null;
    panes.setModePref(mode);
    renderModeUi();
    showMode();
    if (!modeMaps().length && mode === 'maps') newMap();
    else selectInMode();
    syncPanel();
    renderRoute();
    renderArea();
    renderRouteBar();
    fitModeIfHidden();
}

// Radio group: click, or arrow keys / Home / End move and select
el('modeTabs').addEventListener('click', ev => {
    const b = ev.target.closest('[data-mode]');
    if (b) setMode(b.dataset.mode);
});
el('modeTabs').addEventListener('keydown', ev => {
    const order = ['maps', 'route', 'atlas'];
    const i = order.indexOf(state.mode);
    const next = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: 2 }[ev.key];
    if (next === undefined) return;
    ev.preventDefault();
    setMode(order[(next + 3) % 3]);
    el('modeTabs').querySelector(`[data-mode="${state.mode}"]`).focus();
});
el('railModes').addEventListener('click', ev => {
    const b = ev.target.closest('[data-mode]');
    if (b) setMode(b.dataset.mode);
});
el('clearAllBtn').addEventListener('click', clearAll);
el('undoBtn').addEventListener('click', undo);

// Usage hint: dismissible, remembered per browser
try { if (localStorage.getItem(HINT_KEY)) el('hint').hidden = true; } catch { /* ignore */ }
el('hintClose').addEventListener('click', () => {
    el('hint').hidden = true;
    try { localStorage.setItem(HINT_KEY, '1'); } catch { /* ignore */ }
});

// On-screen credit; the PDFs print the full licence line
fetch('/api/attribution')
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(d => {
        el('attribution').textContent = attributionLabel(d.text);
        el('attribution').title = d.text;
    })
    .catch(() => {});

// --- Route -----------------------------------------------------------------------
// One route at a time, uploaded or drawn: one feature on gpxLayer, saved in
// the browser with its name and the show-on-printouts choice.
const gpxInput = el('gpxInput');
let routeName = '';   // name of the route as typed; '' when none

const routeLines = () => gpxRoutes(gpxLayer.getSource().getFeatures());
const routeLabel = () => routeName.trim() || t('gpx.myRoute');

function saveRoute() {
    const lines = routeLines();
    try {
        if (!lines.length) localStorage.removeItem(ROUTE_KEY);
        else {
            const data = serializeRoute({ name: routeName, lines, showOnPrint: el('gpxShow').checked });
            localStorage.setItem(ROUTE_KEY, JSON.stringify(data));
        }
    } catch {
        // Storage blocked or full: the route still works until reload, but
        // an older saved route must not come back in its place
        try { localStorage.removeItem(ROUTE_KEY); } catch { /* ignore */ }
    }
}

function renderRoute() {
    const lines = routeLines();
    const has = lines.length > 0;
    el('routeLoaded').hidden = !has;
    setButton(el('gpxBtn'), 'upload', t('gpx.load'));
    setButton(el('drawBtn'), 'route', t('gpx.draw'));
    setButton(el('editRouteBtn'), 'pen', t('gpx.edit'));
    setButton(el('gpxDownloadBtn'), 'download', t('gpx.download'));
    setButton(el('gpxRemoveBtn'), 'x', t('gpx.remove'));
    el('gpxInfo').textContent = has ? `${routeLabel()} · ${formatKm(routeLengthM(lines), locale())}` : '';
    renderCover();
}

// Replace the route (no lines = no route)
function setRoute(name, lines) {
    const source = gpxLayer.getSource();
    source.clear();
    if (lines.length) source.addFeature(routeFeature(lines));
    routeName = lines.length ? name : '';
    el('routeName').value = routeName;
    saveRoute();
    renderRoute();
}

const clearRoute = () => setRoute('', []);

// Drawing a route or an area: toolbar at the top right of the map. Sheet
// dragging and double-click-to-centre pause while it is open. One tool is
// open at a time.
let toolShape = [];   // route: lines; area: one ring
const anyTool = () => routeTools.active() || areaTools.active();
const openTool = () => (areaTools.active() ? areaTools : routeTools);

function renderRouteBar() {
    const mode = anyTool();
    renderCover();
    renderAtlas();
    el('routeBar').hidden = !mode;
    document.body.toggleAttribute('data-route-mode', !!mode);
    if (!mode) return;
    if (areaTools.active()) {
        const area = formatKm2(ringAreaM2(toolShape), locale());
        el('routeStatus').textContent = t(mode === 'draw' ? 'atlas.drawing' : 'atlas.editing', { area });
        el('routeFinish').disabled = mode === 'draw' && toolShape.length < 3;
    } else {
        const km = formatKm(routeLengthM(toolShape), locale());
        el('routeStatus').textContent = t(mode === 'draw' ? 'gpx.drawing' : 'gpx.editing', { km });
        el('routeFinish').disabled = mode === 'draw' && !(toolShape[0]?.length >= 2);
    }
    el('routeUndo').hidden = mode !== 'draw';
}

function toolModeChanged() {
    translate.setActive(!anyTool());
    toolShape = [];
    renderRouteBar();
}

const routeTools = createRouteTools(map, gpxLayer, {
    onChange: lines => { toolShape = lines; renderRouteBar(); },
    onDone: (mode, lines) => setRoute(mode === 'draw' ? t('gpx.myRoute') : routeName, lines),
    onModeChange: toolModeChanged,
});

const areaTools = createShapeTools(map, areaLayer, {
    type: 'Polygon',
    onChange: ring => { toolShape = ring; renderRouteBar(); },
    onDone: (mode, ring) => setArea(mode === 'draw' ? t('atlas.defaultName') : areaName, ring),
    onModeChange: toolModeChanged,
});

// Phones: get the sheets out of the way of the map
function showMapForRoute() {
    if (!sheet.phone.matches) return;
    sheet.setSheet('peek');
}
el('drawBtn').addEventListener('click', () => { areaTools.cancel(); showMapForRoute(); routeTools.startDraw(); });
el('editRouteBtn').addEventListener('click', () => { areaTools.cancel(); showMapForRoute(); routeTools.startEdit(); });
el('routeUndo').addEventListener('click', () => openTool().removeLast());
el('routeFinish').addEventListener('click', () => openTool().finish());
el('routeCancel').addEventListener('click', () => openTool().cancel());

el('gpxBtn').addEventListener('click', () => gpxInput.click());
el('gpxRemoveBtn').addEventListener('click', () => { routeTools.cancel(); clearRoute(); });
el('gpxShow').addEventListener('change', () => { saveRoute(); renderCover(); });

// --- Atlas area ------------------------------------------------------------------
// One area at a time, drawn: one Polygon feature on areaLayer, saved in the
// browser with its name. The atlas (below) covers it with a grid of sheets.
let areaName = '';   // as typed; areaLabel() fills in the default

function areaRing() {
    const feature = areaLayer.getSource().getFeatures()[0];
    return feature ? featureRing(feature) : null;
}
const areaLabel = () => areaName.trim() || t('atlas.defaultName');

function saveArea() {
    const ring = areaRing();
    try {
        if (!ring) localStorage.removeItem(AREA_KEY);
        else localStorage.setItem(AREA_KEY, JSON.stringify(serializeArea({ name: areaName, ring })));
    } catch {
        // Storage blocked or full: an older saved area must not come back
        try { localStorage.removeItem(AREA_KEY); } catch { /* ignore */ }
    }
}

function renderArea() {
    const ring = areaRing();
    el('areaStart').hidden = !!ring;
    el('areaLoaded').hidden = !ring;
    setButton(el('areaDrawBtn'), 'area', t('atlas.draw'));
    setButton(el('areaEditBtn'), 'pen', t('atlas.edit'));
    setButton(el('areaRemoveBtn'), 'x', t('atlas.remove'));
    el('areaInfo').textContent = ring ? `${areaLabel()} · ${formatKm2(ringAreaM2(ring), locale())}` : '';
    renderAtlas();
}

// Replace the area (null = no area)
function setArea(name, ring) {
    const source = areaLayer.getSource();
    source.clear();
    if (ring) source.addFeature(areaFeature(ring));
    areaName = ring ? name : '';
    saveArea();
    renderArea();
}

el('areaDrawBtn').addEventListener('click', () => { routeTools.cancel(); showMapForRoute(); areaTools.startDraw(); });
el('areaEditBtn').addEventListener('click', () => { routeTools.cancel(); showMapForRoute(); areaTools.startEdit(); });
el('areaRemoveBtn').addEventListener('click', () => { areaTools.cancel(); setArea('', null); });

// Saved area from an earlier visit; junk is ignored
(() => {
    let saved = null;
    try { saved = sanitizeSavedArea(JSON.parse(localStorage.getItem(AREA_KEY))); } catch { /* ignore */ }
    if (saved) setArea(saved.name, saved.ring);
    else renderArea();
})();

// --- Route and Atlas print blocks -----------------------------------------------
// Each set has its own print settings, saved under SETS_KEY. They set up the
// next Create; the sheets keep the settings they were made with
// (state.madeWith), and the block says so when the two differ.
const BLOCK_FIELDS = ['Paper', 'Orientation', 'Scale', 'MapType', 'Grid', 'GridSpacing', 'Overlap'];

function readBlock(mode) {
    const p = BLOCK_PREFIX[mode];
    return sanitizeSetSettings(mode, {
        paperSize: el(`${p}Paper`).value,
        orientation: el(`${p}Orientation`).value,
        scale: parseInt(el(`${p}Scale`).value, 10),
        layer: el(`${p}MapType`).value === 'vector' ? VECTOR_LAYER : 'maastokartta',
        gridMode: el(`${p}Grid`).value,
        gridSpacing: parseInt(el(`${p}GridSpacing`).value, 10),
        overlapPct: Number(el(`${p}Overlap`).value),
    });
}

// The vector option exists only at the scales the vector map supports
function updateBlockControls(mode) {
    const p = BLOCK_PREFIX[mode];
    const ok = VECTOR_SCALES.includes(parseInt(el(`${p}Scale`).value, 10));
    el(`${p}MapTypeVector`).disabled = !ok;
    el(`${p}MapTypeHint`).hidden = ok;
    if (!ok) el(`${p}MapType`).value = 'raster';
    el(`${p}GridSpacing`).disabled = el(`${p}Grid`).value === 'off';
}

function writeBlock(mode, settings) {
    const p = BLOCK_PREFIX[mode];
    el(`${p}Paper`).value = settings.paperSize;
    el(`${p}Orientation`).value = settings.orientation;
    el(`${p}Scale`).value = settings.scale;
    el(`${p}MapType`).value = settings.layer === VECTOR_LAYER ? 'vector' : 'raster';
    el(`${p}Grid`).value = settings.gridMode;
    el(`${p}GridSpacing`).value = settings.gridSpacing;
    el(`${p}Overlap`).value = settings.overlapPct;
    updateBlockControls(mode);
}

function loadBlocks() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(SETS_KEY)); } catch { /* ignore */ }
    for (const mode of ['route', 'atlas']) writeBlock(mode, sanitizeSetSettings(mode, saved?.[mode]));
}

function saveBlocks() {
    try {
        localStorage.setItem(SETS_KEY, JSON.stringify({ route: readBlock('route'), atlas: readBlock('atlas') }));
    } catch { /* ignore */ }
}

function blockChanged(mode) {
    updateBlockControls(mode);
    saveBlocks();
    if (mode === 'route') renderCover(); else renderAtlas();
    if (state.mode === mode) syncPanel();
}

// "Create" or, when the block no longer matches the sheets, "Update"
function renderSetButton(mode, disabled) {
    const p = BLOCK_PREFIX[mode];
    const changed = modeMaps(mode).length > 0
        && settingsChanged(readBlock(mode), state.madeWith[mode], state.margin);
    el(`${p}Changed`).hidden = !changed;
    el(`${p}Btn`).textContent = t(`${p}.${changed ? 'update' : 'create'}`);
    el(`${p}Btn`).disabled = disabled;
    const todo = changed || !modeMaps(mode).length;
    el(`${p}Btn`).classList.toggle('btn-primary', todo);
    el(`${p}Btn`).classList.toggle('btn-secondary', !todo);
}

for (const mode of ['route', 'atlas']) {
    for (const f of BLOCK_FIELDS) {
        el(`${BLOCK_PREFIX[mode]}${f}`).addEventListener('change', () => blockChanged(mode));
    }
}

// Replace one mode's maps with `items` ([{ center, orientation, title }])
// made with `settings` (the block); the other modes keep theirs. Undo brings
// the old set back.
function replaceSet(mode, items, settings, undoLabel) {
    const snapshot = snapshotOf(mode);
    const base = {
        paperSize: settings.paperSize, scale: settings.scale, margin: state.margin,
        layer: effectiveLayer(settings.layer, settings.scale),   // vector only where it exists
        gridMode: settings.gridMode, gridSpacing: settings.gridSpacing, mode,
    };
    removeMode(mode);
    const created = items.map(({ center, orientation, title }) => createEntry(center, { ...base, orientation, title }));
    state.madeWith[mode] = { ...settings, margin: state.margin };
    setActiveId(created[0].id);
    showMode();
    setActive(created[0].id);
    renderCover();
    renderAtlas();

    showMapForRoute();
    fitTo(created);
    offerUndo(undoLabel, snapshot);
}

// --- Route sheets ---------------------------------------------------------------
// Sheets along the route in walking order (cover.js). Shown while a route
// exists and is not being drawn or edited.
const coverSheets = () => planCover(routeLines(), { ...readBlock('route'), margin: state.margin });

function renderCover() {
    const section = el('coverSection');
    const show = routeLines().length > 0 && !anyTool();
    section.hidden = !show;
    if (!show) return;
    el('routeName').placeholder = t('gpx.myRoute');
    const n = coverSheets().length;
    const count = formatNumber(n, locale());
    el('coverCount').textContent = n > MAX_BATCH ? t('cover.tooMany', { count })
        : n === 1 ? t('cover.countOne') : t('cover.count', { count });
    el('coverCount').classList.toggle('warn', n > MAX_BATCH);
    el('coverRouteHidden').hidden = el('gpxShow').checked;
    renderSetButton('route', !n || n > MAX_BATCH);
}

function createCover() {
    const sheets = coverSheets();
    const n = sheets.length;
    if (!n || n > MAX_BATCH) return;
    const name = routeLabel();
    const items = sheets.map((sheet, i) => ({
        center: sheet.center, orientation: sheet.orientation, title: coverTitle(name, i + 1, n),
    }));
    replaceSet('route', items, readBlock('route'), () => createdLabel(n, name, getLang()));
}
el('coverBtn').addEventListener('click', createCover);

// The name is used in titles, the info line and the GPX file name; it does
// not change the sheets, so only the info line is redrawn
el('routeName').addEventListener('input', () => {
    routeName = el('routeName').value;
    saveRoute();
    const lines = routeLines();
    if (lines.length) el('gpxInfo').textContent = `${routeLabel()} · ${formatKm(routeLengthM(lines), locale())}`;
});

// --- Atlas of the area -------------------------------------------------------------
// A grid of sheets over the drawn area (atlas.js), labelled A1, A2, … Shown
// while an area exists and no drawing tool is open.

// A function declaration: the saved area is restored (and rendered) above
function atlasPlan() {
    return planAtlas(areaRing(), { ...readBlock('atlas'), margin: state.margin });
}

function renderAtlas() {
    const section = el('atlasSection');
    const show = !!areaRing() && !anyTool();
    if (show && section.hidden) el('atlasName').value = areaName;
    section.hidden = !show;
    if (!show) return;
    el('atlasName').placeholder = t('atlas.defaultName');
    const { rows, cols, sheets, atLeast } = atlasPlan();
    const n = sheets ? sheets.length : atLeast;
    el('atlasCount').textContent = atlasCountLabel(n, rows, cols, getLang(), !sheets);
    el('atlasCount').classList.toggle('warn', n > ATLAS_MAX);
    renderSetButton('atlas', !n || n > ATLAS_MAX);
}

// Replace the atlas sheets, in reading order
function createAtlas() {
    const { sheets } = atlasPlan();
    const n = sheets?.length ?? 0;
    if (!n || n > ATLAS_MAX) return;
    const block = readBlock('atlas');
    const items = sheets.map(s => ({
        center: s.center, orientation: block.orientation,
        title: atlasTitle(areaName, s.label, t('atlas.defaultName')),
    }));
    const name = areaLabel();
    replaceSet('atlas', items, block, () => createdLabel(n, name, getLang(), 'atlas'));
}
el('atlasBtn').addEventListener('click', createAtlas);

// The name does not change the layout: update the info line only
el('atlasName').addEventListener('input', () => {
    areaName = el('atlasName').value;
    saveArea();
    const ring = areaRing();
    if (ring) el('areaInfo').textContent = `${areaLabel()} · ${formatKm2(ringAreaM2(ring), locale())}`;
});

el('gpxDownloadBtn').addEventListener('click', () => {
    const text = toGpx(routeLabel(), routeLines(), toWgs84);
    saveBlob(new Blob([text], { type: 'application/gpx+xml' }), `${routeLabel()}.gpx`);
});

gpxInput.addEventListener('change', () => {
    const file = gpxInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        let features;
        try { features = readGpx(reader.result); } catch { features = []; }
        const lines = gpxRoutes(features);
        if (!lines.length) {
            notices.show('gpx', 'error', () => t('gpx.noRoute', { file: file.name }));
            return;
        }
        notices.close('gpx');
        routeTools.cancel();
        // Prefer the track/route name; waypoints (Points) also carry names
        const line = features.find(f => f.getGeometry()?.getType() !== 'Point' && f.get('name'));
        setRoute(line?.get('name') || file.name.replace(/\.gpx$/i, ''), lines);
        view.fit(gpxLayer.getSource().getExtent(), { padding: [50, 50, 50, 50] });
    };
    reader.readAsText(file);
    gpxInput.value = '';
});

// Saved route from an earlier visit; junk is ignored
(() => {
    let saved = null;
    try { saved = sanitizeSavedRoute(JSON.parse(localStorage.getItem(ROUTE_KEY))); } catch { /* ignore */ }
    if (!saved) return;
    el('gpxShow').checked = saved.showOnPrint;
    setRoute(saved.name, saved.lines);
})();

el('gpxOpacity').addEventListener('input', () => {
    el('gpxOpacityVal').textContent = `${el('gpxOpacity').value} %`;
});

// --- PDF downloads -------------------------------------------------------------------
const notices = createNotices(el('notices'), {
    closeLabel: () => t('close'),
    politeRegion: el('livePolite'),
    alertRegion: el('liveAlert'),
});

// One progress card for all running jobs, ticking every second. The ticks
// are not announced: the live regions only hear start, done and error.
let runningJobs = 0;
let jobsStarted = 0;
let progressTimer = null;

function tickProgress() {
    notices.refresh('progress');
}

function jobStarted() {
    if (runningJobs++ === 0) {
        jobsStarted = Date.now();
        progressTimer = setInterval(tickProgress, 1000);
        notices.show('progress', 'progress',
            () => progressLabel(runningJobs, Math.round((Date.now() - jobsStarted) / 1000), getLang()),
            { announcement: t('progress.start') });
    }
    tickProgress();
}

function jobFinished() {
    if (--runningJobs === 0) {
        clearInterval(progressTimer);
        notices.close('progress');
    } else {
        tickProgress();
    }
}

// Settings shared by every map, read from the route & precision pane
function sharedSettings() {
    return {
        dpi: el('dpi').value,
        zoomLevel: el('zoomLevel').value,
        routes: routeLines(),
        showRoute: el('gpxShow').checked,
        gpxColor: el('gpxColor').value,
        gpxWidth: el('gpxWidth').value,
        gpxOpacity: el('gpxOpacity').value,
    };
}

function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

// `resultId` keeps each job's outcome separate: one map's error card is
// not replaced by another job finishing, only by that same job running again.
async function trackJob(url, body, resultId) {
    notices.close(resultId);
    jobStarted();
    try {
        const { blob, filename } = await runJob(url, body);
        saveBlob(blob, filename);
        notices.show(resultId, 'success', () => t('download.done', { file: filename }));
        return true;
    } catch (err) {
        const message = () => (err instanceof JobError && err.key ? t(err.key, err.params) : err.message);
        notices.show(resultId, 'error', () => t('download.error', { message: message() }));
        return false;
    } finally {
        jobFinished();
    }
}

async function downloadSingle(entry) {
    if (generatingIds.has(entry.id)) return;
    generatingIds.add(entry.id);
    renderList();
    const ok = await trackJob('/generate-map-async', buildPayload(entry, entryExtent(entry), sharedSettings()),
        `result-${entry.id}`);
    generatingIds.delete(entry.id);
    if (ok) downloadedIds.add(entry.id);
    renderList();
}

function setDownloadAllBusy(busy) {
    downloadAllBusy = busy;
    const btn = el('downloadAllBtn');
    const rail = el('railDownload');
    btn.classList.toggle('loading', busy);
    btn.disabled = busy;
    rail.classList.toggle('loading', busy);
    for (const b of [btn, rail]) {
        if (busy) b.setAttribute('aria-busy', 'true'); else b.removeAttribute('aria-busy');
    }
    rail.innerHTML = icon(busy ? 'loader' : 'download');
}

el('downloadAllBtn').addEventListener('click', async () => {
    const maps = modeMaps();
    if (!maps.length) return;
    setDownloadAllBusy(true);
    const shared = sharedSettings();
    await trackJob('/generate-maps-batch-async', {
        output: el('batchFormat').value,
        maps: maps.map(e => buildPayload(e, entryExtent(e), shared)),
    }, 'result-batch');
    setDownloadAllBusy(false);
});

// --- Language -------------------------------------------------------------------------
// Option labels with numbers follow the language's digit grouping
function formatOptions() {
    for (const o of [...el('scale').options, ...el('coverScale').options, ...el('atlasScale').options]) {
        o.textContent = `1:${formatNumber(Number(o.value), locale())}`;
    }
    for (const o of [...el('gridSpacing').options, ...el('coverGridSpacing').options, ...el('atlasGridSpacing').options]) o.textContent = `${formatNumber(Number(o.value), locale())} m`;
}

// Globe button + menu; the current language is checked
const langMenu = createLangMenu({
    button: el('langBtn'),
    menu: el('langMenu'),
    current: getLang,
    onPick: setLang,
});

function renderScriptText() {
    setButton(el('newBtn'), 'plus', t('maps.new'));
    if (!el('toast').hidden) el('toastMsg').textContent = toastText();
    notices.refresh();
    formatOptions();
    renderRoute();
    renderArea();
    renderRouteBar();
    langMenu.sync();
    renderModeUi();
    renderList();
}

onLangChange(renderScriptText);
renderScriptText();
updateCoveredLeft();
fitModeIfHidden(0);
