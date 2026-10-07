# T2 browser bridge：local-ready，实站阶段尚未放行

2026-10-07，原 Core Worker local/01a11078-dc20-7383-b1dc-54c9e37d5ce5；同 p2-collection/t2-futario-media。按 manager-t2-browser-implementation-scope-20261007.md 实现。仅合成观察／图片与本机 API，没有新来源导航、HTTP、下载、CUA、安装、提交或发布。正式 T2 submit=0。

## 已实现行为

- browser/source adapter 与限额冻结于明确接受 Run；原 HTTP 不转换。旧空值字段请求指纹、客户端 spec/body/hash、旧响应和 v1 ZIP 快照保持原语义。显式新参数内部指纹／客户端 spec 标 2；同键不同参数 409。
- 固定认证入口持久化 listing/detail/finish。Worker 判断资格后发 ticket，才允许选图和上传；服务不接收任意路径或来源成功状态。native 工具目录内 manifest／普通只读稳定句柄校核 ID/URL/大小/SHA，API 接收字节流，Worker 复用 Pillow 和原 Archive journals/fencing。
- 空闲来源安全落为 interrupted/SOURCE_HOST_REQUIRED；旧会话关闭、epoch 提升，等待不耗 R1 处理时间，独立 ZIP／维护继续。browser-continue 原 Run，新 Attempt 保留 completed；客户端 resume 只恢复不确定原意图。完整接收回执可在 native 文件已消失后查询。
- 6 枚举/5 入库保持 partial，missing=1。browser.gallery、product.images/变体/日期/原始分辨率未知分别展示；页面图库齐全仍不把完整商品图集未知报成功，也不覆盖原最新完整指针。browser／混合历史使用 v2，旧 v1 不变，全部历史独有 SHA 打包。
- Repository Skill 自动组织当前支持 CUA DOM/pageAssets → 固定客户端 → Worker；用户不手抄链接、存图或导入 JSON。A03 已按“采集时保持 Codex 运行即可”修改，收到的工作可独立继续。

## 验证原件与结果

| 实际运行 | 结果 | 证据 |
|---|---|---|
| core/media/client/api/exports/maintenance + browser，排除 process | 249 passed / 1 failed / 1 skipped，76.69s；失败仅维护旧 schema==9 断言 | T2-browser-local-tests.xml |
| 修正该断言，定向维护用例 + 全 browser | 19 passed / 1 skipped，37.87s，0 fail | T2-browser-targeted-tests.xml |
| 旧 Windows launcher/kill/fencing/client 回执进程检查 | 8 passed，28.70s，0 skip/fail | T2-browser-legacy-process-tests.xml |
| Manager 独立全 browser（独立根，不能当 Core 根） | 18 passed / 1 skipped，35.22s | .team/fashion-scout/manager-t2-browser-local-review-1.json |

跳过项是 Windows 账户不能创建合成 symlink；普通路径边界、根外文件、重复 manifest ID、URL/SHA/大小拒绝与实际 Windows只读句柄均另有通过检查。锁定 Starlette/httpx 弃用 warning 未更换依赖。语法编译、app.js node --check、git diff --check 通过。未为了文档重复全套。

Core 独立进程原件 `.runtime/t2-browser-process-ce68190c9ef7/evidence.json`：真实 Web 与独立 Worker、固定 CLI，合成数据通过正常 API 入库，无源数据 SQL 种子；上传收到完整服务响应后客户端退出 73，删除 native 文件，resume 原意图从服务确认；等待前台时该 Worker 完成 v2 收藏 ZIP；继续同一 Run，保留一份资产／journal／一次 work attempt。另一首次 Core 根 `.runtime/t2-browser-process-58f4c9d4d89f`。测试进程已正常停止。

Archive 的真实 stage 与 commit 后故障测试、流中断与同键重发、旧会话拒绝、取消、资格排除、坏图／像素／累计限额，以及 v1 冻结包原键重放／显式重试字节不变、混合历史全部 SHA 均通过。所有来源和图片明确为合成，不能据此算实站有效资产。

保护证据 `.runtime/t2-browser-implementation-20261007-01/protection.json`：001–009 和 HEAD 不变，旧 .runtime/t2-live-smoke 四个文件 SHA 均不变、原 schema1–6保留，预览56117和默认根未使用。只使用隔离显式根。T6c 自身 scripts/release 改动单独归属，不是 Core 改动。原 gitignore 的 exports/ 同时忽略源代码与测试目录，因此303文件基线不覆盖这些旧文件；本次精确允许的 exports五文件＋engine 与 tests/exports/test_jobs.py 纳入当前完整 SHA 冻结，不把该基线说成全部仓库历史证明。

## 固定复查／真实阶段命令流程

先配置隔离数据根和空闲本机端口，使用项目固定解释器 `E:\github-workspace\fashion-scout-harness\.venv\Scripts\python.exe -m fashion_scout.client`，每步 `request COMMAND --data-root ROOT --json-input FILE`；configure 独立执行。工具生成受控 JSON，路径／Run／session／ticket 来自真实前步回执。

1. ensure → start（new_intent:true；overrides.source_mode:browser，显式冻结 browser 限额）→ browser-attach。
2. browser-observe listing → browser-status 等资格 → 许可内 detail 观察 → browser-observe detail → browser-status 等 tickets。
3. 当前 CUA 新 inventory 精确匹配所有图库 URL → 许可内 pageAssets bundle → 工具目录／manifest 校核 → browser-upload → browser-status 等 archived。
4. browser-observe finish → progress；open 供真实页面展示，再 user-state 收藏、export／export-status。回执不确定先 intents／resume；来源等待前台则 browser-continue 原 Run，随后新 attach。

DTO 示例及公开工具操作约束见 skills/fashion-scout/references/browser-acquisition.md 和 commands.md；服务 API prefix 固定，模型不传 method/base URL/header/key。64 MiB 是接受／存储边界，浏览器背景资源数／字节／peer unknown，不能称硬网络限额。

下一阶段仍待 Manager 以同任务放行：新隔离 schema10＋安装候选、明确 browser Run，最多一次新正常 listing、一次已核对商品 detail、剩余11次选中图片导出，六张当前可观察图库（若仍存在）、64 MiB 接受/存储、25 MiB单图、50 MP、前台≤15分钟。保留此前12顶层／选中操作，不用诊断旧图冒充新 Run 采集。停止警告／挑战／结构异常／限额，不自动重复。实站链路和最终冻结 wheel／安装包仍未验收。
