# T5c-local-v1 本机维护交付

2026-10-07（Asia/Shanghai）。Worker 实现及本地验证完成，提交后待 Manager 独立验收；不代表整个产品或 T2/T6 门槛通过。

## 已实现

- 手动核验 all/selected：接收事务冻结商品、全部历史版本、资产与根映射；检查真实文件、大小、SHA256、解码及读取前后身份。缺失、损坏、未知分别计数，当前问题去重更新，历史任务结果不改写；不更改收藏、已看、排除和分类。
- 持久维护任务：原键同参数复用，冲突拒绝；独立有界 Worker lane 与心跳，owner/epoch 防旧执行者提交，确认原进程死亡后恢复。浏览器/CLI 意图先保存再发送，丢回执恢复原任务。
- 本机备份：固定 data_root/backups；Worker 首次成功 SQLite backup API 副本定义一致范围，实际复制正式资产，重开校验 DB、外键、范围、文件清单、字节与摘要，再原子发布。部分备份明确 partial。发布后数据库回执失败可校验复用同一包。
- 离线恢复：固定 `python -m fashion_scout.maintenance.restore --data-root SOURCE --json-input INPUT`。输入为严格 JSON：backup_id、target、allow_partial（默认 false）。仅独立全新或空目标，拒绝原数据/原素材根重叠；恢复前校验整个包。保持根 ID 和业务关系，重映射所有历史根，记录审计、停用旧 Worker/活动任务，保留来源冷却与预算。默认不启动服务、不联网、不覆盖原库。
- 后续保存位置：数据库单一权威 + revision CAS，兼容旧 app.json 首次导入；本机可写路径与空间校验，拒绝网络盘、设备、根目录、穿越及 junction。活动任务或未解决归档拒绝切换。长期 Worker 的新 Run 使用新根，旧 Run 显式重试仍用既有 journal 根；异常多根保留原错误证据并拒绝猜测。
- 固定客户端 verify/backup/maintenance-status/storage/set-storage 与 Skill 说明；存储 CAS 丢回执的 resume 仅 GET 核对。折叠“巡检详情与更多信息”中提供维护、集中问题及保存位置，主页面仍是新款/收藏。刷新只 GET，不自动建维护任务。

## 真实验证

| 检查 | 结果 / 原始证据 |
|---|---|
| 核心、API、客户端、导出、维护及真实进程集成 | 187 passed，0 skipped，98.74s；`T5c-tests-final.txt` |
| 受根选择影响的既有素材/适配器回归 | 65 passed，27.81s；`T5c-media-tests.txt`（全部合成输入，非实站） |
| 浏览器意图与既有 UI/导出逻辑 | 28 passed；`T5c-ui-tests-v1.txt` |
| Skill 严格前置格式检查 | quick_validate.py 通过；Windows 需 `-X utf8`，复用隔离 PyYAML，无全局安装 |
| wheel | `T5c-wheel.txt`；64 个生产文件逐字节一致，9 个迁移 |
| 基线保护 | 176 文件基线；19 个明确允许修改，157 个受保护文件摘要未变；详见 `T5c-evidence-v1.json` |

真实进程覆盖复制中 kill、复制中有序停止、备份已发布但数据库未完成时 kill；三种情况恢复同一 job，心跳在长任务期间独立推进，旧 epoch 无权完成。CLI 在实际 HTTP 已处理后 os._exit(73)，新进程 resume 核验/备份均复用原键；存储写回执丢失只核对 revision。发布后数据库完成写入异常亦通过复用测试。

恢复集成先在新根离线完成，验证无 control/无启动，然后仅将合成原素材目录改名使其不可访问；再显式启动恢复库，读取真实图片并核对原 SHA256、浏览收藏及历史版本、重新导出。原数据库/备份哈希不变；多根 ID 保持、恢复后 Archive 无 path UNIQUE 冲突；历史 export 输出无效，不误用旧路径。8→9 升级保持既有校验和；既有 7→当前升级测试保留，另有全新 schema9。

浏览器使用独立 `.runtime/t5c-browser-01` / 55013。打开页面时维护任务 0；离线点击后 queued，刷新后仍同一 job（计数1）；恢复 Worker 后完成，再单次创建实际备份（总计2任务）。8款、12个素材通过、4条未归档引用明确缺失；保存位置修改 revision0→1 后6张历史预览图仍可读。桌面1440×1000、手机390×844无横向溢出，认证后的操作无控制台错误。

截图：`T5c-browser-default.png`、`T5c-browser-queued.png`、`T5c-browser-maintenance.png`、`T5c-browser-mobile.png`。实际备份样例在 `T5c-backup-sample/8ac44c03ef944425beb316d7b979e8df`，包含一致数据库与12个真实合成图片文件；不是仅路径清单或伪造下载。复制后用原持久摘要重新验证，清单 SHA256 `3611f217bd4d5355bd08396151d43155ab1b812d15f496bb9968a23044f2dadd`。

## 范围与限制

实现前契约为 `T5c-contract.md`。仅新增009迁移；001–008、公共业务 DTO、services/runs/catalog/collect、媒体和适配器、launcher/health、T5a/T5b导出引擎、锁文件及旧验证制品不变。config/Archive/Worker 仅根选择兼容和维护调度。Manager 已批准现有迁移数8→9、维护501→严格输入/只读实现断言及回归新隔离根；旧 Run 无关501断言保留。

上限：1000商品、10000资产、100000引用、单素材64MiB、素材总4GiB、DB512MiB、元数据64MiB。每个任务最多保留3个未发布 stage 和3个未完成快照临时文件，超过明确失败；不会自动清理用户文件。Windows路径过长/权限/空间/中途变更均不宣称成功。包校验是完整性检查，不是外部签名或恶意数据库沙箱；同 Windows 用户进程不在既有隔离边界内。

备份位于本机同盘，不能抵御磁盘损坏；partial 默认不能恢复，须明确 allow_partial。历史导出ZIP、control凭据、Cookie/bootstrap、日志、缓存与临时下载不在包中。已有活动 Run 在恢复库为 cancelled/RESTORED_HELD，必须另行明确处理，不自动继续；恢复结果单独保留 partial 状态。

本轮仅检查 `.runtime/t5c-*` 的38个服务描述根，全部已退出；浏览器测试页关闭、视口还原。用户预览 `.runtime/t5b-browser-user-preview-01` / 56117 未读取、迁移、停止或重启。无实站/CDN请求、默认根操作、临时子Agent、全局安装、定时器、Git提交/推送或发布。

早期实验保留日志：初次样例遇到 Windows 长路径，缩短自有 stage 随机后缀后通过；一个测试错误读取 Lease.attempt，改为 Run 的真实 attempt；多根回归保留既有错误码与 journal 证据后通过。最终测试唯一 warning 来自现有 Starlette/httpx 弃用提示。T2 真实素材门槛与 T6 仍待后续授权与独立验收。
