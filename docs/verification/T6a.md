# T6a：本地最终验收准备 v1

日期：2026-10-07（Asia/Shanghai）。任务 `t6a-local-readiness-and-guidance`，轮次 `p6a-readiness-preparation`。Worker已完成本轮准备，提交后待Manager独立审查；不宣布T2、T6或正式发布通过。

## 本轮交付

- [A01–A13证据映射](T6a-acceptance-map.md)：逐项连接既有测试、真实进程/HTTP/字节证据、Manager独立决定和剩余条件。
- [开发版本机预览说明](../local-preview.zh-CN.md)：复用这台电脑的既有解释器与已确认根，固定启动/打开/状态/停止入口及现有收藏、ZIP、维护操作。仓库Skill没有全局安装。
- [剩余受控检查计划](T6a-controlled-checks.md)：真实来源、整个Codex退出、Windows重启/休眠、物理故障、人工流程耗时及新机安装均明确未执行。
- README和路线图只更新当前事实，保留原设计历史；新增测试与证据，未修改生产代码、配置、锁文件、脚本、Skill、旧测试或旧验证制品。

## 隔离现有wheel的实际验证

使用已验收T5c-R1制品 `.runtime/t5c-r1-wheel/fashion_scout-0.2.0a1-py3-none-any.whl`，SHA256：

`9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15`

没有重建wheel、pip安装或下载。测试用既有运行时创建无pip的独立venv，将wheel解包到其site-packages；用普通`.pth`路径复用既有第三方依赖，不执行原editable安装钩子。30个Python执行记录中的业务模块均来自自己的包目录，没有repo/src路径或editable finder。包内66个文件在操作前后逐字节与wheel核对，9个迁移实际应用到新空库。此验证证明当前机器的包入口及资源可用，不能替代依赖独立性、全新电脑安装或最终冻结发布包验收。

包只声明`python -m`模块入口，没有console_scripts。实际执行launcher、client、health、worker、maintenance.restore帮助入口，以及真实Web/Worker/离线恢复进程；固定客户端代码的26个命令与仓库命令表核对。27条实际子进程命令的argv、退出码及原始输出已保存；不是26个命令全部业务执行，也没有调用start。

| 检查 | 本次实际结果 |
|---|---|
| 空库配置/ensure/open/status/new等 | schema1–9，Run0、维护任务0、来源请求0；open的最终OS浏览器动作被测试钩子截取，未声称本轮浏览器渲染 |
| 本地HTTP | 首页200及5个静态资源逐字节匹配；未认证读取401；同源缺CSRF写403；实际一次性会话交换成功 |
| 收藏与导出 | 只读复用既有合成种子：4款、6张已存素材、2张明确缺失。固定客户端收藏1款，Worker导出1款2图succeeded；认证HTTP下载ZIP摘要一致 |
| 核验/备份 | 实际Worker执行，4款/6资产/2缺失，如实partial；备份清单校验成功 |
| 离线恢复 | 明确allow_partial，独立新空目标；6个恢复资产摘要逐项匹配，收藏状态保留；没有启动恢复目标服务、没有新Run |
| 收尾与网络 | 只有1个预置合成terminal Run，run_requests0、collection_http0；测试钩子拒绝非loopback DNS/connect，记录中无尝试。自身Web/Worker有序停止，无强杀 |

ZIP摘要：`656cc76e81b8ddbfc45380b2fbdbed3664404d070411aa68d429df19b52f3103`。备份ID `bae49608c2894d35b5d88a2645a44575`，清单摘要 `581ae3d5bb45b801ecf7c12df6a3980d252679a3e1d4c2490db7a4748b31c5ad`。

执行位置：`E:\github-workspace\fashion-scout-harness`。命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -X utf8 -m pytest tests/integration/test_readiness_package.py -q -s --basetemp .runtime/t6a-pytest-2
```

结果：[原始最终日志](T6a-package-tests-2.txt)为 **1 passed in 14.22s**。首次[日志](T6a-package-tests-1.txt)失败在测试自身的模块命名断言：`python -m`把入口保存在`__main__`，并非必然保留同名模块键；实际业务已完成且服务已停止。仅修正新测试为`__main__.__file__`与argv，并加强实际服务`--instance`断言后重新验证通过。没有修复或改写任何生产文件，也没有重跑全套历史测试来增加计数。

最终实例为 `.runtime/t6a-package-bd0a82ab`，初次实例为 `.runtime/t6a-package-3164de71`；只核对这两个自有根的服务身份。用户预览 `.runtime/t5b-browser-user-preview-01`及56117端口未读取、未迁移、未停止或复用。旧T2数据根与来源/CDN完全未访问。

## 可复核证据与边界

- [包执行原始命令](T6a-package-commands-v1.txt)与[包/模块/HTTP/恢复证据](T6a-package-evidence-v1.json)是上述最终实例的原文件复制，不重构输出。
- [交付保护清单](T6a-evidence-v1.json)由新增测试辅助脚本生成，包含265个受保护文件的逐项摘要复核、两个自有实例收尾、文档链接与T6a制品摘要。[基线](T6a-baseline.json)在本轮改动前保存，旧证据没有回写。
- 当前基于main `51e0dae87065fe725380be0724ac999d0c1fdb84`及原有P0–T5工作区改动；没有commit、push、PR、安装、发布、全局Skill变更或定时器。
- T2最近独立诊断仍是北京时间2026-10-07 09:48 GET429／Retry-After60，累计5/40、剩余35，真实有效素材0；保留原2详情/12图/64MiB约束。T6a没有消耗来源预算；等待期过去不授权重试。
- 现有真实浏览器、故障注入及进程中断证据复用原阶段记录。本轮只有HTTP页面资源检查，无法替代浏览器重新交互、整机退出/重启/休眠/断电、真实网站图集或人工耗时收益。

交付范围已就绪；原Worker提交和E03通知的真实回执保存在团队 `worker-t6a-report.md`，是否验收由Manager独立决定。
