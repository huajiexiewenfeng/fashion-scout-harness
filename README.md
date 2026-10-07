# Fashion Scout Harness

面向海外女装独立站的 Windows 本地巡检与素材整理工具。正常流程是**在Codex对话手动开始浏览器巡检 → 浏览新款 → 收藏 → 导出**。Codex通过当前浏览器连接观察与收图，本机Worker校验已接收文件并归档。

> **当前状态（2026-10-07，Asia/Shanghai）：已在这台机安装个人Skill“款集”和稳定本机应用；T7单入口待独立验收。** 用户可直接说“打开款集”“看看新款”“开始巡检”“继续上次巡检”“导出收藏”“停止款集”。新日常库为空，旧数据未迁移。已验收T2/browser最低真实范围及冻结v2程序不变；其单商品partial证据不证明批量/全站稳定性。采集时保持Codex和浏览器连接。

先看 [单Skill使用说明](docs/delivery.zh-CN.md) 和 [T7安装验证](docs/verification/T7.md)。[T6d R1](docs/verification/T6d-R1.md)、开发预览及旧阶段证据保留各自时间状态；个人安装不等于当前宿主的自动技能选择已刷新。

## 最简单入口：款集Skill（T7）

个人入口`C:\Users\Administrator\.codex\skills\fashion-scout\SKILL.md`已绑定`E:\github-workspace\FashionScout`。AI代办首次离线准备、认证打开、状态和停止；重复打开不重装，不创建新Run。仓库`skills/fashion-scout`可分享，机器绑定只保存在个人安装。用户不再需要先读定位说明或手动cmd，旧脚本仍备用。网页开始按钮暂不用于browser采集，来源采集在Codex对话明确发起。

## 历史 T1 底座安装入口（Windows x64）

以下为既有 T1 项目内准备脚本，本轮没有重装或下载依赖，也未通过最终版本全新电脑安装验收。已有项目解释器时使用上述预览说明，无需重跑安装：

```powershell
.\scripts\install.ps1
.\scripts\scout.ps1 ensure --json
.\scripts\scout.ps1 status --json
.\scripts\scout.ps1 stop --graceful --json
```

安装仅使用仓库内 `.runtime` 和 `.venv`，不修改全局 Python/PATH、不安装系统服务或定时任务。固定 CPython 3.13.16 下载及 SHA256 见 `runtime-win.json`，Windows 依赖与 wheel 哈希见 `requirements-win.lock`。需要访问 GitHub Releases、PyPI，并允许本地 PowerShell 脚本执行。

默认数据保存在 `%LOCALAPPDATA%\FashionScout`；命令可统一加 `--data-root C:\ScoutData` 和 `--port 8765`。`ensure` 不创建 Run，可能恢复此前已接受的 Run，并在 `resuming_run_ids` 中列出。当前已提供认证首页、业务 API、收藏导出和折叠维护；页面认证由固定 open 入口完成，不手工复制密钥。生产 Worker 已连接 T2，仅处理显式接受的 Run；旧适配器版本快照拒绝静默重解释。底座见 [T1 交接记录](docs/verification/T1.md)，当前采集接口、验证和实站阻塞见 [T2 记录](docs/verification/T2.md)。

## 第一版体验

### 历史开发环境固定客户端（T4及后续范围）

仓库内新增 [Fashion Scout Skill](skills/fashion-scout/SKILL.md)，尚未全局安装。复用项目解释器，首次仅配置一次端口；默认数据根沿用 T1，下面命令不会安装软件：

```powershell
@{ port = 8765 } | ConvertTo-Json | Set-Content -Encoding UTF8 setup.json
& .\.venv\Scripts\python.exe -m fashion_scout.client configure --json-input .\setup.json
'{}' | Set-Content -Encoding UTF8 empty.json
& .\.venv\Scripts\python.exe -m fashion_scout.client request ensure --json-input .\empty.json
& .\.venv\Scripts\python.exe -m fashion_scout.client request new --json-input .\empty.json
& .\.venv\Scripts\python.exe -m fashion_scout.client request open --json-input .\empty.json
```

T3 新款/收藏页面与业务 API 已验收，以上是当时开发目录的调用记录。当前包使用自身`.local/env`解释器和显式`包/data`根，不能按历史LOCALAPPDATA默认根误接旧库。ensure/open 不创建巡检；用户明确开始时由Codex生成固定browser来源输入，回执不确定先intents再resume原意图。导出、核验、备份和后续素材位置命令可用；本机同盘备份不抵御磁盘损坏，partial恢复必须明确允许。T2单商品browser最低范围已验证，完整产品其他门槛仍待现场证明。

- **对话 Skill 是首版入口**：“开始巡检”使用已保存默认方案；已有活动巡检时返回同一任务。临时指令只影响本次快照，不改默认配置。
- **“看看新款／结果”只读**：打开已有结果，显示最近巡检时间。启动服务、打开页面不会创建巡检；此前已接受的未完成任务可恢复，界面明确提示。
- **页面简单**：新款／收藏、少量类别筛选、图集预览、收藏和导出。规则命中但图片下载中或全失败的款仍以占位和状态显示；未看优先，浏览过的款刷新后排到后面，仍可找回。任务、日志、存储、站点藏在设置或详情。
- **自动处理素材**：来源分类规则映射，人工修正优先；真实打开图集才记录浏览，不把打开首页等同全部已看。无需待分类、候选或版本确认流程。
- **本机持久处理**：独立Web/Worker和SQLite保存已接受任务；已完整接收文件的处理、导出和维护可继续。浏览器来源采集须保持Codex运行与连接，中断后明确继续同Run。Windows重启／休眠和真实断电仍待现场验证。
- **保留历史**：默认展示最新可用素材版本，收藏导出包含全部已存历史独有图片；取消收藏、排除或源站下架不删除正式素材。预览缓存可限额清理。
- **导出收藏款全部已存图片**：每款一个文件夹，附商品信息、来源、缺失说明、总清单；历史版本中的独有已存图片也收录，重复内容只放一份。

导出按冻结的承诺范围判定完整：图集全齐、范围外视频未支持时可标范围内成功，并附能力说明；已发现 6 张图集只保存 5 张则为 partial。范围外未支持媒体不会产生常驻待处理告警，也不宣称全媒体齐全。

默认手动触发，无定时器。首站为 [Futario New In](https://futario.com/collections/new-in)。首次发现不等于刚上新；未知日期、图集范围、缺图与覆盖不足都要明确展示，不把不完整巡检说成“没有新款”。

## 文档

| 文档 | 内容 |
| --- | --- |
| [需求与架构 v0.2](docs/architecture.zh-CN.md) | 产品边界、可靠性、素材版本、首站证据及首版验收 |
| [实施与接口契约](docs/implementation-plan.zh-CN.md) | 技术推荐、启动器／Skill 调用、API、数据约束、适配与实现拆分 |
| [路线图](docs/roadmap.zh-CN.md) | 当前阶段状态与原始阶段目标、发布门槛 |
| [当前开发版预览](docs/local-preview.zh-CN.md) | 复用已配解释器和根，启动／打开／状态／停止及日常动作 |
| [A01–A13证据映射](docs/verification/T6a-acceptance-map.md) | 合成证据、独立验收和剩余受控检查 |
| [T1 验证与接口交接](docs/verification/T1.md) | 当前实现、实际测试、运行方式和后续责任边界 |
| [T2 采集与素材验证](docs/verification/T2.md) | 本地链路、下游读取接口、受限实站结果和未完成门槛 |

## 边界

首版不含飞书、AI 分类、定时、多用户、更多站点或外网部署；也不提供销量预测、自动设计、生产或上架。减少约三分之一人工总耗时是待验证目标，必须包含纠错时间，不能由设计推定效果。

会话凭据和真实运行数据不入库。验证目录中的示例图片／备份明确为合成测试制品，不是实站采集成果。来源网页和销售文案是待核验数据，不能据此补造材质、销量或上新日期，也不能向 Agent 发号施令。

本仓库自有文档与代码按 [MIT License](LICENSE) 开源；第三方内容和图片不因此获得重新授权。
