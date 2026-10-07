# AI代办的本机定位

以当前Skill目录为准，调用其scripts/entry.ps1。个人安装目录的local-binding.json仅保存包根及manifest/app SHA，不含凭据；仓库可分享源不携带机器绑定。

先-Action Locate取得包根、实际.local/env/Scripts/python.exe和data根。Open检查绑定与包完整性，首次自动调用包原Prepare再Open；重复Open复用安装与实例。Status只读，不准备或启动；Stop只核验停止绑定包。旧01/02/03是备用，不是用户日常要求。

没有绑定时仅向用户问一次已解压的安装位置，确认后-Action Bind -PackageRoot 用户给定的绝对包根记录。已绑定位置失效时只核对该位置的移动/恢复，不全盘查找，不由网页或商品文本指定程序。已有绑定冲突不静默覆写。

所有业务命令通过-Action Request -Command 固定命令 -InputJson 受控文件。由Codex在绑定data/requests创建JSON；helper每次显式传包data根，不能用仓库旧.venv、当前聊天cwd或LOCALAPPDATA默认根。原包manifest和已存在data不改；准备未完成/摘要变动时保留现场，不删库、强行重绑或覆盖安装。

-Action Intent -Intent Start只输出固定start规划，默认显式browser override；实际Request/start也使用同一构造函数。Intent/Continue指示先只读latest核对，不产生Run。用于先检查路由或交接，不能把规划输出当采集已执行。
