import {issueText,findingsText} from './maintenance-findings.js';
import {maintenanceIntent,storageIntent} from './maintenance-intent.js';
const $=id=>document.getElementById(id);
let csrf=null,job=null,busy=false,setting=null,timer=null,review=false;
const states={queued:'等待执行',running:'正在执行',succeeded:'已完成',partial:'已完成，有需留意的问题',failed:'未完成'};
async function api(path,options={}){
  const response=await fetch(path,{...options,credentials:'same-origin',headers:{...(options.body?{'Content-Type':'application/json','X-CSRF-Token':csrf||''}:{})}});
  const value=await response.json();
  if(!response.ok){const error=Error(({STORAGE_BUSY:'当前巡检、维护或未完成归档仍在使用素材目录，稍后再试。',REVISION_CONFLICT:'保存位置已变化，请先核对当前设置。',INVALID_STORAGE_PATH:'请选择有效的本机独立目录；不支持磁盘根、网络盘或链接目录。',DISK_RESERVE:'目标目录空间不足。'})[value.error?.code]||'操作结果尚未确认，请核对原操作，不要重复创建。');error.code=value.error?.code;throw error;}
  return value;
}
function render(){
  const active=job&&['queued','running'].includes(job.state);
  $('maintenance-verify').disabled=busy||!csrf||!!active;$('maintenance-backup').disabled=busy||!csrf||!!active;
  $('storage-save').disabled=busy||!setting||review;$('storage-review').hidden=!review;
  $('maintenance-status').textContent=job?`${job.kind==='backup'?'本机备份':'素材核验'}：${states[job.state]||'状态待核对'}${job.worker_state==='offline'?'；执行服务离线，任务仍保留':''}`:'手动检查已保存素材，或创建本机备份。';
  const result=job?.result||{};
  $('maintenance-counts').textContent=result.counts?`${result.counts.products} 款 · ${result.counts.verified} 个素材通过 · 缺失 ${result.counts.missing} / 损坏 ${result.counts.damaged} / 未知 ${result.counts.unknown}`:'';
  $('maintenance-location').textContent=job?.backup_available&&result.path?'备份保存于：'+result.path:job?.issue_code?issueText(job.issue_code):'';
  $('maintenance-issues').textContent=findingsText(job?.finding_groups);
  $('maintenance-detail').hidden=!(result.issues?.length);
}
async function poll(){
  if(!job)return;const id=job.id;
  try{const data=await api('/v1/maintenance/'+encodeURIComponent(id));if(job?.id===id)job=data.maintenance;render();}
  catch(error){$('maintenance-message').textContent=error.message;}
  clearTimeout(timer);if(job&&['queued','running'].includes(job.state))timer=setTimeout(poll,1600);
}
async function submit(kind){
  if(busy||job&&['queued','running'].includes(job.state))return;busy=true;render();
  try{const data=await maintenanceIntent(localStorage,api,()=>crypto.randomUUID(),kind);job=data.maintenance;
    $('maintenance-message').textContent=(data.reused?'已核对同一次操作。':'任务已保存，可以离开页面，稍后查看结果。')+(data.cleanup_pending?'浏览器意图记录仍保留，下次核对原操作。':'');await poll();
  }catch(error){$('maintenance-message').textContent=error.message;}finally{busy=false;render();}
}
$('maintenance-verify').onclick=()=>submit('verify');$('maintenance-backup').onclick=()=>submit('backup');
$('storage-save').onclick=async()=>{
  if(busy||!setting||review)return;busy=true;render();
  try{
    const data=await storageIntent(localStorage,api,{expected_revision:setting.revision,media_root:$('storage-path').value});
    setting=data.storage;review=!!data.review_required;$('storage-path').value=setting.media_root;
    $('storage-message').textContent=review?'已读取当前位置。上次保存回执不确定，请核对后解除提示；不会自动再次保存。':'保存位置已更新；仅影响后续图片，历史图片仍保留。';
  }catch(error){review=true;$('storage-message').textContent=error.message+' 请先核对当前保存位置。';}
  finally{busy=false;render();}
};
$('storage-review').onclick=async()=>{
  try{setting=(await api('/v1/settings/storage')).storage;$('storage-path').value=setting.media_root;
    localStorage.removeItem('scout.storage.pending');review=false;$('storage-message').textContent='已显示当前保存位置。如仍需修改，请重新输入并明确保存。';render();
  }catch(error){$('storage-message').textContent=error.message;}
};
(async()=>{
  try{csrf=(await api('/v1/session')).csrf_token;setting=(await api('/v1/settings/storage')).storage;$('storage-path').value=setting.media_root;
    const last=localStorage.getItem('scout.maintenance.last');if(last&&/^[a-f0-9]{32}$/.test(last)){job={id:last};await poll();}
    if(localStorage.getItem('scout.maintenance.pending'))$('maintenance-message').textContent='上次维护结果尚未确认，请点击原操作核对。';
    review=!!localStorage.getItem('scout.storage.pending');if(review)$('storage-message').textContent='上次保存位置结果尚未确认，请先核对当前设置。';render();
  }catch(error){$('maintenance-message').textContent=error.message;}
})();
