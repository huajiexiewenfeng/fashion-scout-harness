---
name: fashion-scout
description: 款集本机入口。用户说打开款集、看看新款、开始巡检、继续上次巡检、导出收藏或停止款集时使用；代办定位、离线首次准备和认证打开。采集通过当前Codex浏览器连接，不用于通用网页抓取。
---

# 款集

用户只表达意图，Codex代办；不让用户读安装说明、复制JSON/token/cmd或重复给目录。

- **打开款集／看看新款**：运行本Skill的scripts/entry.ps1 -Action Open。首次自动离线准备，之后复用安装与实例，不新建巡检。
- **状态**：-Action Status只读，不准备或启动。**停止款集**：-Action Stop只停绑定包的自有实例。
- **开始巡检**：只有明确新意图才执行；先Open，读[浏览器来源](references/browser-acquisition.md)，用固定start且显式source_mode=browser。网页开始按钮仍旧方式，暂不用。
- **继续上次巡检**：先读latest/progress及未确定intents，沿原browser Run继续，不发替代start；不把来源续采与客户端resume混淆。上下文不足先核对原记录。
- **收藏／导出收藏**：按[固定命令](references/commands.md)和[回执恢复](references/operations.md)执行用户意图；人工状态使用当前revision，回执未知恢复原意图不换键。

每次固定客户端都经entry.ps1 -Action Request，显式绑定包/data；JSON由Codex写受控文件。绑定缺失或安装位置失效时按[定位](references/setup.md)仅核对一次并记住，不扫描或猜旧库。

采集时保持Codex和浏览器连接；已完整接收文件、导出与维护由独立Worker处理。报告真实计数和partial/unknown，不能把单商品验证说成全站完整，也不把历史限额当永久规则。只用正常可用浏览器与当前授权，不输出密钥、Cookie或bootstrap片段。
