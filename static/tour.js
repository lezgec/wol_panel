'use strict';

// No registration, pairing, command execution or purchase is performed by the tour.
const wolproTourSteps = [
    {title:'Tu primer equipo empieza aquí', text:'Te acompañamos desde el registro de un equipo hasta sus acciones Pro. Puedes avanzar, volver o cerrar el recorrido en cualquier momento.', example:'1. Registra tu equipo\n2. Vincula Alexa y el agente\n3. Consulta el estado y crea acciones', target:'.workspace-intro'},
    {title:'Ponle nombre y dirección MAC', text:'Pulsa Añadir equipo. Usa un nombre fácil de pronunciar y la MAC del adaptador con Wake-on-LAN habilitado. La MAC identifica la tarjeta de red de tu PC.', example:'Nombre: PC Escritorio\nMAC: AA:BB:CC:DD:EE:FF\nEjemplo: utiliza la MAC real de tu equipo.', target:'[data-open-dialog="add-device"]'},
    {title:'Enciende con Alexa', text:'Activa Wake-on-LAN en tu PC. Vincula tu cuenta en la skill WoL Pro desde la app Alexa y descubre los equipos. Necesitas un Echo compatible en la red del PC.', example:'«Alexa, enciende PC Escritorio»\nTambién puedes usar la app Alexa.', target:'.alexa-card'},
    {title:'Todas las opciones en su tarjeta', text:'Expande el equipo para ver encendido, vinculación, acciones y ajustes. Puedes modificar su nombre y MAC. Eliminarlo también elimina su vinculación e historial.', example:'Mis equipos → tu PC\nEncendido · Control de PC · Modificar equipo', target:'.device-list'},
    {title:'Instala y vincula el agente', text:'Descarga el agente desde un PC Windows, instálalo y pulsa Vincular cuenta. Confirma el código temporal desde la app móvil o esta web, seleccionando el mismo equipo registrado.', example:'Windows: Vincular cuenta\nApp o web: Control de PC → Vincular PC\nCompara el código antes de confirmar.', target:'.usage-note', control:true},
    {title:'Comprueba si el PC está conectado', text:'El agente informa de la conexión. Su servicio opcional detecta el PC desde el arranque; las acciones requieren la sesión Windows y el agente abierto. Sin conexión no demuestra que esté apagado.', example:'PC conectado → comunicación confirmada\nControl disponible → puedes enviar acciones', target:'.device-list', control:true},
    {title:'Apagado protegido y acciones', text:'Autoriza el apagado en el agente y crea la acción desde Control de PC. El apagado integrado permite 30 segundos para cancelar. El historial muestra si la orden se recibió o quedó sin confirmar.', example:'Control de PC → Crear una acción\nApagar PC → 30 segundos para cancelar', target:'.device-list', control:true},
    {title:'Aplicaciones y comandos Pro', text:'Premium habilita aplicaciones y comandos guardados. Añádelos y autorízalos en el agente; después crea sus acciones en la app o la web. Los comandos personalizados ejecutan tu script y no usan la cancelación del apagado integrado.', example:'Agente: autoriza Spotify\nPanel: crea «Spotify en mi PC»\nAlexa: usa una rutina con esa acción.', target:'.device-list', control:true},
    {title:'Tu plan y la ayuda siempre a mano', text:'Free incluye un equipo activo y apagado protegido. Premium permite hasta diez equipos activos, aplicaciones y comandos, sin publicidad. Consulta Mi plan para ver tu acceso actual. Puedes repetir este tour cuando quieras.', example:'Mi plan → acceso y equipos activos\nTour de WoL Pro → repetir el recorrido', target:'a[href="/plans"]', plan:true},
];

function createTourProgress(storage, key, count) {
    let value = {seen:false, index:0, completed:false};
    let canPersist = true;
    try {
        const saved = JSON.parse(storage.getItem(key) || 'null');
        if (saved && typeof saved.seen === 'boolean' && Number.isInteger(saved.index) && saved.index >= 0 && saved.index < count)
            value = {seen:saved.seen, index:saved.index, completed:saved.completed === true};
    } catch (_) { canPersist = false; }
    return {
        get value() { return {...value}; },
        get automatic() { return canPersist && !value.seen; },
        save(index, completed = false) {
            value = {seen:true, index, completed};
            try { storage.setItem(key, JSON.stringify(value)); } catch (_) { /* Help remains available without storage. */ }
        },
    };
}

if (typeof module !== 'undefined') module.exports = {createTourProgress, wolproTourSteps};

if (typeof document !== 'undefined') {
    const dialog = document.getElementById('wolpro-tour');
    if (dialog) {
        const steps = wolproTourSteps.filter(step => !step.control || dialog.dataset.tourControl === 'true');
        let storage; try { storage = window.localStorage; } catch (_) { storage = {getItem(){throw new Error('Storage unavailable');},setItem(){}}; }
        const progress = createTourProgress(storage, 'wolpro.web-tour.v1.' + dialog.dataset.tourAccount, steps.length);
        let index = progress.value.completed ? 0 : progress.value.index;
        let highlighted;
        let returnFocus;
        function render() {
            const step = steps[index];
            dialog.querySelector('#tour-title').textContent = step.title;
            dialog.querySelector('#tour-description').textContent = step.text;
            dialog.querySelector('.tour-example').textContent = step.example;
            dialog.querySelector('.tour-progress').textContent = `Paso ${index + 1} de ${steps.length}`;
            const meter = dialog.querySelector('progress'); meter.max = steps.length; meter.value = index + 1;
            dialog.querySelector('[data-tour-back]').disabled = index === 0;
            dialog.querySelector('[data-tour-next]').textContent = index === steps.length - 1 ? 'Terminar' : 'Siguiente';
            progress.save(index);
            dialog.querySelector('.tour-content').scrollTop = 0;
        }
        function start() {
            if (document.querySelector('dialog[open]')) return;
            highlighted?.classList.remove('tour-highlight');
            returnFocus = document.activeElement;
            render(); dialog.showModal();
        }
        dialog.querySelector('[data-tour-back]').addEventListener('click', () => { if (index > 0) { index--; render(); } });
        dialog.querySelector('[data-tour-next]').addEventListener('click', () => {
            if (index < steps.length - 1) { index++; render(); }
            else { progress.save(0, true); index = 0; dialog.close(); }
        });
        dialog.querySelector('[data-tour-restart]').addEventListener('click', () => { index = 0; render(); });
        dialog.querySelector('[data-tour-close]').addEventListener('click', () => dialog.close());
        dialog.addEventListener('close', () => returnFocus?.focus());
        dialog.querySelector('[data-tour-location]').addEventListener('click', () => {
            returnFocus = null;
            dialog.close();
            const step = steps[index];
            let target = step.plan ? document.querySelector('.topbar a[href]:not(.brand)') : document.querySelector(step.target);
            if (step.control && !target?.getClientRects().length) target = document.querySelector('.device-list');
            if (target && target.getClientRects().length) {
                highlighted?.classList.remove('tour-highlight'); highlighted = target;
                target.classList.add('tour-highlight'); target.scrollIntoView({block:'center', behavior:'instant'});
                if (!target.hasAttribute('tabindex') && !target.matches('a,button,input')) target.tabIndex = -1;
                target.focus({preventScroll:true});
            }
        });
        document.querySelectorAll('[data-start-tour]').forEach(button => button.addEventListener('click', start));
        // The mobile client provides its own native tour after login/unlock.
        if (progress.automatic && dialog.dataset.tourAuto !== 'false' && !window.ReactNativeWebView && !document.querySelector('dialog[open]')) start();
    }
}
