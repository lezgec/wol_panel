// Slots stay hidden until a configured consent manager explicitly permits ads.
// This event must be wired to the site's certified CMP when AdSense is activated.
(() => {
    const spaces = [...document.querySelectorAll('[data-ad-space]')];
    if (!spaces.length || window.ReactNativeWebView) return;
    let loaded = false;
    async function activate() {
        if (loaded || window.wolAdsConsent !== true) return;
        const response = await fetch('/api/mobile/v1/plan', {credentials:'same-origin',cache:'no-store'});
        if (!response.ok) return;
        const {plan} = await response.json();
        if (!plan?.ads?.enabled || !plan.ads.web) return;
        const client = spaces[0].dataset.client;
        if (!/^ca-pub-\d{16}$/.test(client)) return;
        loaded = true;
        const script = document.createElement('script');
        script.async = true; script.crossOrigin = 'anonymous';
        script.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='+client;
        script.onload = () => spaces.forEach(space => {
            if (!/^\d+$/.test(space.dataset.slot)) return;
            const slot = document.createElement('ins'); slot.className = 'adsbygoogle';
            slot.style.display = 'block'; slot.dataset.adClient = client; slot.dataset.adSlot = space.dataset.slot;
            slot.dataset.adFormat = 'auto'; slot.dataset.fullWidthResponsive = 'true';
            space.append(slot); space.hidden = false;
            (window.adsbygoogle = window.adsbygoogle || []).push({});
        });
        document.head.append(script);
    }
    window.addEventListener('wol-ads-consent', () => {
        if (window.wolAdsConsent !== true) spaces.forEach(space => { space.hidden=true;space.replaceChildren(); });
        else void activate().catch(()=>undefined);
    });
    void activate().catch(()=>undefined);
    setInterval(async () => {
        if (document.hidden || !loaded) return;
        try {
            const response = await fetch('/api/mobile/v1/plan',{credentials:'same-origin',cache:'no-store'});
            const {plan} = response.ok ? await response.json() : {};
            if (!plan?.ads?.enabled) spaces.forEach(space=>{space.hidden=true;space.replaceChildren();});
        } catch (_) { spaces.forEach(space=>{space.hidden=true;space.replaceChildren();}); }
    },60000);
})();
