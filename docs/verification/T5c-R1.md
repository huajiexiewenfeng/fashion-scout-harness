# T5c-local-R1：恢复复制校验与问题详情

2026-10-07（Asia/Shanghai）。针对 Manager `manager-t5c-rework-1.md` 的 P1/P2 同任务返工，待重新独立验收。v1报告、日志、截图、样例、证据及原wheel全部保留。

## P1 修复

原缺口属实：先验证包再重新打开复制，不能保证复制的是预检字节。恢复现改用专属 `copy_verified`：流式1MiB块累计真实复制SHA256/字节数并对照已验证manifest；源路径/打开句柄在读取前后比较身份，检查reparse，写入flush/fsync后重开目标核对。数据库副本在执行任何根映射SQL前再次按原manifest校验。SQL改写关闭后记录新数据库摘要；最终发布前 `verify_stage` 重读每份暂存资产和改写后的数据库。任一不符抛错、保留私有stage、最终目标不发布；不覆盖原库，也不启动任何服务。

专属7项测试 `tests/maintenance/test_restore_r1.py`：

- 包预检成功后，首张源资产同长度改一字节：拒绝，final不存在。
- 包预检成功后，SQLite业务收藏字段改动且integrity_check仍ok：原字节摘要拒绝，final不存在。
- 源资产已打开并读取时中途改字节：身份变化拒绝，final不存在。
- 完成复制后、发布核验前损坏stage资产：拒绝，final不存在。
- 完成SQL后、发布核验前损坏stage数据库：拒绝，final不存在。
- 正常完整备份恢复成功，逐个读取恢复资产核对原SHA；现有显式partial恢复、跨根历史读取及重新导出仍通过受影响回归。
- 核验/备份均提供已有款名的分组展示数据，同时保留每个原始诊断object_id。

每个故障测试还确认原业务库dump不变。测试仅修改明确的隔离合成备份/暂存文件，不触碰Manager复现fixture。这里处理复制期间变化，不声称抵御同Windows用户恶意进程在最终检查后抢改文件。

## P2 修复

`maintenance/presentation.py` 从核验冻结快照或已校验备份清单中的版本/引用关系取得商品名，按类别+原因分组，返回数量、涉及商品数及最多5个已有款名。缺乏映射或名称时仅显示通用分组，不猜测名称。API原始 `result.issues` 完整保留，新增展示字段不覆盖诊断记录或旧包摘要。

普通折叠详情使用 `maintenance-findings.js`，显示“缺失：图片尚未保存在本机 · 4项，涉及2款”及实际两款名称。未知原因也不暴露内部code/object_id。没有新主导航、向导或逐文件必选操作。新增2项前端检查覆盖分组计数、名称及未知诊断的通用显示。

## 验证与制品

| 检查 | 结果 |
|---|---|
| 针对性故障测试 | 7 passed / 2.53s；`T5c-R1-targeted.txt` |
| 维护、API、客户端、真实维护进程集成 | 85 passed / 58.41s；`T5c-R1-tests.txt`（含上述7项） |
| 前端全套意图及分组显示 | 30 passed / 0 skipped；`T5c-R1-ui-tests.txt` |
| 桌面1440×1000、手机390×844 | 实际点击核验1job，12素材/4缺失，详情合并为2款；手机scrollWidth375≤390，无控制台错误；`T5c-R1-browser-*.png` |
| 新wheel | `.runtime/t5c-r1-wheel/fashion_scout-0.2.0a1-py3-none-any.whl`；SHA256 `9beaa9f5e49063fdb5b36d906b8bac5d1d5a46772f4c5b90a10782a77b772f15` |

浏览器实例仅 `.runtime/t5c-browser-r1-01` / 64078；首次标签同步超时后关闭自己的失效标签并重建，认证会话恢复，随后完成真实操作。测试页已关闭、临时视口已还原、实例已停止。原用户预览56117保持原样。

`T5c-R1-evidence-v1.json` 固定本轮哈希、v1差异、66个生产文件与wheel逐字节匹配、9迁移、157原保护文件一致、R1新增进程根退出证据。相对v1只改原 `maintenance/restore.py`、`maintenance/jobs.py`、`static/maintenance.js` 三个生产文件，新增两个小展示模块及针对测试/验证文件；构建重生成SOURCES清单。未改core/config/Worker/采集/导出引擎，复用Manager已通过的v1 252Python/28前端其余证据，不将其误报为R1全量重跑。

不扩大任务范围；不访问真实来源或默认根，不创建子Agent/定时器，不提交推送发布。部分备份、本机同盘备份与离线恢复边界仍同v1；T2真实素材和T6门槛仍未通过。正式重新提交与通知回执另记团队R1报告。
