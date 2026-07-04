# 2026-07-04 真实钉钉 dispatch smoke

## 目的

验证本地 `config/config.yaml` 中的钉钉 webhook 与加签配置可以完成真实 Markdown 消息发送。此 smoke 只验证通道可用性，不分发真实 tracking alert，不修改告警状态，不包含买卖建议。

## 执行方式

- 发送器：`utils.dingtalk_notifier.DingTalkNotifier`
- 方法：`send_markdown(title, content)`
- 消息标题：`Codex Tracking Agent DingTalk Smoke`
- 消息内容：本地 smoke 范围、时间、无真实告警分发、无买卖建议说明
- 敏感信息：未记录 webhook URL、access token 或 secret

## 结果

- 发送结果：`True`
- 关键输出：`[OK] 钉钉通知发送成功`
- 该 smoke 未调用 `TrackingAlertService.dispatch_pending_alerts()`，因此没有把任何 pending alert 标记为 `dispatched`。

## 后续

如果要验证 Tracking Alert 的真实分发闭环，应新增一个专门任务：构造或选择一条低风险 pending alert，注入真实 notifier adapter，执行 `dispatch_pending_alerts(slot=...)`，并记录 alert_id、slot、ui_status 变化。该任务会改变告警状态，不应混入默认回归。
