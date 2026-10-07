# T6d R1：Skill测试输入补齐与最终v2文案

2026-10-07，原`t6d-browser-final-bundle`，Manager v134返工及同任务按钮限制补充；待重新独立验收。

最终本地候选ZIP：`E:\github-workspace\fashion-scout-harness\.runtime\t6c-final-browser-v2\FashionScout-0.2.0a1-browser-v2-app-5938b20f707c73ebc0042d115abdd7e04d3bf62dd9799362be595afa52393753.zip`，**35,693,175 bytes**。

SHA256：`e84136524449677efb8c72b2a3042f414b36c25cd10c325182e639eb14cedc42`

Manifest：`E:\github-workspace\fashion-scout-harness\.runtime\t6c-final-browser-v2\FashionScout\manifest.json`，SHA256 `f79f619e62c732736ea4a647e486510cb36ca3eb887c3f9bf5b8da646dd7dc2f`。副本见[T6d-R1-manifest-v2.json](T6d-R1-manifest-v2.json)，使用说明见[delivery.zh-CN.md](../delivery.zh-CN.md)。

## 最小返工

新增必需Skill输入后，原input_refresh隔离kit没有复制四文件，Manager复跑默认兼容测试在“Required conversation Skill material missing: SKILL.md”失败，原始tool chunk38da50。按明确授权，只在`tests/release/test_input_refresh.py`的kit复制四份不变Skill输入，并在已有inspect增加四原件字节、skill_files摘要及manifest记录断言。所有原断言保留，生产、builder和Skill原文不改。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -X utf8 -m pytest tests\release\test_input_refresh.py -q -s -W error --basetemp .runtime\t6c-d-r1-pytest-1
```

[原始输出](T6d-R1-tests.txt)：**27 passed in26.51s**。独立kit `.runtime/t6c-inputs-1bc09368`，旧冻结wheel-derived源码；没有重新安装应用、复跑应用套件或请求来源。测试ZIP只为工具fixture，不替代最终输入。

Manager独立安装v1新解压副本已通过，实际Chrome为0款/尚未巡检，schema10/72安装成员一致、Run与来源计数0；原Worker的[离线安装/HTTP证据](T6d.md)亦保留。发现当前默认source_mode=http，网页开始按钮不带browser override。三处文案明确：**本版本采集请在Codex对话发起；网页开始按钮仍为旧方式，暂不用于本版本浏览器采集。** PACKAGE-CONTEXT同时明确Codex按原Skill冻结browser来源，并继续使用实际.local/env解释器与显式包/data根。没有修改按钮、默认方案、业务代码、wheel或Skill。

## 仅文案重打包证明

仍使用唯一冻结应用SHA5938b20f…、原stage/source/src、CPython3.13.16及26依赖，使用同builder新输出`.runtime/t6c-final-browser-v2`与label browser-v2；[原始构建日志](T6d-R1-build-v2.txt)保留，未覆盖v1。

[差异与完整证据](T6d-R1-evidence-v1.json)逐项核对两个manifest/ZIP：118输入集合一致，只有README.zh-CN.md和PACKAGE-CONTEXT.zh-CN.md两文案字节变化，116输入不变；ZIP的119条目只有这两个文件和manifest.json变化，CRC及每个清单摘要通过。manifest顶层只有candidate/files变化，72 source成员、应用wheel、runtime/26依赖、启动/安装/核验脚本、4Skill原字节全部相同。因此复用已通过真实安装证据，不重复整套安装。

R1的31既有文件基线仅三授权文件变化（测试及两包文案），28项不变；delivery和README当前链接/限制另有授权更新。所有v1报告/日志/ZIP、原stage与数据、Core与Skill/锁/runtimepin/pyproject保留。没有访问或停止55016/56117，没有来源请求、下载、新依赖、Agent/新线程/定时器、全局安装、commit/push或发布。

单商品真实最低范围仍为20listing metadata/1detail/6WEBP、收藏及partial schema2 ZIP；日期/变体/完整product.images/原像素、批量稳定性/全站能力未知。浏览器采集须保持Codex运行及连接，已完整收到文件/导出维护可独立处理；网页按钮尚未接通此流程。原Worker R1提交与一次E03真实回执位于团队worker-t6d-r1-report.md。
