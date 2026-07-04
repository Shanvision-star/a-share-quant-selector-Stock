# 2026-07-04 Codex CLI 真实 LLM Smoke

## 目标

验证本地 `web` 主线上的 `provider=codex_cli` 可以通过本机/服务器 Codex CLI 生成 Tracking LLM 建议，同时保持默认回归不调用真实 provider。

## 环境

- Branch: `codex/codex-cli-smoke-record`
- Base: local `web` at `8fb78d5 feat: add codex cli llm provider`
- Provider: `codex_cli`
- CLI command: `codex exec`
- Model: `gpt-5.4-mini`
- Safety flags: `--ephemeral --ignore-user-config --ignore-rules --sandbox read-only`
- Date: `2026-07-04`

## Smoke A: Tracking LLM API Path

执行方式：

- 使用 FastAPI `TestClient` 调用 `POST /api/tracking/T-codex-cli-smoke/llm-advice`
- `tracking_service` 与 `tracking_alert_service` 使用本地 stub，避免真实数据库写入
- `TrackingLLMService` 使用真实 `codex_cli` provider
- 未触发钉钉、券商、QMT、数据更新或策略重建

结果摘要：

| 字段 | 结果 |
|---|---|
| HTTP status | `200` |
| success | `True` |
| provider | `codex_cli` |
| provider_fallback | `False` |
| profile | `default` |
| decision | `hold` |
| suggested_action | `HOLD` |
| suggested_intent.side | `HOLD` |
| tracking_id | `T-codex-cli-smoke` |
| latency_seconds | `31.59` |

结论：路由包装、Tracking LLM 服务分派、Codex CLI provider、JSON schema normalize 均完成真实 smoke。

## Smoke B: Direct CLI Usage Capture

执行方式：

- 直接运行 `codex exec --json --output-schema --output-last-message -`
- 使用同一份 Tracking advice schema
- 只记录 usage 摘要，不记录 prompt 原文或完整模型输出

结果摘要：

| 字段 | 结果 |
|---|---|
| returncode | `0` |
| latency_seconds | `49.32` |
| input_tokens | `19954` |
| cached_input_tokens | `2432` |
| output_tokens | `161` |
| reasoning_output_tokens | `83` |
| decision | `hold` |
| suggested_action | `HOLD` |
| cost | CLI 未返回价格，未计算成本 |

## 边界

- 本 smoke 不进入默认 pytest/CI。
- 本 smoke 不证明真实行情、真实钉钉、真实浏览器页面或实际持仓数据已闭环。
- 本 smoke 不改变 `config/llm.yaml`，不提交任何 API key、token、本机账号或真实路径。
- 后续若要用真实 tracking item 调 `/api/tracking/{id}/llm-advice`，需要另行记录目标 tracking_id、provider、model、latency、tokens 与副作用边界。
