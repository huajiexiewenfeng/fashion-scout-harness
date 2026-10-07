# T2 单次前台诊断：429，实站门槛仍未完成

原任务 p2-collection / t2-futario-media，原Worker执行。授权依据为团队目录 manager-t2-foreground-diagnostic.md。本次仅新诊断观察，不是生产Run重试，不解除任务block，不正式submit。

预检以SQLite只读连接检查真实根 `.runtime/t2-live-smoke/scout.sqlite3`：唯一限制仍为 `not_before=NULL / legacy_response_not_saved`，没有已知未来冷却，旧响应表为空。旧Run、hold和历史响应未修改或回填。

2026-10-06 **14:29:03.123 UTC** 开始，**14:29:04.475 UTC** 结束，网络耗时 **1.351秒**。仅一次：

```text
GET https://futario.com/collections/new-in/products.json?limit=2&page=1
```

使用未修改的PinnedTransport及google_doh，固定已验证提供者，本次新解析公网A记录为104.21.68.184、172.67.197.209。仅连接首地址104.21.68.184:443，实际peer一致；TLSv1.3、TLS_AES_256_GCM_SHA384，原SSLContext保持证书及futario.com主机名/SNI验证。没有替换地址尝试、代理、隐式DNS重解析、挑战处理或系统网络设置变更。

实际响应头：

```text
HTTP status: 429
Date: Tue, 06 Oct 2026 14:29:04 GMT
retry-after: 60
Content-Type: text/plain
Content-Length: 18
server: cloudflare
CF-RAY: a4655b2cfceacc9f-LAX
```

收到429立即停止，不读取响应体、不跟随重定向、不retry；详情/图片请求均0。声明体积18字节，实际读取响应体0字节，未取得商品列表或有效实站素材。请求有30秒总网络时限、2MiB体积上限；保留原始头及证书摘要，未保存Cookie等敏感头。

`Retry-After: 60` 是本次新响应真实证据。按本地接收时间保守计算本次最早时间约 **2026-10-06 14:30:04.475 UTC（22:30:04.475 Asia/Shanghai）**；这不是保证届时可访问，也不是下一次请求授权，更不证明旧未知hold已失效。没有等待后再请求，没有将新期限写入生产DB。后续由Manager基于本次证据独立决定。

原历史保守尝试3次，本次1次，合计4次，原40次总额度最多剩36次；原最多2详情/12图/64MiB共同限制仍有效。生产Worker未启动，任务仍blocked，实站有效图片验收仍缺。

证据：

- `T2-diagnostic-20261006-foreground.json`：完整本次非敏感结构化证据；与下列原始result.json相同。
- `.runtime/t2-diagnostic-20261006-foreground/result.json`：预检/后检、UTC、原始选定响应头、peer/TLS/DNS及预算。
- 同目录 `diagnostic.py`：单次诊断脚本，独占invocation标记阻止意外二次执行。
- 同目录 `baseline-sha256.json`：检查前150个受保护项目文件及生产根文件摘要。结束后均未变，DB预检/后检相同。

本次仅写独立诊断文件；既有代码、迁移、依赖锁、T3/T4/T5a产物与历史报告均未更改。未运行与只读诊断无关的测试、安装或构建。
