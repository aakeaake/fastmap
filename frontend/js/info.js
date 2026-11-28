// Info button and its modal (<dialog>): what FastMap is and how to use it.
// The browser's showModal() gives the backdrop, keeps focus inside, closes
// on Esc and returns focus to the opener. Here: open from the button,
// close on a backdrop click, and open by itself until it has been closed
// once (remembered per browser).
import { INFO_KEY } from './constants.js';

export function createInfo({ button, dialog, storage }) {
    const store = () => storage ?? globalThis.localStorage;

    function open() {
        if (!dialog.open) dialog.showModal();
    }

    button.addEventListener('click', open);
    // The dialog has no padding, so a click on the dialog itself is on the backdrop
    dialog.addEventListener('click', ev => { if (ev.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => {
        try { store().setItem(INFO_KEY, '1'); } catch { /* ignore */ }
    });

    let seen = false;
    try { seen = store().getItem(INFO_KEY) === '1'; } catch { /* ignore */ }
    if (!seen) open();

    return { open };
}
