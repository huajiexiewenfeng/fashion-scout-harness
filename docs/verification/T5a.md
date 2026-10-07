# T5a-local-v1：冻结收藏 ZIP 打包引擎

2026-10-06。p5a-export-engine / t5a-frozen-zip-engine，Worker UI交付，待Manager独立验收。只实现无网络的冻结快照打包库；不完成T5，不接公开API/页面/客户端/Skill/生产Worker/DB。

新增 `src/fashion_scout/exports/{models,manifest,engine,__init__}.py`，测试与合成样例脚本在 `tests/exports/`。内部契约见 [T5a-snapshot-contract.md](T5a-snapshot-contract.md)。已验收的其它代码、锁文件和历史验证报告保持只读。

实现覆盖：严格深层不可变快照；所有历史已存资产关系保留；最新可用图片在前、历史独有在后；同商品按本次实际校验SHA去重并保留多来源/版本；最新观察缺图/未知枚举不被旧图回退掩盖；无图收藏保留元数据；范围外媒体仅说明能力。源文件流式校验+暂存，Pillow单图校验解码，打包后重新核验成员/清单/哈希，最后重读来源摘要检查变化，有界重建后原子无覆盖发布。输出写失败/核验失败不提供成功路径，源文件不变更。

## 实际验证

命令：`.venv\Scripts\python.exe -m pytest tests/exports -q`。

**56 passed，0 skipped，3.08s**，原始输出 [T5a-tests-v1.txt](T5a-tests-v1.txt)。没有重跑会覆盖T4报告的集成用例，也没有启动服务或访问来源。全部资产为pytest临时根/`.runtime/t5a-*`下实际生成的小PNG。

测试包括：

- 最新+历史独有、多URL/多版本关系/同SHA资产去重，以及跨商品各自保留图片。
- 无图商品、最新观察缺图+旧预览共存、未知expected_count=null；范围外video unsupported不降级。
- 文件缺失、hash/bytes不符、快照同hash的无效图片、错误格式、不可读、像素/体积上限。
- 真实文件读取中改写、同字节/相同mtime文件替换、打包期间改变引发剔除重建、连续变化失败。
- Windows stat/fstat时间语义实测后修正身份比较；最终内容重读不依赖旧核验时间。
- 穿越、盘符/ADS、UNC、设备名、尾点空格、反斜杠、NUL字符拒绝；实际Windows junction指向根外被拒绝。当前宿主不具备创建symlink的权限，使用无需改权限的真实junction验证Windows reparse路径，不把模拟检查冒充实际symlink测试。
- ZIP成员重复、大小写冲突、额外文件、内容/manifest篡改、symlink成员标记拒绝。
- 输出写失败、核验失败、原子发布失败/竞争不覆盖；现有同快照包重校验复用、不同快照同ID冲突、损坏包不覆盖；同快照独立attempt结果字节确定性相同。
- 原始嵌套输入/关系列表变动不污染捕获后的快照；JSON中文/来源原字段保留，CSV文本安全；成员集合、所有记录SHA/bytes与实际ZIP逐一一致。

首轮发现并修复Windows身份时间比较误判。引擎使用现有标准库/Pydantic/Pillow，未增依赖或改锁。没有claim全量跨平台/超大数据压力验收、掉电持久性或T5b任务可靠性。

## 真实 ZIP 合成样例

生成命令 `.venv\Scripts\python.exe -m tests.exports.make_samples`；每次使用新时间戳与随机后缀，保留既有证据。样例描述 [T5a-samples-20261006T132431Z-14e5a9c5.json](T5a-samples-20261006T132431Z-14e5a9c5.json)。来源全部为 `example.invalid` 字符串，网络请求为0，未使用Futario/CDN数据。

| 样例 | 结果 | 文件/完整性 |
|---|---|---|
| [承诺范围完整合成 ZIP](T5a-samples/20261006T132431Z-14e5a9c5/complete/export-795cb5c6824609cfc574b105e01aacdcc4d1380f3423183a0f4c649b7e67fcfb.zip) | succeeded | 1商品、3个去重图片文件、7成员、12710 bytes；missing0/unknown0；包含视频范围外说明 |
| [部分缺失合成 ZIP](T5a-samples/20261006T132431Z-14e5a9c5/partial/export-41d2069f0cffd300ac7cada9edd952548dfcf9ac5cd84e5cea4297b6ab60e901.zip) | partial | 2商品、2图片文件、8成员、14174 bytes；最新缺图1+历史损坏资产1、无图商品观察未知1 |

完整包 SHA256 `150951efc9dd66b9db3942d024f449f627ae3953067e805dd4a20473740b0813`；partial包 SHA256 `62c9e471002092bcaf81cee73bcf347f8557962179a33ab50af90f259d7a83bf`。旁附两个冻结快照 JSON，可用 `verify_zip` 独立重新检查。

`T5a-baseline.json` 记录任务开始时其它源代码/Skill/脚本/历史证据的哈希；`T5a-evidence-v1.json` 记录保护检查、本轮源/测试/文档/样例哈希与成员校验结果。样例输出通过函数的无覆盖发布生成，不依赖手工拼ZIP。

## 未完成边界

T5b仍需实现一致性事务捕获收藏、持久ExportJob/Attempt、request_key、lease/取消/retry、API/下载/页面一键入口、维护/备份与其故障恢复。T2真实Futario有效素材门槛与T6整链路仍等待。库内复用描述原包状态，不宣称源文件现在仍完整；未来持久层应保存并核对返回ZIP摘要。

未触碰 `.runtime/t2-live-smoke`、限流记录或用户默认根；未启动生产Worker、发送站点/CDN请求、建定时器、创建子Agent、全局安装、commit/push/PR/发布。本地合成ZIP成功仅证明T5a局部引擎，不能解除后续真实素材/持久任务验收门槛。
