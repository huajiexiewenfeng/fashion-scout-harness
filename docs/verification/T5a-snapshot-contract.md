# T5a ExportSnapshot 内部契约 v1

范围：纯离线“冻结快照 → 校验 ZIP”库；输入由未来 T5b 持久任务层提供。引擎不读收藏实时状态、不读写业务 DB、不请求来源、不管理队列/lease/取消/业务重试，不暴露 HTTP 或 Skill 命令。

入口：`fashion_scout.exports.ExportSnapshot.capture(json_object)` 深复制并校验，得到深层不可变对象。`export_zip(snapshot, roots, output_dir, limits=Limits()) → ExportResult`。`verify_zip(path, snapshot, limits) → manifest` 重新打开包核对，失败抛内部 `ExportError(code)`。

## 快照字段

全部 DTO 拒绝未知字段和隐式类型转换。容器为 tuple；任意来源 JSON 使用 canonical JSON 字符串保存，避免 frozen 模型中仍残留可修改的嵌套 dict/list。`capture` 接受 JSON 可序列化 dict 或现有快照，经序列化/重新验证隔离调用者后续修改。来源 JSON 必须为无重复键、有限数值的对象。

| 对象 | 字段与约束 |
|---|---|
| ExportSnapshot | schema_version=1、export_id、captured_at、promised_scope=`product.images`、products、assets；商品非空，ID唯一 |
| Product | product_id、source_json（商品原字段）、date_basis_json（来源/原始日期、判断依据、首次发现等，由调用方冻结）、latest_available/latest_observed（VersionKey 或 null）、versions、capability_notes |
| VersionKey | version_id + 正整数 revision；必须指向本商品快照内版本 |
| Version | VersionKey + images、enumeration_complete、expected_count、enumeration_reason；完整枚举 expected_count 必须等于冻结关系数；未知枚举 expected_count 必须 null 且有原因 |
| ImageRef | source_image_id、source_url、ordinal、asset_id或null、missing_reason、variant_ids；每版本 source_image_id 与 ordinal 各自唯一 |
| Asset | asset_id、root_id、relative_path、sha256、bytes、format=PNG/JPEG/WEBP/GIF；必须覆盖且仅覆盖所有版本引用的已存资产；ID全局唯一 |
| Capability | scope、status=unknown/unsupported/supported、reason；仅范围外说明，禁止将 product.images 缺失挪入能力说明 |

latest_available 必须至少有一个已存资产引用；这只是冻结时的可用指针，本次导出仍重新验证文件。latest_observed 可以与它不同。无最新观察记录的收藏款可保留，完整性为未知，不能报成功完整。

T2 适配说明：调用方可以从只读 `catalog.product_detail` 的版本/资产关系制定冻结过程，但 T5a 不提供该适配器或执行实时查询。T2 原 manifest 在枚举不完整时可能仍保存已发现数量；T5b 映射时须将它归一为 `expected_count=null` 并保留未知原因，不能拿已发现/已存数当应有总数。所有历史版本中的非空 asset_id 必须纳入快照，不能只取当前预览图集。快照一致性事务和收藏选择归 T5b。

根映射为调用方提供的 `{root_id: 已受控绝对Path}`，不进快照；引擎复制映射。资产只经逻辑 root_id + POSIX 相对路径解析；不接受绝对路径、盘符/ADS、反斜杠、`..`、设备名、尾点空格或任何 symlink/junction/reparse 越界。来源标题/URL始终仅作为数据，不生成路径。

## 顺序、关系与完整性

商品按快照顺序得到 `product-序号-商品ID摘要/`。同商品先遍历最新可用版本（按 ordinal），再遍历其余版本（version_id/revision/ordinal 稳定顺序）。按实际通过校验的 SHA 去重；文件名为序号+完整SHA+受控格式后缀，保留所有通过校验资产的 asset_ids 和版本/来源/variant关系。跨商品仍各自出图，不承诺物理去重。

每款 `product.json` 保留原字段、时间依据、版本指针、全部历史关系/资产元数据、required coverage、能力说明；`missing.json` 分列 missing 与 unknown。坏掉的重复内容资产仍列缺失，即使同SHA另一个资产可读，也不能伪称那个冻结资产已核验。历史版本中从未存下的关系仅保留历史记录；历史**已存资产**全部必需。最新已观察版本的未归档图片关系必需，旧预览可用不能豁免。

`missing_count` 计本商品失败冻结资产＋最新未归档关系，失败资产不再按版本重复计数；同资产跨不同商品各自属于必需范围。`unknown_count` 计最新枚举未知或没有最新观察manifest的商品。unknown 不捏造图片缺失张数。当前可读关系数按来源关系计，与去重后文件数分别保存。

- 没有必需缺失/未知且包核验一致：succeeded，文案“承诺范围内完整”。
- 有必需缺失/未知但能生成核验一致的 ZIP：partial，仍保留无图商品元数据。
- 无法产生有效包、输出资源门槛不满足、核验失败或持续变化：failed，path/sha256/bytes为空。
- 范围外视频等能力说明不增加 missing/unknown，不把图集完整商品永久降为partial。

## 实际文件检查与资源上界

逐资产流式复制到本次拥有的临时目录，默认1 MiB块；前后核对路径、文件身份、长度和时间，实际计算 SHA/bytes 与快照比对。对暂存图使用现有 Pillow verify + reopen/load，仅单图解码，不改尺寸/编码；格式、动画、像素门槛不符拒绝。Windows path stat/fstat 的 ctime 语义可能不同，身份比较使用显式 birthtime，句柄前后另比 change time。最终核对再次从原路径流式算摘要，不能用旧 verified_at 证明现在有效。

ZIP 构建与重开核验后，再核对每个源文件；变化则从计划剔除并记录 SOURCE_CHANGED，最多重建一次。第二遍仍有新变化则 SOURCE_UNSTABLE，零发布。边界是最后核对时的状态；无法承诺发布后外部程序永远不再修改来源。

默认上界：1000商品、10000资产、100000关系、快照JSON16 MiB；单资产64 MiB、全局资产/跨商品输出预算4 GiB、单图50MP、包元数据64 MiB、成员12000、空闲磁盘保底64 MiB。提前为暂存资产、最多两份ZIP及元数据预留空间。Limits 可由受控调用方调整，不是来自来源文字的配置。所有图片不会同时装进内存；暂存总量/ZIP由上述预算约束。

## ZIP 清单和发布/复用

包根 `manifest.json` 含精确快照/摘要、状态/覆盖、资产验证结果、所有数据文件和 manifest.csv 的 path、asset_ids、sha256、bytes、product_id、version_ids、source_urls、relations。CSV列出所有图片/商品信息/缺失文件，UTF-8 BOM；所有文本单元格前置单引号，避免来源值成为表格公式，原始值完整保留在JSON。

索引不能给自己写递归SHA：manifest.csv 不列自身或manifest.json，manifest.json 列CSV但不列自身。manifest.json自身字节由返回的完整 ZIP SHA256覆盖；T5b 应把此摘要持久保存。每个图片/元数据/CSV字节均在关闭后重开核对，成员集合精确一致；大小写重复、额外文件、非法成员路径、加密/非预期压缩、symlink成员或哈希/清单差异均拒绝。

输出名固定 `export-SHA256(export_id).zip`。临时 ZIP 关闭、fsync、重新核验后，通过同卷硬链接原子创建最终名称；目的存在则不覆盖。使用 NTFS 等支持同卷硬链接的文件系统，不支持则明确失败，未实现其它文件系统回退。临时内容只有本次创建且身份未换的普通文件可删除，不递归清理、不碰别人的文件；不明/被替换的临时内容保留。

已存在输出只有在快照摘要/完整内容相同且包重新核验通过时复用；输出状态是原构建回执，不表示当前源文件仍可读，不因当前收藏或版本变化重选。相同 export_id 但不同快照、损坏输出均失败并保留原文件。重新构建同冻结快照的后续业务 retry 可由 T5b 分配独立的受控 attempt 输出目录，快照/export_id不变；本引擎不覆写旧partial包、不创造新业务任务或重新采集。

该库不防御同Windows用户的恶意进程持续篡改自身工作目录，不提供签名或持久完成回执；T5b仍需负责权限、任务状态、导出文件可用性与持久摘要核对。进程崩溃的临时目录恢复/清理也留给未来受控维护，不由本次函数猜测所有权。
