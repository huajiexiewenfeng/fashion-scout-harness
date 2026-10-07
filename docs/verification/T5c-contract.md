# T5c-local-v1 维护、备份、恢复与存储契约（实现前设计）

只在新`.runtime/t5c-*`合成根验证。用户预览根`.runtime/t5b-browser-user-preview-01`及端口56117保持不动，真实来源与T6门槛不变。

## 持久任务

维护状态queued→running→succeeded/partial/failed；一个Worker只运行一个维护任务，独立心跳，owner/epoch检查，确认原进程死亡后恢复原任务。请求键和动作payload先持久保存，原键同payload复用，冲突409。GET不创建任务、不修复素材、不访问来源。verify接收all或非空selected商品ID，创建事务冻结已存版本、引用资产、根映射与未知范围；运行只读检查存在、字节、SHA256、实际图像及前后身份。问题缺失/损坏/未知分列，任务结果保留历史；当前问题表按对象+code去重更新核验时间，不无限追加常驻issue。不改收藏/已看/分类或原资产证据。

## 一致备份

backup请求仅接受destination_id=local，固定输出本data_root/backups，页面说明这是本机副本，不能抵御同盘损坏。任务接受时冻结操作与目的地，业务数据范围在Worker首次成功SQLite backup API副本处冻结；这允许等待期间新增业务进入同一一致时间点，不混用接收时的旧资产清单和稍后的DB。副本落盘并验证后保留供同任务恢复，从它读取全部正式assets、历史版本/用户状态与根映射。DB副本是事实源，实时库后续变化不改变本包。全部引用素材实际复制、解码和hash校验，缺失/损坏/枚举未知说明写入清单；不把不完整包报成功。

备份暂存至受控私有目录，清单包含格式版本、任务ID、一致DB摘要和字节、根/素材关系、文件清单、问题与完整性。关闭后重开校验，再以Windows同卷不覆盖rename原子发布。发布后DB回执失败可核验复用同目录；磁盘/权限错误报失败，kill恢复同任务。备份不包括control凭据、Cookie、bootstrap、运行日志、临时下载、缓存及现有导出ZIP。上限：1000商品、10000资产、单素材64MiB、素材总量4GiB、DB512MiB、元数据64MiB；超出有明确失败，不无限处理。

## 固定离线恢复

固定入口接收明确源data_root、备份ID及本机目标目录，默认仅全新或空目标；非空/已有DB拒绝。先验证清单、DB完整性/外键、范围对应与全部被备份文件的hash，再向隔离暂存根恢复并发布到目标，不启动任何服务或发起Run。partial默认拒绝；只有显式allow_partial才保留缺失问题并报告partial恢复，绝不冒称完整。

恢复把每个storage_root映射至新根media/roots/<确定性根键>，保持root_id/资产相对路径/版本关系/用户状态。原库、原素材和备份不修改。写入恢复审计保存原运行状态、旧新根映射和包摘要；旧worker身份失效，活动Run转cancelled并记录RESTORED_HELD、旧export输出失效且待显式retry，维护未完成任务不自动接管。历史export的资产根映射更新到恢复根，原快照不重选，下载不指向旧输出。来源冷却与历史请求/预算证据保留，不能藉恢复清除限流。恢复状态独立于历史业务结果。

## 单一存储配置

migration009新增专属storage_preferences单行revision/media_root及维护表扩展，001–008不改。DB一旦有配置就是唯一权威，app.json不双写；旧文件仅在首次明确配置或首次归档时作为兼容默认。GET无写入，未初始化时revision0。PATCH严格expected_revision CAS，只影响将来归档；旧root_id与文件不移动、不删除。路径必须是本机绝对非根目录，拒绝UNC、设备、网络盘、父级穿越、reparse/junction、应用控制/备份目录；验证可写与剩余空间。活动Run/维护或未完成归档journal时返回busy409。

Paths的当前根读取刷新DB权威配置，Archive实例冻结本次选择；长期Worker不会永远使用启动时缓存路径。切换检查与写入同事务，后来的Run只在切换提交后选择新根，活动journal不会半程换根。旧已完成Run手动retry需沿用其已有journal根：在config/Archive/Worker的窄根选择处处理，不改Run幂等/租约/hash语义。若实现中发现需要修改受保护共享业务模块，先提出具体最小需求。

## API、客户端及页面

POST maintenance/verify、maintenance/backup，GET maintenance/{id}与settings/storage，PATCH settings/storage；沿用现有认证/CSRF/Host/Origin与严格DTO。新增固定verify/backup/maintenance-status/storage/set-storage命令；原maintenance空输入作为只读能力说明保持安全。write journal先存意图，丢回执原键POST；存储CAS未知回执只读核对不盲写。折叠“更多信息”容纳手动核验、本机备份、位置输入和集中摘要；主导航不变。页面刷新只查询，不自动核验/备份/retry。离线恢复不增加页面向导。

此文档先冻结实现选择，后续实际证据和限制另记T5c.md。未实测部分不预先声明通过。
