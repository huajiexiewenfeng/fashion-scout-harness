import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {resolveRunIntent,resolveOperationIntent} from '../../src/fashion_scout/static/intent.js';

// Execute the actual page script. This small DOM double models replacement,
// labels, disabled state and image load/decode/frame events; no browser/network.
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attrs={};this.listeners={};this.textContent='';this.classList={toggle(){}};this.disabled=false;this.hidden=false;this.open=false;this.naturalWidth=600;}
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}}
  replaceChildren(...nodes){for(const n of this.children)n.parentElement=null;this.children=[];this.append(...nodes);}
  replaceWith(node){const p=this.parentElement;if(p){const i=p.children.indexOf(this);p.children[i]=node;node.parentElement=p;this.parentElement=null;}}
  setAttribute(key,value){this.attrs[key]=value;}
  addEventListener(name,fn){this.listeners[name]=fn;}
  showModal(){this.open=true;}
  close(){this.open=false;this.listeners.close?.();}
  async decode(){}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this);this.parentElement=null;}
}
const text=node=>[node.textContent,...node.children.map(text)].join(' ');
function page(request,storage={getItem:()=>null,setItem(){},removeItem(){}}){
  const nodes=new Map(),frames=[];
  const get=selector=>{if(!nodes.has(selector))nodes.set(selector,new Element());return nodes.get(selector);};
  const context=vm.createContext({document:{querySelector:get,querySelectorAll:()=>[],createElement:tag=>new Element(tag),visibilityState:'visible'},
    requestAnimationFrame:fn=>frames.push(fn),resolveRunIntent,resolveOperationIntent,sessionStorage:storage,
    crypto:{randomUUID:()=> 'test-intent'},URLSearchParams,encodeURIComponent,console,__request:request});
  let source=readFileSync(new URL('../../src/fashion_scout/static/app.js',import.meta.url),'utf8').replace(/^import .*;\r?\n/m,'');
  source=source.slice(0,source.lastIndexOf('\n(async()=>'));
  vm.runInContext(source+'\napi=__request; globalThis.exposed={state,patchProduct,card,openGallery,renderImage};',context);
  const app=context.exposed;
  const mount=(products,gallery)=>{for(const p of products){app.state.items.set(p.id,p);get('#grid').append(app.card(p));}app.state.gallery=gallery;get('#gallery').open=true;};
  return {app,get,mount,async paint(){const image=get('#image-stage').children.find(n=>n.tagName==='IMG');assert.ok(image);await image.onload();while(frames.length)await frames.shift()();}};
}
function product(id='a'){
  return {id,title:'Test '+id,effective_category:'dress',has_material_update:true,source:{},first_seen_at:'2026-10-01T00:00:00Z',
    user_state:{revision:1,favorite:false,category_override:null,viewed_at:'2026-10-02',seen_content_digest:'old'},
    media_state:'ready',using_previous_images:false,version_id:'latest',version_revision:2,
    images:[{asset_id:'current',preview_url:'/preview',original_url:'/original'}],
    album:{},latest_observed_album:{expected_count:1,stored_count:1,missing:[]},versions:[{id:'latest',revision:2}]};
}
test('Category override and reset update card and gallery immediately, without moving IDs',async()=>{
  let saved=product();const ui=page(async(path,options)=>{
    if(options){const change=JSON.parse(options.body);saved={...saved,effective_category:change.category_override||'dress',user_state:{...saved.user_state,category_override:change.category_override,revision:saved.user_state.revision+1}};return {user_state:saved.user_state};}
    return {product:saved};
  });
  ui.mount([product(),product('b')],{...product(),index:0,eventId:'keep',historicalSelection:true,images:[{asset_id:'history'}]});
  await ui.app.patchProduct('a',{category_override:'tops'});
  assert.equal(ui.get('#gallery-category').textContent,'上装');assert.equal(ui.app.state.gallery.effective_category,'tops');
  assert.match(text(ui.get('#grid').children[0]),/上装/);
  await ui.app.patchProduct('a',{category_override:null});
  assert.equal(ui.get('#gallery-category').textContent,'连衣裙');assert.equal(ui.get('#category-override').value,'');
  assert.match(text(ui.get('#grid').children[0]),/连衣裙/);
  assert.deepEqual(ui.get('#grid').children.map(n=>n.dataset.productId),['a','b']);
  assert.deepEqual(Array.from(ui.app.state.items.keys()),['a','b']);
  assert.equal(ui.app.state.gallery.images[0].asset_id,'history');assert.equal(ui.app.state.gallery.eventId,'keep');
});
for(const historical of [false,true])test(`Rendered ${historical?'historical':'latest'} image refreshes authoritative material badge without sorting`,async()=>{
  const saved={...product(),has_material_update:historical};let posted;
  const ui=page(async(path,options)=>{if(options){posted=JSON.parse(options.body);return {user_state:saved.user_state};}return {product:saved};});
  const gallery={...product(),version_id:historical?'old':'latest',version_revision:historical?1:2,index:0,eventId:'render-event',eventRecorded:false,eventPending:false};
  ui.mount([product(),product('b')],gallery);ui.app.renderImage();await ui.paint();
  assert.equal(posted.version_id,historical?'old':'latest');assert.equal(gallery.eventRecorded,true);
  assert.equal(ui.app.state.items.get('a').has_material_update,historical);
  assert.equal(text(ui.get('#grid').children[0]).includes('看后更新'),historical);
  assert.deepEqual(ui.get('#grid').children.map(n=>n.dataset.productId),['a','b']);
  assert.equal(gallery.version_id,historical?'old':'latest');
});
test('Explicit history is not described as current missing-image fallback',async()=>{
  const old={...product(),version_id:'old',version_revision:1,using_previous_images:true};
  const ui=page(async()=>({product:old}));ui.mount([product()],null);
  await ui.app.openGallery('a','old',1);
  assert.equal(ui.get('#gallery-status').textContent,'正在查看你选择的历史图集。');
  await ui.app.openGallery('a');
  assert.match(ui.get('#gallery-status').textContent,/当前观察图集有缺失/);
});
for(const action of ['retry','cancel']){
  for(const fail of ['getItem','setItem'])test(`${action}: ${fail} failure shows notice, sends nothing and restores controls`,async()=>{
    let posts=0;
    const storage={getItem:()=>null,setItem(){},removeItem(){},[fail](){throw new Error('SecurityError');}};
    const ui=page(async()=>{posts++;},storage);ui.app.state.run={id:action+'-'+fail};
    await ui.get('#'+action).onclick();
    assert.equal(posts,0);assert.equal(ui.get('#'+action).disabled,false);
    assert.match(ui.get('#notice').textContent,/尚未发送请求/);
  });
  test(`${action}: cleanup failure reports accepted and retry only clears retained intent`,async()=>{
    const entries=new Map();let posts=0,fail=true;
    const storage={getItem:k=>entries.get(k)||null,setItem:(k,v)=>entries.set(k,v),removeItem:k=>{if(fail)throw new Error('SecurityError');entries.delete(k);}};
    const run={id:action+'-cleanup',state:'failed',created_at:'2026-10-01',worker_state:'offline',counts:{},coverage:[],issues:[]};
    const ui=page(async(path,options)=>{if(options){posts++;assert.equal(entries.get(`scout.${action}.${run.id}`),JSON.parse(options.body).request_key);return {run};}return {latest_run:run};},storage);ui.app.state.run=run;
    await ui.get('#'+action).onclick();
    assert.equal(posts,1);assert.equal(ui.get('#'+action).disabled,false);assert.match(ui.get('#notice').textContent,/已接受/);assert.match(ui.get('#notice').textContent,/暂未清理/);
    fail=false;await ui.get('#'+action).onclick();assert.equal(posts,1);assert.equal(entries.size,0);assert.equal(ui.get('#'+action).disabled,false);
  });
  test(`${action}: lost response retains exact key for same-operation replay`,async()=>{
    const entries=new Map(),bodies=[];let fail=true;
    const storage={getItem:k=>entries.get(k)||null,setItem:(k,v)=>entries.set(k,v),removeItem:k=>entries.delete(k)};
    const run={id:action+'-lost',state:'failed',created_at:'2026-10-01',worker_state:'offline',counts:{},coverage:[],issues:[]};
    const ui=page(async(path,options)=>{if(options){bodies.push(options.body);if(fail)throw new Error('Lost after COMMIT');return {run};}return {latest_run:run};},storage);ui.app.state.run=run;
    await ui.get('#'+action).onclick();assert.equal(entries.size,1);assert.equal(ui.get('#'+action).disabled,false);
    fail=false;await ui.get('#'+action).onclick();assert.equal(bodies.length,2);assert.equal(bodies[0],bodies[1]);assert.equal(entries.size,0);
  });
}
