// Inline SVG icons: one stroke family on a 24px grid.

const ICON_PATHS = {
    download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    loader: '<path d="M12 3a9 9 0 1 0 9 9"/>',
    x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    upload: '<path d="M12 20V9"/><path d="m7 14 5-5 5 5"/><path d="M5 4h14"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/>',
    target: '<circle cx="12" cy="12" r="7"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    collapse: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="m16 10-2 2 2 2"/>',
    expand: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="m14 10 2 2-2 2"/>',
    sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
};

export function icon(name) {
    return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name]}</svg>`;
}

// Icon + text label inside a button
export function setButton(btn, iconName, text) {
    btn.innerHTML = `${icon(iconName)}<span></span>`;
    btn.lastChild.textContent = text;
}

// Flags for the language switch, drawn as SVG (emoji flags render as plain
// letters on Windows). United Kingdom for English, Finland for Finnish.
const FLAGS = {
    en: '<svg class="flag" viewBox="0 0 60 30" aria-hidden="true"><clipPath id="flag-uk-c"><path d="M30 15h30v15zv15H0zH0V0zV0h30z"/></clipPath>'
        + '<path d="M0 0v30h60V0z" fill="#012169"/><path d="M0 0l60 30m0-30L0 30" stroke="#fff" stroke-width="6"/>'
        + '<path d="M0 0l60 30m0-30L0 30" clip-path="url(#flag-uk-c)" stroke="#c8102e" stroke-width="4"/>'
        + '<path d="M30 0v30M0 15h60" stroke="#fff" stroke-width="10"/><path d="M30 0v30M0 15h60" stroke="#c8102e" stroke-width="6"/></svg>',
    fi: '<svg class="flag" viewBox="0 0 18 11" aria-hidden="true"><path d="M0 0h18v11H0z" fill="#fff"/>'
        + '<path d="M5 0h3v11H5zM0 4h18v3H0z" fill="#002f6c"/></svg>',
};

export function flag(lang) {
    return FLAGS[lang] ?? '';
}

// Fill every [data-icon] placeholder in the markup
export function hydrateIcons(root = document) {
    root.querySelectorAll('[data-icon]').forEach(n => { n.innerHTML = icon(n.dataset.icon); });
}
