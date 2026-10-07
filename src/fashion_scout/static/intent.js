// Recover a single explicit intent. Only its non-secret ID is durable in this tab.
export async function resolveRunIntent(storage, request, uuid) {
  const slot = "scout.pending-intent";
  let key = storage.getItem(slot);
  if (key) {
    try {
      const accepted = await request("/v1/runs/by-request/" + encodeURIComponent(key));
      storage.removeItem(slot);
      return {...accepted, recovered: true};
    } catch (error) {
      if (error.status !== 404) throw error;
    }
  } else {
    key = uuid();
    // If persistence fails, fail before issuing a request whose key could be lost.
    storage.setItem(slot, key);
  }
  const accepted = await request("/v1/runs", {method:"POST", body:JSON.stringify({request_key:key,trigger:"ui",overrides:{}})});
  storage.removeItem(slot);
  return accepted;
}

// Retain an acknowledged operation in this page if storage cleanup fails. A later
// click retries cleanup instead of issuing a new operation. After reload, the
// retained durable key can still be replayed against the server's idempotency map.
const acknowledgedOperations = new Map();
export async function resolveOperationIntent(storage, request, uuid, runId, action) {
  if (!["retry", "cancel"].includes(action)) throw new Error("不支持的巡检操作。");
  const slot = `scout.${action}.${runId}`;
  let accepted = acknowledgedOperations.get(slot);
  if (!accepted) {
    let key;
    try {
      key = storage.getItem(slot);
      if (!key) {
        key = uuid();
        storage.setItem(slot, key);
      }
    } catch {
      throw new Error("无法保存本次操作记录，尚未发送请求。请恢复浏览器存储后再试。");
    }
    accepted = await request(`/v1/runs/${encodeURIComponent(runId)}/${action}`, {
      method: "POST", body: JSON.stringify({request_key:key, ...(action === "retry" ? {scope:"failed"} : {})}),
    });
    acknowledgedOperations.set(slot, accepted);
  }
  try {
    storage.removeItem(slot);
    acknowledgedOperations.delete(slot);
    return accepted;
  } catch {
    return {...accepted, cleanup_pending:true};
  }
}
