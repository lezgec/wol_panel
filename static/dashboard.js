'use strict';

function openDialog(dialog) {
    if (!dialog.open) dialog.showModal();
}

document.querySelectorAll('[data-open-dialog]').forEach(button => {
    button.addEventListener('click', () => openDialog(document.getElementById(button.dataset.openDialog)));
});
document.querySelectorAll('[data-close-dialog]').forEach(button => {
    button.addEventListener('click', () => button.closest('dialog').close());
});
document.querySelectorAll('[data-auto-open]').forEach(openDialog);

document.querySelectorAll('[data-wake-form]').forEach(form => {
    const select = form.querySelector('[name="wake_method"]');
    const fields = form.querySelector('[data-router-fields]');
    const note = form.querySelector('[data-method-note]');
    function update() {
        const router = select.value === 'router';
        fields.hidden = !router;
        fields.querySelectorAll('input').forEach(input => {
            input.disabled = !router;
            input.required = router;
        });
        note.textContent = select.value === 'alexa'
            ? 'Encendido desde la app Alexa o por voz usando el Echo de casa.'
            : select.value === 'local'
            ? 'Solo funciona cuando el servidor de esta web está en la red de la PC.'
            : 'Encendido desde esta web usando el destino y el puerto de tu router.';
    }
    select.addEventListener('change', update);
    update();
});

document.querySelectorAll('[data-action-form]').forEach(form => {
    const kind = form.querySelector('[name="kind"]');
    const fields = form.querySelector('[data-app-fields]');
    const app = form.querySelector('[name="app_key"]');
    function update() {
        fields.hidden = kind.value !== 'launch';
        app.disabled = fields.hidden;
        app.required = !fields.hidden;
    }
    kind.addEventListener('change', update);
    update();
});

const pairForm = document.querySelector('[data-pair-form]');
function updatePairFields() {
    if (!pairForm) return;
    const fields = pairForm.querySelector('[data-new-pc-fields]');
    fields.hidden = pairForm.querySelector('[name="device_id"]').value !== '0';
    fields.querySelectorAll('input').forEach(input => {
        input.disabled = fields.hidden;
        input.required = !fields.hidden;
    });
}
if (pairForm) {
    pairForm.querySelector('[name="device_id"]').addEventListener('change', updatePairFields);
    updatePairFields();
}
document.querySelectorAll('[data-link-device]').forEach(button => {
    button.addEventListener('click', () => {
        const dialog = document.getElementById('link-pc');
        dialog.querySelector('[name="device_id"]').value = button.dataset.linkDevice;
        updatePairFields();
        openDialog(dialog);
    });
});

document.querySelectorAll('[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
});

function openSelectedCard() {
    const id = window.location.hash.slice(1);
    const card = document.getElementById(id);
    if (card && card.matches('[data-device-card]')) card.open = true;
}
document.querySelectorAll('[data-device-card]').forEach(card => {
    card.addEventListener('toggle', () => {
        if (card.open) {
            document.querySelectorAll('[data-device-card]').forEach(other => {
                if (other !== card) other.open = false;
            });
            window.history.replaceState(null, '', window.location.pathname + window.location.search + '#' + card.id);
        } else if (window.location.hash === '#' + card.id) {
            window.history.replaceState(null, '', window.location.pathname + window.location.search);
        }
    });
});
window.addEventListener('hashchange', openSelectedCard);
openSelectedCard();
