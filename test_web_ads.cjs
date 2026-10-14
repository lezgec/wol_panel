const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(__dirname + '/static/web_ads.js', 'utf8');
const free = () => ({tier:'free',suspended:false,ad_free_until:0,ads:{enabled:false,web:true,allowed_views:['home']}});
const settled = async () => { for(let i=0;i<8;i++) await new Promise(setImmediate); };

function harness(options={}) {
    class Element {
        constructor(tag,dataset={}) { this.tag=tag;this.dataset=dataset;this.hidden=true;this.style={};this.children=[];this.events={}; }
        append(node) { node.parent=this;this.children.push(node); }
        remove() { if(this.parent) this.parent.children=this.parent.children.filter(x=>x!==this); }
        querySelector(tag) { return this.children.find(x=>x.tag===tag); }
        getBoundingClientRect() { return {width:this.hidden?0:360}; }
        addEventListener(name,cb) { this.events[name]=cb; }
    }
    const spaces=['banner','rectangle'].map((layout,i)=>new Element('aside',{client:'ca-pub-8703217786138724',slot:String(100+i),layout}));
    const privacy=new Element('button'), usPrivacy=new Element('button'), head=new Element('head');
    const observers=[];
    const document={head,hidden:false,events:{},querySelectorAll:()=>spaces,
        querySelector:s=>s==='[data-ad-privacy]'?privacy:usPrivacy,createElement:tag=>new Element(tag),
        addEventListener(name,cb){this.events[name]=cb;}};
    const window={events:{},addEventListener(name,cb){this.events[name]=cb;},ReactNativeWebView:options.webview};
    const state={plan:options.plan||free(),failure:false,requests:0,interval:undefined,tcf:undefined,gpp:undefined,ping:undefined};
    window.__tcfapi=(_command,_version,cb)=>{state.tcf=cb;};
    window.__gpp=(command,cb)=>{ if(command==='ping') { if(state.ping) cb(state.ping,true); } else state.gpp=cb; };
    const context={document,window,navigator:{globalPrivacyControl:options.gpc||false},Date,AbortController,
        setTimeout:()=>1,clearTimeout:()=>{},setInterval:cb=>{state.interval=cb;},
        MutationObserver:class { constructor(cb){this.cb=cb;observers.push(this);} observe(){} disconnect(){this.disconnected=true;} },
        fetch:async()=>{state.requests++;if(state.failure)throw Error('offline');return {ok:true,json:async()=>({plan:state.plan})};}};
    vm.runInNewContext(source,context);
    const callback=async(key)=>{
        for(const item of [...window.googlefc.callbackQueue]) if(item[key]) item[key]();
        await settled();
    };
    const usStatus=async(status=0)=>{
        Object.assign(window.googlefc.usstatesoptout,{InitialUsStatesOptOutStatusEnum:{DOES_NOT_APPLY:0,NOT_OPTED_OUT:1,OPTED_OUT:2},getInitialUsStatesOptOutStatus:()=>status});
        await callback('INITIAL_US_STATES_OPT_OUT_DATA_READY');
    };
    const tcf=async(data={gdprApplies:false},success=true)=>{state.tcf(data,success);await settled();};
    const gpp=async(data,success=true)=>{state.gpp({pingData:data},success);await settled();};
    const load=async()=>{head.children.find(x=>x.tag==='script').onload();await settled();};
    const visible=()=>spaces.filter(s=>!s.hidden&&s.querySelector('ins')).length;
    const sync=async()=>{state.interval();await settled();};
    return {state,window,document,spaces,privacy,usPrivacy,head,observers,callback,usStatus,tcf,gpp,load,visible,sync};
}
const acceptedEu={gdprApplies:true,cmpStatus:'loaded',eventStatus:'useractioncomplete',vendor:{consents:{755:true}},purpose:{consents:{1:true,2:true,7:true,9:true,10:true}}};
const usData=value=>({cmpStatus:'loaded',signalStatus:'ready',parsedSections:{usnat:[value]}});
async function allowed(h) { await settled();await h.callback('CONSENT_API_READY');await h.tcf();await h.usStatus();await h.load(); }

test('Premium, pause, disabled web, disallowed view and WebView never bootstrap Google',async()=>{
    for(const plan of [{...free(),tier:'premium'},{...free(),suspended:true},{...free(),ad_free_until:Date.now()/1000+1800},{...free(),ads:{web:false,allowed_views:['home']}},{...free(),ads:{web:true,allowed_views:[]}}]) {
        const h=harness({plan});await settled();assert.equal(h.head.children.length,0);assert.equal(h.visible(),0);
    }
    const h=harness({webview:{}});await settled();assert.equal(h.state.requests,0);assert.equal(h.head.children.length,0);
});
test('no slots before both regional decisions and SDK are ready; mobile scope does not block web',async()=>{
    const h=harness();await settled();assert.equal(h.head.children.length,1);
    assert.equal(h.window.adsbygoogle.pauseAdRequests,1);
    await h.callback('CONSENT_API_READY');await h.tcf();assert.equal(h.visible(),0);
    await h.usStatus();assert.equal(h.visible(),0);await h.load();assert.equal(h.visible(),2);
    assert.equal(h.window.adsbygoogle.pauseAdRequests,0);
    assert.equal(h.window.adsbygoogle.requestNonPersonalizedAds,1);
    await h.sync();assert.equal(h.window.adsbygoogle.length,2);assert.equal(h.head.children.length,1);
});
test('EU rejection, consent and revocation update both slots',async()=>{
    const h=harness();await settled();await h.callback('CONSENT_API_READY');await h.usStatus();await h.load();
    await h.tcf({...acceptedEu,purpose:{consents:{}}});assert.equal(h.visible(),0);assert.equal(h.privacy.hidden,false);
    await h.tcf(acceptedEu);assert.equal(h.visible(),2);
    await h.tcf({...acceptedEu,vendor:{consents:{755:false}}});assert.equal(h.visible(),0);
    assert.equal(h.window.adsbygoogle.pauseAdRequests,1);
    await h.tcf(acceptedEu);assert.equal(h.visible(),2);
    let reopened=false;h.window.googlefc.showRevocationMessage=()=>{reopened=true;};
    h.privacy.events.click();assert.equal(h.visible(),0);await h.callback('CONSENT_API_READY');assert.equal(reopened,true);
});
test('US decisions fail closed before initial status, on incomplete data, opt-out or GPC',async()=>{
    const h=harness();await settled();await h.callback('CONSENT_API_READY');await h.tcf();await h.load();
    await h.gpp(usData({SaleOptOut:2}));assert.equal(h.visible(),0);
    await h.usStatus(1);assert.equal(h.visible(),0);assert.equal(h.usPrivacy.hidden,false);
    await h.gpp(usData({}));assert.equal(h.visible(),0);
    await h.gpp(usData({SaleOptOut:2,SharingOptOut:2,TargetedAdvertisingOptOut:2}));assert.equal(h.visible(),2);
    await h.gpp(usData({SaleOptOut:1}));assert.equal(h.visible(),0);
    await h.gpp(usData({SaleOptOut:2,Gpc:true}));assert.equal(h.visible(),0);
    await h.gpp(usData({SaleOptOut:2}),false);assert.equal(h.visible(),0);
    await h.usStatus(999);assert.equal(h.visible(),0);
});
test('TCF accepts established NPA legitimate interest while honoring storage consent and publisher restrictions',async()=>{
    const h=harness();await allowed(h);
    const li={...acceptedEu,vendor:{consents:{755:true},legitimateInterests:{755:true}},purpose:{consents:{1:true},legitimateInterests:{2:true,7:true,9:true,10:true}}};
    await h.tcf(li);assert.equal(h.visible(),2);
    for(const restriction of [0,1,999]) {
        await h.tcf({...li,publisher:{restrictions:{7:{755:restriction}}}});assert.equal(h.visible(),0);
    }
    await h.tcf({...li,publisher:{restrictions:{7:{755:2}}}});assert.equal(h.visible(),2);
    await h.tcf({...li,purpose:{...li.purpose,consents:{1:false}}});assert.equal(h.visible(),0);
    await h.tcf({...li,vendor:{...li.vendor,legitimateInterests:{755:false}}});assert.equal(h.visible(),0);
});
test('global privacy control never permits slots',async()=>{const h=harness({gpc:true});await allowed(h);assert.equal(h.visible(),0);});
test('focus and tab visibility check policy without refreshing existing ads',async()=>{
    const h=harness();await allowed(h);h.document.hidden=true;h.document.events.visibilitychange();
    h.document.hidden=false;h.document.events.visibilitychange();h.window.events.focus();await settled();
    assert.equal(h.visible(),2);assert.equal(h.window.adsbygoogle.length,2);
});
test('plan changes while Google loads prevent slots; policy, pause and network errors remove them',async()=>{
    const h=harness();await settled();await h.callback('CONSENT_API_READY');await h.tcf();await h.usStatus();
    h.state.plan={...free(),tier:'premium'};await h.load();assert.equal(h.visible(),0);
    h.state.plan=free();await h.sync();assert.equal(h.visible(),2);
    h.state.plan={...free(),ad_free_until:Date.now()/1000+1800};await h.sync();assert.equal(h.visible(),0);
    h.state.plan=free();await h.sync();assert.equal(h.visible(),2);
    h.state.plan={...free(),ads:{web:false,allowed_views:['home']}};await h.sync();assert.equal(h.visible(),0);
    h.state.plan=free();await h.sync();h.state.failure=true;await h.sync();assert.equal(h.visible(),0);
});
test('empty inventory collapses, SDK failure and provider exceptions do not break the panel',async()=>{
    const h=harness();await allowed(h);h.spaces[0].querySelector('ins').dataset.adStatus='unfilled';h.observers[0].cb();assert.equal(h.visible(),1);
    await h.sync();assert.equal(h.window.adsbygoogle.length,2);
    const failed=harness();await settled();failed.head.children[0].onerror();await settled();assert.equal(failed.visible(),0);
    const throws=harness();await allowed(throws);await throws.tcf({gdprApplies:true});
    throws.window.adsbygoogle.push=()=>{throw Error('provider');};
    await throws.tcf();assert.equal(throws.visible(),0);
});
