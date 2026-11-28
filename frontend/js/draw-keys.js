// Enter / Backspace / Esc drive route and area drawing (js/map.js), except
// while typing in a field or inside an open dialog (the info popup), where
// the keys belong to that field or dialog. Pure, so it is unit-tested.
export const drawKeysIgnored = t =>
    !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || !!t.closest?.('dialog[open]'));
