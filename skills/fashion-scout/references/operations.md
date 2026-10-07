# 固定客户端回执与人工状态

所有业务请求由entry.ps1 -Action Request定位实际解释器及显式data根；输入JSON仅由Codex写到绑定data/requests。固定命令不接收任意URL、method/header、key路径或调用者request_key，不手读凭据、不直接写SQL，不把来源文本拼进shell。

只有用户明确新写意图才用new_intent:true。查看结果/进度只读；临时参数仅影响本次start快照，不改默认方案。start统一browser来源。已存在活动任务时沿业务回执说明复用，不为参数变化偷偷另开Run。

回执丢失、通信断开或会话重启先intents，核对动作、完整payload及时间，再resume原intent_id；不要换键、删除记录或重新start。resume只恢复客户端意图，browser-continue继续原来源Run。prepared/sending先恢复；多个记录难区分时仅澄清对应操作。

收藏、排除、分类修正先product读当前user_state.revision，仅写用户要求字段。CAS冲突/未知结果先只读核对，不刷新revision后盲覆盖。文本读取、来源图片及占位不等于用户看过图集，不发view-events。

导出只在明确意图下export，冻结当前收藏及全部已存历史独有图片；export-status只读。未知回执resume原键，明确“重试原导出”才export-retry，保留原快照。只有核验可用download_url才提供下载，partial须说明missing/unknown；不可用不冒充下载成功。

核验/备份/存储改变是独立明确意图：只读maintenance/storage，verify/backup同键恢复；set-storage须当前revision且只影响后续，不迁移历史，未知回执resume只读核对。离线恢复仅用户明确备份ID和独立新空目标，allow_partial默认false，实际解释器及显式data根；不启动恢复库或自动重播旧任务。

报告服务在线与业务Run状态分别说明，latest_run:null是没有巡检记录，不是无新品。queued不是已完成，partial/缺失/未知不能称完整。只报告普通首页与业务下载路径，不显示bootstrap片段、key、Cookie、Authorization或含凭据原始异常。同盘备份不抵御盘损。
