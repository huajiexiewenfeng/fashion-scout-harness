// Non-secret intent is saved before sending. Reload only inspects it.
export async function maintenanceIntent(storage,request,uuid,kind){
  const slot='scout.maintenance.pending';let intent;
  try{
    const saved=storage.getItem(slot);
    intent=saved?JSON.parse(saved):{kind,body:{request_key:uuid(),...(kind==='verify'?{scope:'all'}:{destination_id:'local'})}};
    if(!['verify','backup'].includes(intent.kind)||!intent.body||!/^[A-Za-z0-9_-]{1,128}$/.test(intent.body.request_key))throw Error();
    const keys=Object.keys(intent.body).sort().join(',');
    if(keys!==(intent.kind==='verify'?'request_key,scope':'destination_id,request_key')||intent.kind==='verify'&&intent.body.scope!=='all'||intent.kind==='backup'&&intent.body.destination_id!=='local')throw Error();
    if(intent.kind!==kind)throw Error('PENDING_OTHER');
    if(!saved)storage.setItem(slot,JSON.stringify(intent));
  }catch(error){throw Error(error.message==='PENDING_OTHER'?'请先核对上一次维护操作。':'无法保存或核对维护意图，尚未发送请求。');}
  const result=await request('/v1/maintenance/'+intent.kind,{method:'POST',body:JSON.stringify(intent.body)});
  try{storage.setItem('scout.maintenance.last',result.maintenance.id);storage.removeItem(slot);}catch{result.cleanup_pending=true;}
  return result;
}

export async function storageIntent(storage,request,payload){
  const slot='scout.storage.pending';let saved;
  try{saved=storage.getItem(slot);}catch{throw Error('无法读取保存位置意图，尚未发送请求。');}
  if(saved){
    const result=await request('/v1/settings/storage');
    return {...result,review_required:true}; // Unknown CAS result never replays PATCH.
  }
  try{storage.setItem(slot,JSON.stringify(payload));}catch{throw Error('无法保存位置变更意图，尚未发送请求。');}
  const result=await request('/v1/settings/storage',{method:'PATCH',body:JSON.stringify(payload)});
  try{storage.removeItem(slot);}catch{result.review_required=true;}
  return result;
}
