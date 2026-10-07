# T2 当前用户代理对照：仍429，实际错误文本已取得

原T2/p2-collection诊断补充，依据manager-t2-existing-proxy-comparison-20261007.md。新正文捕获修正先完成六类合成检查并保存阶段报告；确认没有在途请求，原路body-repair可选GET已取消且未执行。Manager的Chrome JSON导航ERR_BLOCKED_BY_CLIENT保守计第8次，没有来源HTTP状态。

## 实际对照

只读复核WinINET代理仍启用、无PAC/认证，endpoint恰为已观察的回环7897；监听PID/进程族与先前mihomo记录一致。不修改任何系统或代理设置，不读取软件规则/订阅/配置/凭据。仅一次GET原JSON URL：

```text
https://futario.com/collections/new-in/products.json?limit=2&page=1
```

HTTPX显式proxy为当前用户配置端点，trust_env=False，UA保持FashionScout/0.2 (bounded local research)，Accept */*、Accept-Encoding identity，Cookie/Authorization均未发送。HTTP/1.1，redirect0/retry0/详情0/图片0；30秒总限时通过固定代理backend和既有DeadlineStream覆盖TCP、CONNECT、TLS、read/write。固定CONNECT authority=futario.com:443，未请求别的域或端口。

2026-10-07T05:55:41.011530Z（北京时间13:55:41.011530）接收，网络耗时0.706秒：

```text
HTTP: 429
Date: Wed, 07 Oct 2026 05:55:40 GMT
retry-after: 60
Content-Type: text/plain
Content-Length: 18
server: cloudflare
CF-RAY: a46aa882ff2688bd-LAX
Body: local_rate_limited
```

**这次正文是实际私有文件的18个字节，没有换行。** SHA256为fa2dd01ed96d38758e89e354653c39f366bc7a34e485772c8aa2174b53a465d3，与第7次body digest相同。本次先独占写原始字节、flush/fsync、只读，再产生脱敏摘要；原文文件没有复制到公开docs，只披露这个无认证/个人字段的短公开错误文本。原第7次result保持不变，不伪造其原始文件。

TLSv1.3、futario.com证书/hostname/SNI验证保持；证书SHA与之前公网固定路径相同。实际socket/transport peer是127.0.0.1:7897，**并非源站peer**，源站地址由现有proxy进行CONNECT域名处理，无法端到端证明数值source peer。此次明确属于诊断模式，不能当作满足生产PinnedTransport公共地址/peer约束，也未将该模式接入生产。

## 结论和最小后续

该对照没有恢复JSON：现有用户proxy与之前数值socket/TUN路径都收到429，body hash相同。因对照间隔和源站规则未知，不对具体限流原因作因果断言；至少不支持“只加现有proxy就能修好”的结论。

local_rate_limited与Envoy官方本地限流过滤器的默认响应文本一致，故现在可以优先按**网关/反向代理本地限流**分支核对。它不是Cloudflare1015数字码，也不证明Envoy运行在本电脑或mihomo是生成者。“local”描述生成限流的组件位置，不等同用户的本机。[Envoy官方本地限流源码](https://github.com/envoyproxy/envoy/blob/main/source/extensions/filters/http/local_ratelimit/local_ratelimit.cc)

Envoy官方示例也显示429/local_rate_limited的组合，但只是证明此字符串存在于中间层实现；本轮响应头白名单没有保存x-local-rate-limit，其是否出现未知，不能以未记录推断不存在。server/CF-RAY不足以直接将正文生成者归为Futario或Cloudflare；需要该请求的实际网关/来源日志关联。[Envoy官方本地限流示例](https://www.envoyproxy.io/docs/envoy/v1.37.7/start/sandboxes/local_ratelimit)

现有浏览器证据仍需分清：Futario首页已加载商品可见；Shop域New In不能充当Futario JSON成功；Chrome的新JSON导航被客户端拦截。不存在原JSON在普通浏览器的成功正文，因此不能归为单纯Python库故障或全站不可用。

可执行的下一判别应查具体组件和计数键：在合法授权下，用UTC05:55:41Z、URL/UA、Ray ID a46aa882ff2688bd-LAX与实际body local_rate_limited，核对来源/网关日志或规则是哪个处理层返回、按请求/连接/入口还是共享额度计数；网络配置负责人核对已有隧道与显式proxy实际使用的路由策略是否同一。当前只作建议，没有读取这些私有日志、联系第三方或改变出口。Cloudflare管理员能利用Ray ID与时间窗检索相关事件，采样未命中仍需保留不确定性。[Cloudflare Ray ID](https://developers.cloudflare.com/fundamentals/reference/cloudflare-ray-id/)

先完成取证质量修复是确定可本地修正的问题，已通过新副本的合成检查；生产任何网络/错误分类修改须Manager独立审查。尚无实际商品正文，解析器和归档层修改无法解除请求前的限流。后续实站小样本仍需明确新授权、最新冷却和累积预算，不能继续换代理/UA/IP或解除浏览器保护。

## 预算、保护和工件

累计保守 **9/40，最多剩31次**：其中最初DNS拒绝和Chrome本地阻断均按保守尝试入账，不冒称源HTTP请求。此轮1个JSON GET，原2详情/12图/64MiB共用限制仍在。最新冷却依据1791352601.0115564，约北京时间13:56:41.011556，只存新证据，不改旧hold/Run/预算。请求已结束，本Worker无在途来源请求。

旧根仍schema1–6、Run failed/attempt1，before/after完全一致，4个旧root文件hash不变。284个项目保护文件未出现变化；已为并行T6b的scripts/release、tests/release、T6b文档和README授权变更单列字段，本次该列表为空。没有生产、系统设置、默认根、56117预览或已验收原件写入；无Worker/安装/Agent/定时器/发布。

- `T2-existing-proxy-20261007-result.json`与`.runtime/t2-existing-proxy-20261007-01/result.json`相同；SHA256 b5a069b4174d23867766b46f7ad9aefbef6ce879b5777135f0ddce7e01bb7542。
- 同runtime `diagnostic.py` SHA256 239de50e6c0205ed855660d2b27495e6f8863d9c0320394f11d4529a9d5306a5，独占标记阻止二次运行。
- 同runtime `private-error/response-body.bin`为原始捕获，仅runtime保留；18字节/hash如上。
- 同runtime `baseline-sha256.json`为保护摘要，实际命令为项目`.venv` Python -B运行该独立脚本。

T2继续blocked，非正式submit，等待Manager独立决定下一步。
