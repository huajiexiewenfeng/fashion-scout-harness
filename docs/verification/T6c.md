# T6c：发布输入工具准备 v1

2026-10-07（Asia/Shanghai）。任务`p6c-release-preparation / t6c-release-input-refresh`。本轮完成构建工具输入更新，待Manager独立验收；不是新采集验收或新版最终候选包交付。Core正在原T2任务修改生产代码，本轮未以进行中的src或Skill作为通过证据，也未修改README、delivery或architecture。

## 接口与保留行为

`scripts/release/build_bundle.py`新增：

| 参数 | 契约 |
|---|---|
| `--app-wheel`与`--app-sha256` | 必须成对出现，SHA必须为64位十六进制；空值不回退为默认输入。核对所选文件实际摘要，不从文件自动推定预期值 |
| `--source-root` | 指向已冻结的src根，包含fashion_scout/；默认仍为项目src。始终逐字节、逐资源集合与所选wheel核对，完成组包前再次核对。当前Core未冻结时不执行这个默认源码入口 |
| `--label` | 1–32位小写字母/数字/连字符，不能包含目录分隔符、点路径、空字符串或超长值；版本来自wheel自身METADATA，不由标签覆写 |
| `--output` | 保留新建直属.runtime/t6b-*行为，并允许t6c-*。目录必须不存在，原子mkdir领取唯一输出；旧目录与并发竞争不会覆盖既有制品 |

没有提供应用wheel/hash时，仍选择原T5c-R1 wheel及固定SHA `9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15`，默认缓存/runtime和旧候选ZIP名称均保留。兼容表示旧命令与输入选择语义保留；工具模板及清单新增字段会改变新生成ZIP字节，不能承诺旧包SHA不变。原已验收T6b ZIP及证据没有回写。

显式输入或标签的候选名为：

```text
FashionScout-<wheel版本>-<标签或local-candidate>-app-<完整应用SHA256>.zip
```

相同版本但不同应用字节也有独立候选身份；清单同时保存`app_wheel`相对路径、`app_version`、完整`app_sha256`、每个源码/资源的大小与SHA及总`source_sha256`。接收者需独立核对冻结与审查来源；字节核对不自动授予批准。

将来正式重建的参数形式如下，仅是接口示例，本轮未对进行中的Core执行：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\release\build_bundle.py `
  --output .runtime\t6c-new-reviewed-input `
  --app-wheel '<Manager确认的冻结wheel绝对路径>' `
  --app-sha256 '<已独立确认的64位SHA256>' `
  --source-root '<与该wheel对应的冻结src根>' `
  --label browser-ingress-reviewed
```

## 输入拒绝与包内入口

构建器只接收受支持的fashion_scout纯Python wheel布局；核对文件名、METADATA分发名/版本、py3-none-any标签、现有Python约束和已锁定依赖。RECORD须覆盖全部成员且每个非self成员摘要/大小匹配；拒绝重复、越界、链接、加密、异常大小或不支持payload。关键模块、两HTML入口、5静态资源及至少001–009连续迁移不得缺失；允许合法新增资源和后续连续迁移，但必须与冻结源集合一致。

错hash、缺一项/空值、错误分发、缺资源或迁移、RECORD损坏、源码字节/集合差异、缺冻结根、越界标签或输出都返回非零。已知这些输入拒绝发生在创建输出前；下载或组包中的IO失败保留已领取的目录供检查，不覆盖重用。应用及依赖/运行时实际复制摘要也会再次核对；Python-O不会取消校验。

`scripts/release/templates/package.ps1`按清单的受控`app_wheel`文件名安装，并核对其摘要与`app_sha256`绑定；拒绝其它包名、越界路径或SHA冲突。保留旧清单没有app_wheel字段时的原文件名回退。准备/打开/停止其余逻辑不变，100字符包根限制仍适用。

runtime pin和26依赖锁均沿用。没有新依赖、下载或安装；旧显式--download能力保留但本任务未使用。没有弱化冻结源检查，也没有产品测试后门。

## 实际验证与证据

全部CLI测试使用`.runtime/t6c-inputs-ae307604`中的独立工具副本、从原已验收wheel解出的冻结旧源码副本、原运行时/依赖缓存副本。测试变体仅在这些新t6c目录增加明确“T6C ISOLATED TEST FIXTURE ONLY”标记、调整测试METADATA/RECORD或增添测试资源；不读取Core进行中的源，也不将变体作为新生产wheel交付。

- 旧命令不传app/hash/source参数即能在隔离旧工程成功构建，选择原输入和原ZIP名称；再次调用保留全部既有文件SHA并拒绝覆盖。
- 两个相同0.2.0a1版本但不同字节，以及0.2.0a2/新增第67资源的测试wheel，候选名、清单和实际ZIP成员绑定正确。66→67没有硬编码包文件数；每个冻结资源摘要核对一致。
- 两个同时启动的构建进程竞争一个新输出，只有一个成功、另一个exit2，成功制品逐成员核对。仅为两个普通测试进程，无子Agent。
- 公共Status入口从测试ZIP的独立较短解压目录核对新版wheel字段，随后如实提示尚未prepare/exit2；无.local/data生成。恶意清单wheel路径与SHA冲突明确拒绝。没有实际安装、开浏览器、启动Web/Worker或来源请求。
- 21种参数/输入拒绝包括缺一项、三个空值组合、错/畸形SHA、Python-O下错SHA、错包名/分发、缺资源/迁移、RECORD坏、wheel越界、源变字节/多资源/缺根、标签越界/空/过长及输出越界；无构建制品生成。

命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -X utf8 -m pytest tests\release\test_input_refresh.py -q -s -W error --basetemp .runtime\t6c-pytest-4
```

[主日志](T6c-tests-4.txt)：**25 passed in19.68s**。随后仅调整测试日志文件名为basename，避免越界拒绝案例的日志离开logs子目录；[该项复核](T6c-tests-5.txt)1 passed/24 deselected in0.19s。第一次19/21通过、两项被测试目录的100字符限制提前拒绝，改为独立较短解压位置后21通过。并发增强轮25通过但遇Windows错误输出解码告警，构建器显式UTF-8输出后告警视为错误复核通过；全部旧失败/告警日志T6c-tests-1/2/3.txt保留。

完整[CLI/PowerShell命令记录](T6c-command-records-v1.json)、[输入/清单与制品摘要](T6c-input-evidence-v1.json)来自实际测试结果，不重构输出。[文件边界证据](T6c-evidence-v1.json)以[初始基线](T6c-baseline.json)核对本Worker负责范围：192个既有文件中只改构建器与package.ps1两项允许文件，190项不变；旧T6b ZIP SHA仍为 `6fa3a026a87da7d7c03da6daa075c55efc526eb0a5b108deb8d3ca32fe1a0960`。

Core独占且正在变化的src、Skill和相关文档没有纳入本Worker的不可变声明；本Worker没有访问它们进行构建验证。HEAD仍main51e0dae87065fe725380be0724ac999d0c1fdb84，原未提交成果保留。

## 提交范围与未满足项

只修改两个release工具文件，新增release输入测试及T6c文档/证据、隔离t6c输出与自己的团队报告。README/delivery/architecture、原锁/runtimepin/pyproject、旧证据未改。用户预览56117、旧T2根和真实默认根未访问；无源/CDN请求、安装、浏览器、业务服务、全量旧应用测试、子Agent/新聊天/定时器、全局Skill、commit/push/发布。

本轮可单独验收的是构建工具准备。新browser ingress的冻结生产wheel、审查、真实适配、后续正式重建和候选安装/运行验证仍由Manager另行协调；不自行监视、等待或启动这些未派发工作。原Worker submit及一次E03真实结果留在团队worker-t6c-report.md。
