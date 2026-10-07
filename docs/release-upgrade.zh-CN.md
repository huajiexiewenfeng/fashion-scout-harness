# T8b 冻结、打包与保留数据升级

T8b 当前先完成准备。最终 wheel/ZIP 和日常安装升级，必须等待 Manager 明确给出已验收 T8 Core 的源码 checkpoint，并确认当前 Run 及文件归档结束。准备材料和测试快照不代表源码已验收。日常 `E:\github-workspace\FashionScout`、个人 Skill 和其 binding 在准备期间均不访问或修改；测试只使用新的 `.runtime/t8b-*` 副本与独立端口。

## 配对输入

`scripts/release/freeze_inputs.py` 将当前 `src/fashion_scout`、pyproject、许可、锁、runtime pin、release 脚本/模板与七份 Skill 资源复制到新目录。它只使用现有 setuptools 84.0.0、已锁 26 个 wheel 和 CPython 归档，执行真实 build backend；前后核对源输入没有变化，随后核对 wheel 的 RECORD、元数据、逐文件内容与冻结源码完全配对。拒绝覆盖、链接、缺依赖和并发修改；失败目录保留，不视为有效输入。

以下命令是开发验收入口，不是日常用户步骤；输出目录必须不存在。`--checkpoint` 只记录 Manager 的实际来源标签，程序不会从标签推定批准。

```powershell
& .\.venv\Scripts\python.exe -I -B scripts\release\freeze_inputs.py --output .runtime\t8b-final-inputs --checkpoint '<Manager已验收的实际源码checkpoint>'
$pair = Get-Content -Raw .runtime\t8b-final-inputs\freeze-receipt.json | ConvertFrom-Json
& .\.venv\Scripts\python.exe -I -B .runtime\t8b-final-inputs\scripts\release\build_bundle.py --output .runtime\t8b-final-inputs\.runtime\t8b-final --app-wheel $pair.app_wheel --app-sha256 $pair.app_sha256 --source-root $pair.source_root --label multisite
```

最终构建使用冻结目录中的 builder，不能回到变化中的开发树取 Skill/模板。wheel 摘要显式传入；现有 resource set/字节、RECORD、依赖/CPython pin、ZIP/manifest 和安装完整性校验全部保留。历史默认 wheel 仅在与其配对的隔离历史树上测试，不自动当成当前候选。包收齐 `SKILL.md`、四份 references、`scripts/entry.ps1`、`agents/openai.yaml`；不打包机器 binding、data、凭据或 `.local`。

## 临时验证

运行 `pytest tests/release/test_input_refresh.py tests/release/test_bundle.py`。安装验证从真正 ZIP 解压并在包内普通安装，核对当前配对 wheel 的安装字节、全部实际 migration、模块来源、固定认证页面/静态资源、合成收藏导出和备份。合成实例在首次 Prepare 前预置明确测试配置，选独立空闲端口；不访问或停止 8765。另有 fresh-default Prepare 核验自动建立默认配置且不启动实例，保留配置拒绝静默重绑定的实际行为。损坏、缺文件、配置冲突、未完成准备、长路径、端口占用、重复打开和 Stop 后真实进程退出的拒绝/恢复校验仍执行。测试截取最终 OS browser-open 并限制 loopback；不代表真实来源采集或新电脑验证。

## 日常升级执行 checkpoint

1. Manager 提供已验收源码和完成归档的明确 checkpoint 后，重新用固定 API 获取最新状态、业务计数与待处理意图。确认无活动采集、未接收/归档 ticket、导出和维护任务；不使用此前 3 款/12 图或 20 款/89 图作为最终基线。记录 Run、收藏、排除、素材、意图与回执的实际计数及相关行/文件摘要；不输出令牌、key 或 session 内容。
2. 用旧包自己的 Stop 停止旧实例，核验其 Web/Worker 的进程身份均已退出。端口不是进程归属证据，不按 8765 杀进程。停止后做一致性 SQLite 检查与最终基线，备份完整包和全部 `data`、素材、control/历史身份文件、配置、意图回执、导出、备份及 `.local` 到新独占回滚目录，逐文件大小/摘要相符后才允许替换。任何链接/外部素材根需先明确处理，不跟随扫描未知目录。
3. 在独立短目录检查最终 ZIP SHA、CRC、安全成员集合与每个 manifest 输入。保持日常包绝对位置、data 根、client 配置和端口不变。保留旧 `.local` 到已核验回滚位置，再替换仅包资源、payload/许可和 manifest，manifest 最后写入。`data` 保持原地，不重建库、不重新 configure，不用 SQL 更改商品业务。
4. 在日常原位置使用新 package Prepare，创建新的包内环境；旧数据配置存在时保持不变。新 wheel、安装来源及完整性核验通过后，以固定 Open 恢复。允许程序正常执行明确的 schema migration；核对此前每个业务表的既有列/行语义、Run、素材摘要、收藏/排除和意图回执。新列/表单独记录，不能以总数相同替代保留校验。重新读取 API，确认多站配置、实图默认展示和同一 Run 的历史仍可见。
5. 确认 app 健康和数据保留后，备份原个人 Skill 七资源和非秘密 binding，按 repo/包的已冻结资源同步，原路径/manifest/app SHA 精确更新 binding。CheckPackage 不放宽；源码、包内资源和个人资源逐字节匹配。用户仍以自然语言发起。保留回滚备份；不自动删除旧库或安装、提交、推送和发布。

## 失败恢复与身份边界

替换、Prepare、迁移或验证失败时停止推进，保存真实结果。若新实例已启动，只 Stop 已核验属于此包的新身份；先保留失败的新 `.local`/data，再从已验证回滚副本恢复原包、原 `.local` 和必要的整个 data 到原绝对位置，恢复原个人 Skill/binding。重新校验原包哈希、旧 schema 和业务基线后才用旧包 Open。不得单独用旧程序打开已迁移的新库；回滚未实际演练前不能宣称可恢复。

源码 `launcher.ensure_running` 在已正常 Stop 的 descriptor 上会生成新的 `app_instance_id` 和 key，这是当前运行实例的生命周期行为。Manager 已在 T8b 原生 checkpoint 明确：保留同一 package/data、数据库全部历史 Run/product/user_state/intents/素材和原身份记录；不要求正常 Stop/Open 后活跃运行 UUID 不变。整个 data/control 的旧身份记录和 key 保留在原位置与备份中，记录新旧运行 UUID 对照。release 不修改 stopped 标记或私造 descriptor，不绕过 launcher 身份校验。

这些是具体执行和验收方案。准备阶段不执行日常 Stop、备份、替换、恢复或个人 Skill 同步；最终实测的计数、摘要和回滚结果另存 T8b 验证材料，不用本方案代替执行证据。
