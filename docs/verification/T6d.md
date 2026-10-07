# T6d：冻结浏览器采集版本机候选包 v1

2026-10-07（Asia/Shanghai），`p6d-browser-distribution / t6d-browser-final-bundle`，待Manager独立验收。T2/browser最低真实范围和T6c-R1工具已批准；本轮只交付冻结本机包，不再次采集或推定全站/批量稳定性。

ZIP：`E:\github-workspace\fashion-scout-harness\.runtime\t6c-final-browser-v1\FashionScout-0.2.0a1-browser-v1-app-5938b20f707c73ebc0042d115abdd7e04d3bf62dd9799362be595afa52393753.zip`，**35,692,990 bytes**。

ZIP SHA256：`283f97f86dab387f05eaa48a2f6c93c7def5bda54765d85b42cf4013a225c925`

Manifest：`.runtime\t6c-final-browser-v1\FashionScout\manifest.json`，SHA256 `f22a985d019b0efd2710d82c0f49b3dd3aa3e80be75e0ba03954519e9d0817b3`；原字节副本见[T6d-manifest-v1.json](T6d-manifest-v1.json)。用户主说明为[delivery.zh-CN.md](../delivery.zh-CN.md)；包内README及PACKAGE-CONTEXT提供解压/启动/对话定位，不需要用户手工JSON或认证材料。

## 冻结输入与构建

唯一应用输入是原stage `.runtime/t2-browser-live-20261007-01/wheel/fashion_scout-0.2.0a1-py3-none-any.whl`，SHA256 `5938b20f707c73ebc0042d115abdd7e04d3bf62dd9799362be595afa52393753`。source实际层级为同stage的`source/src`；[本輪输入证据](T6d-input-evidence-v1.json)核对原build-provenance.json的72生产成员、10迁移、source/pyproject/锁摘要及wheel。没有从当前源码重新造wheel。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\release\build_bundle.py --output .runtime\t6c-final-browser-v1 --app-wheel .runtime\t2-browser-live-20261007-01\wheel\fashion_scout-0.2.0a1-py3-none-any.whl --app-sha256 5938b20f707c73ebc0042d115abdd7e04d3bf62dd9799362be595afa52393753 --source-root .runtime\t2-browser-live-20261007-01\source\src --label browser-v1
```

[原始构建日志](T6d-build-v1.txt)，exit0；完整离线使用既有CPython3.13.16 archive及26锁定依赖，未启用download、不改pin/锁/版本。包118个manifest输入文件，manifest自身另计；无data、.local、真实商品/素材、日志、cookies或token。

Manager同任务补充授权后，只对builder新增四份现有Skill原字节复制与复制前后SHA复核，纳入manifest.skill_files。相对结构保持`skills/fashion-scout/SKILL.md`及references的setup/commands/browser-acquisition.md；四份原件未改，未全局安装。包内PACKAGE-CONTEXT明确实际虚拟环境是`.local/env/Scripts/python.exe`，每次固定客户端显式`--data-root <包根/data>`；不能沿历史Skill中的仓库.venv或LOCALAPPDATA默认配置误接旧库。

## 实际独立解压与离线安装

独立解压根：`E:\github-workspace\fashion-scout-harness\.runtime\t6c-d-smoke-18206465\FashionScout`，84个UTF-16字符。实际运行ZIP内三个CMD，未在构建目录启动；[原始安装/运行输出](T6d-smoke-v1.txt)及[完整记录](T6d-smoke-evidence-v1.json)可复核。

- Prepare普通wheel离线安装成功，Python3.13.16/SQLite3.53.1，26锁定依赖pip check无缺失，安装应用72文件逐字节与唯一wheel及原provenance一致。准备后没有业务DB或服务descriptor。
- Open与Stop成功，32固定命令包含六个browser命令；只读browser-status对不存在Run真实返回RUN_NOT_FOUND/404/exit4，说明入口已识别且没有创建任务。6个browser表为空，Run/Run意图/来源HTTP计数全0，实际迁移1–10完整。
- 14份运行时导入记录中业务模块来自本解压包的安装目录，没有editable finder、开发src或项目.venv依赖路径。真实Web/Worker入口与身份可核对；最终OS浏览器动作由测试副本钩子截取，没有重复真实浏览器渲染。
- 单独重开同自有根做[本机HTTP检查](T6d-http-evidence-v1.json)：一次性认证交换、首页200、未认证读取401，9个静态资源与安装文件逐字节一致。只请求本机loopback，测试钩子拒绝非loopback DNS/connect，记录无来源尝试。
- 两次操作均协作停止这一根并核对真实Web/Worker退出，forced_roles为空；HTTP收尾再读DB仍Run0/Run意图0/来源0。55016实际演示和56117预览及其数据/服务均未访问或停止。

验证命令分别为`python -B -X utf8 docs/verification/T6d-smoke.py`与`T6d-http-check.py`，仅本轮交付冒烟，未改测试逻辑、重跑既有应用套件或再次真实采集。测试hook仅存在于独立解压副本，交付ZIP不含hook。

## 使用与真实能力边界

普通用户完整解压后01准备、02打开、03停止；在Codex引用PACKAGE-CONTEXT，让它按随包Skill手动开始浏览器巡检。采集期间保持Codex运行及浏览器连接；中断后同Run明确继续。已完整接收的文件校验归档、导出和维护可由独立Worker继续。不会宣称脱离Codex自动采集。

先前真实验证只有20条listing metadata、1个detail、6张WEBP、收藏及schema2 ZIP，结果partial。日期、变体、完整product.images和原像素未知；本轮没有把真实数据加入包，也没有验证批量稳定性、全站能力、真正新电脑、系统重启/休眠/物理断电或人工省时。

## 文件边界与交接

[T6d-evidence-v1.json](T6d-evidence-v1.json)核对本轮366既有文件基线：仅允许的builder、README模板和delivery说明3项变化，363项保持原SHA；README当前交付小节另有允许更新，新增PACKAGE-CONTEXT模板和T6d文档/证据。原src72、Skill四原件、旧代码/测试/证据、locks/runtimepin/pyproject不改。旧T6b包、stage及其全部原件保留。

没有源码另造wheel、来源请求、下载、新依赖、全局安装、业务架构/测试逻辑改动、Agent/新聊天/定时器、commit/push或外部发布。Stage输入与包制品的摘要完整记录，原Worker submit/E03真实回执在团队worker-t6d-report.md。是否接受本轮本机候选交付由Manager独立决定。
