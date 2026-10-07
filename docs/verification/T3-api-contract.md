# T3 本机 API / 浏览器契约（交给 T4）

R1补充（2026-10-06）：HTTP契约不变。页面在用户状态PATCH或view-event成功后只读GET单商品，原位置同步有效分类与素材更新标记，冻结ID链不重排。retry/cancel存储get/set失败时零POST并恢复按钮；响应不确定保留原持久键；成功响应后清理失败明确提示已接受并保留页面内确认结果，后续先清理而不新建请求。主动历史选择与自动缺图回退的页面提示已分开。

版本 T3-local-v1，2026-10-06。实现基于 v0.2-contract-2；T2 实站素材门槛仍未验收。本契约不授权客户端直改 SQLite、探测来源或安装软件。

## 启动与身份

固定项目解释器运行 `-m fashion_scout.launcher ensure --data-root <已配置绝对根> --port <已配置端口> --json`，复用 T1 的 PID/birth/executable/command 与健康 HMAC 校验。返回 `app_instance_id / api_base_url / web_ready / worker_state / resuming_run_ids`。ensure 不创建新 Run，但既有已接受任务可能恢复；需要如实告知用户。只读 status 不启动服务。默认数据根行为仍由 T1 控制，T3 的所有验证均显式隔离。

`open` 是新增固定 launcher action，参数与 ensure 相同：ensure → 核验实例 → 本地读取 `control/<instance>.key` → Bearer POST `/v1/session/bootstrap` → 系统浏览器打开一次性入口。stdout 只返回普通启动结果与 `browser_opened`，不输出 key 或一次性 URL。`browser_opened:false` 不能声称已打开。

T4 从自身已核验 descriptor（`control/runtime.json`）定位实例 key，内存读取，API 使用 `Authorization: Bearer <key>`。不得把 key 加入 argv、URL、日志、stdout、对话或浏览器 storage。不要接受任意基址／任意路径替换本地实例。禁用环境代理，固定 `http://127.0.0.1:<port>`，先复用 T1 `verify_health` 核验身份。

## 页面会话

1. 本地 Bearer POST `/v1/session/bootstrap`，JSON `{}`（拒绝多余字段），返回 `bootstrap_url / expires_in:60 / request_id`。此返回仅用于本地打开，不应打印。
2. URL 为同源 `/bootstrap#<一次性随机码>`。码在 fragment，HTTP 访问日志不接收它。外部脚本载入后立即 `history.replaceState` 清除 fragment，再 POST `/v1/session/exchange` `{code}`。成功后 `location.replace('/')`。同一码第二次或过期返回 401；服务重启失效。
3. 服务设置实例/端口命名的 host-only、Path=/、HttpOnly、SameSite=Strict Cookie，8 小时绝对有效期。会话仅内存保存，不写业务 DB。
4. 浏览器 GET `/v1/session` 取得 `csrf_token`，仅保存在页面内存。POST/PATCH 必须带精确同源 Origin 与 X-CSRF-Token；普通 Bearer 客户端无 Origin 时不需要 CSRF，出现错误 Origin 一律 403。
5. Host 必须精确匹配 `127.0.0.1:<configured-port>`；无通配 CORS。跨站 Sec-Fetch-Site 拒绝。所有响应 no-store、no-referrer、nosniff，页面 CSP 禁止外部脚本、内联脚本和 framing。

本机 HTTP 使用 `Secure=False`，以确保真实浏览器可发送 Cookie；不冒用只能在 HTTPS 可靠工作的配置。此安全边界面向浏览器跨站攻击，不隔离同一 Windows 用户下的恶意本地进程。浏览器 Cookie 按主机而非端口隔离；端口/实例命名避免应用误用，不能替代 OS 文件权限。未来外网、多用户、HTTPS 属于范围外。

## 通用格式

JSON 响应含 `request_id`；错误为 `{error:{code,message,retryable,details},request_id}`。图片成功响应为二进制且 X-Request-ID 响应头存在。写 DTO 拒绝多余字段、错误类型、非法 null；布尔与正整数严格校验（包括拒绝 window_days=7.0）。ISO 时间为 UTC；ID 为不透明字符串。

健康 `/v1/health` 保留 T1 handshake 字段和 HMAC proof，以维护启动安全；它不要求 Bearer。首页/固定静态外壳也公开，但业务 JSON、图片均需 Bearer 或有效浏览器会话。

## 已实现路由

| 方法 / 路径 | 请求 / 语义 |
|---|---|
| GET `/v1/settings/default-plan` | `{revision,plan,available}` |
| PATCH `/v1/settings/default-plan` | `expected_revision` + 提供的顶层方案字段；嵌套 discovery/network/storage 是完整严格对象；revision CAS，409 不覆盖；null 无效 |
| GET `/v1/sites` | 已保存入口、适配版本、启用/基线与能力说明；不访问来源 |
| POST `/v1/runs` | `request_key,trigger=ui/skill,overrides={}`；202 新接受／200 复用；`run,reused,reuse_reason,ignored_overrides` |
| GET `/v1/runs/by-request/{key}` | `{run}`；404 表示查询当时无已接受映射 |
| GET `/v1/runs/latest` | `latest_run:null 或 Run,latest_completed_at,latest_successful_at` |
| GET `/v1/runs/{id}` | `{run}`；含 state/stage/snapshot/counts/coverage/issues/resumed_at；worker_state 与业务 state 分列 |
| POST `/v1/runs/{id}/retry` | `request_key,scope=failed`，返回原 Run；不新建巡检 |
| POST `/v1/runs/{id}/cancel` | `request_key`；返回当前 Run，运行中会安全取消 |
| GET `/v1/products` | view=new/favorites，category 可选，limit 默认40/最大100，cursor 可选；items/snapshot_id/snapshot_expires_at/next_cursor/total/latest_run_summary |
| GET `/v1/products/{id}` | `{product}`；version_id 可选，version_revision 可选（需要 version_id）；精确历史修订可读 |
| PATCH `/v1/products/{id}/user-state` | expected_revision + favorite/excluded/category_override；只改提供字段；category_override:null 清除；409 要重新读取，禁止自动覆盖 |
| POST `/v1/products/{id}/view-events` | event_id/version_id/version_revision；先真实呈现至少一张图，再提交；重复event_id不刷新时间或覆盖后续证据，不同目标409 |
| GET `/v1/assets/{id}` | rendition=preview/original；业务ID解析受控根内文件，不接受本地路径，不发网络；缺失404；preview在内存缩略，不写业务DB或预览文件 |

分类键沿用 T2：dress / knitwear / tops / outerwear / bottoms / sets / other。未知筛选值产生空列表，不能变成任意 SQL。详情保留 source 时间依据、最新可用/完整/观察指针、版本历史、当前选择、latest_observed_album 和 album。枚举未知时 expected_count=null；范围外能力说明不变成缺图。旧图回退须同时显示当前观察缺失，不能隐藏错误。

列表 new 条件为 first_eligible_at 非空且未排除，不以图片可用为门槛；收藏包含缺图款。首次短只读事务冻结完整 ID 顺序 `(viewed_at is not null, first_seen_at DESC, id ASC)`。内存快照 900 秒、最多128份，签名 cursor 绑定 view/category/limit/next_index/有效期。重放返回同一段 ID；状态更新不移动当前链。更换过滤409；过期、逐出或重启410，必须刷新，不能静默接实时排序。

浏览事件验证商品所属版本/修订、至少一张引用图片当前可读且 SHA 与档案一致、版本内容 SHA 集合摘要一致，保存不可变版本摘要。浏览器实际 load + decode + 两帧绘制后才发送，失败/占位/列表预加载不发送。服务无法认证人的视觉注意力；认证客户端仍负责如实提交实际呈现事件。看过历史版本保存历史摘要。已看排序不因来源URL/图序/缺图/内容变化复位；只有不同的已核验版本内容集合才显示更新标记。本地文件丢失不伪造新内容身份。

## 意图与不支持项

一次明确“开始巡检”生成并保存一个 request_key。结果断连：GET 同键；404 才可同键同payload重放，409/503/未知不换键。页面仅将非秘密意图键写入 sessionStorage；持久化失败时不发 POST。活动 Run 复用；原键在 Run 终态仍对应原任务。新意图才可用新键。GET/刷新/图片展示不会创建任务或访问来源。

Manager 已确认：合法非空 item_ids 返回501 SELECTIVE_RETRY_UNAVAILABLE且零副作用；null、空列表、重复/非字符串/空ID为422。UI不暴露指定单项选择。完整失败部分重试正常调用 T1。

导出、maintenance、storage PATCH 目前明确501 FEATURE_UNAVAILABLE，无假成功、无副作用。UI没有导出按钮。T5 完成后再接入导出；T4 尚未实现固定客户端。本次静态 HTML + textContent 取代 Jinja2，经 Manager 确认，不新增生产依赖。资源已打入wheel。严禁把 T3 合成联调当作 T2 真实来源或全产品验收。
