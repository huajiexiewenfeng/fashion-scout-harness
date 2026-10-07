import {resolveExportIntent} from './export-intent.js';
const $=id=>document.getElementById(id);
let csrf=null,job=null,busy=false,count=0,timer=null,refreshTimer=null;
const labels={queued:'正在等待打包',running:'正在打包收藏',succeeded:'收藏打包完成',partial:'收藏已打包，部分素材缺失或范围未知',failed:'这次导出未完成'};
async function api(path,options={}){
  const response=await fetch(path,{...options,credentials:'same-origin',headers:{...(options.body?{'Content-Type':'application/json','X-CSRF-Token':csrf||''}:{})}});
  const value=await response.json();
  if(!response.ok){const error=new Error(({EMPTY_FAVORITES:'还没有收藏款式，请先收藏再导出。',EXPORT_ACTIVE:'这个导出仍在处理中。',EXPORT_UNAVAILABLE:'文件已丢失或校验失败，可在更多信息里重试原导出。',AUTH_REQUIRED:'请从本机入口重新打开页面。',CSRF_REQUIRED:'页面会话已失效，请重新打开。'})[value.error?.code]||'导出请求未完成；可再次点击核对同一次操作。');error.code=value.error?.code;throw error;}
  return value;
}
function render(){
  const active=job&&['queued','running'].includes(job.state);
  let pending=false;try{pending=!!localStorage.getItem('scout.export.pending');}catch{}
  $('export-create').disabled=busy||!csrf||!!active||(!count&&!pending);
  $('export-create').textContent=busy?'正在提交…':active?'导出进行中':pending?'核对上次导出':'导出收藏';
  $('export-status').textContent=job?`${labels[job.state]||'状态待确认'} · ${job.counts.products} 款${job.state==='partial'?` · ${job.missing_count} 项缺失 / ${job.unknown_count} 项范围未知`:''}`:count?'将收藏款的全部已存历史图片一起打包。':'收藏款式后，就可以在这里打包已存图片。';
  $('export-worker').textContent=job?.worker_state==='offline'?'执行服务离线，任务和已完成结果仍保留。':'';
  const link=$('export-download');link.hidden=!job?.download_url;
  if(job?.download_url)link.href=job.download_url;
  $('export-retry').hidden=!job||active;$('export-retry').disabled=busy;
  if(job?.issues?.includes('EXPORT_UNAVAILABLE'))$('export-worker').textContent='文件已丢失或校验失败，可在更多信息里重试原导出。';
}
async function poll(){
  if(!job)return;
  const id=job.id;
  try{const next=(await api('/v1/exports/'+encodeURIComponent(id))).export;if(job?.id===id&&(!job.attempt||next.attempt>=job.attempt))job=next;render();}
  catch(error){if(job&&!job.state)job=null;$('export-message').textContent=error.message;}
  clearTimeout(timer);if(job&&['queued','running'].includes(job.state))timer=setTimeout(poll,1200);
}
async function refreshCount(){
  $('export-panel').hidden=$('favorites-tab').getAttribute('aria-pressed')!=='true';
  if($('export-panel').hidden)return;
  try{count=(await api('/v1/products?view=favorites&limit=1')).total;render();}catch{}
}
async function submit(retry=false){
  if(busy||(!retry&&job&&['queued','running'].includes(job.state)))return;
  busy=true;render();$('export-message').textContent='';
  try{
    const data=await resolveExportIntent(localStorage,api,()=>crypto.randomUUID(),retry?job.id:null);
    job=data.export;
    $('export-message').textContent=(data.reused?'已找到同一次导出。':'导出已保存，可以离开页面，稍后回来下载。')+(data.cleanup_pending?'浏览器记录尚未清理；下次操作会核对原请求。':'');
    await poll();
  }catch(error){$('export-message').textContent=error.message||'连接中断，请再次点击核对原导出。';}
  finally{busy=false;render();}
}
$('export-create').onclick=()=>submit();$('export-retry').onclick=()=>submit(true);
new MutationObserver(refreshCount).observe($('favorites-tab'),{attributes:true,attributeFilter:['aria-pressed']});
new MutationObserver(()=>{clearTimeout(refreshTimer);refreshTimer=setTimeout(refreshCount,150);}).observe($('grid'),{childList:true});
(async()=>{
  try{
    csrf=(await api('/v1/session')).csrf_token;
    const saved=localStorage.getItem('scout.export.last');
    if(saved&&/^[a-f0-9]{32}$/.test(saved)){job={id:saved};await poll();}
    if(localStorage.getItem('scout.export.pending'))$('export-message').textContent='上次导出结果尚未确认，点击按钮可核对原操作。';
    await refreshCount();render();
  }catch(error){$('export-message').textContent=error.message||'暂时无法读取导出记录。';}
})();
