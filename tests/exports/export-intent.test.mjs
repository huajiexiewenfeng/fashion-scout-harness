import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resolveExportIntent} from '../../src/fashion_scout/static/export-intent.js';
const memory=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};};
for(const id of [null,'original-job']){
  test(`${id?'retry':'create'} lost response retains exact payload and key`,async()=>{
    const storage=memory(),requests=[];
    await assert.rejects(resolveExportIntent(storage,async(path,options)=>{requests.push([path,options.body]);throw Error('lost');},()=> 'stable',id));
    const result=await resolveExportIntent(storage,async(path,options)=>{requests.push([path,options.body]);return {export:{id:'job'},reused:true};},()=>{throw Error('must not change key');},id);
    assert.deepEqual(requests[0],requests[1]);assert.equal(result.export.id,'job');assert.equal(storage.getItem('scout.export.last'),'job');
  });
}
for(const action of ['getItem','setItem'])test(`${action} failure makes zero requests`,async()=>{
  const storage=memory();storage[action]=()=>{throw Error('storage')};let count=0;
  await assert.rejects(resolveExportIntent(storage,async()=>{count++;},()=> 'stable'));
  assert.equal(count,0);
});
test('acknowledged but cleanup failure retains same intent across refresh',async()=>{
  const storage=memory(),remove=storage.removeItem;storage.removeItem=()=>{throw Error('cleanup')};
  let calls=[];const request=async(path,options)=>{calls.push(options.body);return {export:{id:'job'}}};
  assert.equal((await resolveExportIntent(storage,request,()=> 'stable')).cleanup_pending,true);
  storage.removeItem=remove;await resolveExportIntent(storage,request,()=> 'new');assert.equal(calls[0],calls[1]);
});
test('invalid saved payload never creates another key or request',async()=>{
  const storage=memory();storage.setItem('scout.export.pending',JSON.stringify({request_key:'old',selection:'all'}));
  await assert.rejects(resolveExportIntent(storage,()=>{throw Error('sent');},()=>{throw Error('new key');}));
});
