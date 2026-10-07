"use strict";
(async () => {
  const code = location.hash.slice(1);
  history.replaceState(null, "", "/bootstrap");
  try {
    const response = await fetch("/v1/session/exchange", {method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code})});
    if (!response.ok) throw new Error();
    location.replace("/");
  } catch {
    document.querySelector("#message").textContent = "打开链接已失效。请通过本机启动入口重新打开款集。";
  }
})();
