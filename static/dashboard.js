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

document.querySelectorAll('[data-method-note]').forEach(note => { note.textContent = 'Encendido desde la app Alexa o por voz usando un Echo compatible en la red de casa.'; });

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

// Refresh connection only; preserve open forms and keep commands explicitly user initiated.
if (document.querySelector('[data-pc-status]')) {
    let checkingStatus = false;
    async function refreshPcStatus() {
        if (document.hidden || checkingStatus) return;
        checkingStatus = true;
        try {
            const response = await fetch('/windows/status', {credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
            if (!response.ok) throw new Error('No se pudo consultar el estado.');
            const data = await response.json();
            document.querySelectorAll('[data-pc-status]').forEach(badge => {
                const pc = data.devices[badge.dataset.pcStatus];
                const ready = pc?.state === 'ready';
                const connected = ready || pc?.state === 'connected';
                badge.classList.toggle('is-online', connected);
                badge.textContent = ready ? 'PC conectado · control disponible' : connected ? 'PC conectado · agente de sesión sin conexión' : pc?.active ? 'Sin conexión' : 'Sin vincular';
                document.querySelectorAll('[data-pc-run]').forEach(button => {
                    if (button.dataset.pcRun === badge.dataset.pcStatus) button.disabled = !ready || pc?.plan_active === false || (button.dataset.premiumAction === 'true' && !pc?.can_launch);
                });
                const notice = document.querySelector('[data-pc-notice="' + badge.dataset.pcStatus + '"]');
                if (notice) {
                    notice.hidden = ready;
                    notice.textContent = connected ? 'El PC está conectado. Inicia sesión en Windows y abre el agente para usar aplicaciones y comandos.' : 'No hay comunicación reciente. El PC puede estar apagado, suspendido, sin Internet o con el agente cerrado.';
                }
            });
        } catch (_) {
            document.querySelectorAll('[data-pc-status]').forEach(badge => {
                badge.classList.remove('is-online');
                badge.textContent = 'Estado sin actualizar';
            });
            document.querySelectorAll('[data-pc-run]').forEach(button => { button.disabled = true; });
        }
        finally { checkingStatus = false; }
    }
    setInterval(refreshPcStatus, 5000);
    document.addEventListener('visibilitychange', refreshPcStatus);
}
