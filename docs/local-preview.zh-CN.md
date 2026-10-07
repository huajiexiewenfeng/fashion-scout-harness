# 当前开发版的本机预览

更新：2026-10-07（Asia/Shanghai）。适用于这台 Windows x64 电脑上已准备好的 `E:\github-workspace\fashion-scout-harness` 项目与已确认的数据根。不是正式发布包或全新电脑安装手册。T1、T3、T4、T5的本地范围已验收；T2真实素材、T6整体门槛仍未通过。Skill仅在[仓库内](../skills/fashion-scout/SKILL.md)，没有全局安装。

## 启动、打开、状态、停止

复用项目解释器，不重新安装依赖。在 PowerShell 中先设置项目和**已经确认、已配置**的数据根。下列尖括号是要替换的值，不能原样运行；不要把测试目录或别人的预览根当作日常库，也不要猜测旧库版本。

```powershell
Set-Location 'E:\github-workspace\fashion-scout-harness'
$scoutPython = 'E:\github-workspace\fashion-scout-harness\.venv\Scripts\python.exe'
$scoutRoot = '<已确认且已配置的绝对数据根>'
$scoutInput = Join-Path $env:TEMP 'fashion-scout-empty.json'
'{}' | Set-Content -LiteralPath $scoutInput -Encoding UTF8

# 先查看状态；不启动服务
& $scoutPython -m fashion_scout.client request status --data-root $scoutRoot --json-input $scoutInput
# 启动／复用 Web 与 Worker
& $scoutPython -m fashion_scout.client request ensure --data-root $scoutRoot --json-input $scoutInput
# 经一次性认证入口打开页面；不手工复制 key、Cookie 或 bootstrap URL
& $scoutPython -m fashion_scout.client request open --data-root $scoutRoot --json-input $scoutInput
# 只读查看已有新款
& $scoutPython -m fashion_scout.client request new --data-root $scoutRoot --json-input $scoutInput
# 用完后协作停止这一个已确认根的服务
& $scoutPython -m fashion_scout.launcher stop --data-root $scoutRoot --graceful --json
```

`status`/`new`不创建巡检；`ensure`/`open`也不创建新Run，但可能恢复这个根里**此前已接受**的任务。因此启动前要知道根的用途与未完成任务。`web_ready`和`worker_state`分别说明页面服务与执行器，queued不等于正在采集。停止返回错误时保留提示并核对该实例，不按端口强杀其它程序。

若只需空库开发预览，可明确选择一个新的 `.runtime/t6a-manual-preview-*` 根与空闲端口，由开发者先写 `{"port":选定端口}` 的受控JSON，执行 `client configure --data-root 所选根 --json-input 文件`，然后按上面的固定入口使用。configure不创建业务库或巡检；新根初始没有商品。本说明不自动造演示数据，不启动56117既有预览，也不提供绕过配置冲突的方法。首次准备／新电脑安装仍是独立待验收工作；仓库安装脚本的存在不代表该门槛完成。

## 浏览、收藏、导出

1. 在“新款”按类别查看，点击款式打开图集。真实呈现图片才记已看；刷新后已看款移入后组，仍能找回。缺图占位仍可收藏，不等于完整图集。
2. 点收藏，再切换“收藏”。有收藏后点“导出收藏”；完成并校验可用时出现“下载 ZIP ↓”。包包含冻结时收藏款的全部已存历史独有图片、来源与缺失清单。
3. `partial`可下载，但要阅读缺失／未知说明；它不是完整采集。导出只读已存文件，不重抓来源。文件丢失或篡改时按页面提示明确“重试原导出”，不能把未校验的路径当作可用下载。

刷新只查询。若写入回执不确定，页面会核对同一次操作；固定客户端使用 `intents` 找原记录，再 `resume` 原 `intent_id`。不要用新键或重新 start 代替恢复。固定命令、严格JSON字段见[命令表](../skills/fashion-scout/references/commands.md)。

## 核验、本机备份与素材位置

展开“巡检详情与更多信息”，可点击“核验已存素材”或“创建本机备份”。两者只在明确点击后执行，不补抓来源。集中问题以缺失／损坏／待确认及款名展示，维护结果与巡检结果分开。

备份在当前根的 `backups` 目录，包含一致数据库与实际正式素材。它是本机副本，不能防止同盘损坏。`partial`备份明确不完整，默认恢复会拒绝；恢复只在用户明确选择独立新空目标并接受缺失后运行离线工具，不在页面内启动恢复向导：

```text
项目解释器 -m fashion_scout.maintenance.restore --data-root 已确认源根 --json-input 受控恢复JSON文件
```

JSON仅含真实备份ID `backup_id`、绝对新空目录 `target`、布尔 `allow_partial`（默认false）。ID取已确认维护结果，不猜测；不要覆盖原库。恢复校验清单及实际复制字节后重映射根，保存原历史与人工状态，停用旧运行身份并保留限流证据；不会自动启动服务或请求来源。使用恢复库需要另行明确配置、启动。

“后续图片保存位置”仅影响将来归档，已有图片保留原根；不是历史目录迁移。活动巡检／维护或未解决归档会拒绝切换。保存回执不确定时先“核对当前设置”，核对后再决定是否重新修改，不自动覆盖新的revision。网络盘、磁盘根和链接目录不支持。

## 当前限制

“开始巡检”才是新采集意图；本说明不要求点击它。Futario最新2026-10-07 09:48受控诊断仍为429／Retry-After60，真实有效素材0，累计5/40次；倒计时结束不等于新的访问授权。8款演示、T6a合成冒烟与备份样例都不能证明真实站点适配。

已有证据证明独立进程、部分中断恢复和本机业务操作；整个Codex退出、Windows重启／休眠／真实断电、全新电脑安装、实际节省工作耗时仍待后续受控检查。历史目录迁移、定时、云端、多用户不在本版范围。详细状态见[A01–A13映射](verification/T6a-acceptance-map.md)。
