// Numbers for the UI: the language's decimal mark, but thousands always
// grouped with a no-break space ("1:20 000", "1 234 maps"), in English too.
// Pure, so it runs in Node tests.
const GROUP = ' ';

export function formatNumber(n, locale, options = {}) {
    return new Intl.NumberFormat(locale, options).formatToParts(n)
        .map(p => (p.type === 'group' ? GROUP : p.value))
        .join('');
}
