# 固定命令与 JSON

统一为 `python -m fashion_scout.client request COMMAND --json-input FILE`。FILE 为不超过1 MiB的 JSON 对象；未知/重复字段、NaN、错类型拒绝。下面使用真实业务 ID 的位置须取前次结果，不猜测。

| COMMAND | JSON 输入 | 语义 |
|---|---|---|
| status / ensure / open | `{}` | 只读状态 / 启动服务 / 一次性页面会话；后两者可能恢复已接受巡检或导出 |
| new / favorites | `{}` 或 `{"category":"tops","limit":40,"cursor":"前页游标"}` | 冻结分页；limit1–100，游标失效刷新而不拼接不同快照 |
| product | `{"product_id":"ID"}` | 可附 version_id 与 version_revision；修订须有版本 ID；不记浏览 |
| latest | `{}` | 最新 Run，可为 null，含最近完成/成功时间 |
| progress | `{"run_id":"ID"}` | Run、stage、计数、覆盖、问题与 Worker 状态 |
| sites / default-plan | `{}` | 只读本机站点能力/默认方案，不探测来源 |
| start | `{"new_intent":true,"overrides":{"window_days":7}}` | trigger 固定 skill；overrides 可省略；可含已保存站点子集 site_ids、unknown_date_policy=include/exclude |
| retry / cancel | `{"new_intent":true,"run_id":"ID"}` | 原 Run，retry 固定 scope=failed；无 item_ids 或 overrides |
| browser-status | `{"run_id":"ID"}` | 只读前台来源状态、资格、消息回执和 Worker 图片 tickets |
| browser-attach / browser-continue | `{"new_intent":true,"run_id":"ID"}` | 来源会话 / 同一等待前台 Run 的业务续采，不是客户端 resume |
| browser-observe | `{"new_intent":true,"run_id":"ID","session_id":"会话ID","observation":{"kind":"finish"}}` | listing/detail/finish 严格事实 DTO，不接受业务成功字段 |
| browser-upload | `{"new_intent":true,"run_id":"ID","session_id":"会话ID","ticket_id":"ticket","native_directory":"工具导出目录","manifest_path":"工具manifest","asset_id":"工具资产ID","source_url":"原图库URL","sha256":"64位摘要","bytes":123}` | 有资格 ticket 后的有限 native 只读文件；服务仅收字节流 |
| browser-asset-failure | `{"new_intent":true,"run_id":"ID","session_id":"会话ID","ticket_id":"ticket","code":"HOST_EXPORT_FAILED"}` | 也可 HOST_ASSET_UNAVAILABLE/HOST_LIMIT_REACHED；保留缺失 |
| user-state | `{"product_id":"ID","expected_revision":1,"favorite":true}` | 也可 excluded 布尔、category_override；仅发送明确变更字段 |
| set-default-plan | `{"expected_revision":1,"window_days":7}` | 独立明确修改；可含 T3 PlanPatch 顶层字段，复杂嵌套对象须完整；冲突不盲覆盖 |
| intents | `{}` | 本机意图列表、状态、原完整 payload、非秘密路径 |
| resume | `{"intent_id":"intents 返回的标识"}` | 原记录核对/恢复，不创建新意图 |
| export | `{"new_intent":true}` | 显式冻结当前收藏并后台打包全部已存历史图片，不请求来源 |
| export-status | `{"export_id":"ID"}` | 只读导出状态/缺失/未知/认证下载业务URL |
| export-retry | `{"new_intent":true,"export_id":"ID"}` | 原快照新尝试，不读取当前收藏重选 |
| maintenance / storage | `{}` | 只读最近维护任务 / 当前素材根、revision 和本机备份根 |
| verify | `{"new_intent":true,"scope":"all"}` | 显式核验；也可 scope=selected、product_ids 非空唯一列表（最多1000）；all 不接受 product_ids |
| backup | `{"new_intent":true,"destination_id":"local"}` | 显式创建本机一致性备份；不接受任意目的路径 |
| maintenance-status | `{"maintenance_id":"ID"}` | 只读状态、分组问题及通过完整性验证的备份位置 |
| set-storage | `{"expected_revision":1,"media_root":"E:\\ScoutingImages"}` | 仅修改后续归档位置；忙碌拒绝，CAS 不自动重放 |

分类：dress、knitwear、tops、outerwear、bottoms、sets、other；`category_override:null` 清除人工覆盖。路径 ID 仅接受1–128个 ASCII字母/数字/下划线/连字符，仍逐段 URL 编码。未知字段不能充当 URL、method、header 或凭据。

写入成功 data 内有 intent_id、intent_state 和 result；恢复已接受意图 cached_receipt:true 表示历史回执，需另读当前状态。查询已接受 start 的原键恢复时 reused/reuse_reason/ignored_overrides 可能为 null：原始接收回执缺失，不能推测。记录 prepared/sending 需 resume；rejected/review_required 不自动重放。意图日志不自动删除。

复杂默认方案字段沿用仓库 `docs/verification/T3-api-contract.md` 与 `src/fashion_scout/api/models.py` 的只读契约。不自行增加端点、修改 API 或直接写 SQLite。客户端没有 view-events 命令。

T5b补充：export与export-retry同样先持久化意图再发送。服务无by-key导出查询，resume以原键原payload重放固定POST；服务幂等返回原job/当前状态或原retry，冲突不换键。export-status仅GET。已接受回执可能过期，下载前重新读状态；只有ready且包/快照/持久摘要核验通过时返回download_url，丢失或篡改410，不创建替代导出。verify/backup 同样同键恢复；maintenance-status 仅 GET。set-storage 不确定结果的 resume 只 GET storage，标为 review_required，不重新 PATCH。
