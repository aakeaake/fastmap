// User-facing strings built from data. Pure.

const fi = n => n.toLocaleString('fi-FI');

export function displayName(entry, index) {
    return entry.title || `Kartta ${index + 1}`;
}

// Short form for the label drawn on the map
export function shortName(name) {
    return name.length > 16 ? `${name.slice(0, 15)}…` : name;
}

// "A4 · 1:20 000"
export function mapSummary({ paperSize, scale }) {
    return `${paperSize} · 1:${fi(scale)}`;
}

export function deletedLabel(count) {
    return count === 1 ? 'Kartta poistettu' : `${count} karttaa poistettu`;
}

// On-screen credit "© Maanmittauslaitos MM/YYYY". The month comes from the
// server's licence line (Finnish time); today is the fallback.
export function attributionLabel(serverText, now = new Date()) {
    const month = /(\d{2}\/\d{4})/.exec(serverText ?? '')?.[1]
        ?? `${String(now.getMonth() + 1).padStart(2, '0')}/${now.getFullYear()}`;
    return `© Maanmittauslaitos ${month}`;
}

export function progressLabel(running, secs) {
    const what = running === 1 ? 'Luodaan PDF:ää' : `Luodaan ${running} tiedostoa`;
    return `${what}… ${secs} s`;
}
