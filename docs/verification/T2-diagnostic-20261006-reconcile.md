# T2 活动冷却行一次性本地对账回执

原任务 p2-collection / t2-futario-media；依据 Manager 的 manager-t2-fresh-cooldown-review.md 执行。2026-10-06 **14:34:19.392 UTC** 完成。T2仍blocked，未正式submit；本轮真实HTTP请求0，未启动Worker，未进入其它工作。

目标严格限定 `E:\github-workspace\fashion-scout-harness\.runtime\t2-live-smoke\scout.sqlite3`。写入前验证目标DB摘要与上次诊断保存的摘要一致；原始新诊断result.json及文档副本SHA256均为 `be7f1ca1557e78a8b88fa206fa7139fa33c97b7a3c7971b16884d986302d9438`，URL/GET/429/原始Retry-After60/Date/接收UTC一致。无活动Fashion Scout服务，旧Run仍failed且lease_until为空，历史owner对应Worker为stopped。

维护脚本首次只读预检误假设终态Run应清空owner，因此在任何写入前停下；读取既有finish实现确认owner保留是正常历史记录后，将预检限定为终态、租约为空、对应Worker已停止及无活动进程。没有记录冲突，没有失败SQL重试；实际CAS只执行一次。

写入前使用独占创建保存完整旧行、拟写新行、授权与新证据路径/摘要、目标DB摘要、所有表逻辑摘要及进程状态。该audit-before.json先flush/fsync，再设为只读；记录采用写一次、不覆盖和hash核验方式保存。短事务再次比较完整旧行和数据库逻辑快照，仅当完全一致才执行CAS。旧历史未知限制保留在该审计及先前未修改的诊断、报告中。

| 字段 | 旧活动行 | 新活动行 |
| --- | --- | --- |
| site_id | futario | futario |
| not_before | NULL | 1791297004.4749758 |
| mode | legacy_response_not_saved | server_foreground_reconciled |
| request_seq | NULL | NULL |
| recorded_at | 1791286123.4316926 | 1791296944.4746 |

新recorded_at来自实际接收时间2026-10-06 14:29:04.474600 UTC；新not_before按Manager明确审核的原始诊断值保存，约14:30:04.474976 UTC。该活动限制依据新的服务器响应，未宣称旧响应是什么或旧未知等待何时到期。没有将诊断关联至旧请求，没有伪造collection_http或collection_http_results。

事务影响行数1。提交后重新打开只读连接复核：新行与事务内值一致，schema摘要不变，**另外35个表的行数及全部行内容摘要不变**，其它站点冷却行不变。Run、快照、attempt、累计计数、assets、原始响应和迁移历史均保留。真实根仍为原6迁移状态，没有执行新迁移或替换数据库。项目生产代码、已有迁移、依赖锁及既有报告未改，未触碰collector行为，因此不重复运行fixture测试。

证据文件：

- `T2-diagnostic-20261006-reconcile-before.json`：写入前审计副本；SHA256 `eb0b38c77e4ff8bd67fa6a53b27449e166d0ffce13f247642b7d1e05f9328fd6`。
- `T2-diagnostic-20261006-reconcile-receipt.json`：提交后回执；SHA256 `d4310ef74ef094e23d7cd6c6cb0ac4d016fcb2b1df402cb285d05894a7929977`。
- `.runtime/t2-diagnostic-20261006-reconcile/audit-before.json`、`receipt.json`：已fsync、只读的原件。
- 同runtime目录 `reconcile.py`：固定目标/固定证据/固定旧新值的单次维护脚本，审计文件存在即拒绝第二次写入；SHA256 `e8621758eb8050797a0d99c42411d69c69936b890aac4d87a26251415639d9ab`。

总实站尝试仍4次，最多剩36次；新时间已经过去不代表授权再次请求或来源可用。真实图片验收仍未满足，仍等待Manager新的独立授权，不自动retry、轮询或定时。
