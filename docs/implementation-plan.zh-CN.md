# v0.2 实施计划与接口／数据契约

版本：v0.2-contract-2；原设计日期：2026-10-06，附 2026-10-07 浏览器来源修订。下文保留设计基线；已实现程度以验证记录为准，不能把设计当验收。产品决策以[架构 v0.2](architecture.zh-CN.md)为准。参数必须经 Windows 与 Futario 实测后锁定。

## 2026-10-07 来源入口修订

用户接受“采集时保持 Codex 运行即可”。新增 source_mode=browser/futario-browser-host-v1；原 HTTP 快照不迁移成 browser，001–009 不改，只增 010 收件箱／来源会话／回执。来源捕获属于 Skill 当前前台浏览器工具，Python 不接入 Codex 内部协议。仅当前正常页面可观察 DOM 和 pageAssets 导出；验证／登录／安全警告即停止，不重试被客户端阻断的 JSON，不改网络或保护设置。

固定客户端先 start 明确接受 Run，再 browser-attach、browser-observe。Worker 持久化元数据并计算资格后，browser-status 返回可导出的 gallery ticket；Skill 才按原 URL 选择 pageAssets 并 browser-upload。Web 只接受带固定客户端认证的字节流，不接受任意本机文件路径。客户端只读 native 工具导出目录内的有限 manifest／稳定文件句柄，校对 ID、URL、SHA、大小。Worker 复用 Pillow、同卷临时文件、Archive journal 与 fencing，来源文本不能指定业务成功状态。

source_wait 持久化为 interrupted/SOURCE_HOST_REQUIRED，保留 completed；不因 ensure/read/attach 创建新 Run或反复领取。等待不消耗实际处理时钟；独立导出／维护继续。browser-continue 是原 Run 新 Attempt／epoch，旧会话不再写入；resume 是原客户端意图回执恢复。上传回执可在 native 临时文件已消失后按原键核对。

browser.gallery 与原 product.images 完整性分别记录。不可观察原全图集时 Run／v2 ZIP 仍 partial/unknown；页面图库全齐不覆盖原最新完整图集指针。v1 请求空值字段／客户端 spec/body/hash／HTTP 响应和 v1 快照摘要保持旧形式；显式新来源参数使用内部版本 2 的请求指纹，新浏览器客户端 spec 标 2。混合历史 v2 每个版本保留 coverage_scope，所有历史独有 SHA 照旧导出。

冻结浏览器限额默认观察 40、选中资产 12、接收字节 64 MiB、单图沿用 25 MiB／50 MP、单前台会话 900 秒、空闲 120 秒。64 MiB 是本机接受／存储约束；浏览器自动背景请求数、字节和 peer 未计量，不能宣称总 HTTP 或网络硬上限。真实阶段另受 Manager 的剩余次数和导航许可约束。可执行流程见 [Skill 浏览器来源说明](../skills/fashion-scout/references/browser-acquisition.md)；本地测试不是实站验收。

## 1. 技术选择与官方依据

| 层 | 单一推荐 | 理由及实现门槛 |
| --- | --- | --- |
| 运行时 | CPython 3.13 x64，项目独立 venv | 下载、文件校验、SQLite、ZIP 可共用一语言；P1 锁定受维护补丁与实际 Windows wheel，不依赖 Codex 内部 Python |
| API | FastAPI + Uvicorn（单 Web 进程）+ Pydantic 2 | 请求／响应结构校验与 OpenAPI；采集 Worker 另进程，Uvicorn 多 worker 不等于业务执行器 |
| 页面 | Jinja2 模板 + 原生 JS/CSS | 页面少、无独立前端构建链；图集、收藏和状态轮询即可；模板自动转义，不注入源站 HTML |
| 状态／队列 | Python sqlite3，编号 SQL migrations，无 ORM | 显式事务、唯一键和租约 CAS 易核对；SQLite 本机 WAL、foreign_keys=ON、synchronous=FULL、busy_timeout=5000ms；短事务、有限忙重试 |
| 来源 HTTP | HTTPX | 连接池、流式下载、明确连接／读／写／池超时；业务层单独实现有界重试与限速 |
| 图片 | Pillow | verify 后重新打开并 load 实际解码；记录格式／尺寸，启用像素限制，不把 HTTP 200 当成功 |
| 输出／哈希 | 标准库 zipfile、hashlib、pathlib | ZIP64、逐文件哈希和安全路径；图片以 ZIP_STORED 为主，信息文件可 deflate |
| 启动 | 项目内 Python launcher，固定入口；双击入口仅薄包装 | 管理独立 Web 与 Worker，默认本机监听；不自动安装、采集、创建计划任务或注册 Windows 服务 |
| 验证 | pytest + HTTPX API 测试，合成 HTTP／文件故障夹具；Windows 实测记录 | 覆盖真实故障边界；文档阶段不安装或运行镜像测试 |

在 P1 依赖准入时记录解释器版本、sqlite3.sqlite_version、所有直接／传递依赖精确版本与哈希锁，形成可复现 Windows 环境。不能把上述主版本范围当锁文件。本机 PATH 的 python 当前不可用；团队工具 Python 3.12.14 仅为协调工具，并非项目环境。

SQLite 官方已公布 WAL-reset 修复：采用 **SQLite >= 3.51.3** 作为本方案单一门槛；启动自检不满足则拒绝写入并报环境不兼容，不静默换日志模式或替换宿主 DLL。须在 P1 选择满足条件的项目解释器发行构建后验证。WAL 只用于本机磁盘，仍只有一个 writer；备份使用一致性 backup API，不直接复制正在写入的单个 db 文件。[SQLite WAL](https://www.sqlite.org/wal.html)、[Python sqlite3](https://docs.python.org/3.13/library/sqlite3.html)

技术资料核对日为 2026-10-06；官方能力是选型依据，不是项目实现证明：

- FastAPI 支持 Jinja2 模板与静态资源；Pydantic 提供模型校验。项目会拒绝未知写字段，并使用严格布尔／数值约束，避免默默转换用户参数。[FastAPI 模板](https://fastapi.tiangolo.com/advanced/templates/)、[Pydantic Models](https://pydantic.dev/docs/validation/latest/concepts/models/)
- HTTPX 分别控制 connect/read/write/pool 超时；流式 read 超时不能替代整次下载时限，项目另设总时限与最大字节。[HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/)
- Pillow verify 不实际解码，因此仍须 reopen + load；ZIP 生成后要核验清单及内容，不能只以写文件成功判定。[Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html)、[Python zipfile](https://docs.python.org/3/library/zipfile.html)
- Python 提供 Windows 进程创建标志，但脱离控制台不自动证明逃离宿主 job 生命周期。启动器要验证父终端／对话退出后仍存活，失败则作为 A03 阻塞，不宣传后台常驻已实现。[Python subprocess](https://docs.python.org/3.13/library/subprocess.html)、[FastAPI 进程说明](https://fastapi.tiangolo.com/deployment/server-workers/)

## 2. 本机启动与 Skill 调用

以下是**拟定命令契约，不是现在可执行的安装说明**：

| 固定入口 | 行为与返回 |
| --- | --- |
| launcher ensure --json | 校验本机 runtime descriptor、端口归属、应用实例 ID；复用或隐藏启动两个独立进程；返回 app_instance_id、api_base_url、web_ready、worker_state、resuming_run_ids |
| launcher status --json | 只读本机进程／健康信息，不启动、不创建任务 |
| launcher stop --graceful | 停止领取，安全边界落盘，保留可恢复任务；不取消业务任务 |
| client request <固定子命令> --json-input <受控文件> | 从本机配置取凭据，调用下表 API；输出结构化结果，绝不直改 DB |

项目内入口拟为 python -m fashion_scout.launcher 与 python -m fashion_scout.client；由安装后 Skill 保存解释器和安装根的绝对定位。安装、首次根目录设置属于一次性准备。日常调用不安装软件、不拼接自然语言 shell。数据默认根为用户 LocalAppData 下 FashionScout；media_root 可单独配置。descriptor 只记录实例／端口／凭据文件定位，不向对话输出凭据。

Web 只监听 127.0.0.1，默认端口 8765（占用冲突明确失败，不连接陌生服务）。启动器使用参数数组、固定 cwd、受控 env、shell=False、日志文件重定向；子进程不继承对话 stdout 管道。禁止依赖任意 PID 文件杀进程：核验 PID＋启动标识＋应用实例及健康接口。具体 Windows flags 和宿主 Job Object 行为必须通过 P1 实测后固定。

| 用户意图 | Skill 行为 |
| --- | --- |
| 看看新款／结果 | 如需要先 ensure 服务；只 GET /v1/products 与 /v1/runs/latest，不 POST Run；显示最近巡检与覆盖 |
| 开始巡检 | ensure → POST /v1/runs，生成并保存本次意图 request_key；断连按同键查询／重放，不能换键猜测未接受 |
| 进度 | GET 指定 Run，执行器离线／恢复与业务状态分列 |
| 收藏／取消收藏／类别修正 | PATCH 商品用户状态，字段范围固定 |
| 导出收藏 | POST /v1/exports，后台持久生成；返回状态与就绪下载链接 |
| 重试失败部分 | POST 原 Run retry，保留原 run_id 和历史，不创建新巡检 |
| 修改默认方案 | 单独 PATCH settings/default-plan，显式用户意图与 revision |

ensure 不创建新 Run；它启动 Worker 后，**已接受任务可能恢复并产生来源请求**。Skill 回答“正在恢复此前任务 X”，不能声称读请求本身发起采集。无已接受任务时，ensure／页面 GET 不应产生来源网络请求。

本机客户端使用受控本地 token；浏览器使用同源 HttpOnly 会话及 CSRF。首次浏览器会话由启动器一次性 bootstrap 建立，短时失效并从地址移除，不把长期 token 放 URL。限定 Host、Origin，不开放通配 CORS。预览／ZIP 路径只接受业务 ID，禁止任意本地路径。所有来源请求只向配置域与经验证的图片 CDN，逐次检查 DNS／重定向，拒绝回环、私网、文件协议；无需用户参与日常操作。

## 3. HTTP 契约 v1

所有时间 UTC ISO 8601；ID 为不透明字符串（源站大整数也用字符串）；金额使用十进制字符串与币种，缺失为 null。响应 JSON 含 request_id；错误为 {error:{code,message,retryable,details},request_id}。默认分页 limit=40、最大 100，商品 cursor 绑定只读查询会话的冻结集合、分组和排序键（见 3.2）；不能只冻结时间上界而使用实时已看分组。GET 无业务写入或自动补抓；真实浏览状态单独写。

### 3.1 任务与设置

| 方法／路径 | 输入 | 输出／约束 |
| --- | --- | --- |
| GET /v1/health | 无 | app_instance_id、schema_version、web_ready、worker_state、heartbeat_at；不泄露路径／凭据 |
| GET /v1/settings/default-plan | 无 | revision、已保存方案与可用范围 |
| PATCH /v1/settings/default-plan | expected_revision、明确变更字段 | 乐观锁更新；409 冲突；临时巡检不调用这里 |
| PATCH /v1/settings/storage | expected_revision、media_root | 校验本机绝对路径／可写／容量；只影响后续归档，保留旧 root 记录；不移动历史文件 |
| GET /v1/sites | 无 | 已配置首站入口、适配器能力／限制、最近覆盖；不探测源站 |
| POST /v1/runs | request_key、trigger=skill/ui、overrides={} | 新建 202；复用 200；返回 run、reused、reuse_reason、ignored_overrides；只有此端点创建新巡检 |
| GET /v1/runs/by-request/{key} | 原意图键 | 原来已接受的 Run；不存在 404，不自动创建 |
| GET /v1/runs/latest | 无 | latest_run 可 null、latest_completed_at、latest_successful_at；无任务显示未巡检 |
| GET /v1/runs/{id} | 无 | state、stage、snapshot、计数、coverage、worker_state、issues、resumed_at |
| POST /v1/runs/{id}/retry | request_key、scope=failed、item_ids 可选 | 原任务的修复 Attempt；只重试失败／缺失／中断，保留历史；已有其他活动 Run 返回 409 |
| POST /v1/runs/{id}/cancel | request_key | queued 可直接取消；运行中 cancelling，安全点取消；终态返回现状 |
| POST /v1/maintenance/verify | request_key、scope=all/selected、product_ids | 持久核验任务；不隐式补抓；问题集中列出 |
| POST /v1/maintenance/backup | request_key、配置中的 destination_id | DB 一致性备份、素材清单／校验；不接受任意路径 |
| GET /v1/maintenance/{id} | 无 | 核验／备份状态、进度、缺失与错误；不启动额外工作 |

创建 Run 的检查顺序：校验 payload → 按 request_key 查已接受请求（相同键不同 payload 为 409）→ BEGIN IMMEDIATE 内检查活动巡检 → 如有，绑定新 request_key 到该 Run 并明确 overrides 未采用 → 如无，验证已保存设置、冻结快照、插入 Run 与请求映射 → COMMIT 后返回。索引仅允许一个活动巡检，终态释放；同键在任务完成后仍返回原任务，不再次执行。

第一次建立基线与 subsequent 由已完成的 discovery baseline 判断；partial 不将基线标成完整。Run 中的 seen_before_run 从创建前观察快照决定，不能因重试已写 Product 就把本轮新发现误判成旧品。retry 将原终态结果存入 RunAttempt 后转 queued，巡检 ID 不变；活动唯一约束仍生效。终态取消后的继续属于显式 retry 原任务，不由启动器自动重启。

默认方案的固定字段为 site_ids、window_days、unknown_date_policy（include/exclude）、discovery（page_size/max_pages_per_pass/passes/max_requests/max_products）、max_details、network（detail_concurrency/image_concurrency/min_interval_ms/timeouts/max_attempts）、storage（max_image_bytes/max_pixels/run_download_bytes/min_free_bytes/preview_cache_bytes）。数值必须正整数、已知 site_id 必须启用；window_days 首版允许 7 或 14。overrides 只允许 window_days、unknown_date_policy 与已保存站点子集，资源上限修改在设置中单独完成。实际 Run.snapshot 必须展开全部值及绝对 window_start/window_end、adapter_version、plan_revision，恢复不重新读取默认值。

以下为缩略拟定返回，仅展示部分 snapshot 字段：
~~~json
{
  "request_id": "req-01",
  "reused": false,
  "reuse_reason": null,
  "ignored_overrides": [],
  "run": {
    "id": "run-01",
    "state": "queued",
    "worker_state": "online",
    "plan_revision": 1,
    "snapshot": {
      "site_ids": ["futario"],
      "window_days": 14,
      "unknown_date_policy": "include",
      "new_run_trigger": "manual"
    }
  }
}
~~~

### 3.2 商品、素材和导出

| 方法／路径 | 输入 | 输出／约束 |
| --- | --- | --- |
| GET /v1/products | view=new/favorites、category、cursor、limit | latest_run_summary、items、snapshot_id、snapshot_expires_at、next_cursor；new 包含未排除且曾命中规则的发现款，图片完成不是可见门槛；未看优先与稳定翻页规则见下文，不冒称真实上新 |
| GET /v1/products/{id} | version_id 可选 | 商品、日期依据、人工状态、最新可用／最新完整／最新观察、图集范围、缺失和历史列表 |
| PATCH /v1/products/{id}/user-state | expected_revision；favorite/excluded/category_override 可选 | 仅变更提供字段；null category_override 清除人工覆盖；不删图片 |
| POST /v1/products/{id}/view-events | event_id、version_id、version_revision | 实际打开且呈现至少一张图后幂等记录 viewed_at／seen_version_id／seen_content_digest；纯列表或错误占位不调用；版本摘要由服务核验 |
| GET /v1/assets/{id} | rendition=preview/original | 受控文件；不存在 404 ASSET_MISSING，GET 不补抓；缺失事件由核验任务记录 |
| POST /v1/exports | request_key、selection=favorites | 202 新导出／200 幂等复用；冻结商品、版本、全部已存素材集合及 promised_coverage／required_coverage，空收藏 422 |
| GET /v1/exports/{id} | 无 | state、商品／文件数、missing_count、issues、download_url（就绪才有） |
| GET /v1/exports/{id}/download | 无 | 就绪 ZIP；未就绪 409，已丢失 410 |
| POST /v1/exports/{id}/retry | request_key | 同一冻结快照重建包，不重新采集、不按当前收藏重选 |

**商品集合与排序。** 规则判定命中即持久设置 Product.first_eligible_at 与规则证据，不等待下载或归档成功。new 选取 first_eligible_at 非空且未 excluded 的商品，category 使用当前有效分类；已看仍在集合中。历史从未命中的元数据项在任务明细查看。favorites 取 favorite=true 的全部商品（包括缺图），同样未看优先；取消收藏仅在刷新后改变当前查询集合。返回 media_state=queued/downloading/ready/partial/failed，无图片用占位，latest_available_version_id 允许 null。

排序键固定为 (seen_group ASC, first_seen_at DESC, product_id ASC)，seen_group=0 表示 viewed_at 为 null，1 表示已看。同组用稳定 ID 破同时间并列。刷新时看过 A、未看 B，则 B 位于 A 前；A 留在已看后组，不被删除。仅普通 Observation、图集重排、原 URL 改写或失败重试不重置 viewed_at。

仅对 viewed_at 非空的已看商品，实际可用图片内容集合摘要与 seen_content_digest 不同才设 has_material_update=true；未看商品不加“看后更新”标记。摘要按去重 SHA-256 集合排序计算，不含观察时间、图序或 URL。只显示更新标记，不自动把已看商品推回未看组；补齐图片若实际改变集合也只标更新。新版本还未获得可读图片则提示处理状态，不猜测内容更新。view-event 指向实际已呈现版本＋revision（看历史版本也可），服务保存其摘要；重复 event_id 不刷新时间或覆盖后续已看证据。

**稳定分页会话。** 首次 GET 在短只读事务中读取全部合格 ID 及 seen_group、first_seen_at、product_id，按上式固定顺序后释放事务。Web 保存 15 分钟的只读内存查询快照，属于可丢弃查询缓存，不写业务 DB、不维持长事务。cursor 仅携带受签名的 snapshot_id、next_index、过滤摘要与有效期；每个 ID 在该链只返回一次，重放同 cursor 返回同一 ID 段。浏览写入、分类／收藏／排除变化、新商品或新素材均不移动当前链的 ID 与分组；可更新卡片状态但不得重排或插入。刷新不带 cursor，重新建立快照并应用全部新状态。内存快照被逐出、服务重启或到期时返回 410 CURSOR_EXPIRED，提示刷新，绝不静默接续实时排序。不同过滤条件用旧 cursor 返回 409。因此读第一页时标 A 已看，继续后页不会漏项或重复；新状态刷新后才把 A 移到后组。

只读商品返回 album.expected_count（枚举不完整可 null）、stored_count、missing[]、coverage_scope、coverage_complete、verified_at，不能把 stored_count 填进未知 expected_count。missing 项含 source_image_id、source_url、reason、retryable；范围外媒体写入 capability_notes[{scope,status:unknown/unsupported,detail}]，既不混成已发现缺图，也不产生 actionable Issue。

ZIP 布局：安全 product_id/（最新可用版本图片在前、历史独有图在后）、product.json、missing.json；包根 manifest.json 与 manifest.csv。每个实际文件列 path、asset_id、sha256、bytes、product_id、version_ids、来源 URL；商品信息列原字段与时间依据，不添销售结论。无可用图片的收藏款仍生成信息与缺失文件。

导出创建时冻结每款 promised_coverage（明确承诺的支持区域，首版 product.images 图集）和 required_coverage（该区域枚举状态、应有来源图片关系、选定版本、全部已存历史资产集合）。必需图集关系使用快照时最新已观察的支持范围 manifest，即使默认预览回退旧可用版本，也不能抹掉最新已发现缺图。枚举尚不完整时保留 expected_count=null 与原因，不缩小承诺或把当前已存数量当应有总数。

导出状态：queued/running/succeeded/partial/failed。required_coverage 内缺失、枚举不完整、损坏或冻结资产不能读时，有效 ZIP 可产出但标 partial；承诺范围完整且文件清单校验通过则 succeeded。范围外 unknown／unsupported 仅写 capability_notes，不改变成功状态、不增加 missing_count、不生成需人工处理的常驻告警；成功文案为“承诺范围内完整”，不是“全媒体完整”。例如 product.images 图集全齐、视频在范围外未支持 → succeeded＋能力说明；图集已发现 6 张仅存 5 张 → partial、missing_count=1。范围内图数未知且只存 5 张也为 partial，不能用视频范围外规则豁免。

完全无法写有效包为 failed。存入临时 ZIP、核验文件集和每个哈希后原子改名；ZIP 与 manifest 不一致不能提供下载。导出前后源文件变动则拒绝该文件并列缺失，不把旧核验当现状；不可变归档路径减少竞态。出包失败不改变原采集结果。

## 4. Futario 适配契约与初始参数

官方 Product Ajax API 描述了 products/{handle}.js，但不保证第三方站点永远开放；collection products.json 是本次站点小样本观察，不宣称有通用稳定 API 承诺。[Shopify Product Ajax](https://shopify.dev/docs/api/ajax/reference/product)

published_at、created_at 与首次发现分开保存，源站发布不等于真实款式上市。[Shopify JSON 字段](https://help.shopify.com/en/manual/shopify-admin/using-json)

适配器接口只输出 DTO，不写 DB／文件：

| 方法 | 返回契约 |
| --- | --- |
| capabilities() | adapter_version、discovery_method、date_fields、media_scopes 与 verified/unknown 状态 |
| discover(entry,cursor,limits) | items[{source_id,handle,url,source_published_at,raw_date,category_raw}]、next_cursor、terminal、page_signature、evidence_url、observed_at |
| fetch_product(ref) | 原字段、variants、album[{source_image_id,url,ordinal,variant_ids}]、范围／总数可靠性、updated_at、etag/last_modified（如有） |
| normalize_media_url(url) | 仅经站点验证的尺寸处理，保留原 URL 和转换说明；不全局删查询参数 |

正常公开 HTTP 结构化数据优先；结构变化即记录错误，首版不自动启用浏览器绕过。日期按来源偏移转 UTC，无偏移或解析失败记 unknown。下架只记 unavailable 观察；不得删除本地 Product 或素材，也不能因一次超时推断下架。

分页不按日期提前停止。每轮遍历配置的 New In 清单：直到有可验证结束条件，保存逐页签名、ID 去重数、实际上限。列表可能重排，因此在预算内做一次第二遍 ID 集核对；两遍稳定且各自到达结束条件，才记本次 discovery_complete（仍不是源站原子快照保证）。重复页、循环游标、集合变化、上限或错误均标 partial，不无限重扫；保留下次手动巡检线索。只支持这个栏目，不把其等同全站所有商品。

首次 baseline 的下载规则：日期处于 [run_created_at-window_days,run_created_at] 优先（默认 14 天）；unknown 默认 include 并标未知；已知更早仅保存发现元数据。后续：本轮首次发现（包括源日期较早者）自动归档并标“首次发现”；已归档商品重验图集；既知未归档者按本次日期规则再评估。先前因日期／预算未处理原因持久保存。未来日期异常归 unknown。无需人工预选或候选确认。

初始参数都是**建议起点，未实测校准**，保存在默认方案，可受控调整：

| 参数 | 提案 | 触顶语义 |
| --- | --- | --- |
| 页大小／页数 | 20；每遍最多 30 页，最多 2 遍，发现 HTTP 最多 60 请求 | 未获得结束证据为 partial；不是已覆盖 600 商品承诺 |
| 唯一商品／详情 | 每轮 600 个唯一发现；最多 300 个详情处理 | 超限持久列未处理，不报无新品 |
| 并发／频率 | 每站 1 个详情；2 个图片流；每站新请求至少间隔 1 秒 | 共用站点限速器，429 整站退避 |
| 请求超时 | connect/pool 10s、read/write 30s；整请求 120s | 有界失败；流式下载同受总时限 |
| 重试 | 首次＋最多 2 次；指数 2/8 秒加抖动 | Retry-After 优先；超过等待预算持久延迟，不提前重试 |
| 单图／像素 | 25 MiB、50 MP | 不解码超限内容；承诺图集内超限项计缺失／partial，不能改成范围外能力说明来豁免 |
| 单轮新增下载 | 2 GiB（流式累计＋在途预留） | 停止新下载、partial，保留已存与未完成步骤 |
| 空闲保底 | data_root 与 media_root 所在卷各至少 5 GiB，并预留包大小与临时文件 | 不够则停止对应写入，磁盘错误保留可恢复状态 |
| 预览缓存 | 512 MiB LRU | 仅可重建预览清理，不动正式素材与导出包 |
| 租约 | heartbeat 10s、lease 60s | 接管前核验旧本机进程已退出；时间过期不单独证明死亡 |

两张 2／4.3 MB 样本不足以估算全站存储；P1 记录分位体积、每款张数、历史增量及 ZIP 双份占用，再校准预算。多色、动态详情、发布日期真实含义、重排分页、完整栏目覆盖、源文件分辨率仍是明确待验证项。

## 5. 数据模型与不变量

所有表有 schema migration；外键启用。以下是下一阶段必须落实的逻辑约束，不是已存在表。

| 对象 | 核心字段／唯一性 |
| --- | --- |
| Settings / StorageRoot / Site | revision、默认方案、根目录 ID／路径／用途、来源域／entry／adapter；根不可静默重绑定 |
| Run / RunRequest / RunAttempt | id、state、snapshot_json、created_at、started_at、finished_at、lease_owner/epoch/until、cancel_requested；request_key 唯一＋payload_hash；Attempt 追加历史 |
| SiteRun / DiscoveryPage | run+site 唯一；pass/page/cursor/signature、discovered_ids、terminal、coverage/exclusions；完整基线按 site/entry 记录 |
| Product | site+source_id 唯一；first_seen_at 不变；first_eligible_at／eligibility_rule_ref 在首次命中时记入，不以归档完成为条件；latest_observation_id、latest_available_version_id、latest_complete_version_id |
| Observation | run+product+attempt+revision 唯一；原字段、原日期、解析依据、observed_at；不覆写人工状态 |
| ProductVersion / VersionImage | product+manifest_digest 唯一；有序来源／实际内容摘要；version+source_image_id 唯一，ordinal 保留；版本不删改已归档内容 |
| Asset / ArchiveJournal | storage_root_id、relative_path、sha256、bytes、format、width/height、state、verified_at；不可变文件键；journal 记 temp/final/DB 阶段 |
| WorkItem / Attempt | run+product+step+source_image_key 唯一；state、retry_after、次数、lease_epoch；新素材版本用独立 item generation |
| ProductUserState / ViewEvent | product 状态唯一；favorite、excluded、category_override、revision、viewed_at、seen_version_id／revision、seen_content_digest；event_id 唯一，采集无权覆盖已看 |
| ExportJob / ExportMember / ExportAsset | request_key 唯一；selection_snapshot、版本／资产列表、promised_coverage、required_coverage、capability_notes、output_hash、缺失项与状态；创建后范围冻结 |
| MaintenanceJob / Issue | 核验／备份范围与结果；错误码、关联 ID、retryable、evidence_ref；无凭据原始日志 |

逻辑幂等不等于物理文件自动全局去重。首版按商品归档，重复轮次复用同商品同哈希；跨商品可共享下载缓存，但各自保留来源关系，不承诺全库物理去重。重复 URL 不同 ordinal 的关系要保留；合并导出按哈希去重仍保留全部关系。

source_image_id 优先使用源站图像 ID；仅提供 URL 时由适配器生成版本化键（规范化来源 URL 的摘要＋同 URL 出现序号），保存原 URL，不能把它当文件内容哈希。图集顺序变化仍更新 manifest。构建中的版本先用独立 draft_id，manifest_digest 仅在明确来源及已取得内容后冻结；补齐产生新 revision，引用包含 version_id＋revision，避免导出引用可变对象。

版本构建两阶段：持久来源 manifest 与 pending 工作项；下载后确定内容哈希，再冻结版本。相同来源 URL 也需条件请求或重新下载校验：只有可信未变响应且本地校验有效才能复用；无校验器时重新 GET 比较哈希。partial 版本可逐项补齐为新 revision，保留旧 revision 与引用，不能修改已冻结导出快照。

文件提交前的 journal 用 run/item/epoch 和目标路径关联。落盘不可变目标可由任何恢复步骤核对，但“完成”写回必须验证当前 epoch；旧执行者最多留下可识别孤立文件，不能覆盖新文件。删除缓存／临时文件须验证根内路径、journal 所属与无活动使用，不批量猜测清理。

恢复顺序：确认旧进程失效 → CAS 提升租约 epoch → 核对 staging／归档及 DB → 复用已校验结果 → 继续未完成项 → 重算计数／coverage。DB busy 有限重试并退回队列；损坏／权限失败需人工处理，不新建空 DB 替代。已完成终态任务不因服务启动重跑。

## 6. 实现顺序、文件归属与依赖

以下目录均为拟新增，P0 未创建业务文件。文件所有者表示下一阶段任务范围，由 Manager 正式派发；本文件不自行创建团队任务。

| 单元 | 独占文件范围 | 编码／夹具前置 | 真实集成前置与交付 |
| --- | --- | --- | --- |
| T1 核心与本机底座 | pyproject.toml、锁文件、src/fashion_scout/domain/、db/、services/runs.py、launcher.py、worker.py、tests/core/ | 已验收 P0 契约 | 固定 DTO／migrations、并发判重、lease/journal、环境门槛，分别交付已验收接口与可运行产物 |
| T2 Futario 与素材 | adapters/futario.py、media/、tests/adapters/、tests/media/ | 已验收 T1 DTO／存储接口 | 等待 T1 数据层／任务实际产物验收；验证分页／日期／多色未知／坏图／同 URL 更新；提供 T5 归档契约 |
| T3 API 与简页 | api/、templates/、static/、tests/api/ | 已验收 T1 服务接口 | 等待 T1 业务服务产物验收；提供 T4 已验收路由契约与路由实现；真实素材展示另等 T2 归档验收 |
| T4 Skill 客户端 | client.py、skills/fashion-scout/SKILL.md、tests/client/ | 已验收 T1 launcher 接口＋T3 路由契约后可用 Mock 编码 | 必须等待 T1 启动器＋T3 实际路由产物验收，才验证意图隔离／request_key／无 DB 直写的真实调用 |
| T5 ZIP／维护 | exports/、maintenance/、tests/exports/ | 已验收 T1 数据接口＋T2 归档契约后可用素材夹具编码 | 必须等待 T1 数据层＋T2 实际归档产物验收，才验证真实收藏集合／ZIP／备份恢复 |
| T6 集成与可靠性 | tests/integration/、docs/verification/；仅提出其它模块修复需求 | 已验收 A01–A13 检查方案；可先编写故障夹具 | T1–T5 实际产物验收并接入后执行 Windows 关闭／kill／休眠／磁盘故障与整链路；原所有者修复 |

首个可运行纵向切片由 T1 加 T2/T3/T4/T5 的最小路径形成：已配置 Futario → Skill 开始巡检 → SQLite 任务 → 独立 Worker → 小样本图集校验归档 → 页面浏览／收藏 → ZIP → 中断恢复与第二次幂等。保守小范围导致 partial 是允许的诚实结果，不能伪称完整站点支持。

编码并行与集成放行分别记录：T1 接口经 Manager 验收后 T2／T3 可并行；T4 还需 T3 路由契约、T5 还需 T2 归档契约验收，才可基于固定 Mock／夹具独立编码。对应真实实现尚未验收时只能报告单元／契约检查结果，集成任务保持等待，不能以 Mock 通过代替前置产物或整链路验收。T3 与真实媒体的集成也等待 T2；T6 等全部必要实际产物。Manager 按这些前置分别派发，不把“T1 后可并行”解释成一律具备集成条件。

migration 与公共 DTO 仍由 T1 单一所有者维护，其他任务提交变更需求，不能各自改表。串行主线先贯通一条真实链路，再补齐故障与全范围验收。任何阶段只通过自身项，A01–A13 未全覆盖不得宣布 v0.2 交付。

P0 仅文档：核对 Git diff、链接、旧概念矛盾与完整验收映射。P1 之后才运行有意义的 API／事务竞态／文件断点测试，不为本说明写镜像测试。
