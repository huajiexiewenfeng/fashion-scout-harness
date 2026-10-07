# T8 多站正常浏览器采集核心交付

交付状态：核心代码、仓库协议和受影响回归已就绪，待原 Manager 独立验收。不是安装或全站巡检完成声明。

原正式 Core Worker：local / 01a11078-dc20-7383-b1dc-54c9e37d5ce5；团队 fashion-scout-20261006-01a11029；p8-multisite / t8-multisite-browser。在 E:/github-workspace/fashion-scout-harness 的 main 原 checkout 工作；HEAD 保持 857eca53ae4b61a60fa33c4cda8f76af4c45c0aa。

本次 20 个核心代码/协议/测试输入的 SHA 清单及版本在 [T8-multisite-evidence.json](T8-multisite-evidence.json)，code_snapshot_sha256 为 **f6c52be52114034507d225693b9312a645d25f43168960e492f8c8ab02d7d880**。版本是排序输入文件 SHA 清单的摘要，不冒充 Git commit 或发布 wheel。

## 结果与边界

- 显式注册 Futario、RIHOAS、SimpleRetro。每个 browser Run 冻结一个 site_id、入口和 adapter；商品真实持久化为 site_id-数字 source_id。新站仅支持正常浏览器来源，不增加 HTTP adapter、任意主机或网络绕过。
- listing/detail 同站校验，会话依 Run/epoch，图片 ticket 依 Run/商品/站点。图片只接受精确站点已验证 CDN 路径；新站仅自身 www host /cdn/shop/files/，Futario共享 CDN 仅已验证店铺前缀。不同站的观察、ticket、URL、adapter 均拒绝。上传 URL仍与 Worker ticket逐字一致。
- 第二页真实 page_url 保留 ?page=2，固定入口路径只允许 page=1..1000且与page_number一致；其它参数/路径/跨站被拒绝。Futario Load More 可保持同一 URL。RIHOAS 已观察 collection/products 链接与详情 /products/{handle}按同站数字 ID+handle对齐，均保留真实观察URL。SimpleRetro同标题不同商品 ID不合并。
- 新款查询只纳入存在实际归档、可解码且 SHA/字节/已知格式尺寸匹配的本地图片。只有元数据、丢图、坏图均不显示空卡。直接商品审计、收藏缺图、版本与导出语义保留。查询不写用户状态；收藏/排除/已看/人工分类不重置。卡片增加来源站名。
- 程序默认提高为每站240张选中资产、100条观察、host3600秒、idle600秒；64MiB接收、25MiB单图、5000万像素及存储/磁盘边界保留。旧保存方案若精确等于旧程序默认，只对未来 Run解析为新默认，不改保存 JSON/revision；自定义限额保留。临时 browser部分覆盖与保存方案合并，不丢字节限制。旧 Run快照保持原40/12/900/120等限额。
- 旧HTTP v1摘要与快照、Futario v2显式模式/浏览器请求键、原回执字节与客户端意图规格保持兼容。新显式browser限额摘要只记录实际传入字段，避免未来默认变化破坏幂等。归档、恢复、scope及混合历史导出继续共用原路径，001–010迁移不变。
- 日期不可见仍unknown。未闭合图库不能complete；browser.gallery闭合也不证明完整product.images，Run继续诚实partial。冻结查询total是初始成员计数；后续文件损坏时不渲染空的新款卡片，刷新建立新成员快照。

## 实际验证

全部受影响节点的最新结果去重后 **235 passed / 1 skipped / 0 failed / 0 errors**，不是重跑全仓测试。唯一跳过是本机账户不能创建合成 Windows符号链接。原始失败与后续修复日志保留；首轮新增测试误读既有回执字段及意图键格式，修正断言后通过。

| 检查 | 实际结果 | 日志 |
|---|---|---|
| browser采集、API新款/用户状态、core Run与client初轮 | 98pass / 4个新增测试断言失败 / 1skip | T8-core-tests-1.txt/xml |
| 新站/实图可见性定向修复 | 14pass / 1个测试意图键格式失败 | T8-multisite-tests-2.txt/xml |
| 固定客户端规格、adapters/media/exports兼容 | 130pass | T8-storage-compat-tests-3.txt/xml |
| 最终browser采集、API新款、Run兼容 | 66pass / 1skip | T8-core-tests-4.txt/xml |
| app.js语法；Python编译 | 退出0 | 命令在evidence JSON |

新增正例是明确的合成DOM事实与合成WEBP字节，经真实生产API → 独立Worker → Pillow → Archive → 查询，不用SQL伪造来源成功。覆盖三个顺序单站Run、同数字ID三个命名空间、真实分页URL结构、元数据先隐藏/归档后出现、跨站/错ticket/错URL拒绝、所选站独立baseline、同标题两商品与Futario重查保留用户状态。37条排除的独立合成旧库回归确认初始化和读视图不重置；旧数据兼容夹具使用SQL只重建旧限额/摘要，不充当正向采集证据。所有正向browser测试collection_http=0。

Manager另行独立运行新站/可见性测试19pass，原生通知提供路径 E:/github-workspace/.team/fashion-scout/t8-manager-tests.txt；本 Worker未把该通知改写为正式验收。

保护基线 .runtime/t8-multisite-20261007-01/baseline.json含392个原tracked SHA。审计无越界改动；main/HEAD、旧证据、001–010保持，6项发布路径变化归属并行T8b。此 Worker没有执行发布构建/冻结/安装、个人Skill写入、日常库操作、分支/worktree/reset/commit/push或额外来源访问。pytest报告已有TEMP清理警告，未手工删该目录或改变环境。此前冻结旧core输入造成的8个release测试错误属于T8b处理，本交付未重跑或替换其发布输入。

## 发布与实际三站巡检交接

T8b在 Manager通过本代码清单之后，按既有授权冻结最新core wheel与资源、制作并核验包，再按已授权升级流程应用仓库Skill协议；本交付未替代这一阶段。最终发布必须包含domain/sites.py、上述20项摘要覆盖的输入以及仓库Skill引用，不能复用T2/T7旧wheel/resources来宣称T8已安装。

实际来源DOM依据来自本轮原生Manager验证：RIHOAS主listing product-block[data-product-id]及当前主form/slider；SimpleRetro限定主[id^=product-list-][id$=__main] > product-card及当前h1/product-gallery数字ID，忽略隐藏推荐和无关SEO；Futario选项限当前.product-single__meta。细节与示例ID记录在 [browser-acquisition.md](../../skills/fashion-scout/references/browser-acquisition.md)。本 Worker尚未执行新release的实站三站文件采集；Manager将继续这一阶段。

升级后 Codex代办以下步骤，用户无需JSON：读取当前绑定实例、intents/latest/progress/sites/default-plan；原活动Run先按同Run恢复。随后依次以source_mode=browser/site_ids=[该站]建立Futario、RIHOAS、SimpleRetro Run并核对冻结入口/adapter/limits。每站从当前正常主列表提交真实数字ID，选约20款的有限图库范围；按主商品DOM逐款枚举所有可观察图、真实序号/闭合状态/当前选项。等待Worker资格ticket，在当前pageAssets新inventory按确切URL选中bundle，固定客户端核对manifest/SHA/字节后上传，等待archived或登记failure，再提交finish，读终态与归档计数才进入下一站。触顶、工具异常或无可靠闭合证据如实partial/unknown。

巡检结束分别核对site_id、商品数、真实图片数、缺失、未知日期、归档SHA和Run范围；刷新新款只显示实图，原排除/收藏状态保留。每站的票据、会话、bundle及计数不能混用。正常页面不可用不尝试products.json/.js、代理、Cookie或营销CDN替代。
