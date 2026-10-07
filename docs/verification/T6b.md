# T6b：本机候选包 v1

2026-10-07（Asia/Shanghai）。`p6b-local-delivery / t6b-local-delivery-bundle`，Worker本轮交付待Manager独立验收。沿用T5c-R1已验收应用wheel，未修改生产代码，T2真实素材、T6全产品与真正新电脑安装门槛仍未通过。

## 交付位置与入口

候选ZIP：`E:\github-workspace\fashion-scout-harness\.runtime\t6b-final-v1\FashionScout-0.2.0a1-local-candidate-v1.zip`，35,656,479 bytes。

ZIP SHA256：`6fa3a026a87da7d7c03da6daa075c55efc526eb0a5b108deb8d3ca32fe1a0960`

清单：`E:\github-workspace\fashion-scout-harness\.runtime\t6b-final-v1\FashionScout\manifest.json`；SHA256 `03e28a4696e205d921369a3bb94791001f56310631b261a826058064e9f56684`。同字节副本见[T6b-manifest-v1.json](T6b-manifest-v1.json)。ZIP内部根仅为`FashionScout`，包含113个被清单保护的输入文件及清单自身。

解压后首次双击`01 Prepare.cmd`，日常`02 Open.cmd`，停止`03 Stop.cmd`。包内`data`固定保存业务数据，`.local`固定保存自身运行时与venv；无需系统Python、token复制或JSON编辑。首次prepare普通wheel安装，完整包离线可完成；不启动服务、创建Run或装定时器。open认证入口启动/复用服务，可恢复已接受任务，不新建采集Run。操作说明见[本机候选包使用说明](../delivery.zh-CN.md)；README仅新增当前交付入口小节。

## 输入、构建与保护

| 输入 | 固定值／实际观察 |
|---|---|
| 应用wheel | `fashion_scout-0.2.0a1-py3-none-any.whl`，SHA256 `9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15`；原T5c-R1只读沿用，66源码/资源逐字节一致 |
| CPython archive | 3.13.16，原`runtime-win.json`指定GitHub release20261003，SHA256 `ec43f1a85c29f147d7ae2d13218c52c70b24a983a82ab22d6c607c0593060e10`；本地缓存复用 |
| 依赖 | 原`requirements-win.lock`全部26个wheel，含原锁的测试/构建依赖；pip取出时均显示Using cached，随后逐个锁hash校验。不改版本或依赖锁 |
| 许可 | 自有MIT、26依赖原license文件/metadata及CPython与随附pip组件原license保留在`licenses`，原wheel/archive自身也保留许可 |
| 排除内容 | ZIP中没有data、.local、用户凭据、原运行库、测试种子、项目src或项目.venv路径依赖；运行后这些数据只在解压副本生成 |

依赖缓存准备的实际工具结果为chunk `137bbe`，`pip --isolated download --no-deps --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r requirements-win.lock --dest .runtime/t6b-dependencies-v1`，exit0。只使用固定PyPI解析/缓存与已锁摘要，未请求Futario/CDN。

最终构建命令与[原始输出](T6b-build-final-v1.txt)：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\release\build_bundle.py --output .runtime\t6b-final-v1
```

构建器要求新`.runtime/t6b-*`输出，不覆盖旧候选；检查原wheel与当前66个生产文件及资源集合完全匹配，核心变动时拒绝沿用。允许显式`--download`补齐原pin/锁hash的缺失输入，本轮最终构建没有使用该选项。构建不会安装或启动服务。最终ZIP与下面实际解压验证的ZIP逐字节一致，因此保留原通过证据，无额外全套重跑。

## 独立解压实际验证

实际测试ZIP来自`.runtime/t6b-candidate-faa57b90`，测试目录`.runtime/t6b-checks-57799f5f`，包根：

`E:\github-workspace\fashion-scout-harness\.runtime\t6b-checks-57799f5f\真实解压 空格 & 单引号'sx\FashionScout`

这个路径正好100字符。测试执行CMD三个入口，不只调用构建目录的脚本。记录见[T6b-verification-v1.json](T6b-verification-v1.json)，原始[安装](T6b-install-v1.json)、[打开](T6b-open-v1.json)、[重复打开](T6b-open-repeat-v1.json)、[停止](T6b-stop-v1.json)、[pip check](T6b-pip-check-v1.json)、[合成业务命令](T6b-flow-original-v1.json)。

- 实际项目自有Python3.13.16、SQLite3.53.1；新venv普通安装26锁定依赖与应用wheel，pip check无缺失，所有66包文件与wheel一致。没有editable finder、项目src或项目.venv依赖路径。
- 19份真实Python执行记录含Web/Worker实际入口及固定client，业务模块均来自本解压安装；状态与后台PID/出生时间来自该实例。重复打开复用同instance及Web/Worker身份。
- prepare后没有DB、runtime descriptor、来源Run；启动后实际9迁移，空库Run0/来源0。HTTP认证交换及首页200、5资源与安装文件逐字节一致，未认证读取401。
- 最终OS浏览器动作由只在测试副本注入的钩子截取，记录入口origin及一次性码是否存在，没有记录实际凭据或URL片段；本轮不宣称新增浏览器渲染。钩子同时拒绝非loopback DNS/connect，记录无来源尝试。
- 新隔离种子1款2图明确合成，素材使用生产`originals/<摘要前缀>/<摘要>.png`布局。固定client收藏，生产Worker完成ZIP，认证HTTP下载与摘要一致；实际备份succeeded，1款2资产，清单及实际字节核验成功。最终只有种子terminal Run1，run_requests0、collection_http0。
- 自有实例停止返回forced_roles为空，实际Web/Worker退出。重复prepare保持配置与已有data哨兵摘要；端口被自有监听器占用时返回PORT_IN_USE/exit3且监听器仍存活。损坏wheel、缺包资源、未确认既有data、配置冲突、实际tar启动失败/半安装重试、已安装资源丢失均拒绝执行并保留data；错误传播为非零退出码。

最终测试命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -X utf8 -m pytest tests\release -q -s --basetemp .runtime\t6b-pytest-5
```

[最终日志](T6b-tests-5.txt)：**8 passed in41.85s**；前一版路径修正后的基础[日志](T6b-tests-4.txt)：8 passed in40.17s。没有重跑旧阶段整套测试。

## 路径范围及保留的失败

第一版开发脚本有PowerShell参数组合问题（`T6b-dev-install-1.txt`）；初次7项测试中6项因当前PowerShell缺Get-FileHash自动加载失败（`T6b-tests-1.txt`）。仅修改新包脚本为受控路径拆分与.NET SHA256。第二次6项通过，CMD测试调用本身引用不正确（`T6b-tests-2.txt`），修正新测试的原生命令引用。第三次安装/认证/收藏成功，但126字符根导出失败（`T6b-tests-3.txt`）：ZIP路径263字符，独立266字符文件创建失败，同目录短文件成功；保存[最小复现](T6b-path-limit-repro-v1.json)并已向Manager发送一次“阶段诊断，尚未正式提交”。原生接受，未据此更改生产代码或系统LongPaths。

最终内部目录缩短为FashionScout，准备前检查Windows UTF-16包根长度最多100；101字符含中文/空格目录被拒绝，未产生.local，data哨兵保留。边界不是单个样例推定：对当前默认内部布局，用SQLite有符号64位计数最大19位给epoch/attempt留界，并核对实际安装/备份路径。

| 派生路径 | 100字符包根的长度上界 | 来源／验证 |
|---|---:|---|
| 实际已安装文件含pyc | 本次最长222 | 遍历独立解压安装文件；固定runtime原archive最长文件在213内 |
| 默认永久素材 | 194 | collect.py：originals/2位前缀/64位摘要，最长webp扩展 |
| 原始下载temp（64位epoch） | 207 | db/archive.py：32位Run/epoch/32位文件ID.part |
| ZIP最终路径（64位attempt） | 250 | exports/jobs.py与engine.py：32位job/attempt/64位导出摘要.zip；常见第1次为237 |
| 备份暂存资产 | 245 | maintenance/backup.py：32位job/stage-12位/assets/64位摘要.bin；本次Worker确实完成该路径复制与校验 |
| 备份正式资产 | 222 | 本次最长正式备份文件222，逐成员核验通过 |

范围只涵盖新包默认内部data/media及当前生产生成的固定ID/摘要路径；任意外部素材根、导入历史任意相对文件名、离线恢复目标、未来包内增加更深资源或底层路径变更须单独核对，不能把100字符承诺扩展为任意长路径支持。未来核心变更须重建并复核候选。

## 最终证据与剩余门槛

[T6b-evidence-v1.json](T6b-evidence-v1.json)记录本轮前保存的[282文件基线](T6b-baseline.json)逐项不变、候选ZIP/清单、制品hash、本地文档链接和已知自有服务退出。只读核对旧失败实例及本轮两个成功实例；没有扫描其他进程或数据根。用户预览`.runtime/t5b-browser-user-preview-01`/56117、旧T2/真实默认根没有访问。

未修改src、旧脚本、Skill、原配置/依赖锁、旧测试或旧证据，未改系统PATH/注册表/服务/计划任务或主项目.venv。故障测试只清空自己的子进程PATH来制造tar不可用。没有来源/CDN请求、子Agent、新聊天、定时器、全局Skill安装、commit/push/PR/发布。T2预算与诊断仍由原任务管理；本轮安装本机隔离副本的授权不等于源站访问或最终发布授权。

本轮交付候选仍包含旧已验收wheel的应用版本。真实来源整链路、整个Codex退出、Windows重启/休眠/物理断电、真正新电脑安装和人工含纠错耗时尚未证明。原Worker提交/E03实际回执留在团队`worker-t6b-report.md`，是否通过由Manager独立决定。
