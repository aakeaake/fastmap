// The route card: everything about the route (draw, import, name, edit,
// export, remove, print style), opened from the route button on the map's
// right edge. Non-modal: the map stays usable while it is open.
// On phones it takes the bottom sheet's place: the node moves into the
// sheet (after its header), which keeps its grabber and heights, and the
// sheet's mode panel hides while the card is open ([data-card]).
//   open()             show it and move focus to its heading
//   close({ focus })   hide it; focus goes back to the button unless false
//   toggle(), isOpen()
export function createRouteCard({ button, card, closeBtn, panel, sheet }) {
    const title = card.querySelector('h2');
    const home = { parent: card.parentNode, next: card.nextSibling };
    const head = panel.querySelector('.sheet-head');

    // Phones: inside the sheet; wider screens: beside the map controls
    function place() {
        if (sheet.phone.matches) {
            if (card.parentNode !== panel) panel.insertBefore(card, head.nextSibling);
        } else if (card.parentNode !== home.parent) {
            home.parent.insertBefore(card, home.next);
        }
        panel.toggleAttribute('data-card', sheet.phone.matches && !card.hidden);
    }

    function setOpen(open) {
        card.hidden = !open;
        button.setAttribute('aria-expanded', String(open));
        place();
    }

    const api = {
        isOpen: () => !card.hidden,
        open() {
            setOpen(true);
            if (sheet.phone.matches && sheet.state === 'peek') sheet.setSheet('half');
            title.focus();
        },
        close({ focus = true } = {}) {
            if (card.hidden) return;
            setOpen(false);
            if (focus) button.focus();
        },
        toggle() {
            if (api.isOpen()) api.close(); else api.open();
        },
    };

    closeBtn.addEventListener('click', () => api.close());
    card.addEventListener('keydown', ev => {
        if (ev.key !== 'Escape') return;
        ev.preventDefault();
        api.close();
    });
    sheet.phone.addEventListener('change', place);
    place();
    return api;
}
