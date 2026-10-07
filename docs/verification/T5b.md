# T5b-local-v1：持久收藏导出与页面、对话入口

2026-10-06。round `p5b-local-export-flow` / task `t5b-durable-export-flow`。原Worker UI实现，待Manager独立验收。仅本机合成素材链路；T2真实来源、T5c维护、T6整体验收仍未完成。

## 交付行为

收藏页明确点击“导出收藏”后，服务在一致事务冻结当时的商品、全部已存历史图片和版本/来源关系，持久保存ExportJob及Attempt，再由独立Worker后台打包。用户可以离开或刷新页面；只读查询不会新建任务。partial允许下载且明确显示缺失/未知；空收藏友好禁用。新款/收藏/图集原交互保留，高级原快照重试放入折叠详情。

新增export专属migration008、capture/jobs/runner、导出路由、页面意图模块，以及客户端export/export-status/export-retry。既有Worker增加一条固定串行导出lane及独立心跳，不改变采集Run lease逻辑、不启动来源Run。T5a引擎仅增加可选协作检查点；原默认调用保持兼容。旧owner/epoch拒绝完成，确认死亡才恢复，停止后仍是同任务/同attempt。ZIP已发布但DB回执缺失时核验复用。显式retry保留原快照、增加独立attempt目录，不重新采集或重选收藏。

创建、重试、CLI journal和页面localStorage均使用先保存的非秘密幂等键。未知回执同键同payload恢复，不换键。就绪链接必须通过持久结果、快照、完整包成员和SHA256核验；未就绪409，丢失/篡改410，不能传任意路径。接口细节见 `T5b-api-contract.md`。

## 实测结果

- 最终Python回归 **163 passed，0 skipped，57.99s**，`T5b-tests-final.txt`。包含core/Worker、API、T4客户端与真实HTTP回归、T5a引擎、8项持久层测试、5项真实导出进程测试。仅既有Starlette/httpx弃用警告，未改依赖。
- 前端Node回归 **21 passed，0 failed**，`T5b-ui-tests-v1.txt`。包含原15项UI/意图检查及6项导出意图故障检查。
- 独立过程补测 **5 passed，16.87s**，`T5b-process-tests-v1.txt`；持久层补测 **8 passed，2.38s**，`T5b-jobs-tests-v1.txt`。
- 旧schema7升级保留商品/收藏revision，新库8迁移通过。首次总回归有两处旧测试固定迁移数7失败，只有对应断言改为8；定向2项通过，随后最终163项全通过。原始失败日志`T5b-tests-v1.txt`与修正日志`T5b-migration-fix-v1.txt`均保留。
- Skill Creator quick_validate实际通过，`T5b-skill-validation-v1.txt`。复用T4隔离工具目录，不安装项目或全局依赖；作者检查意图分流，不冒称独立Agent行为测试。
- wheel `.runtime/t5b-wheel/fashion_scout-0.2.0a1-py3-none-any.whl`，SHA256 `75ec0e0845bea729845db4270e2ba4492b83b3d92f459499459d67d9a48848f5`。构建日志`T5b-wheel-v1.txt`；证据脚本逐一比对包内全部生产文件及8份迁移。

真实过程测试使用独立`.runtime/t5b-*`、真实SQLite/素材文件/Worker/Web/HTTP/客户端子进程。只在测试helper暂停实际复制首个源数据块之后或原子发布之后，没有生产“假成功”开关。执行中graceful/kill恢复同一个job和attempt；旧epoch无法完成；发布后kill重启复用原ZIP。额外关闭Web时，暂停复制的Worker继续独立心跳，释放后正常完成。launcher父进程及CLI结束后后台任务继续；CLI收到真实HTTP回执后os._exit(73)，新客户端进程resume仍只有一个job、两个明确重试attempt。每个测试均验证来源请求0并停止本次服务。

并发相同创建、键冲突、冻结后取消收藏/改变指针、最新缺图保留旧图片、空收藏、原快照重试、损坏包/丢包/非法路径、认证/Origin/严格字段均覆盖。原T5a56项图像/文件变化/历史范围/Windows junction/输出失败回归继续通过。junction测试只增加finally清理它自己创建的链接，避免新pytest清理残留；没有清扫旧临时目录。

## 真实浏览器证据

隔离根 `.runtime/t5b-browser-v1`，8件明确合成商品、1个预置终态fixture Run。页面先显示空收藏且禁用导出；通过实际爱心操作收藏1件有图和1件缺图款，再点击一次导出。测试停止本根已核验身份的闲置Worker以观察排队，刷新页面后job/attempt仍各1；ensure恢复执行，得到partial：2款、2资产、缺失2、未知0。整个过程来源请求0，没有新巡检Run。

实际点击认证下载链接得到25591字节ZIP，SHA256 `2847cac526d884f4698166911175a4f972606e679fe93447c8b1e58a4bccb62f`，与DB记录一致。独立保存浏览器下载副本`T5b-browser-download.zip`，重开ZIP检查CRC和清单。证据`T5b-browser-evidence-v1.json`记录job ID与下载路径。浏览器警告/错误日志为空。

截图：`T5b-browser-empty.png`、`T5b-browser-queued.png`、`T5b-browser-partial-desktop.png`、`T5b-browser-partial-mobile.png`。测试视口1440×1000和390×844；实际文档clientWidth与scrollWidth分别同为1425、375，无横向溢出。截图像素由浏览器返回的实际渲染区域决定，未加工。测试tab已关闭、视口已reset、Web/Worker已正常停止；不留预览服务。排队测试短时顶部既有巡检心跳状态仍在线，而导出区域已按真实进程死亡显示离线；旧巡检区最多按原30秒心跳判定刷新，未改该已验收逻辑。

## 文件与保护边界

`T5b-baseline.json`包含开始时141个既有文件。17项预期变化：导出必要生产接线/Skill、迁移数与501更新的最小回归测试、T4集成输出改至本轮独立根、junction自清理、构建生成的egg-info SOURCES。其余 **124份保护文件哈希不变**，包括001–007、domain、services、media/adapters、health/launcher、依赖锁、原T3/T4/T5a验收证据和两个T5a样例ZIP。完整清单与本轮文件哈希见`T5b-evidence-v1.json`。

T4集成测试本次写`.runtime/t5b-t4-regression-*/integration-evidence.json`，不再覆盖旧T4-local-integration.json。`T5b-process-evidence-v1.json`保存最终各场景原始独立证据路径/hash/内容；所有T5b已启动服务身份只读审计均无存活角色。未访问`.runtime/t2-live-smoke`、用户默认根、Futario/CDN或改限流记录，无临时子Agent、全局安装、定时器、commit/push/PR/发布。

## 复现命令

工作目录 `E:\github-workspace\fashion-scout-harness`，固定项目解释器；每次测试使用新的隔离basetemp，证据输出选新版本名，避免覆盖已验收记录。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core tests/api tests/client tests/exports tests/integration/test_export_flow.py -q --basetemp .runtime/t5b-regression-final
node --test tests/ui/intent.test.mjs tests/ui/state-transitions.test.mjs tests/exports/export-intent.test.mjs
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --no-build-isolation -w .runtime/t5b-wheel
.\.venv\Scripts\python.exe -m tests.exports.verify_t5b_delivery
```

最后一条仅生成首份不可覆盖交付证据，重复执行会拒绝已有输出；独立复核可按其只读检查逻辑核对，不要覆盖旧证据。浏览器helper只接受仓库`.runtime/t5b-browser-*`明确根，普通生产入口无该测试选项。

## 未完成项

T2真实有效素材门槛、T5c维护/备份/存储迁移、T6休眠/断电/完整Codex退出等仍待验收。现阶段没有导出历史列表、取消导出、逐文件百分比；完成包状态查询会复核整包，较大包有磁盘成本。崩溃残留临时目录保留待后续所有权清理。技能未全局启用。本报告是Worker交付证据，不是自我验收。
