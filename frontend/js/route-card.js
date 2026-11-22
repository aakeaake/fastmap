// The route card: everything about the route (draw, import, name, edit,
// export, remove, print style), opened from the route button on the map's
// right edge. Non-modal: the map stays usable while it is open.
//   open()             show it and move focus to its heading
//   close({ focus })   hide it; focus goes back to the button unless false
//   toggle(), isOpen()
export function createRouteCard({ button, card, closeBtn, panel, sheet }) {
    const title = card.querySelector('h2');

    function setOpen(open) {
        card.hidden = !open;
        button.setAttribute('aria-expanded', String(open));
    }

    const api = {
        isOpen: () => !card.hidden,
        open() {
            setOpen(true);
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
    return api;
}
