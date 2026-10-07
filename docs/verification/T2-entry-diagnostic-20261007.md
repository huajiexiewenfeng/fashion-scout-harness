# T2 栏目入口单次诊断：HTML也返回429

原任务 p2-collection / t2-futario-media，原Worker执行。依据团队文件 manager-t2-html-diagnostic-20261007.md，T2仍blocked，未正式submit。此次只诊断用户指定栏目入口，没有适配器或生产数据修改。

## 本次事实

先只读校验上一轮result.json SHA256为577b802e230f6fe575252b6197f0b1d80fcedb09a836231c823904ae7c02232c；其最新响应是2026-10-07T01:48:53.032820Z的429/Retry-After60，截止1791337793.0328717。此次检查已超过该截止，累计记录仍5次、剩35次。旧诊断库值与上次persisted_after相同，schema仍1–6，Run仍failed/attempt1；没有新请求/响应、图片或资产记录。旧DB活动hold比最新诊断更早，未用它代替最新截止。

唯一请求为 `GET https://futario.com/collections/new-in`。开始2026-10-07T05:27:40.341902Z；接收2026-10-07T05:27:41.726111Z（北京时间13:27:41.726111），网络耗时1.382秒。未调用结构化端点、详情、图片、JS或任何子资源。

实际非秘密请求头：

```text
host: futario.com
accept: */*
connection: keep-alive
user-agent: FashionScout/0.2 (bounded local research)
accept-encoding: identity
```

使用现有未修改的google_doh/PinnedTransport；本次fresh公网记录顺序104.21.68.184、172.67.197.209，只连接首地址104.21.68.184:443，peer相同。TLSv1.3、TLS_AES_256_GCM_SHA384，证书/hostname/SNI校验开启。未循环换地址、代理、网络或客户端身份，未提供Cookie或模拟浏览器头。

原始响应：

```text
HTTP status: 429
Date: Wed, 07 Oct 2026 05:27:41 GMT
Content-Type: text/plain
Content-Length: 18
retry-after: 60
server: cloudflare
CF-RAY: a46a7f837ecb1663-LAX
```

收到429即关闭响应，不读取响应体、不retry或跟随redirect。声明体积18字节，实际body读取0，因而没有保存真实HTML，也无法判断该体内错误代码。请求总网络上限30秒、体积上限2MiB；没有等待后再请求。

本次新Retry-After依据为1791350921.7261615，约 **2026-10-07 13:28:41.726162 Asia/Shanghai**（05:28:41.726162 UTC）。新记录比上一轮更新，只保存在本次诊断证据中，旧DB/活动hold未更新。期限过去不保证可用，也不是下一次请求授权。

累计保守次数为 **6/40，最多剩34次**。明细为最初不安全DNS拒绝1次（未到TCP）、Manager HEAD1次、原生产Worker listing GET1次、10月6日前台listing GET1次、10月7日前台listing GET1次、本次HTML GET1次。没有reset；原最多2详情/12图/64MiB共同限制继续保留。本次详情/图片请求0，生产Worker未启动。

## 与已有证据比较

| 证据 | 可核查请求/结果 | 限制 |
| --- | --- | --- |
| 前期开发基线 | 文档摘要称普通公开HTTP可读collection JSON、商品.js及HTML页1/2/12，且有两张可解码源图 | 未提供当时原始状态/请求头/UA/Accept/连接路径/捕获文件，不能将摘要当作当前成功复现，也不能据此推断触发限制的因素 |
| 早期Manager诊断 | HEAD /collections/new-in经公网固定peer/TLS返回429 | 方法与本次GET不同；原始完整响应头未保留 |
| 10月7日结构化诊断 | GET /collections/new-in/products.json?limit=2&page=1，429、Retry-After60；脚本配置相同FashionScout UA和identity编码 | 未取得商品正文，不证明结构化数据已变或JSON端点独有限制；该次完整实际请求头未单独保存 |
| 本次HTML诊断 | GET /collections/new-in，实际UA/Accept如上，429、Retry-After60 | 未取得HTML正文，不能证明栏目布局、商品标识/图集关系或挑战类型 |

结论仅限本受控客户端路径：限制至少覆盖上述JSON列表与栏目HTML，不能靠把发现入口换成HTML便宣称可采集。server/CF-RAY表明响应带Cloudflare标识，但不能单独证明具体Cloudflare规则、应用层原因、IP/UA差异或所有用户均受限。两次DNS首地址不同来自fresh响应顺序，未进行地址选择试验，不能推断地址的因果关系。

## 最小后续方案

当前不改适配器，也不继续重复相同请求。先获取**已存在的早期成功原始捕获与当时命令/非秘密头**（若能合法取得），或来源方对自动访问入口、频率和授权的明确说明，以缩小差异；不能从缺失记录补造细节。来源方确认合法可用路径后，由Manager独立授权一个有界样本验证，仍执行累计预算/新冷却。

任何适配更改仍需实际证明：商品稳定ID和时间字段、完整分页结束与两遍集合、商品详情及product.images图集/变体关系、允许的图片host，以及至少一份真实源图通过生产Worker验证归档。若未来仅获得静态HTML或离线提供的素材，可用于解析回归，但不能自动替代实站Worker验收。没有这些事实前保留T2 blocked，已验收本地模块继续按原限制使用。

以上是待Manager审查的方案，不执行联系来源方、额外访问、离线导入或适配器修改。用户预览56117、默认根、生产配置、已有代码/迁移/锁/Skill及旧报告未操作。

## 证据与保留检查

- `T2-entry-diagnostic-20261007-result.json` 与 `.runtime/t2-entry-diagnostic-20261007-01/result.json` 相同；SHA256 **1255dca0dd32d2654377fd4e5dd8780799c5b8b92165962101478026cad118d7**。
- 同runtime目录 `diagnostic.py`：固定单次脚本/独占执行标记，SHA256 e3c388b6e003acc055e9ffb34c8f0e69ee3392989043ff16415a740811877672。
- 同目录 `baseline-sha256.json`：请求前249个受保护项目文件及旧根文件摘要；SHA256 63b907f2bf2901866e1314c3189e037c937e6c301a750ceeb2ed5b2dc910206f。

结束后旧根文件hash和DB观察值与请求前相同，249个项目保护文件hash全部不变。只导入现有HTTP传输/DTO，没有ensure/initialize、迁移、Run处理或安装。只读诊断没有改变生产行为，因此不重复无关测试。报告后等待Manager审查。
