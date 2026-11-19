// Current UI language and translating the markup.
//   data-i18n="key"                    sets textContent
//   data-i18n-attr="attr:key;attr:key" sets attributes (aria-label, title,
//                                      placeholder, ...)
// Text built in scripts calls t() and re-renders on onLangChange().
import { DEFAULT_LANG, LANGS, LOCALES, translate } from './strings.js';

const LANG_KEY = 'fastmap.lang';

let lang = (() => {
    try {
        const saved = localStorage.getItem(LANG_KEY);
        return LANGS.includes(saved) ? saved : DEFAULT_LANG;
    } catch {
        return DEFAULT_LANG;
    }
})();
const listeners = [];

export const getLang = () => lang;
export const locale = () => LOCALES[lang];
export const t = (key, params) => translate(lang, key, params);

export function applyTranslations(root = document) {
    document.documentElement.lang = lang;
    document.title = t('page.title');
    root.querySelectorAll('[data-i18n]').forEach(n => { n.textContent = t(n.dataset.i18n); });
    root.querySelectorAll('[data-i18n-attr]').forEach(n => {
        for (const pair of n.dataset.i18nAttr.split(';')) {
            const [attr, key] = pair.split(':');
            n.setAttribute(attr.trim(), t(key.trim()));
        }
    });
}

export function onLangChange(fn) {
    listeners.push(fn);
}

export function setLang(next) {
    if (!LANGS.includes(next) || next === lang) return;
    lang = next;
    try { localStorage.setItem(LANG_KEY, next); } catch { /* ignore */ }
    applyTranslations();
    listeners.forEach(fn => fn(lang));
}
