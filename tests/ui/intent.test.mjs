import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveRunIntent} from '../../src/fashion_scout/static/intent.js';
const storage=()=>{const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};};
test('Accepted but lost response recovers by the same key, never POSTs again',async()=>{
  const s=storage(),calls=[];let postCount=0;
  const request=async(path,options)=>{calls.push(path);if(options?.method==='POST'){postCount++;assert.equal(JSON.parse(options.body).request_key,'intent-1');throw new Error('connection lost after COMMIT');}return {run:{id:'accepted'}};};
  await assert.rejects(resolveRunIntent(s,request,()=> 'intent-1'));
  assert.equal(s.getItem('scout.pending-intent'),'intent-1');
  const result=await resolveRunIntent(s,request,()=>{throw new Error('must not generate a new key');});
  assert.equal(postCount,1);assert.equal(result.run.id,'accepted');assert.equal(result.recovered,true);
  assert.deepEqual(calls,['/v1/runs','/v1/runs/by-request/intent-1']);
});
test('Verified absent request replays the exact key; unknown/conflict does not POST',async()=>{
  const s=storage();s.setItem('scout.pending-intent','retained');let body;
  const result=await resolveRunIntent(s,async(path,options)=>{if(!options)throw {status:404};body=JSON.parse(options.body);return {run:{id:'replay'}};},()=>{throw 0;});
  assert.equal(body.request_key,'retained');assert.equal(result.run.id,'replay');
  for(const status of [409,503,401,undefined]){
    s.setItem('scout.pending-intent','retained');let calls=0;
    await assert.rejects(resolveRunIntent(s,async()=>{calls++;throw Object.assign(new Error(),{status});},()=>{throw 0;}));
    assert.equal(calls,1);assert.equal(s.getItem('scout.pending-intent'),'retained');
  }
});
test('Storage failure prevents acceptance without a durable intent key',async()=>{
  let called=false;
  await assert.rejects(resolveRunIntent({getItem:()=>null,setItem:()=>{throw new Error('storage unavailable');}},async()=>{called=true;},()=> 'intent'));
  assert.equal(called,false);
});
