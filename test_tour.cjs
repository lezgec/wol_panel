const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createTourProgress, wolproTourSteps} = require('./static/tour.js');
function storage() { const data=new Map(); return {getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)}; }
test('first visit, pause and resume are scoped to the account',()=>{
  const s=storage(); const a=createTourProgress(s,'account-a',9);
  assert.equal(a.automatic,true); a.save(4);
  const resumed=createTourProgress(s,'account-a',9);
  assert.equal(resumed.automatic,false); assert.equal(resumed.value.index,4);
  assert.equal(createTourProgress(s,'account-b',9).automatic,true);
});
test('completion and restarting are durable without executing an action',()=>{
  const s=storage(); const a=createTourProgress(s,'account-a',9);
  a.save(0,true); const completed=createTourProgress(s,'account-a',9);
  assert.equal(completed.value.completed,true); assert.equal(completed.automatic,false);
  completed.save(0); assert.equal(createTourProgress(s,'account-a',9).value.completed,false);
  assert.equal(wolproTourSteps.length,9);
});
test('unavailable storage does not force repeated automatic dialogs',()=>{
  const a=createTourProgress({getItem(){throw Error('unavailable');},setItem(){throw Error('unavailable');}},'a',9);
  assert.equal(a.automatic,false); assert.doesNotThrow(()=>a.save(2)); assert.equal(a.value.index,2);
});
