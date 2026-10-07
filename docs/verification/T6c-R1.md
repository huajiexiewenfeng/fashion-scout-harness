# T6c R1：本地版本加号与清单语法对齐

2026-10-07（Asia/Shanghai），原任务`t6c-release-input-refresh`，Manager state117返工。本轮只修复一个已实证的构建/包内预检语法差异，待Manager重新独立验收。

Manager原反例位于 `E:\github-workspace\.team\fashion-scout\manager-t6c-plus-repro.json`：`0.2.0a1+browser` wheel通过构建，ZIP包含带`+`的wheel文件名；90字符根内包Status却在通用清单成员校验处报Invalid manifest member。构建器VERSION_PATTERN和专门wheelMember校验已经允许`+`，通用路径字符类遗漏了它。

修复仅在 `scripts/release/templates/package.ps1` 的通用成员字符类加入字面`+`。未扩大版本解析，未改构建器、Core或依赖；点路径、绝对路径、重复成员、根边界、文件摘要及wheel专用语法检查保持。

新增两项测试，并复用一项相关清单绑定回归。命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -X utf8 -m pytest tests\release\test_input_refresh.py -q -s -W error -k 'local_version_plus or plus_manifest or package_manifest_cannot' --basetemp .runtime\t6c-r1-pytest-1
```

[原始日志](T6c-R1-tests.txt)：**3 passed / 24 deselected in11.55s**，告警视为错误。隔离根`.runtime/t6c-inputs-b95213e3`；从原T5c-R1 wheel生成明确测试fixture和对应冻结树，没有用Core正在变化的src。

实际plus fixture：`fashion_scout-0.2.0a1+browser-py3-none-any.whl`，SHA256 `1a0d778b356d99640c257f8425a5f7ebc6ed171771b55b82dd9f0417ea6c5136`。实际构建ZIP再解压到90字符根，原生PowerShell公共Status通过所有清单文件及wheel/SHA核对，返回“Run 01 Prepare.cmd first”/exit2，没有data或.local。这说明预检语法一致；本轮没有安装或启动应用服务，不把预检当完整启动验收。

plus清单中父目录`../outside+file.txt`、绝对路径、分号、反斜杠、重复成员及篡改wheel成员SHA的六类变体，仍在预检拒绝，无data/.local；旧专用wheel路径越界、其它包名及app_sha冲突三类回归也通过。每次检查后恢复测试副本原清单，原Manager反例与既有ZIP未改。

[R1证据](T6c-R1-evidence-v1.json)包含实际原始命令、receipt、预检与文件SHA；[R1基线](T6c-R1-baseline.json)22个既有文件中仅package.ps1和test_input_refresh.py两允许项变化，20项不变。旧T6c v1报告、25项通过日志、输入/命令证据及旧T6b ZIP摘要均保留。未重跑全套业务、浏览器或安装；未访问Core生产源/Skill、默认根、用户56117或旧T2根，无源/CDN请求、下载、新依赖、Agent/新聊天/定时器、全局安装或提交发布。

原任务仍只交付发布输入工具准备。Core冻结wheel、真实采集及后续正式新候选重建仍由Manager另行协调；原Worker R1提交和一次E03真实通知回执在团队worker-t6c-r1-report.md。
