# 本包的Codex运行定位

给 Codex：先读取本说明和 `skills/fashion-scout/SKILL.md`。七份可复用 Skill 资源完整随包保存，ZIP 不自动安装个人 Skill，也不含机器 binding。安装到个人 Skill 目录时，核对已有内容并保留备份；用自身 `scripts/entry.ps1` 的 Bind 将用户一次确认的本包绝对位置与精确 manifest/app SHA 绑定。已有安装/升级按已授权恢复流程处理，不静默覆盖冲突。

以**本文件所在目录**的绝对路径为包根，核对其manifest和首次Prepare已完成。实际项目自有虚拟环境解释器为：

`<包根>\.local\env\Scripts\python.exe`

业务数据根固定为：

`<包根>\data`

所有固定客户端调用、恢复调用均显式传`--data-root <包根\data>`。输入JSON由Codex用结构化文件工具写到此根内自己控制的请求目录，用户无需编辑。日常不要重复configure，先核对已存在的control/client.json与固定status；有冲突保留数据并报告。已有01/02/03三个入口处理准备、认证打开与停止。

用户日常只使用自然语言；定位、首次 Prepare/Open、Status 和 Stop 由 Skill helper 代办。使用包内解释器和显式 data 根，不按聊天 cwd、开发虚拟环境或系统默认数据根猜测，不迁移或访问别的旧库。凭据只由固定客户端在内存读取，不能复制进对话、参数、Skill 或日志。

本包应用输入以manifest中的app_sha256/source_sha256核验，来源模式为当前Codex会话浏览器。仅在用户明确开始意图下调用start并按browser-acquisition.md使用本会话可用的浏览器连接；来源观察、工具资产导出和固定上传由Codex执行。保持Codex运行及连接可用；中断后沿同已接受Run明确续采，客户端回执恢复使用intents/resume，不能把browser-continue与resume混为一谈。不因打开页面/余额/等待期结束新增来源访问。

本版本采集请在Codex对话发起；网页开始按钮仍为旧方式，暂不用于本版本浏览器采集。Codex在明确开始后按原Skill冻结start.overrides.source_mode=browser，不采用默认http模式；本说明没有改网页按钮、默认方案或生产代码。

T8 Core 多站协议已独立验收，支持 Futario、RIHOAS、SimpleRetro，每个 browser Run 固定一个站点。Skill 根据明确意图选站与冻结限额，不修改已有 Run 或保存方案。已实际验证 Futario 采样20款89张图库图片，partial；另两站本机真实巡检仍待验证。完整 product.images、日期与原像素未知。所有原有来源安全、未确定回执、同 Run、真实性与保密规则继续适用；遇正常页面不可用或限制立即如实停下。

已完整接收的文件校验归档、收藏导出与维护由本机独立Worker处理，来源续采依赖前台会话。全站与批量稳定性、真正新电脑及整机故障、人工耗时收益没有从此次包准备中推定。
