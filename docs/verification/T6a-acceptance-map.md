# T6a：A01–A13事实与剩余门槛

2026-10-07（Asia/Shanghai），基于架构v0.2-contract-2第7节、当前源码、既有原始日志和Manager独立验收。此表是最终验收准备，不是T6全项批准。真实进程、HTTP、文件字节可以在合成业务数据上实测；这种“真实执行”不等于真实Futario素材。

Manager原规划为 [remaining acceptance map](../../../.team/fashion-scout/manager-final-acceptance-map-20261007.md)。T2独立本地审查 [local-v2 review](../../../.team/fashion-scout/manager-t2-local-v2-review.md)仅认可合成契约，未正式approve T2。最新实站[单次诊断](T2-diagnostic-20261007-foreground.md)为09:48的429／Retry-After60、累计5/40、资产0。本任务没有源站请求，未改变限流、预算或T2状态。

| 门槛 | 已有具体证据与独立确认 | 本轮打包观察 | 尚未证明／后续判定 |
|---|---|---|---|
| A01 同API、只读入口、无新Run、最近时间 | [T3](T3.md)及[T4](T4.md)；`test_get_empty_no_business_writes_and_idempotent_runs`、`tests/client/test_local_integration.py::test_real_cli_lifecycle_and_cross_process_recovery`；[Manager T3](../../../.team/fashion-scout/manager-t3-acceptance.md)与[T4](../../../.team/fashion-scout/manager-t4-acceptance.md)确认认证页面/固定客户端与开页无Run。T3真实浏览器记录最近巡检与未巡检。 | wheel的status/ensure/open/new、HTTP首页与资源；空库Run0、maintenance0、来源0。open最后OS浏览器动作被测试钩子截取，没有宣称重新渲染浏览器。 | 同一交付版本真实归档款在Skill/API/UI上贯通，最近来源时间可核对；见S1。 |
| A02 默认/覆盖快照、幂等与并发 | [T1](T1.md)原始`T1-R1-tests.txt/xml`；`test_snapshot_default_cas_and_replay_terminal`、`test_concurrent_requests_and_claims`、T4真实HTTP丢回执恢复；[Manager T1](../../../.team/fashion-scout/manager-t1-acceptance.md)、T4确认。 | 固定命令清单与包内DTO/文档对应；未发start、未新增Run意图。 | 实站切片沿相同冻结参数/复用规则，不能用T6a新增采集代证；S1。 |
| A03 页面/对话/终端关闭后后台继续 | T1 `test_exited_parent_idempotent_ensure_status_and_safe_stop`；T5b `test_web_exit_does_not_stop_accepted_export_or_heartbeat`，`T5b-process-tests-v1.txt`及[Manager T5b](../../../.team/fashion-scout/manager-t5b-acceptance.md)。是启动父进程/Web退出，不是整个宿主退出。 | launcher调用进程结束后独立Web/Worker仍完成ZIP和维护；记录真实加载路径和停止结果。 | 整个Codex关闭/重开尚无实测，不能从DETACHED或breakaway参数推断；S2。 |
| A04 中断恢复/fencing/状态不丢 | T1真实kill同Run旧epoch拒绝；T5b导出复制中kill/有序停/发布后恢复；T5c维护同类进程实验，独立心跳及历史人工状态。见[T5b](T5b.md)、[T5c-R1](T5c-R1.md)、[Manager T5c](../../../.team/fashion-scout/manager-t5c-acceptance.md)。 | 未重复kill/系统实验；正常有序停止仅自己的包实例。 | Windows重启/休眠唤醒、实站同Run恢复未证明；S3及S1。 |
| A05 分页/上限/故障覆盖、状态诚实 | T2本地`tests/adapters/test_futario.py`和`test_collection.py`、`test_http.py`，`T2-local-v2-tests.txt`；独立105项只是包含这些用例的运行记录。部分枚举、预算、重复/错误页与失败无结果有语义断言。T1 outcomes也有完整范围判定。 | 核验/备份的合成缺失真实返回partial，不能替代来源分页验证。 | Futario真实分页/完整栏目与当前预算可行性未知；多站隔离仅夹具（首版仅1站），不宣称现场多站；S1。 |
| A06 自动规则、日期、多色/图集边界 | T2 `test_unknown_dates`、变体关系、首次基线旧日期规则、`test_gallery_unknown_video_does_not_make_full_gallery_partial`；源码和[T2本地v2](T2-local-v2.md)独立审查。T3显示未知日期/缺图占位。 | 仅复用带“合成测试”标识的已存图片种子，无真实下载。 | 当前实站有效列表/图片、真实多色/动态详情边界及源日期语义需取证；未验收能力继续unknown/unsupported；S1。 |
| A07 坏图/超时/限速/重试/同URL历史 | T2 `test_gallery_six_with_one_invalid_is_partial_then_same_run_repairs`、`test_same_url_content_change_retains_history_order_only_same_content_identity`、图像解码/限像素/HTTP有限退避；`T2-local-v2-tests.txt`及Manager本地v2审查。 | 无源站重试；保持当前限制。 | 真实素材通过生产Worker归档和受控同任务修复未证明；429本身只证明受限，不是成功或无新品；S1。 |
| A08 staging/空间/拒绝/缺失/计数 | T1归档发布前/后/DB失败、错误目标不覆盖；T2磁盘reserve/权限注入/owned_temps身份保护；T5c R1五类复制/暂存损坏拒绝最终发布。原始日志[T5c-R1测试](T5c-R1-tests.txt)，Manager重复旧单字节反例现拒绝。 | wheel的实际ZIP/备份字节、恢复资产SHA逐项核对；未填满磁盘/改ACL/断电。 | 最终实站归档一致性、真实电源丢失持久性仍未知；S1/S4。注入PermissionError不等于真实硬件故障。 |
| A09 分类/人工状态/已看/冻结分页 | T3 API `test_frozen_query_chain_mutations_replay_expiry_restart`、`test_user_cas_null_missing_images_and_view_evidence`；T3 R1实际JS与浏览器分类/历史/已看派生状态；[原始R1](T3-R1.md)及Manager T3接受。T1/T2重试保留人工状态。 | 固定client将真实合成商品favorite设置成功，恢复后仍为1；不写view-events，不冒称实际浏览。 | 用真实归档款完成浏览→刷新→未看优先及历史回溯；S1/S5。 |
| A10 全历史冻结导出/覆盖/不重抓 | T5a引擎成功与partial ZIP逐成员hash/来源/历史关系，Manager独立56用例；T5b job/attempt、实际HTTP下载/丢回执/恢复；[T5a独立](../../../.team/fashion-scout/manager-t5a-acceptance.md)、T5b独立记录；源码`tests/exports`保留“6存5”和范围外视频用例。 | 包版单款2张图succeeded，认证下载ZIP摘要一致；随后备份全4款6资产+2缺失partial。来源请求0。 | 实际Futario收藏的全部已存历史范围和ZIP完整性待S1；合成成功不证明源站图集齐全。 |
| A11 取消/核验/备份恢复/根配置 | T1 cancel/retry保留成果；T5c-R1实际一致DB+资产、原根离线后浏览/导出、长期Worker新旧根选择、CAS与多根异常；Manager state81接受/82闭轮，故障复现和样例独立核对。 | 包版核验/备份、严格JSON显式partial新根离线恢复，所有恢复资产hash匹配，favorite保留，恢复未启动服务；没有根迁移操作。 | 真实图库一体应用仍依赖S1；同盘备份不防盘坏，历史目录迁移另立范围。 |
| A12 本机鉴权/来源安全/不泄露 | T3 Host/Origin/session/CSRF、只读asset根约束；T4固定白名单/凭据加载/URL边界；T2公共peer/DNS/redirect/MIME限制；T5a路径与ZIP内容/转义检查，各阶段已独立审阅。 | 包版未认证GET401、同源缺CSRF写403、一次性认证HTTP首页；无凭据输出；测试钩子拒绝非loopback DNS/connect，记录无尝试。 | 包入口抽样不是渗透测试；真实重定向/CDN须保持原保护并在S1验证。不能为通过测试弱化限制。 |
| A13 新款/收藏可用、含纠错省时 | T3/T5b/T5c真实浏览器桌面/窄屏截图及交互，缺图仍可见可收藏，R1问题分组款名；用户见过8款演示。只能证明已测功能，不证明业务收益。 | 本轮HTTP页面/资源完整、合成收藏/下载成功，未新增用户实操或耗时实验。 | 真实操作者完成S5，计入纠错/等待/整理；减少约三分之一仍是未验证目标。 |

原始日志均保留在本目录：T1-R1、T2-local-v2、T3-R1、T4、T5a、T5b、T5c-R1各自日志对应当时版本。Manager审查记录中的实际tool session/chunk是其独立运行来源，不能冒充本Worker本轮重跑。T6a只新增包入口冒烟，完整命令与加载路径见[T6a报告](T6a.md)及`T6a-package-evidence-v1.json`。

剩余S1–S6的最小步骤、授权前提、判定与停止条件见[受控检查计划](T6a-controlled-checks.md)。此表不关闭任何尚未满足的A项。
