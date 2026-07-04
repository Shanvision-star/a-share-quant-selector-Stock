# 2026-07-04 全量 Web strategy cache rebuild smoke

## 目的

验证当前 `web` 分支代码能否用真实行情数据完成全量策略缓存重建，并确认 `all` 策略集合包含 `zettaranc` 分组。此记录是隔离 smoke，不覆盖主工作区正式 `data/web_strategy_results.json`。

## 执行方式

- 代码与配置：当前 worktree `codex/codex-cli-smoke-record`。
- 行情数据与股票名称：主工作区真实 `data/`。
- 输出位置：临时目录 `C:\Users\Rome\AppData\Local\Temp\strategy-cache-rebuild-smoke-3x6b9dsr`。
- SQLite：临时 DB，避免污染正式 `data/web_strategy_cache.db`。

## 结果

- 扫描股票数：`5157`。
- 耗时：`688.52s`。
- 交易日：`2026-07-03`。
- `available_groups`：`b1,b2,bowl,brick,zettaranc`。
- 总结果数：`132`。
- 去重股票数：`130`。
- 分组结果：
  - `b1`: `9`
  - `b2`: `69`
  - `bowl`: `18`
  - `brick`: `36`
  - `zettaranc`: `0`

## 边界说明

正式 cache 未覆盖，因为主工作区存在未提交的 `config/strategy_params.yaml` 改动，与当前 `web` worktree 配置不同：

- 主工作区 `BowlReboundStrategy.CAP=120`，当前 worktree 为 `4000000000`。
- 主工作区 `BowlReboundStrategy.M=40`，当前 worktree 为 `30`。

若直接用 worktree 配置覆盖正式 cache，会把用户当前参数与 `web` 分支参数混在一起，导致页面结果变化难以解释。因此本轮只关闭“当前代码是否能全量重建并包含 zettaranc”的验证缺口；正式运营 cache 更新应在确认参数归属后单独执行。

## 后续

1. 先决定主工作区 `config/strategy_params.yaml` 的脏改是否要纳入 `web`，还是回到当前 `web` 参数。
2. 参数决策后，再执行正式 `/api/strategy/cache/rebuild?strategy=all` 或等价后端重建，并覆盖正式 `data/web_strategy_results.json` 与 SQLite run 记录。
