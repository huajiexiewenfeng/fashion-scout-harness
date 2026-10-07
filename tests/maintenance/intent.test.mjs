import {test} from 'node:test';
import assert from 'node:assert/strict';
import {maintenanceIntent,storageIntent} from '../../src/fashion_scout/static/maintenance-intent.js';
function memory(){const map=new Map();return {getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};}
for(const kind of ['verify','backup'])test(kind+' lost response reuses exact intent',async()=>{
  const s=memory(),calls=[];
  await assert.rejects(maintenanceIntent(s,async(p,o)=>{calls.push([p,o.body]);throw Error('lost');},()=> 'same',kind));
  const result=await maintenanceIntent(s,async(p,o)=>{calls.push([p,o.body]);return {maintenance:{id:'job'}}},()=>{throw Error('new key');},kind);
  assert.deepEqual(calls[0],calls[1]);assert.equal(result.maintenance.id,'job');
});
for(const fn of ['getItem','setItem'])test(fn+' storage failure prevents maintenance write',async()=>{
  const s=memory();s[fn]=()=>{throw Error()};let sent=0;
  await assert.rejects(maintenanceIntent(s,()=>{sent++;},()=> 'same','verify'));assert.equal(sent,0);
});
test('different pending operation is not replaced',async()=>{
  const s=memory();await assert.rejects(maintenanceIntent(s,()=>{throw Error('lost')},()=> 'same','verify'));
  let calls=0;await assert.rejects(maintenanceIntent(s,()=>{calls++},()=> 'other','backup'));assert.equal(calls,0);
});
test('CAS lost response only reads current settings',async()=>{
  const s=memory(),calls=[];const payload={expected_revision:0,media_root:'C:/new'};
  await assert.rejects(storageIntent(s,async(p,o)=>{calls.push(o?.method||'GET');throw Error('lost');},payload));
  const result=await storageIntent(s,async(p,o)=>{calls.push(o?.method||'GET');return {storage:{revision:1,media_root:'C:/new'}}},payload);
  assert.deepEqual(calls,['PATCH','GET']);assert.equal(result.review_required,true);assert.ok(s.getItem('scout.storage.pending'));
});
test('maintenance cleanup failure retains same key',async()=>{
  const s=memory();s.removeItem=()=>{throw Error('blocked')};const calls=[];
  const req=async(p,o)=>{calls.push(o.body);return {maintenance:{id:'job'}}};
  assert.equal((await maintenanceIntent(s,req,()=> 'same','backup')).cleanup_pending,true);
  await maintenanceIntent(s,req,()=> 'other','backup');assert.equal(calls[0],calls[1]);
});
