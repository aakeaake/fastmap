// FastMap UI: wires the map, the map list, the panes and PDF downloads.
import { GRID_MODES, HINT_KEY, PAPER_MM, STORAGE_KEY } from './constants.js';
import { centerToShow, containsExtent, visibleCenter as visibleCenterOf, visibleExtent } from './geometry.js';
import { applyTranslations, getLang, locale, onLangChange, setLang, t } from './i18n.js';
import { hydrateIcons, icon, setButton } from './icons.js';
import { JobError, runJob } from './jobs.js';
import { addTranslate, createMap, makeBaseSource, readGpx } from './map.js';
import { createLangMenu } from './lang-menu.js';
import { createNotices } from './notices.js';
import { createPanes } from './panes.js';
import { buildPayload, gpxRoutes } from './payload.js';
import { parseMargin } from './saved.js';
import { createSheet } from './sheet.js';
import {
    active, createEntry, entryCenter, entryExtent, getEntry, placeEntry, restoreFrom, serialize, state, syncLabel,
} from './state.js';
import { attributionLabel, deletedLabel, displayName, mapSummary, progressLabel, shortName } from './text.js';

const el = id => document.getElementById(id);
hydrateIcons();
applyTranslations();

const { map, view, baseLayer, gpxLayer, lockedLayer, activeLayer } =
    createMap('map', { isActive: id => id === state.activeId });

const generatingIds = new Set();
const downloadedIds = new Set();   // downloaded and unchanged since

const nameOf = e => displayName(e, state.maps.indexOf(e), getLang());
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

function setActive(id) {
    const cur = active();
    if (cur && cur.id !== id) moveFeature(cur, lockedLayer);
    state.activeId = id;
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
    // inherit the active map's settings so consecutive maps stay consistent
    const cur = active();
    const settings = cur ? {
        paperSize: cur.paperSize,
        orientation: cur.orientation,
        scale: cur.scale,
        layer: cur.layer,
        margin: cur.margin,
        gridMode: cur.gridMode,
        gridSpacing: cur.gridSpacing,
    } : {};
    setActive(createEntry(visibleCenter(), settings).id);
}

function deleteEntry(id) {
    const i = state.maps.findIndex(m => m.id === id);
    if (i === -1) return;
    const snapshot = serialize();
    const gone = state.maps[i];
    moveFeature(gone, null);
    state.maps.splice(i, 1);
    if (id === state.activeId) {
        if (state.maps.length) setActive(state.maps[Math.max(0, i - 1)].id);
        else newMap();
    } else {
        renderList();
        persist();
    }
    // Name it in whatever language is showing when the message is drawn
    offerUndo(() => t('map.deleted', { name: displayName(gone, i, getLang()) }), snapshot);
}

function removeAll() {
    for (const e of state.maps) moveFeature(e, null);
    state.maps = [];
    state.activeId = null;
}

function clearAll() {
    const snapshot = serialize();
    const count = state.maps.length;
    removeAll();
    try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
    newMap();
    offerUndo(() => deletedLabel(count, getLang()), snapshot);
}

// Restore a snapshot onto an empty map list; false if nothing in it was valid
function loadSnapshot(data) {
    const created = restoreFrom(data);
    created.forEach(e => moveFeature(e, lockedLayer));
    if (!created.length) return false;
    setActive(getEntry(data.activeId) ? data.activeId : state.maps[state.maps.length - 1].id);
    return true;
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

function undo() {
    if (!undoSnapshot) return;
    const snapshot = undoSnapshot;
    hideToast();
    removeAll();
    if (!loadSnapshot(snapshot)) { newMap(); return; }
    el('mapList').querySelector(`[data-key="select-${state.activeId}"]`)?.focus();
}

// --- Settings form <-> selected map -------------------------------------------
function syncPanel() {
    const e = active();
    if (!e) return;
    el('paperSize').value = e.paperSize;
    el('orientation').value = e.orientation;
    el('scale').value = e.scale;
    el('margin').value = e.margin;
    baseLayer.setSource(makeBaseSource(e.layer));
    el('title').value = e.title;
    el('gridMode').value = e.gridMode;
    el('gridSpacing').value = e.gridSpacing;
    el('gridSpacing').disabled = e.gridMode === 'off';
}

function panelChanged() {
    const e = active();
    if (!e) return;
    downloadedIds.delete(e.id);
    e.paperSize = PAPER_MM[el('paperSize').value] ? el('paperSize').value : 'A4';
    e.orientation = el('orientation').value === 'landscape' ? 'landscape' : 'portrait';
    e.scale = parseInt(el('scale').value, 10) || 20000;
    e.margin = parseMargin(el('margin').value);
    e.layer = 'maastokartta';
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
    state.maps.forEach((e, i) => {
        const li = document.createElement('li');
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'rail-map';
        b.dataset.key = `rail-${e.id}`;
        b.textContent = String(i + 1);
        if (generatingIds.has(e.id)) b.classList.add('generating');
        else if (downloadedIds.has(e.id)) b.classList.add('done');
        const label = `${nameOf(e)} · ${summaryOf(e)}`;
        b.setAttribute('aria-label', label);
        b.title = label;
        b.setAttribute('aria-pressed', String(e.id === state.activeId));
        b.addEventListener('click', () => selectAndReveal(e));
        li.append(b);
        ul.append(li);
    });
    if (focusKey) ul.querySelector(`[data-key="${focusKey}"]`)?.focus();
}

function listRow(e) {
    const isActive = e.id === state.activeId;
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
    if (generatingIds.has(e.id)) {
        dlBtn.classList.add('generating');
        dlBtn.innerHTML = icon('loader');
        dlBtn.setAttribute('aria-label', t('map.generating', { name }));
        dlBtn.setAttribute('aria-disabled', 'true');
    } else if (downloadedIds.has(e.id)) {
        dlBtn.classList.add('done');
        dlBtn.innerHTML = icon('check');
        dlBtn.setAttribute('aria-label', t('map.downloadAgain', { name }));
    } else {
        dlBtn.innerHTML = icon('download');
        dlBtn.setAttribute('aria-label', t('map.download', { name }));
    }
    dlBtn.title = dlBtn.getAttribute('aria-label');
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
    const ul = el('mapList');
    const listFocus = ul.contains(focused) ? focused.dataset.key : null;
    const railFocus = el('railMaps').contains(focused) ? focused.dataset.key : null;

    ul.replaceChildren(...state.maps.map(listRow));
    if (listFocus) {
        (ul.querySelector(`[data-key="${listFocus}"]`)
            ?? ul.querySelector(`[data-key="select-${state.activeId}"]`))?.focus();
    }
    renderRail(railFocus);

    const cur = active();
    el('activeName').textContent = cur ? nameOf(cur) : '';
    const summary = el('sheetSummary');
    summary.textContent = '';
    if (cur) {
        const b = document.createElement('b');
        b.textContent = nameOf(cur);
        summary.append(b, ` · ${summaryOf(cur)}`);
    }
    el('downloadAllBtn').textContent = state.maps.length > 1
        ? t('download.allCount', { count: state.maps.length }) : t('download.one');
    refreshLabels();
}

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
});
const covered = () => ({ left: panes.coveredLeft(), bottom: sheet.coveredBottom() });

// Centre of the part of the map the user can actually see
// (from the view, so it works before the first frame has rendered)
function visibleCenter() {
    return visibleCenterOf(view.getCenter(), view.getResolution(), covered());
}

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
addTranslate(map, activeLayer, {
    onMove: ids => ids.forEach(id => { const e = getEntry(id); if (e) syncLabel(e); }),
    onEnd: ids => {
        ids.forEach(id => downloadedIds.delete(id));
        persist();
        renderList();
    },
});

// Double-click centres the selected rectangle there (no zoom)
map.on('dblclick', ev => {
    const cur = active();
    if (!cur) return;
    placeEntry(cur, ev.coordinate);
    areaChanged(cur);
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
if (!loadSnapshot(savedSnapshot())) newMap();

for (const id of ['paperSize', 'orientation', 'scale', 'margin', 'gridMode', 'gridSpacing']) {
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

// --- GPX route -------------------------------------------------------------------
const gpxBtn = el('gpxBtn');
const gpxInput = el('gpxInput');
let gpxName = '';   // name of the loaded route, '' when none

function renderGpx() {
    if (gpxName) setButton(gpxBtn, 'x', t('gpx.remove'));
    else setButton(gpxBtn, 'upload', t('gpx.load'));
    el('gpxInfo').textContent = gpxName;
    el('sharedSummary').textContent = gpxName ? t('shared.summaryRoute', { name: gpxName }) : t('shared.summary');
}

gpxBtn.addEventListener('click', () => {
    if (!gpxLayer.getSource().getFeatures().length) { gpxInput.click(); return; }
    gpxLayer.getSource().clear();
    gpxName = '';
    renderGpx();
});

gpxInput.addEventListener('change', () => {
    const file = gpxInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        let features;
        try { features = readGpx(reader.result); } catch { features = []; }
        if (!gpxRoutes(features).length) {
            notices.show('gpx', 'error', () => t('gpx.noRoute', { file: file.name }));
            return;
        }
        notices.close('gpx');
        gpxLayer.getSource().clear();
        gpxLayer.getSource().addFeatures(features);
        // Prefer the track/route name; waypoints (Points) also carry names
        const line = features.find(f => f.getGeometry()?.getType() !== 'Point' && f.get('name'));
        gpxName = line?.get('name') || file.name.replace(/\.gpx$/i, '');
        renderGpx();
        view.fit(gpxLayer.getSource().getExtent(), { padding: [50, 50, 50, 50] });
    };
    reader.readAsText(file);
    gpxInput.value = '';
});

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
        routes: gpxRoutes(gpxLayer.getSource().getFeatures()),
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
    if (!state.maps.length) return;
    setDownloadAllBusy(true);
    const shared = sharedSettings();
    await trackJob('/generate-maps-batch-async', {
        output: el('batchFormat').value,
        maps: state.maps.map(e => buildPayload(e, entryExtent(e), shared)),
    }, 'result-batch');
    setDownloadAllBusy(false);
});

// --- Language -------------------------------------------------------------------------
// Option labels with numbers follow the language's digit grouping
function formatOptions() {
    for (const o of el('scale').options) o.textContent = `1:${Number(o.value).toLocaleString(locale())}`;
    for (const o of el('gridSpacing').options) o.textContent = `${Number(o.value).toLocaleString(locale())} m`;
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
    renderGpx();
    langMenu.sync();
    renderList();
}

onLangChange(renderScriptText);
renderScriptText();
