# T8b 准备 checkpoint：尚未正式提交

2026-10-07；team `fashion-scout-20261006-01a11029` / round `p8-multisite` / task `t8b-release-upgrade`。自身 Worker `local/01a1110e-d333-73e3-82e3-851c5b3d6866`，精确 Manager `local/01a11029-0e09-7101-b5b3-1cf2bc8c87d9`，E04 `e04-83dc699ae161a21f4c59142a3de90be53a08abf6d1bd930f24bdd5257529ae94`。自身已恢复 active/ready/connected。main HEAD `857eca53ae4b61a60fa33c4cda8f76af4c45c0aa`；Core 并行修改归原 Core Worker，未覆盖。

准备工作完成，最终任务未提交。等待 Manager 已验收 T8 Core 的源码 checkpoint 才冻结最终输入、构建最终 ZIP 和升级日常安装。没有访问/Stop/修改日常 `E:\github-workspace\FashionScout` 或其 data，没有修改个人 Skill/binding；未访问旧 55016/56117 库。Manager 已明确原历史身份保存、新活跃运行 UUID 可按正常 Stop/Open 生命周期变化，方案已据此更新。

## 修改与方案

- 新增 `scripts/release/freeze_inputs.py`：复制当前源码、构建元数据、锁/pin、release 模板及七资源 Skill；使用现有 setuptools 84.0.0 离线真实 build_wheel，前后拒绝输入变化，wheel/RECORD/源码逐文件配对。只用既有 CPython 归档与 26 个锁定 wheel，无依赖下载或全局安装。
- `test_bundle.py` 不再默认拿历史冻结 wheel 对照活动开发源码；显式使用新配对输入及冻结 builder。保留历史兼容测试和全部 resource set/字节/RECORD/pin/安装校验。真实迁移集合来自该配对包，实库逐版本匹配，不再错误固定 schema 9。
- 隔离运行使用首次 Prepare 前明确的测试端口配置，避免 8765。补充 fresh-default Prepare，继续真实验证自动建立默认配置且不启动服务，未放宽 configure 拒绝重绑定。
- builder 和配对测试收齐 T7 的七资源 Skill，仍不打包机器 binding、业务库、素材、凭据或 `.local`；添加受控 `.runtime/t8b-*` 前缀，未放宽目录归属或重写旧候选。
- 两份包内说明改为单 Skill 日常入口。停旧实例、完整一致性备份、原位替换、恢复环境、业务语义核对、个人 Skill/binding 同步及失败回滚的具体顺序见 [升级方案](../release-upgrade.zh-CN.md)。这些日常步骤尚未执行，回滚能力尚未实际演练。

## 实际验证

1. `pytest tests/release/test_input_refresh.py tests/release/test_bundle.py -q -s` 的输入部分 **27 passed**；初次新 freeze helper 在 `-I` 下不能导入相邻 builder，造成后八 fixture errors。已改为按自身确切文件加载，没有放宽隔离。原始 [tests-1](T8b-prep-release-tests-1.txt) 保留。
2. 随后真实安装验证 **7 passed / 1 failed**：在已自动配置的临时包改端口，被正确拒绝为 `CLIENT_CONFIG_CONFLICT`。已将独立端口配置前置到首次 Prepare 并额外保留 fresh-default 自动配置测试，没有修改产品行为。[tests-2](T8b-prep-release-tests-2.txt) 保留。
3. 最新 `pytest tests/release/test_bundle.py -q -s` **9 passed in 57.91s**，exit 0，原始 chunk `e2694f` / [tests-3](T8b-prep-release-tests-3.txt)。包括 ZIP 实际解压、离线包内普通安装、pip check、逐字节配对、缺失/损坏/配置/长路径/端口拒绝、重复打开、认证 HTTP/静态资源与模块来源、合成 1 款 2 图收藏导出及完整备份。schema 1–10 实库逐版本匹配；source_requests 0；Stop 后真实 web/worker 均 false。
4. `python -I -B docs/verification/T8b-prep-repro.py .runtime/t8b-inputs-6ca6cf5f` exit 0，chunk `57f93a`；同冻结输入再执行真实 wheel backend 和 ZIP builder，**wheel 与 ZIP 逐字节一致**。[repro 原始结果](T8b-prep-repro.txt)、[repro 结构化证据](T8b-prep-repro-evidence.json)。这仅证明该准备快照的可复现性，不将并行 Core 的临时快照当成最终已验收输入。

最新临时安装的完整证据：`E:\github-workspace\fashion-scout-harness\.runtime\t8b-checks-30a9c9f4\verification.json`。包根 100 字符，包含中文/空格/&/单引号；验证过路径预算和全部进程来源。最终 OS browser-open 是测试拦截，loopback guard 无外站请求；不宣称真实新来源巡检、新电脑或整机恢复通过。临时包末尾故意移除静态资源验证拒绝，不用于日常安装。

## 仅供准备验证的冻结制品

冻结根：`E:\github-workspace\fashion-scout-harness\.runtime\t8b-inputs-6ca6cf5f`，`freeze-receipt.json` checkpoint 为 `unreviewed-validation-snapshot`，approval_inferred=false。73 个程序/资源与 wheel 完全配对，26 个依赖、7 个 Skill 资源、121 个 manifest 输入；ZIP 35,698,038 bytes，不含用户数据。

| 输入 | SHA256 |
| --- | --- |
| 准备快照 wheel | `19e5b2317716bb7fe8b56f7473b677d72f2657a4618715eba3c9856a28f16967` |
| 冻结源码 inventory | `ac785d91fb6eaba89d6a8f03853bc10b4f5c158b2aed90d03bb3b3bb2975d701` |
| 准备验证 ZIP | `e65ff705a0de28bbcce359afa9ace66c13ef20246b7fc1e303928687d8b37115` |
| manifest | `cc075f708ee9142abf002cd51d8d4353e2fa746eacb378785939432a39acdf9a` |

ZIP 的确切绝对路径和构建/输入回执见 [准备证据](T8b-prep-evidence.json)，不是最终发布包。程序原 CPython pin、锁、pyproject、Core src/协议 refs 均未由本 Worker 修改；模型/effort 保持，有效实际值未另核验。未新建 branch/worktree/子 agent/线程/定时器，未提交、推送或发布；没有重跑应用全套。最终安装与真实数据升级的证据将在明确 checkpoint 后另行产生。

本准备阶段已通过一次原生 send_message_to_thread 通知精确 Manager，实际返回 isError=false、目标 threadId 匹配。宿主接受回执位于 `E:\github-workspace\.team\fashion-scout\worker-t8b-prep-notice-receipt.json`；不等于 Manager 接收/验收，不伪造正式 submission，不使用 E03 正式提交通知账本。等待已约定的 Core 验收 checkpoint，不轮询 Manager。

Manager 随后通过精确原生回复确认已只读审查准备报告、代码 diff、36 项验证及 repro 证据和升级方案，认可准备 checkpoint。T8b 最终任务仍未完成/提交；按该回复等待 Core 正式验收，不重复测试或额外开发。日常安装与个人 Skill 保持当前状态，最终升级前按最新 API 重新核对。
