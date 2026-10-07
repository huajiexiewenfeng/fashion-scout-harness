# T2 独立诊断正文取证修正：六类本地检查通过

依据Manager同任务body-evidence-repair范围及随后暂缓/取消原路GET的指令。原T2仍blocked，本阶段未正式submit；生产实现没有改动。

旧第7次18字节错误正文没有原文文件或stdout，诊断进程已结束，不能恢复。原result与SHA保留不变，不回填错误解释或从候选哈希猜测。新副本修复取证流程：无论普通文字、code、HTML或二进制，先将最多16KiB原始字节独占写入新的gitignored runtime目录，flush/fsync后设只读；然后记录SHA、长度、type、encoding及脱敏短文本。报告对实际token/password/Bearer/邮箱/IP/URL字段脱敏；普通短公开文本不因未匹配某个code格式被丢弃。原始私有文件不复制到公开docs。HTML只静态解析，不执行或跟随。

六类合成检查通过：普通429文本、标准error code、敏感字段、HTML、二进制、超过16KiB。每个案例断言原始文件精确等于输入的允许前缀，SHA匹配；敏感样例原文仅保留runtime，报告中指定假凭据和邮箱均去除；HTML脚本内容不展示；二进制仍有原始文件；超过上限正好保存16KiB并标注截断。全部是假数据，不重构第7次原文。

实际命令：

```powershell
.\.venv\Scripts\python.exe -B .runtime/t2-body-repair-20261007-01/verify-capture.py
```

此阶段来源请求0、没有在途来源请求。新diagnostic副本的命令入口只输出deferred，不调用network main；执行验证过返回source_requests=0。原路可选第8次GET已被Manager的新代理对照范围取代，不执行两项请求。

验证时账目7/40余33，原合成记录保存该当时值；随后Manager保守记Chrome ERR_BLOCKED_BY_CLIENT文档导航为第8次、现在8/40余32，不能将它写成来源HTTP429。Manager已有浏览器DOM证实Futario首页商品可见，New In tab实际Shop域，尚无普通浏览器的原JSON成功正文。下一项代理诊断单独记录预算和事实。

文件：

- `.runtime/t2-body-repair-20261007-01/capture.py` SHA256 a570f6244849a6f6e07c713024db447000fac2c9f081ccbca9a658f41f175764。
- 同目录`diagnostic.py` SHA256 16d5e4afbc844ca8cfc2f94d68c8ad76b0e53ffe98bd0615c9dd96291a910f47，当前network main不启用。
- `T2-body-repair-20261007-synthetic.json`与runtime合成证据相同，SHA256 6e623f84774c1507ed360a872a832c4b6cc15a4da7d4eb024cadb51b6abacf58。
- runtime的synthetic各子目录存假输入原始response-body.bin，不公开复制。

没有修改production、已应用迁移、锁、旧真实库/hold/Run、默认根或56117预览；T6b并行打包Worker的授权新文件/README变更不属于本Worker写入。后续生产诊断扩展仍需Manager独立决定，不将这六类本地验证冒充真实源图归档验收。
