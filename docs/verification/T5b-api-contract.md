# T5b-local-v1：收藏导出契约

此版本连接 T5a 离线 ZIP 引擎与本机 SQLite、独立 Worker、认证页面和固定客户端。只验收隔离合成素材；不代表来源采集或整产品验收。

## HTTP

沿用已有 Host、Origin、Bearer/页面 session 与 CSRF 边界，严格拒绝额外字段。JSON 回执沿用 `request_id` 等现有统一封装。

| 请求 | 输入/结果 |
|---|---|
| `POST /v1/exports` | `{request_key,selection:"favorites"}`；新接受202，同键同payload200且`reused:true`；空收藏422零任务，键冲突409 |
| `GET /v1/exports/{id}` | `{export:{id,state,created_at,finished_at,attempt,resumed_at,worker_state,counts:{products,assets},missing_count,unknown_count,issues,download_url,sha256}}` |
| `POST /v1/exports/{id}/retry` | `{request_key}`；终态原任务/原快照新增attempt，新接受202；原键重放200，不新增attempt；活动任务409 |
| `GET /v1/exports/{id}/download` | 认证ZIP流；未就绪409，不存在任务404，丢包/摘要/快照/成员/路径校验失败410；不接受文件路径参数 |

`state`为queued/running/succeeded/partial/failed。`counts`是冻结的商品/资产数量，不是实时逐文件百分比。`worker_state`独立报告真实进程和心跳。partial有有效ZIP时可以下载，但必须说明缺失和未知；succeeded也只承诺快照内product.images范围。范围外视频说明不降低图片覆盖。ready需持久终态、结果/快照一致、完整ZIP及摘要通过；状态查询也会重验包，失败隐藏链接并附EXPORT_UNAVAILABLE。下载返回已核验的同一打开句柄，Content-Length和安全文件名固定，不能下载任意本机文件。

## 冻结与幂等

migration008只扩展预留导出表和新增导出专属attempt/request表，001–007保持不变。创建时在一个短BEGIN IMMEDIATE事务内冻结收藏商品、全部版本/历史资产关系、最新观察和可用版本指针、来源字段/日期依据、人工分类/收藏revision、资产路径/摘要/字节/格式及根映射。事务不读素材字节或打ZIP。后续取消收藏或版本指针变动不改变范围；无图款保留元数据，枚举未知保持expected_count=null。

export_requests保存键、动作payload摘要和任务映射；create和retry共用键空间。并发同键只建一个job/attempt。业务retry保留export_id和snapshot，写入独立`exports/<32hex-id>/attempt-00000N`目录，不重新采集或按当前收藏重选。旧attempt结果仍在，只有当前attempt提供下载。没有by-key查询端点，未知结果以原键原payload安全重放相应POST。

## 后台执行与恢复

既有Worker只增加一条串行导出lane，与采集lane并行且并发数固定；导出不会创建Run或调用来源。每个活动导出有独立心跳线程，默认3秒更新、30秒lease。持久owner/epoch/attempt在领取、心跳、文件处理检查点和完成事务中核对。时间流逝本身不允许抢占仍活或身份未知的进程；确认原进程死亡后CAS恢复同一attempt。正常停止在协作检查点释放，启动器之后恢复已接受任务。

复制、源文件复核、ZIP写入/校验及发布前都有协作检查点。ZIP发布后DB写入失败，保留原attempt；重启核验现包后复用，不覆盖已发布包。旧epoch无法完成新执行权。原子无覆盖发布、图像和成员校验、清理边界继承T5a。崩溃残留临时目录暂保留，未实现维护清扫。

## 页面与客户端

收藏页增加一个主按钮、简短任务状态及就绪下载。先将非秘密完整请求payload写入localStorage，再POST；丢回执保留原键，显式再次点击核对。活动期间禁用重复点击。打开/刷新只GET上次任务，不自动POST/retry；高级“重试原导出”位于折叠详情。空收藏禁用；Worker离线与业务结果分开提示。

客户端固定命令：`export {new_intent:true}`、`export-status {export_id}`、`export-retry {new_intent:true,export_id}`。沿用已验收持久意图journal和intents/resume。查询不创建任务，模型不用手读token或业务SQL；下载交认证页面。Skill未全局安装。maintenance/storage/backup仍501或FEATURE_UNAVAILABLE，留待T5c。

## 保留限制

每次ready状态读取会复核整包，较大ZIP可能有明显磁盘开销；目前只展示阶段与冻结数量。localStorage只记最近导出，不是完整历史任务列表。固定本机用户可以修改自己的数据库/文件，摘要用于完整性而非抵御同用户恶意管理行为。正常停止仍可能等待当前有界图像解码或最终摘要，启动器超时会诚实报未停止。未验证整个Codex退出、休眠、断电与真实来源素材；这些保留给T2/T6。
