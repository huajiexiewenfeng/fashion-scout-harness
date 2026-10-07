# T2 本地阶段 v2：Manager R1–R3 修正

2026-10-06，原任务 p2-collection / t2-futario-media 仍 executing；这是执行中修正证据，不是正式提交、验收或进入T3。依据 Manager 的 manager-t2-local-review-1.md / manager-t2-local-repro.json。没有修改 Manager 的复现数据，也没有实站请求。

## 行为与恢复契约

R1：`Context.collection_started` 在当前租约执行段开始时取 monotonic；Catalog 的请求前/收到字节后使用同一个起点。首次 `collection_runs.started_at` 只作审计。停机或执行结束后的站点等待不会永久耗尽重试时间；当前执行中的有界短退避仍计时。下一次显式 retry 或既有Run的授权恢复有新的受控执行段。快照、Run ID、已完成工作、历史、累计HTTP/图片/发现/详情/字节预算与持久来源冷却均保留。运行中请求还受既有单请求总时限约束，不宣称实时硬中断任何OS调用。

累计额度耗尽时对应 issue 的 retryable=false，evidence_ref 附 `action=review_frozen_limits_then_explicit_new_run;same_run_limits_do_not_reset`。普通 retry 不能增加预算；若确需更多工作，需用户复核并调整之后的默认/临时方案、显式接受新Run，不能改旧快照或自动扩大限额。实站诊断的跨Run总授权额度也不能通过新Run绕过。RUN_TIME_BUDGET 则支持在累计额度仍足够且冷却允许时原Run恢复。

R2：内容摘要只使用排序后的有效图片 SHA256 去重集合。新增失败图片、删除缺图、补入与已有图片相同字节、重排图集只改变覆盖/清单revision；补齐不同字节或同URL真实内容变化产生新内容身份。旧冻结manifest/资产不修改，最新观察、最新可用和最新完整指针仍分别更新。旧开发阶段v1的冻结记录保留原始摘要，不对它们伪造回填；当前公式用于此修正后生成的版本。旧v1样本不作为T3已验收数据基线。

R3：新增007 owned_temps，记录 root、Run/item、epoch、相对路径和文件dev/inode。先持久意图、再独占创建，再保存身份。仅在媒体temp范围、身份一致、租约仍有效、无活动/blocked journal引用且不是asset路径时清理。SQLite写锁覆盖最后身份检查和unlink，阻止新租约/意图在检查与删除之间插入。commit完成数据库事务后才清理，包括已有相同hash目标时的独立副本；原件不可覆盖，也不删除。旧T1 journal 的兼容清理先核验hash/大小，再在有效租约内复核generation及文件身份，不改旧迁移。

未stage的网络/解码失败temp及时清理。stage后崩溃保留journal所需字节；DB提交后清理前崩溃，下一次该Run恢复会清理且不重下载。清理失败记录 retained/error_code，下一次该Run恢复重查；身份不明或变化保留人工核对，绝不以文件名猜测所有权。创建与身份记录之间的进程崩溃可能留下allocated且无身份文件，也保留待查。所有保留均关联有限请求预算内的具体意图，不遍历删除其它Run/未知文件；永久权限故障或身份异常需要操作人员处理，不宣称自动零残留。当前无全局清理后台任务。

## 检查

项目专用 Python，真实Worker+SQLite+文件，来源使用合成 HTTP transport：

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q --basetemp .runtime/pytest-t2-local-v2 --junitxml docs/verification/T2-local-v2-tests.xml
```

**105 passed in 36.82s，0 skipped / failures / errors。** 保留原91项并增加14项：长停机原Run修复、执行段到时、字节到达后到时、长停机+冷却到期原Run修复、累计额度不重置且给操作指引、三种缺图修复/去除、只增缺图、重复巡检与坏图清理、提交后清理前崩溃、替换文件身份和旧epoch保护、活动journal保留、发布IO后租约失效不删除temp。原DB提交失败测试同时确认temp保留。原件hash、历史manifest和三个latest指针有明确断言。

001–006 SHA256 与v1证据一致，仅新增007；pip check、离线wheel构建及7迁移打包检查、git diff --check通过。wheel为 `.runtime/wheels-t2-local-v2/fashion_scout-0.2.0a1-py3-none-any.whl`，SHA256 `11c52f33bf10fdaae84746cdfa42128bc667775c27232228d51d3bc311782a4a`，未发布。当前文件hash、测试统计、保留原始实站结果hash和进程检查见 T2-local-v2-evidence.json。

## 仍未完成

本轮0实站请求。原始Run f097800bb3344468b174059282955973 仍无真实有效图片；旧status/Retry-After/peer未存，未知等待限制不猜期限。保守累计仍3次，原授权最多剩37次且受2详情/12图/64MiB共同约束。真实源字段/CDN/有效图归档门槛仍缺，不能正式submit。本次不创建定时器、不push/PR/发布、不进入T3，不更改真实数据根或限流记录。
