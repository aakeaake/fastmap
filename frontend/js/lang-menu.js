// Globe button that opens a small language menu (menu / menuitemradio).
// Keyboard: Enter, Space or ArrowDown opens it on the current language;
// arrows move, Home / End jump, Esc closes and returns focus, Tab closes.

export function createLangMenu({ button, menu, current, onPick }) {
    const items = [...menu.querySelectorAll('[role="menuitemradio"]')];

    const isOpen = () => !menu.hidden;

    function sync() {
        for (const it of items) it.setAttribute('aria-checked', String(it.dataset.lang === current()));
    }

    function open(focusChecked = true) {
        sync();
        menu.hidden = false;
        button.setAttribute('aria-expanded', 'true');
        if (focusChecked) (items.find(it => it.dataset.lang === current()) ?? items[0]).focus();
        document.addEventListener('pointerdown', onOutside, true);
    }

    function close({ focus = false } = {}) {
        if (!isOpen()) return;
        menu.hidden = true;
        button.setAttribute('aria-expanded', 'false');
        document.removeEventListener('pointerdown', onOutside, true);
        if (focus) button.focus();
    }

    function onOutside(ev) {
        if (!menu.contains(ev.target) && !button.contains(ev.target)) close();
    }

    function pick(lang) {
        close({ focus: true });
        onPick(lang);
    }

    button.addEventListener('click', () => (isOpen() ? close() : open()));
    button.addEventListener('keydown', ev => {
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); open(); }
    });
    for (const it of items) it.addEventListener('click', () => pick(it.dataset.lang));
    menu.addEventListener('keydown', ev => {
        const i = items.indexOf(document.activeElement);
        const move = { ArrowDown: i + 1, ArrowUp: i - 1, Home: 0, End: items.length - 1 }[ev.key];
        if (move !== undefined) {
            ev.preventDefault();
            items[(move + items.length) % items.length].focus();
        } else if (ev.key === 'Escape') {
            ev.preventDefault();
            close({ focus: true });
        } else if (ev.key === 'Tab') {
            close();
        }
    });

    sync();
    return { sync, close };
}
