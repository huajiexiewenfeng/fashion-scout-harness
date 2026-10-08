"use strict";
import {resolveRunIntent, resolveOperationIntent} from "./intent.js";
const $ = selector => document.querySelector(selector);
const names = {dress:"连衣裙",tops:"上装",knitwear:"针织",outerwear:"外套",bottoms:"下装",sets:"套装",other:"其他"};
const states = {queued:"等待巡检",running:"正在巡检",interrupted:"等待恢复此前巡检",cancelling:"正在安全停止",cancelled:"已取消",succeeded:"承诺图集范围已完成",partial:"部分完成，有缺失待处理",failed:"巡检未完成"};
const active = new Set(["queued","running","interrupted","cancelling"]);
const state = {csrf:null,view:"new",category:"",cursor:null,items:new Map(),run:null,busy:false,gallery:null,generation:0,listGeneration:0,renderedSelection:null};
function el(tag, cls, text) { const node=document.createElement(tag); if(cls)node.className=cls; if(text!==undefined)node.textContent=text; return node; }
function notify(text) { $("#notice").textContent=text; $("#notice").hidden=!text; }
function date(value) { if(!value)return "日期未知"; const d=new Date(value); return isNaN(d)?"日期未知":d.toLocaleDateString("zh-CN"); }
async function api(path, options={}) {
  const headers={...options.headers};
  if(options.body)headers["Content-Type"]="application/json";
  if(options.method && options.method!=="GET")headers["X-CSRF-Token"]=state.csrf||"";
  let response;
  try { response=await fetch(path,{...options,headers,credentials:"same-origin"}); }
  catch { const error=new Error("暂时无法连接本机服务。请求结果可能已被接受，请保留当前操作并重新连接。"); error.code="NETWORK"; throw error; }
  const data=await response.json();
  if(!response.ok){const error=new Error(({AUTH_REQUIRED:"请通过本机启动入口重新打开款集。",CSRF_REQUIRED:"页面会话已失效，请重新打开。",CURSOR_EXPIRED:"列表已过期，请点击刷新列表。",REVISION_CONFLICT:"状态已被另一处更新，已重新读取。请确认后再操作。",INVALID_PAYLOAD:"输入内容不符合要求。",ACTIVE_RUN:"已有巡检进行中，请先查看当前进度。"})[data.error?.code]||"操作未完成，请查看巡检详情或稍后再试。");error.code=data.error?.code;error.status=response.status;throw error;}
  return data;
}
function runStatus(summary){
  const run=summary.latest_run;state.run=run;
  const waitingHost=run?.issue_code==="SOURCE_HOST_REQUIRED";
  $("#run-status").textContent=run?`${waitingHost?"等待 Codex 前台继续采集":states[run.state]||"状态待确认"} · ${date(run.created_at)}`:"尚未巡检";
  $("#worker-status").textContent=waitingHost?"采集时需要 Codex 运行；已收到的图片、导出和维护继续处理":run?(run.worker_state==="offline"?"执行服务离线；已保存的任务与结果仍保留":run.resumed_at&&active.has(run.state)?"正在恢复此前已接受的任务":"执行服务在线"):"";
  $("#start").disabled=state.busy||!state.csrf||!!(run&&active.has(run.state));
  $("#start").textContent=run&&active.has(run.state)?"巡检进行中":"＋ 开始巡检";
  $("#run-detail").textContent=run?`已存图片 ${run.counts.completed||0} · 失败项 ${run.counts.failed||0} · ${run.coverage.some(c=>c.complete)?"清单范围已覆盖":"清单覆盖尚未确认"}${run.issues.length?" · 存在来源或素材问题":""}`:"尚无巡检记录。";
  $("#run-actions").hidden=!run;$("#retry").hidden=!run||!["partial","failed","cancelled"].includes(run.state);$("#cancel").hidden=!run||!active.has(run.state);
}
async function refreshStatus(){try{runStatus(await api("/v1/runs/latest"));}catch(error){$("#worker-status").textContent=error.message;}}
function card(product){
  const node=el("article","card");node.dataset.productId=product.id;
  const imageButton=el("button","card-image");imageButton.setAttribute("aria-label","查看图集："+product.title);
  const holder=el("span","placeholder",product.images.length?"正在载入图片":"暂无可用图片");imageButton.append(holder);
  if(product.images.length){const image=el("img");image.alt=product.title;image.loading="lazy";image.onload=()=>holder.hidden=true;image.onerror=()=>{image.remove();holder.textContent="图片暂时无法显示";};image.src=product.images[0].preview_url;imageButton.append(image);}
  imageButton.onclick=()=>openGallery(product.id);node.append(imageButton);
  const favorite=el("button","favorite-button",product.user_state.favorite?"♥":"♡");favorite.setAttribute("aria-label",product.user_state.favorite?"取消收藏："+product.title:"收藏："+product.title);favorite.setAttribute("aria-pressed",String(product.user_state.favorite));favorite.onclick=()=>toggleFavorite(product.id);node.append(favorite);
  const heading=el("div","card-heading");const title=el("button","card-title",product.title);title.onclick=()=>openGallery(product.id);heading.append(title);
  if(!product.user_state.viewed_at)heading.append(el("span","badge","未看"));else if(product.has_material_update)heading.append(el("span","badge update","看后更新"));node.append(heading);
  const meta=el("div","card-meta");meta.append(el("span","",product.site_name||product.site_id||"Futario"),el("span","",names[product.effective_category]||"其他"),el("span","",product.source.source_published_at?"来源标注 "+date(product.source.source_published_at):"来源日期未知"));node.append(meta);
  if(product.media_state!=="ready")node.append(el("p","missing-note",({queued:"图片待处理",downloading:"图片收集中",partial:"部分图片缺失",failed:"暂未取得完整图集"})[product.media_state]||"图集待确认"));
  return node;
}
function updateCard(pid){const existing=[...$("#grid").children].find(n=>n.dataset.productId===pid);if(existing)existing.replaceWith(card(state.items.get(pid)));}
let listRequest=null;
function listing(append=false){
  const selection=JSON.stringify([state.view,state.category]);
  if(append&&!state.cursor)return listRequest?.promise||Promise.resolve();
  const query=new URLSearchParams({view:state.view,limit:"40"});if(state.category)query.set("category",state.category);if(append)query.set("cursor",state.cursor);
  const key=String(query);
  // Repeated refresh/load-more clicks share the same in-flight read. A changed
  // filter starts a new generation; old results cannot replace the new view.
  if(listRequest?.selection===selection&&(append||listRequest.key===key))return listRequest.promise;
  const generation=++state.listGeneration;
  const keepPosition=!append&&state.renderedSelection===selection;
  const targetCount=keepPosition?state.items.size:40;
  const scrollY=typeof window!=="undefined"?window.scrollY:0;
  const request={key,selection,promise:null};listRequest=request;
  $("#more").disabled=$("#refresh").disabled=true;
  $("#refresh").textContent="正在刷新…";$("#grid").setAttribute("aria-busy","true");
  if(!state.items.size){$("#empty").hidden=true;$("#grid").replaceChildren(...Array.from({length:4},()=>el("div","skeleton")));}
  request.promise=(async()=>{try{
    let data=await api("/v1/products?"+query);if(generation!==state.listGeneration)return;
    const received=[...data.items];
    // Refresh the already-loaded span through one new frozen cursor chain, so
    // a person halfway down page two keeps the same amount of content/scroll.
    while(!append&&received.length<targetCount&&data.next_cursor){
      const nextQuery=new URLSearchParams(query);nextQuery.set("cursor",data.next_cursor);
      data=await api("/v1/products?"+nextQuery);if(generation!==state.listGeneration)return;
      received.push(...data.items);
    }
    const previousNodes=new Map([...$("#grid").children].filter(n=>n.dataset.productId).map(n=>[n.dataset.productId,n]));
    const nextItems=append?new Map(state.items):new Map();
    const nodes=[];
    for(const product of received){
      if(nextItems.has(product.id))continue;
      nextItems.set(product.id,product);
      const old=state.items.get(product.id);
      nodes.push(old&&JSON.stringify(old)===JSON.stringify(product)&&previousNodes.has(product.id)?previousNodes.get(product.id):card(product));
    }
    if(append)$("#grid").append(...nodes);else $("#grid").replaceChildren(...nodes);
    state.items=nextItems;state.renderedSelection=selection;
    if(keepPosition&&typeof window!=="undefined")window.scrollTo({top:scrollY,behavior:"instant"});
    state.cursor=data.next_cursor;$("#more").hidden=!state.cursor;$("#count").textContent=`${data.total} 款 · 未看优先`;
    $("#empty").hidden=state.items.size>0;
    $("#empty-title").textContent=state.view==="favorites"?"把喜欢的，留在这里":state.category?"这个类别还没有款式":"你的下一份灵感，从这里开始";
    $("#empty-copy").textContent=state.view==="favorites"?"点击款式旁的爱心，即可加入收藏。缺图的款式也可以先收藏。":state.category?"换个类别看看，或刷新已有结果。":"还没有收集到款式。点击「开始巡检」，完成后在这里浏览。";
    runStatus(data.latest_run_summary);
  }catch(error){if(generation!==state.listGeneration)return;notify(error.message);if(!state.items.size){$("#grid").replaceChildren();$("#empty").hidden=false;$("#empty-title").textContent="暂时无法读取列表";$("#empty-copy").textContent="稍后再刷新，已保存的款式和收藏仍保留。";}}
  finally{if(generation===state.listGeneration){$("#more").disabled=$("#refresh").disabled=false;$("#refresh").textContent="刷新列表";$("#grid").setAttribute("aria-busy","false");}if(listRequest===request)listRequest=null;}})();
  return request.promise;
}
async function patchProduct(pid, changes){
  const product=state.gallery?.id===pid?state.gallery:state.items.get(pid);
  try{
    const data=await api(`/v1/products/${encodeURIComponent(pid)}/user-state`,{method:"PATCH",body:JSON.stringify({expected_revision:product.user_state.revision,...changes})});
    product.user_state=data.user_state;
    await refreshProductState(pid);
  }catch(error){
    if(error.code==="REVISION_CONFLICT"){
      try{await refreshProductState(pid);}catch{notify("状态已改变，但暂时无法重新读取。请刷新后再操作。");return;}
    }
    notify(error.message);
  }
}
const productReads=new Map();
async function refreshProductState(pid){
  const sequence=(productReads.get(pid)||0)+1;productReads.set(pid,sequence);
  const {product}=await api(`/v1/products/${encodeURIComponent(pid)}`);
  if(productReads.get(pid)!==sequence)return;
  // Replace an existing card in place: never rebuild or sort the frozen ID chain.
  if(state.items.has(pid)){state.items.set(pid,product);updateCard(pid);}
  if(state.gallery?.id===pid){
    // Preserve the selected historical images/index/event identity.
    Object.assign(state.gallery,{user_state:product.user_state,effective_category:product.effective_category,has_material_update:product.has_material_update});
    updateGalleryFavorite();
  }
}
const favoriteBusy=new Set();
async function toggleFavorite(pid){if(favoriteBusy.has(pid))return;favoriteBusy.add(pid);try{const p=state.gallery?.id===pid?state.gallery:state.items.get(pid);await patchProduct(pid,{favorite:!p.user_state.favorite});}finally{favoriteBusy.delete(pid);}}
function updateGalleryFavorite(){if(!state.gallery)return;$("#gallery-favorite").textContent=state.gallery.user_state.favorite?"♥ 已收藏 · 点击取消":"♡ 收藏这款";$("#gallery-favorite").setAttribute("aria-pressed",String(state.gallery.user_state.favorite));$("#category-override").value=state.gallery.user_state.category_override||"";$("#gallery-category").textContent=names[state.gallery.effective_category]||"其他";}
async function openGallery(pid, versionId=null, revision=null){
  const generation=++state.generation;state.gallery=null;
  $("#gallery-title").textContent="正在读取款式…";$("#image-stage").replaceChildren(el("div","placeholder","正在载入…"));
  if(!$("#gallery").open)$("#gallery").showModal();
  try{
    const query=versionId?"?"+new URLSearchParams({version_id:versionId,version_revision:revision}):"";
    const {product}=await api(`/v1/products/${encodeURIComponent(pid)}${query}`);if(generation!==state.generation||!$("#gallery").open)return;
    state.gallery={...product,index:0,eventId:crypto.randomUUID(),eventRecorded:false,eventPending:false,historicalSelection:!!versionId&&product.using_previous_images};
    $("#gallery-title").textContent=product.title;$("#gallery-category").textContent=names[product.effective_category]||"其他";updateGalleryFavorite();
    $("#gallery-date").textContent=`首次发现 ${date(product.first_seen_at)} · ${product.source.source_published_at?"来源标注 "+date(product.source.source_published_at):"来源日期未知"}`;
    const browserGallery=product.latest_observed_album.coverage_scope?.includes("browser.gallery");
    $("#gallery-coverage").textContent=`当前观察图集：应有 ${product.latest_observed_album.expected_count??"未知数量"} 张，已存 ${product.latest_observed_album.stored_count} 张。${browserGallery?"范围为页面可观察图集；完整商品图集、变体与原始分辨率仍未知。":"仅包含来源商品图集。"}`;
    const reasons={HTTP_404:"来源图片不存在",HTTP_429:"来源暂时限流",ASSET_MISSING:"本机图片缺失",INVALID_IMAGE:"来源文件无法识别为图片",NETWORK_ERROR:"图片传输未完成",DECODE_FAILED:"图片无法解码"};
    $("#gallery-missing").textContent=product.latest_observed_album.missing.length?product.latest_observed_album.missing.map((item,i)=>`第 ${i+1} 项：${reasons[item.reason]||"图片尚未成功取得"}`).join("；"):product.latest_detail_error?"本次商品详情读取失败；既有图片仍保留。":"未记录已发现缺图；范围外媒体状态未确认。";
    const source=product.source.url||"";$("#source-link").hidden=!/^https:\/\//.test(source);if(/^https:\/\//.test(source))$("#source-link").href=source;
    $("#versions").replaceChildren(...product.versions.map((v,i)=>{const option=el("option","",`图集 ${i+1} · 修订 ${v.revision}`);option.value=JSON.stringify([v.id,v.revision]);option.selected=v.id===product.version_id&&v.revision===product.version_revision;return option;}));
    renderImage();
  }catch(error){if(generation===state.generation){$("#gallery-title").textContent="暂时无法打开图集";$("#image-stage").replaceChildren(el("div","placeholder",error.message));}}
}
function renderImage(){
  const p=state.gallery;if(!p)return;
  $("#gallery-status").textContent=p.historicalSelection?(p.images.length?"正在查看你选择的历史图集。":"此历史图集暂无可用图片，款式和收藏状态仍会保留。"):!p.images.length?"暂未取得可用图片，款式和收藏状态仍会保留。":p.using_previous_images?"当前观察图集有缺失，正在显示此前可用图片。":p.media_state!=="ready"?"图集尚未完整，现有图片可继续浏览。":"当前图集可用。";
  $("#previous").hidden=$("#next").hidden=p.images.length<2;$("#image-count").textContent=p.images.length?`${p.index+1} / ${p.images.length}`:"暂无图片";
  const item=p.images[p.index];$("#original").hidden=!item;
  if(!item){$("#image-stage").replaceChildren(el("div","placeholder","暂无可用图片 · 可以先收藏"));return;}
  $("#original").href=item.original_url;
  const image=el("img");image.alt=p.title+"，第 "+(p.index+1)+" 张";
  const placeholder=el("div","placeholder","正在载入图片…");$("#image-stage").replaceChildren(placeholder,image);
  image.onload=async()=>{
    if(state.gallery!==p||!$("#gallery").open||image.parentElement!==$("#image-stage")||!image.naturalWidth)return;
    placeholder.hidden=true;
    // After decode and a painted frame, assert a real visible gallery image, never a card preload.
    try{await image.decode();}catch{return;}
    requestAnimationFrame(()=>requestAnimationFrame(async()=>{
      if(state.gallery!==p||!$("#gallery").open||image.parentElement!==$("#image-stage")||document.visibilityState!=="visible"||p.eventRecorded||p.eventPending)return;
      p.eventPending=true;
      try{const data=await api(`/v1/products/${encodeURIComponent(p.id)}/view-events`,{method:"POST",body:JSON.stringify({event_id:p.eventId,version_id:p.version_id,version_revision:p.version_revision})});p.eventRecorded=true;p.user_state=data.user_state;await refreshProductState(p.id);}
      catch(error){if(state.gallery===p)$("#gallery-status").textContent=error.message;}finally{p.eventPending=false;}
    }));
  };
  image.onerror=()=>{image.remove();placeholder.textContent="图片加载失败 · 未记录为已看";if(state.gallery===p)$("#gallery-status").textContent="这张图片暂时无法读取，已保留款式与缺失提示。";};image.src=item.original_url;
}
function moveImage(delta){const p=state.gallery;if(p?.images.length){p.index=(p.index+delta+p.images.length)%p.images.length;renderImage();}}
$("#close-gallery").onclick=()=>$("#gallery").close();$("#gallery").addEventListener("close",()=>{state.generation++;state.gallery=null;});
$("#gallery").addEventListener("keydown",event=>{if(event.target.tagName==="SELECT")return;if(event.key==="ArrowLeft"){event.preventDefault();moveImage(-1);}if(event.key==="ArrowRight"){event.preventDefault();moveImage(1);}});
$("#previous").onclick=()=>moveImage(-1);$("#next").onclick=()=>moveImage(1);$("#gallery-favorite").onclick=()=>state.gallery&&toggleFavorite(state.gallery.id);
$("#versions").onchange=event=>{const [id,revision]=JSON.parse(event.target.value);openGallery(state.gallery.id,id,revision);};
$("#category-override").onchange=event=>state.gallery&&patchProduct(state.gallery.id,{category_override:event.target.value||null});
for(const view of ["new","favorites"]){$("#"+view+"-tab").onclick=()=>{state.view=view;for(const item of ["new","favorites"]){$("#"+item+"-tab").classList.toggle("active",item===view);$("#"+item+"-tab").setAttribute("aria-pressed",String(item===view));}notify("");listing();};}
for(const button of document.querySelectorAll("[data-category]")){button.onclick=()=>{state.category=button.dataset.category;for(const b of document.querySelectorAll("[data-category]")){b.classList.toggle("active",b===button);b.setAttribute("aria-pressed",String(b===button));}notify("");listing();};}
$("#refresh").onclick=()=>{notify("");listing();};$("#more").onclick=()=>listing(true);
async function startRun(){
  if(state.busy)return;state.busy=true;$("#start").disabled=true;
  try{
    const data=await resolveRunIntent(sessionStorage,api,()=>crypto.randomUUID());
    notify(data.recovered||data.reused?"已找到此前接受的巡检，正在显示它的当前状态。":data.run?.snapshot?.source_mode==="browser"?"巡检已接受。采集时需保持 Codex 运行；已收到图片的处理继续在后台完成。":"巡检已接受。你可以离开页面，稍后再查看结果。");await refreshStatus();
  }catch(error){notify(error.message+" 再次点击将核对同一次操作，不会自动换成新巡检。");}
  finally{state.busy=false;await refreshStatus();}
}
$("#start").onclick=startRun;
for(const action of ["retry","cancel"]){$("#"+action).onclick=async()=>{
  const button=$("#"+action);if(!state.run||button.disabled)return;
  const runId=state.run.id;button.disabled=true;
  try{
    const result=await resolveOperationIntent(sessionStorage,api,()=>crypto.randomUUID(),runId,action);
    notify((action==="retry"?"已接受原巡检的失败部分重试。":"已接受取消请求，执行中的工作会在安全位置停止。")+(result.cleanup_pending?" 浏览器操作记录暂未清理；再次操作会核对同一次请求。":""));
    await refreshStatus();
  }catch(error){notify(error.message||"操作未完成，请恢复浏览器存储后再试。");}
  finally{button.disabled=false;}
};}
(async()=>{try{state.csrf=(await api("/v1/session")).csrf_token;const plan=await api("/v1/settings/default-plan");$("#plan-summary").textContent=`当前默认：近 ${plan.plan.window_days} 天 · ${plan.plan.unknown_date_policy==="include"?"包含":"不包含"}来源日期未知款式。`;await listing();if(sessionStorage.getItem("scout.pending-intent"))notify("有一次开始巡检的结果尚未确认。点击「开始巡检」会先核对原操作。");setInterval(()=>{if(document.visibilityState==="visible")refreshStatus();},6000);}catch(error){$("#grid").replaceChildren();$("#run-status").textContent="页面尚未连接";notify(error.message);}})();
