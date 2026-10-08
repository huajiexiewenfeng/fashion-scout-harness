# T9 列表刷新性能交付（已落地）

2026-10-08 上海时间，原 Worker 已将验证过的包升级到正在使用的 **E:/github-workspace/FashionScout**，端口仍8765。完整性、Skill Open及固定Request均通过；待原 Manager 正式验收。main/HEAD保持ade9d9af8a1ef84c466e57b207a20c6c1b788651，无commit/push/worktree。

列表改为当前版本的轻量封面投影：批量读元数据，每款只选择一个可用封面，已由Archive解码的图片每请求重查SHA、大小和格式/尺寸头；旧UNKNOWN元数据仅对封面完整验证。没有跨请求缓存，因此相同大小、恢复mtime的损坏也会被重新拒绝；无效封面可回落下一张。新款仍拒绝空图/非图片，收藏缺图保留。列表保留用户/分类/来源/更新提示与冻结分页，images最多一张；完整图集、当前缺失和历史只由product详情读取，协议与个人Skill已同步。

刷新保留旧卡片、滚动和已展开的40+20范围，成功后按新的同一cursor链替换；相同请求防重，旧筛选结果不能覆盖新请求，失败保留旧结果和可重试控件。未修改采集、归档承诺、用户状态或基础依赖。

| 同一真实库只读测量 | 旧安装（Manager） | 当前实际安装（Worker） |
|---|---:|---:|
| 首屏40款 | 6.278秒 | 0.041468秒 |
| 下一页20款 | 2.4446秒 | 0.016037秒 |
| 刷新40款 | 6.6897秒 | 0.034691–0.046389秒 |

首屏完整图像解码0次；只检查60款封面，下一页只检查20张。冷样本是新Presentation实例，未清空操作系统文件缓存；无长期结果缓存。PowerShell Skill启动/包核验/请求整进程约1秒，原5秒服务读取超时消失。Skill new/next/refresh得到40+20/60唯一ID，收藏4；product正常独立读取13图、14历史版本。

实际验证：**37 Python + 17 UI + 9既有精确候选包检查全部通过**，diff-check/安装完整性退出0。坏封面、hash匹配但非图片、相同size/mtime损坏、UNKNOWN旧资产、非封面损坏详情、收藏/排除/分类/已看和分页契约均覆盖。保留首轮Skill输入目录拒绝记录，之后使用绑定data/requests的受支持路径成功，未放宽校验。原生Manager另确认实际Chrome首屏40→下一页60唯一→刷新保留60，busy=false、无错误、可见封面全部加载，六核心表hash与其基线相同；其独立截图/基准路径列在证据JSON中。

升级前确认无活动Run/归档/导出/维护，以原包Stop核验自有进程退出。完整备份10,556文件/289,529,231字节并逐项SHA核对，恢复副本数据库相同；旧.local保留。manifest资源原地替换后正常Prepare/Open，同一data位置，49表原行及3,268旧数据文件保留。当前库**80商品记录、60可见、432资产、收藏4、排除20、6历史Run、635图集版本、4,887版本图片引用**保持，无新巡检/来源HTTP。运行UUID按正常Stop/Open由8595ed14-2465-40a8-9062-7a312d155237变为99579f08-976c-469f-8885-8f41b6593d88；旧control身份文件和备份保留。未执行生产运行环境回滚，不把恢复副本校验称为运行回滚演练。

精确交付：8项代码/协议/测试SHA清单版本 **eecc58e593eef80d7559ade583a08ac45ec189b3f06008b9ab0d1f0f777d6e8a**；wheel **231a9e5380fbc961865d1bc84f3351ae804319ee26c8298531e257e8e6b3c731**；ZIP **07be069a153241e7de577a43e1d239d5e1782cc201fb21797fd1ceaa7c75d9e0**；manifest **960a275997339dbb8241569fcc1ee70ef9d611e6589910976ccc0cec797970af**。冻结74源码资源逐字节对应wheel，26依赖与CPython pin保持；个人Skill7资源和原位置binding对应该manifest。

证据：[T9-evidence.json](T9-evidence.json)，SHA9873a9c5655ca324009f8f245cf39944b3c4c236a30dcf59d5123b56240c86c6；基准T9-installed-benchmark.json；入口T9-live-verification.json；测试T9-targeted-tests-2.txt/xml、T9-ui-tests.txt、T9-candidate-verify.txt；完整步骤T9-upgrade.py及各阶段日志。候选与冻结在 .runtime/t8b-t9f；完整备份/恢复副本/旧环境在 .runtime/t9-upgrade-v1，均保留。保护基线429原tracked文件，无任务外修改，001–010迁移和原采集实现不变。
