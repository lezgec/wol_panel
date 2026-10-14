// Google CMP owns regional consent. Only explicit, fresh account policy allows slots.
(() => {
    'use strict';
    const spaces = [...document.querySelectorAll('[data-ad-space]')];
    if (!spaces.length || window.ReactNativeWebView) return;
    const client = spaces[0].dataset.client;
    if (!/^ca-pub-\d{16}$/.test(client)) return;
    const privacy = document.querySelector('[data-ad-privacy]');
    const usPrivacy = document.querySelector('[data-ad-us-privacy]');
    let plan, checking, sdk, sdkReady = false, eu = false, us = false, usApplies = false, usReady = false;
    let tcfListening = false, gppListening = false, generation = 0, rendering = false;
    const observers = new Map();
    const eligible = () => plan?.tier === 'free' && !plan.suspended &&
        plan.ad_free_until <= Date.now()/1000 && plan.ads?.web === true &&
        Array.isArray(plan.ads.allowed_views) && plan.ads.allowed_views.includes('home');
    const consent = () => eu && us && navigator.globalPrivacyControl !== true;
    const allowed = () => eligible() && consent() && !document.hidden;
    function hide() {
        generation++;
        if (window.adsbygoogle) window.adsbygoogle.pauseAdRequests = 1;
        for (const space of spaces) {
            observers.get(space)?.disconnect(); observers.delete(space);
            space.hidden = true;
            space.querySelector('ins')?.remove();
        }
    }
    async function refresh() {
        if (checking) return checking;
        checking = (async () => {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 8000);
            try {
                const response = await fetch('/api/mobile/v1/plan', {credentials:'same-origin',cache:'no-store',signal:controller.signal});
                const value = response.ok ? await response.json() : {};
                plan = value.plan;
            } catch (_) { plan = undefined; }
            finally { clearTimeout(timeout); }
            if (!eligible()) hide();
        })().finally(() => { checking = undefined; });
        return checking;
    }
    function decision() {
        if (!consent()) hide();
        else void sync();
    }
    function purposeAllowed(data, purpose) {
        const restriction = data.publisher?.restrictions?.[purpose]?.[755];
        if (restriction === 0 || (restriction !== undefined && ![1,2].includes(restriction))) return false;
        const granted = data.vendor?.consents?.[755] === true && data.purpose?.consents?.[purpose] === true;
        // Storage always requires consent. Google's other NPA purposes can use
        // the CMP's established legitimate interest, respecting restrictions.
        if (purpose === 1) return restriction !== 2 && granted;
        const legitimate = data.vendor?.legitimateInterests?.[755] === true && data.purpose?.legitimateInterests?.[purpose] === true;
        return restriction === 1 ? granted : restriction === 2 ? legitimate : granted || legitimate;
    }
    function receiveTcf(data, success) {
        eu = success === true && (data?.gdprApplies === false ||
            (data?.gdprApplies === true && data.cmpStatus === 'loaded' &&
             ['tcloaded','useractioncomplete'].includes(data.eventStatus) &&
             [1,2,7,9,10].every(purpose => purposeAllowed(data, purpose))));
        if (privacy) privacy.hidden = !(eligible() && success && data?.gdprApplies === true);
        decision();
    }
    function optedOut(value) {
        if (!value || typeof value !== 'object') return false;
        return Object.entries(value).some(([key,field]) =>
            (['SaleOptOut','SharingOptOut','TargetedAdvertisingOptOut','OptOutSale'].includes(key) && (field === 1 || field === 'Y')) ||
            (['Gpc','GPC'].includes(key) && field === true) || optedOut(field));
    }
    function receiveGpp(data, success) {
        const sections = Object.entries(data?.parsedSections || {}).filter(([name]) => name.startsWith('us'));
        const ready = success === true && data?.cmpStatus === 'loaded' && data?.signalStatus === 'ready';
        const knownChoices = value => value && typeof value === 'object' && Object.entries(value).some(([key, field]) =>
            (['SaleOptOut','SharingOptOut','TargetedAdvertisingOptOut','OptOutSale'].includes(key) && [0,1,2,'Y','N'].includes(field)) || knownChoices(field));
        // Unknown or incomplete state is never treated as permission.
        us = usReady && ready && (!usApplies || (sections.length > 0 && sections.every(([,value]) => knownChoices(value)))) && !sections.some(([,value]) => optedOut(value));
        decision();
    }
    function listen() {
        if (!tcfListening && typeof window.__tcfapi === 'function') {
            tcfListening = true;
            window.__tcfapi('addEventListener', 2, receiveTcf);
        }
        if (!gppListening && typeof window.__gpp === 'function') {
            gppListening = true;
            window.__gpp('addEventListener', (event, success) => {
                if (event?.pingData) receiveGpp(event.pingData, success);
                else { us = false; decision(); }
            });
        }
    }
    function bootstrap() {
        if (sdk) return sdk;
        window.googlefc = window.googlefc || {};
        const fc = window.googlefc;
        fc.usstatesoptout = fc.usstatesoptout || {};
        fc.usstatesoptout.overrideDnsLink = true;
        fc.callbackQueue = fc.callbackQueue || [];
        fc.controlledMessagingFunction = async message => {
            await refresh(); message.proceed(eligible());
        };
        fc.callbackQueue.push({CONSENT_API_READY: listen});
        fc.callbackQueue.push({CONSENT_DATA_READY: listen});
        fc.callbackQueue.push({INITIAL_US_STATES_OPT_OUT_DATA_READY: () => {
            const api = fc.usstatesoptout, states = api.InitialUsStatesOptOutStatusEnum;
            const status = api.getInitialUsStatesOptOutStatus?.();
            if (!states) return;
            usReady = typeof status === 'number' && [states.DOES_NOT_APPLY,states.NOT_OPTED_OUT,states.OPTED_OUT].includes(status);
            usApplies = status !== states.DOES_NOT_APPLY;
            us = usReady && (status === states.DOES_NOT_APPLY || status === states.NOT_OPTED_OUT);
            if (usPrivacy) usPrivacy.hidden = !(eligible() && usApplies && usReady);
            listen();
            if (usApplies && typeof window.__gpp === 'function') {
                us = false; window.__gpp('ping', receiveGpp);
            }
            decision();
        }});
        // The standard AdSense tag deploys the published Google CMP. No ins/push
        // ad request is made until both regional decisions are ready and allowed.
        window.adsbygoogle = window.adsbygoogle || [];
        window.adsbygoogle.requestNonPersonalizedAds = 1;
        window.adsbygoogle.pauseAdRequests = 1;
        sdk = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.async = true; script.crossOrigin = 'anonymous';
            script.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='+client;
            script.onload = () => { sdkReady = true; resolve(); };
            script.onerror = () => { script.remove(); reject(new Error('AdSense no disponible')); };
            document.head.append(script);
        }).catch(() => { sdk = undefined; sdkReady = false; hide(); });
        return sdk;
    }
    async function render() {
        if (rendering || !allowed()) return;
        rendering = true;
        const stamp = generation;
        try {
            await sdk;
            await refresh();
            if (!sdkReady || !allowed() || stamp !== generation) return;
            window.adsbygoogle.pauseAdRequests = 0;
            for (const space of spaces) {
                const existing = space.querySelector('ins');
                if (existing) { space.hidden = existing.dataset.adStatus === 'unfilled'; continue; }
                if (!/^\d+$/.test(space.dataset.slot)) continue;
                space.hidden = false;
                if (space.getBoundingClientRect().width <= 0) { space.hidden = true; continue; }
                const slot = document.createElement('ins');
                slot.className = 'adsbygoogle'; slot.style.display = 'block';
                slot.dataset.adClient = client; slot.dataset.adSlot = space.dataset.slot;
                slot.dataset.adFormat = space.dataset.layout === 'banner' ? 'horizontal' : 'rectangle';
                slot.dataset.fullWidthResponsive = 'true';
                const observer = new MutationObserver(() => {
                    if (!allowed() || slot.dataset.adStatus === 'unfilled') space.hidden = true;
                });
                observer.observe(slot, {attributes:true,attributeFilter:['data-ad-status']});
                observers.set(space, observer);
                space.append(slot); space.hidden = false;
                window.adsbygoogle.push({});
            }
        } finally { rendering = false; }
    }
    async function sync() {
        if (document.hidden) return;
        try {
            await refresh();
            if (!eligible()) return;
            void bootstrap();
            if (allowed()) await render();
        } catch (_) { hide(); }
    }
    privacy?.addEventListener('click', () => {
        eu = false; hide();
        window.googlefc.callbackQueue.push({CONSENT_API_READY: () => window.googlefc.showRevocationMessage()});
    });
    usPrivacy?.addEventListener('click', () => {
        us = false; hide();
        window.googlefc.callbackQueue.push({INITIAL_US_STATES_OPT_OUT_DATA_READY: () =>
            window.googlefc.usstatesoptout.openConfirmationDialog(opted => {
                if (opted) { us = false; decision(); }
                else if (typeof window.__gpp === 'function') window.__gpp('ping', receiveGpp);
            })});
    });
    // Returning to the tab checks policy without refreshing an existing ad.
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void sync(); });
    window.addEventListener('focus', () => void sync());
    window.addEventListener('pageshow', () => void sync());
    setInterval(() => void sync(), 60000);
    void sync();
})();
