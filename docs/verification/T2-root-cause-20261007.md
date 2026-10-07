# T2 根因定位：网络路径已确认，来源侧具体规则仍待证据

原任务 p2-collection / t2-futario-media，原Worker。2026-10-07根因范围及后续取证修订均保留；T2仍blocked，本文件是非正式提交的阶段记录。用户新证据是**这台电脑的普通浏览器能正常看到Futario商品**（由Manager转达，页面取证由Manager另行只读进行）。因此不能称整个站点不可用，当前问题限定为采集客户端与普通浏览器之间的差异。

Manager后续只读实证见团队manager-browser-source-observation-20261007.md：已有Chrome的futario.com首页DOM有商品/价格和50张已加载图；已有New In tab实际在shop.com托管页，不能当作原Futario栏目URL成功。随后原JSON URL的Chrome新文档导航为ERR_BLOCKED_BY_CLIENT、无可核对来源HTTP状态，保守记第8次（不是源站429/200）。当前总8/40余32，body-repair的可选原路GET已取消授权；下一项仅为Manager独立授权的已有loopback代理对照，另保存工件。

后续第9次已有代理对照已完成，实证见T2-existing-proxy-20261007.md：同JSON URL/FashionScout UA，经既有无认证回环7897代理仍为429，实际保存18字节公开正文 **local_rate_limited**。原始字节SHA与第7次一致，但第7次原文文件仍不存在、不回填其result。最新总9/40余31；本Worker无在途来源请求。这一对照未证明改用当前系统代理即可恢复，不能据此把proxy模式接入生产。

## 有证据的新发现

Windows WinINET系统代理已启用，目标为回环HTTP端口7897，无认证字段、无PAC；端口确实有回环监听，进程族为mihomo。只读取端口与进程名分类，没有读取该软件的私有目录、配置、日志、命令行或凭据。WinHTTP显示direct，进程HTTP_PROXY/HTTPS_PROXY/ALL_PROXY等均未设置。

接口4为Up的非物理虚拟隧道接口，配置基准测试网段DNS及默认IPv4路由。Windows本地Find-NetRoute对源站当时的两个公网地址和DoH地址8.8.8.8都选择接口4。**已经确认系统选中的路由是隧道接口；尚未证明其上游出口IP、是否共用限流额度或是否引发429。** `trust_env=False`不改变操作系统路由。HTTPX官方说明它控制环境变量配置，不是操作系统隧道开关。[HTTPX环境变量](https://www.python-httpx.org/environment_variables/)

原系统DNS得到198.18.0.210，属于IANA的198.18.0.0/15 Benchmarking、非全球可达范围，因此原安全检查拒绝它符合设计。结合当前隧道/DNS元数据，这与fake-IP式DNS接管一致，但具体DNS模式仍是推断，不从网段反推具体软件配置。[IANA IPv4特殊用途地址](https://www.iana.org/assignments/iana-ipv4-special-registry)

离线合成检查实际PinnedBackend的数值sockaddr只解析一次，HTTPcore/PinnedTransport组成的GET路径、Host=futario.com、SNI=futario.com、证书校验开关正确；插入进程级合成HTTPS_PROXY后trust_env=False仍无proxy mounts。没有发现这些构造造成真实429的证据。合成TLS只是检查参数传递；真实诊断的证书/peer检查另有原始结果。

## 第7次响应与证据丢失

离线检查不能还原原18字节错误解释，因此在已过最新截止后按原根因范围仅GET同栏目一次：2026-10-07T05:40:03.753852Z（北京时间13:40:03.753852）实际返回429，原始Retry-After60，CF-RAY=a46a91a10a939dea-LAX，Content-Type=text/plain，Content-Length=18；fresh DNS首地址172.67.197.209与peer一致、TLS校验开启，耗时1.397秒。

此次读取了18字节，SHA256为 **fa2dd01ed96d38758e89e354653c39f366bc7a34e485772c8aa2174b53a465d3**。但诊断脚本仅允许固定error-code文本，错误地将其它所有文本替换为nontrivial body redacted；原文没有写入文件或stdout。执行工具已报告进程退出，已保存目录和输出没有原文，**原文无法恢复，本轮未取得可用于定位的可读错误解释**。这是本Worker的取证缺陷，不能声称已识别Cloudflare1015或其它数字错误码。

曾做离线公开短语哈希比对，未匹配；这些候选不是来源响应，未重写result或伪造正文。收到Manager证据质量反馈后停止候选匹配，不再试图猜测重构。最新原始result、此缺陷及其本地复现均保留。

累计保守 **7/40，最多剩33次**。最新独立证据中的not_before=1791351663.7538998，约北京时间13:41:03.753900；旧DB/hold/Run没有写入或迁移。正文观察16KiB/30秒上限，实际body18，无重试/redirect/子资源/详情/图片/生产Worker。第8次可选请求已被最新Manager指令暂缓，等待其浏览器页面证据，不在本阶段执行。

## 根因矩阵与判别步骤

| 项目 | 状态与证据 | 下一判别步骤 / 修复位置 / 验收 |
| --- | --- | --- |
| 初始系统DNS非公网 | 已证实198.18.0.210被安全检查拦截；当前DoH得到公网并能握手 | 应用已有显式google_doh模式可解决该解析阻碍；保留全部地址校验，不能放开198.18网段。验收：冻结resolver模式、公网与peer/TLS匹配。此处解决不了后续429 |
| 操作系统路由接管 | 已证实源站和DoH选择虚拟接口4；系统代理7897有mihomo监听 | 网络配置负责人确认现有隧道的实际路由/DNS模式和合法业务出口；若确有配置错误，在正式授权下修正该配置。验收：目标路由与预期一致、DNS不再异常。未授权切出口或更改配置，不把代理存在等同429原因 |
| 环境代理被HTTPX暗中使用 | 本次环境变量均未设置；离线注入代理也无mounts，定制backend直调socket | 在检查范围内排除应用层自动环境代理；WinINET与OS隧道是另一层，尚未确认浏览器实际代理链。不能仅改trust_env就声称物理直连 |
| Host/SNI/数值地址构造缺陷 | 本地合成断言通过，真实peer和证书验证通过 | 无根据不改底座。若浏览器实际使用不同最终域名/路由，应先核对Manager的只读URL和页面证据；不是将浏览器身份移植进采集器 |
| 错误解释丢失 | 已证实production SafeHTTP在非200前不读正文；本次独立诊断又过度脱敏丢掉非固定格式 | 修复新诊断副本：先保存<=16KiB原始私有文件，再hash/编码/字段脱敏。短公开纯文本不因格式未知被删除。离线验收普通429、数字code、敏感字段、HTML、二进制、上限。生产只在Manager另行批准后考虑 bounded issue evidence |
| 来源侧实际限制 | JSON和HTML在当前客户端路径均429/Retry-After60，普通浏览器成功是新用户证据 | 先核对浏览器当前URL、真实商品DOM与观察时间，排除缓存/不同域名；再对比客户端路径/内容。若需来源方定位，提供时间+Ray ID+URL/UA查匹配规则与计数键。是否Cloudflare规则、origin限制、共享出口、UA/TLS指纹均未证实 |
| 网关本地限流文本 | 第9次经现有proxy仍429，实际正文local_rate_limited；与第7次body hash相同 | 已有proxy并未恢复；该文本与Envoy本地限流过滤器的公开默认文本一致，可作为网关/反向代理限流的优先判别分支，不能断言本电脑运行Envoy或一定是mihomo造成。核对匹配规则/计数窗口、请求HTTP协议与浏览器实际路径；不做出口轮换 |
| 图集/归档实现导致429 | 请求在列表/HTML前就被拒，无详情/图片请求 | 当前429发生在解析/图集/归档之前，这些层无法通过修补解析器解决它。验收仍需真实发现→详情→源图→Worker归档→页面/收藏→导出切片 |

HTTP429本身不说明服务器如何识别用户、按什么范围计数，因此本程序7次不等于对方计数必然7次。[RFC6585 §4](https://www.rfc-editor.org/info/rfc6585/)

## 可执行的最小后续路径

第一步已在新范围执行准备：保存本报告与未改变的原始result，修正独立diagnostic捕获器并用合成数据证明不会再次丢失解释。当前error excerpt提案只是离线样例，不是生产隐私解析器；需要按新修订补足二进制/编码/原始字节保留测试。

离线捕获修正已完成：新的T2-body-repair-20261007.md与合成证据覆盖六类情形，先原始私有runtime文件flush/fsync，再分类/脱敏。旧第7次原文仍不可恢复，没有新原路请求。

第二步由Manager读取用户已有浏览器页面，核对当前商品确可见、最终URL和是否已有可用的非认证公开响应。浏览器成功意味着存在合法可用的用户访问路径，但不自动证明本机器采集客户端只需换UA或proxy。可利用已存在的公开页面静态内容做零额外请求分析；不搬Cookie/认证，不执行挑战，不请求提取出的图片。

第三步若路径差异仍不解释，来源/网络配置负责人需要以下可直接使用的最小资料：本次UTC05:40:03.753852Z、栏目URL、明确FashionScout UA、429/Retry-After60、Ray ID **a46a91a10a939dea-LAX**，以及本机路由选择接口4、系统proxy7897和WinHTTP direct的脱敏事实。Cloudflare站点管理员可用Ray ID和短时间窗查Security Events，查看匹配动作、规则和来源信息；采样查询未命中不等于请求未发生。[Cloudflare Ray ID](https://developers.cloudflare.com/fundamentals/reference/cloudflare-ray-id/)

修复只有在差异确认后定位到相应层：诊断丢失现在可本地修复；若正常网络配置错误由该配置负责人修复；若来源策略需来源方许可的自动访问方式或限额调整。没有依据时不改安全校验、不自动轮换出口、不用身份伪装试通。本阶段未联系任何第三方。

新实证让判别更具体：Envoy官方源码的本地限流过滤器会生成local_rate_limited文本，而非只根据“local”单词推测电脑出错。下一步应先核对实际网关/服务策略；普通浏览器已加载主页与新JSON导航本地阻断之间没有同URL成功对照，仍不能将任何一项当完整API可用证明。[Envoy本地限流源码](https://github.com/envoyproxy/envoy/blob/main/source/extensions/filters/http/local_ratelimit/local_ratelimit.cc)

## 原始工件与保护

`.runtime/t2-root-cause-20261007-01/` 保存network-metadata、routing-metadata、proxy-owner-metadata、offline-transport、result、baseline摘要与实际脚本。公开docs只放脱敏元数据/结构化响应，未保存秘密proxy URL/PAC/软件配置或个人浏览内容。

| 文件 | SHA256 |
| --- | --- |
| T2-root-cause-20261007-response.json | 2c9c355be2194479c41c6d8cfce7e8dbcf30010f6c57f244cca86d406aebe466 |
| T2-root-cause-20261007-network.json | ff414afb059391c362c376bd4affab0dee57b251d1b0a93dde6b6ed1a9448bcc |
| T2-root-cause-20261007-routes.json | a5084a200c7215a1ba529c2599f329ded7bbb33031eb4690d5c80c488dacc540 |
| T2-root-cause-20261007-offline.json | 00a886bbdf69d436d5f95cf3bcd8228e6f758ad47db651c9b84b015889445c0d |

第7次观察前后旧root和251个项目保护文件hash一致。后续T6b Worker拥有新release脚本/测试/文档和README小节的并行变更，与本Worker只写诊断工件的范围分别记录。当前没有生产修复、旧DB写入、系统网络修改、预览56117或默认根操作；T2实站门槛仍未满足。
