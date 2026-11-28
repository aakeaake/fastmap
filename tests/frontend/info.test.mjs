import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createInfo } from '../../frontend/js/info.js';
import { INFO_KEY } from '../../frontend/js/constants.js';

// A <dialog> stand-in: showModal() throws when already open, like the real one
function fakeDialog() {
    const d = new EventTarget();
    d.open = false;
    d.shown = 0;
    d.showModal = () => {
        if (d.open) throw new Error('InvalidStateError');
        d.open = true;
        d.shown++;
    };
    d.close = () => {
        if (!d.open) return;
        d.open = false;
        d.dispatchEvent(new Event('close'));
    };
    return d;
}
const memory = (init = {}) => {
    const m = { ...init };
    return { getItem: k => m[k] ?? null, setItem: (k, v) => { m[k] = String(v); }, m };
};
const broken = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };

test('the info popup opens by itself on the first visit', () => {
    const dialog = fakeDialog();
    createInfo({ button: new EventTarget(), dialog, storage: memory() });
    assert.equal(dialog.shown, 1);
});

test('the info popup stays closed once seen', () => {
    const dialog = fakeDialog();
    createInfo({ button: new EventTarget(), dialog, storage: memory({ [INFO_KEY]: '1' }) });
    assert.equal(dialog.shown, 0);
});

test('closing the info popup marks it seen', () => {
    const dialog = fakeDialog();
    const storage = memory();
    createInfo({ button: new EventTarget(), dialog, storage });
    dialog.close();
    assert.equal(storage.m[INFO_KEY], '1');
});

test('the info button opens it, and a second click while open does not throw', () => {
    const dialog = fakeDialog();
    const button = new EventTarget();
    createInfo({ button, dialog, storage: memory({ [INFO_KEY]: '1' }) });
    button.dispatchEvent(new Event('click'));
    button.dispatchEvent(new Event('click'));
    assert.equal(dialog.shown, 1);
});

test('a click on the backdrop closes the info popup', () => {
    const dialog = fakeDialog();
    createInfo({ button: new EventTarget(), dialog, storage: memory() });
    dialog.dispatchEvent(new Event('click'));   // target === dialog
    assert.equal(dialog.open, false);
});

test('blocked storage: the info popup still opens, and closing does not throw', () => {
    const dialog = fakeDialog();
    createInfo({ button: new EventTarget(), dialog, storage: broken });
    assert.equal(dialog.shown, 1);
    assert.doesNotThrow(() => dialog.close());
});
