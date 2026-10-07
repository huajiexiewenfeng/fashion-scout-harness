// Durable non-secret payload first; missing response is replayed with the same key.
export async function resolveExportIntent(storage, request, uuid, jobId=null) {
  const slot=jobId?`scout.export.retry.${jobId}`:"scout.export.pending";
  let intent;
  try {
    const saved=storage.getItem(slot);
    intent=saved?JSON.parse(saved):{request_key:uuid(),...(jobId?{}:{selection:"favorites"})};
    if(!intent || !/^[A-Za-z0-9_-]{1,128}$/.test(intent.request_key) ||
       Object.keys(intent).sort().join(",")!==(jobId?"request_key":"request_key,selection") ||
       (!jobId&&intent.selection!=="favorites")) throw new Error();
    if(!saved)storage.setItem(slot,JSON.stringify(intent));
  }catch{throw new Error("无法保存或核对导出记录，尚未发送请求。请先恢复浏览器存储。");}
  const result=await request(jobId?`/v1/exports/${encodeURIComponent(jobId)}/retry`:"/v1/exports",{
    method:"POST",body:JSON.stringify(intent)});
  try{
    storage.setItem("scout.export.last",result.export.id);
    storage.removeItem(slot);
    return result;
  }catch{return {...result,cleanup_pending:true};}
}
