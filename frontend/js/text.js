// User-facing strings built from data, in the given language. Pure.
import { ATLAS_MAX } from './atlas.js';
import { LOCALES, translate } from './strings.js';

const num = (n, lang) => n.toLocaleString(LOCALES[lang] ?? LOCALES.en);

export function displayName(entry, index, lang = 'en') {
    return entry.title || translate(lang, 'map.default', { n: index + 1 });
}

// Short form for the label drawn on the map
export function shortName(name) {
    return name.length > 16 ? `${name.slice(0, 15)}…` : name;
}

// "A4 · 1:20,000" / "A4 · 1:20 000"
export function mapSummary({ paperSize, scale }, lang = 'en') {
    return `${paperSize} · 1:${num(scale, lang)}`;
}

export function deletedLabel(count, lang = 'en') {
    return count === 1 ? translate(lang, 'deleted.one') : translate(lang, 'deleted.many', { count });
}

// "Created 7 maps for <name>"; `kind` 'cover' (a route) or 'atlas'
export function createdLabel(count, name, lang = 'en', kind = 'cover') {
    return count === 1 ? translate(lang, `${kind}.createdOne`, { name })
        : translate(lang, `${kind}.created`, { count: num(count, lang), name });
}

// "12 maps · 3 rows × 5 columns", or the too-many warning above ATLAS_MAX
export function atlasCountLabel(count, rows, cols, lang = 'en') {
    if (count > ATLAS_MAX) return translate(lang, 'atlas.tooMany', { count: num(count, lang) });
    const phrase = (n, key) => (n === 1 ? translate(lang, `${key}One`) : translate(lang, key, { count: num(n, lang) }));
    return translate(lang, count === 1 ? 'atlas.countOne' : 'atlas.count', {
        count: num(count, lang), rows: phrase(rows, 'atlas.rows'), cols: phrase(cols, 'atlas.cols'),
    });
}

// On-screen credit "© Maanmittauslaitos, CC BY 4.0, MM/YYYY" (the licensor's name, the
// same in both languages). The month comes from the server's licence line
// (Finnish time); today is the fallback.
export function attributionLabel(serverText, now = new Date()) {
    const month = /(\d{2}\/\d{4})/.exec(serverText ?? '')?.[1]
        ?? `${String(now.getMonth() + 1).padStart(2, '0')}/${now.getFullYear()}`;
    return `© Maanmittauslaitos, CC BY 4.0, ${month}`;
}

export function progressLabel(running, secs, lang = 'en') {
    return running === 1
        ? translate(lang, 'progress.one', { secs })
        : translate(lang, 'progress.many', { count: running, secs });
}
