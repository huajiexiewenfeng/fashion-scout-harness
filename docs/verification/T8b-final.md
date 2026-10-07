# T8b 最终包与原位升级交付

已完成最终冻结、构建、全量备份、原位升级和个人 Skill 同步，待 Manager 独立验收。2026-10-07 **21:51:57（上海）**已向精确 Manager 通知可继续 RIHOAS/SimpleRetro 采集；以下是该时点冻结的升级结果。随后不再访问/停止/修改日常实例，避免干扰新采集。

team `fashion-scout-20261006-01a11029` / round `p8-multisite` / task `t8b-release-upgrade`；原 UI/release Worker `local/01a1110e-d333-73e3-82e3-851c5b3d6866`。Manager 已在 state156 验收 Core checkpoint `f6c52be52114034507d225693b9312a645d25f43168960e492f8c8ab02d7d880`，20 项输入 SHA 均再次匹配后才冻结。原构建 HEAD `857eca53ae4b61a60fa33c4cda8f76af4c45c0aa`保留；Manager 后续按用户授权推送 `35003a804be7458191c862b0ab08926a3ad55ecd`，本 Worker 不执行 Git 写操作。

## 制品与运行入口

[最终 ZIP](../../.runtime/t8b-final-inputs/.runtime/t8b-final/FashionScout-0.2.0a1-multisite-app-287336f1719448c4234fe469164dc69d034c001952f9b03bc512b45295f08f11.zip)，35,701,773 bytes，121 个 manifest 输入、73 个应用文件、26 个既有锁依赖、7 个 Skill 资源，不含用户数据/素材/凭据。完整回执位于 `E:\github-workspace\fashion-scout-harness\.runtime\t8b-final-inputs\.runtime\t8b-final\build-receipt.json`。

| 输入 | SHA256 |
| --- | --- |
| ZIP | `d8823ca70c1975189fc95d00c75926cd2245629e6c3890b4ba0d470367b9c511` |
| app wheel | `287336f1719448c4234fe469164dc69d034c001952f9b03bc512b45295f08f11` |
| manifest | `d46ebf6bf59a3704073b5bb1f3681f30d541af2260dbfaa866f7b85e78b14000` |
| 冻结源码 inventory | `f299045ba6d2999264dbede675447e5940f7c3b672e30afee23a3ebf4c93a0bb` |

日常位置保持 `E:\github-workspace\FashionScout`，data 和 8765 不变。[个人款集 Skill](C:/Users/Administrator/.codex/skills/fashion-scout/SKILL.md) 七资源与 repo/包原字节相同，非秘密 binding 精确更新到上述 manifest/app SHA；实际 helper Locate/Status 和 repo/个人 quick_validate 均通过，CheckPackage 未放宽。宿主自动选择刷新没有另作 UI 验证。

## 升级验证时的数据保留

旧实例 `581c24cc-1864-4e88-9f5d-c1995b02441a` 自有 Stop 后，真实 Web/Worker 均 false；新版 Open 后 `8595ed14-2465-40a8-9062-7a312d155237` 的 Web/Worker 均 true，所属 PID/启动身份核验通过。正常运行 UUID 变化符合 Manager 已明确标准，原 control 身份记录、key、配置和回执保留在 data/备份中，未绕过 launcher。

| 数据 | 升级前 | 升级验证后 |
| --- | ---: | ---: |
| 新款显示 / 图 / 空卡 | 20 / 89 / 0 | 20 / 89 / 0 |
| 全部历史商品 / 图集版本 | 40 / 233 | 40 / 233 |
| version_images / assets | 1097 / 89 | 1097 / 89 |
| 收藏 / 排除 / view_events | 4 / 20 / 12 | 4 / 20 / 12 |
| 历史 Run / 服务端 Run 意图 | 3 / 3 | 3 / 3 |
| 客户端意图 | 309 | 309 |
| migrations / 来源 HTTP 记录 | 10 / 0 | 10 / 0 |

49 张表每个既有主键行/列摘要保留，不仅比较总数。workers 仅省略生命周期 heartbeat/state，历史身份列仍逐行核对；无业务 SQL 写入。唯一表计数变化是 sites 1→3（新增两站）和 workers 3→4（新进程注册）。SQLite quick_check=ok、foreign_key_check 无问题，1,281 个原非日志/运行描述/SQLite 数据文件逐 SHA 相同，包括素材、配置、原身份文件和意图回执。旧日志保留并允许追加，完整旧 SQLite/运行描述也在全量备份中。

固定 API 返回三站 browser adapter；最新历史 Run `0f711f657c78497c99590ade6ea354b4` 仍 partial。没有在本升级任务创建来源 Run、来源访问或修改收藏/排除/方案。

## 备份与恢复核验

全量旧包及 data、`.local`、许可/payload、配置和历史文件：`E:\github-workspace\fashion-scout-harness\.runtime\t8b-upgrade-v1\backup\FashionScout`。**8,551 文件 / 218,103,277 bytes，全部摘要与停止后的原件一致**；个人 Skill 的八个原文件含 binding 单独完整备份至同目录 `backup\personal-skill`。

实际复制恢复到 `...\t8b-upgrade-v1\restored-copy\FashionScout`，全部文件逐字节摘要相同，恢复副本只读 SQLite/49 表业务摘要与原件完全相同。原 `.local` 还保留在 `...\t8b-upgrade-v1\original-local`。未移动日常 data、重建库、重配端口或迁移旧 55016/56117 库。

这是升级前一致性快照的真实文件/数据库恢复核验；**没有在生产故障下回滚并重启，也没有整机/断电/新电脑验证**。恢复方案见 [release-upgrade](../release-upgrade.zh-CN.md)；独立副本的 `.local`/client 原绝对绑定仍指向原位置，因此没有从副本启动程序。通知可继续采集后产生的新数据属于后续运行，不属于本升级前快照，不自动回退它们。

## 实际命令与证据

- `freeze_inputs.py --checkpoint f6c52be...` 和冻结目录 builder：exit 0，20 项验收输入完全匹配；[freeze](T8b-final-freeze.txt)、[build](T8b-final-build.txt)，原生 chunk `be8740`/`6a8dba`。离线使用既有 CPython/26 个锁 wheel；没有新依赖下载。
- `python -I -B docs/verification/T8b-final-verify.py` 直接运行现有 9 项 release 检查，对象为确切最终 ZIP，无再次 freeze。**9 passed**、exit 0，chunk `e02f87`；[原始结果](T8b-final-tests.txt)、完整安装/来源/合成导出备份/进程退出证据在 `.runtime/t8b-final-checks/verification.json`。合成只用独立端口和 loopback guard，最终 OS browser-open 为测试拦截；日常新环境未加入该 hook。
- 同冻结输入再 build 最终 ZIP：ZIP/manifest **逐字节相同**，exit 0，chunk `733678`；[repro](T8b-final-repro-evidence.json)。准备时的 27 项输入/拒绝用例结果保留，不重复整套应用测试。
- `T8b-upgrade.py preflight/backup/replace/prepare/verify` 均 exit 0，chunk `1ce171`/`7a3178`/`5038ec`/`fdf48e`/`460cce`；[preflight](T8b-upgrade-preflight.txt)、[backup](T8b-upgrade-backup.txt)、[replace](T8b-upgrade-replace.txt)、[prepare](T8b-upgrade-prepare.txt)、[verify](T8b-upgrade-verify.txt)。所有结构化命令/完整数据摘要/恢复核验与冻结 ready 时点在 `.runtime/t8b-upgrade-v1`。
- quick_validate repo/个人均 valid，chunk `00059b`，只复用此前 yaml 缓存，未新装依赖。新环境、包与数据位置明确；凭据没有复制入报告/Skill/调用参数。

[完整最终证据](T8b-final-evidence.json)包含全部路径、摘要、前后表计数变化和作用时点。原阶段证据未重写，后补升级文件已完整落盘，可由 Manager 追加 Git 提交。没有创建新分支/worktree、子 agent、线程或定时器，模型/effort 未改。RIHOAS/SimpleRetro 后续真实采集由 Manager 继续；本交付不宣称全站、完整 product.images、日期或原像素已知。
