# T2 2026-10-07 单次前台诊断：仍为429

依据 manager-t2-foreground-20261007.md，原Worker执行原任务 p2-collection / t2-futario-media 的一次诊断。没有新任务、生产Run重试、unblock或正式submit。

先只读核对真实旧根 `.runtime/t2-live-smoke/scout.sqlite3`：schema仍为1–6，原Run仍failed/attempt1；collection_http仍1行，响应表为空，图片请求和资产均0。活动hold仍是已审计的 server_foreground_reconciled，not_before=1791297004.4749758，recorded_at=1791296944.4746，request_seq=NULL；检查时没有未来deadline。对照前次原始诊断及对账回执SHA256，既有诊断目录没有新增未对账记录，确认历史保守4次、余额36。

仅请求一次：

```text
GET https://futario.com/collections/new-in/products.json?limit=2&page=1
```

开始UTC **2026-10-07T01:48:51.143821Z**，接收UTC **2026-10-07T01:48:53.032820Z**（北京时间09:48:53.032820），网络耗时1.887秒。使用现有未修改的google_doh/PinnedTransport，fresh DNS返回172.67.197.209、104.21.68.184；两者均公网，仅连接本次首地址172.67.197.209:443，实际peer一致。首地址顺序由本次DNS响应决定，未循环换IP。TLSv1.3、TLS_AES_256_GCM_SHA384，证书和futario.com主机名/SNI校验开启。

```text
HTTP status: 429
Date: Wed, 07 Oct 2026 01:48:52 GMT
retry-after: 60
Content-Type: text/plain
Content-Length: 18
server: cloudflare
CF-RAY: a4693efd3f1f2b9e-LAX
```

429立即停止，未读取响应体，未重试或跟随redirect，未访问详情/图片。声明体积18字节，实际响应体读取0；总网络上限30秒，体积上限2MiB。原始非敏感头保留，无Cookie等私密头；未取得有效商品列表或真实图片。

本次Retry-After60的新依据对应本地接收时间后约 **2026-10-07T01:49:53.032872Z / 北京时间09:49:53.032872**，not_before=1791337793.0328717。只记录在本次证据中，**没有写入旧DB或替换当前活动hold**。期限过去不是再次访问的授权或成功保证。

历史4+本次1=**累计5次**，原40次最多剩**35次**；最多2详情、12图、64MiB的原共同上限继续保留。原始Run/counters没有人为增加诊断关联，也没有reset预算。

结束后复核旧根文件摘要、DB观察值均与请求前一致，235个受保护项目文件摘要不变。仅导入HTTP传输与DTO模块，没有ensure/initialize或迁移，旧根没有升级至当前代码schema9。未操作默认根、用户预览目录或56117服务，未执行安装/测试/发布/定时器。末尾只读监听查询未返回56117监听项，未据此擅自启动或修复预览。

证据：

- `T2-diagnostic-20261007-foreground.json`，与 `.runtime/t2-diagnostic-20261007-foreground/result.json` 相同；SHA256 `577b802e230f6fe575252b6197f0b1d80fcedb09a836231c823904ae7c02232c`。
- 同runtime目录 `diagnostic.py`：本次固定边界脚本，独占invocation标记禁止意外二次运行；SHA256 `8a3de02cd98cb2973854d8e4710e77fd74a7f3e318009b0da836119f7a48dc63`。
- 同目录 `baseline-sha256.json`：235个项目保护文件与旧根文件前置摘要；SHA256 `eb0252992d69093eec015a87d00301129f450532ec17bc526e2c44c5acaef576`。

T2仍blocked，实站有效素材门槛未完成。本轮不执行到期重试、后续采集或新的本地冷却对账，交原Manager独立判断。
