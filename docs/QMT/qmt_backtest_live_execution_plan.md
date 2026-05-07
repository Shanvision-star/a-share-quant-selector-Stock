# QMT 预留与 20 万资金实盘执行计划

日期：2026-05-07

目标：在现有日线选股系统基础上，建设可回测、可模拟、可人工确认、并可在未来预留接入 QMT / miniQMT 的低成本量化执行链路。

## 零、当前资金与券商权限结论

用户已向银河证券确认：银河 QMT 量化权限约需 300 万额度；当前计划资金约 20 万。因此本项目当前不把银河 QMT 自动交易作为主线能力，避免把开发押在无法开通的券商权限上。

当前主线：

1. 本地日线策略选股。
2. 本地回测引擎验证。
3. 盘中 1 分钟线二次确认。
4. 生成 `OrderIntent` 下单意图。
5. `paper` 模拟盘或 `confirm_manual` 人工确认。
6. 用户在券商客户端手动下单。
7. 日终导入成交记录，做复盘和参数校验。

QMT 定位：

- 只做预留接口，不作为当前 20 万资金阶段的必要依赖。
- `QmtBrokerAdapter` 可以保留空实现、只读实现或文档接口，但默认不开启。
- 未来资金规模或券商权限满足后，再从 `readonly` 只读模式开始，不直接进入自动下单。

## 一、项目约束

| 项目 | 约束 |
| --- | --- |
| 券商账户 | 银河证券 QMT 量化权限按 300 万门槛预留；当前 20 万资金不依赖 QMT |
| 交易接口 | 当前不绑定券商接口；未来若 QMT / miniQMT 权限可用，再以本机 `xtdata`、`xttrader`、账户权限和客户端版本为准 |
| 资金规模 | 当前按 20 万现金的小资金执行方案设计，默认小仓位、低频率、强风控 |
| 策略来源 | 现有 B1、B2、碗底、砖型图日线选股结果 |
| 买入触发 | 日线选股后，盘中接入分时线/盘口做二次确认 |
| LLM 使用 | 不进入实时交易循环，只用于总结、复盘、文档和参数解释 |
| 实盘开关 | 默认模拟/人工确认，不默认自动实盘 |
| 风控底线 | 单票仓位、单日买入金额、最大持仓数、停牌/涨跌停/ST 禁买必须硬编码兜底 |

## 二、QMT 与 miniQMT 的项目定位

| 项目 | QMT | miniQMT | 本项目建议 |
| --- | --- | --- | --- |
| 形态 | 完整量化终端 | 轻量客户端/API 通道 | 当前只预留适配层，不作为主线依赖 |
| 项目依赖 | 可用作终端和接口 | 更适合作为外部 Python 程序的交易通道 | 策略、回测、风控留在本项目 |
| 主要接口 | 迅投体系接口 | `xtdata` 行情 + `xttrader` 交易 | 统一封装为 `QmtBrokerAdapter` |
| 回测 | 可能自带平台能力 | 通常不作为本项目回测核心 | 回测引擎自研，QMT 只做真实行情/交易 |
| 适合 20 万资金 | 银河当前门槛不匹配 | 取决于具体券商权限 | 当前不接实盘下单，只保留接口 |

结论：代码里不要写死完整 QMT，也不要写死 miniQMT。当前统一保留 `QmtBrokerAdapter` 接口，但项目主线先实现 `SimBrokerAdapter`、人工确认和成交复盘。只有未来本机可以通过 `xtquant` 访问行情和交易，且券商权限满足时，才启用同一套适配层。

## 三、总体架构

```text
日线数据更新
  -> 策略选股缓存
  -> 标准 Signal
  -> 分时买点监控
  -> OrderIntent 下单意图
  -> SimBroker / ManualBroker
  -> 人工成交导入与持仓同步
  -> 回测/模拟/实盘统一报告
```

核心原则：

- 策略只产生 `Signal`，不直接下单。
- 分时模块把 `Signal` 转成 `OrderIntent`。
- 风控模块决定 `OrderIntent` 是否允许进入模拟盘或人工确认。
- `QmtBrokerAdapter` 仅做预留，未来只负责调用 QMT / miniQMT，不写策略判断。
- 回测、模拟盘、实盘尽量复用同一套买卖规则。

## 四、核心对象

| 对象 | 字段 | 说明 |
| --- | --- | --- |
| `Signal` | `code, signal_date, strategy, score, reason, metadata` | 日线策略输出，不代表一定买入 |
| `MinuteBar` | `code, datetime, open, high, low, close, volume, amount` | 分时买入确认数据 |
| `OrderIntent` | `code, side, target_amount, limit_price, reason, risk_tags` | 经过分时规则和风控后的下单意图，还不是券商委托 |
| `Order` | `order_id, code, side, price, volume, status` | 模拟券商、人工流水或未来 QMT 返回的委托 |
| `Trade` | `trade_id, order_id, code, price, volume, fee, time` | 成交回报 |
| `Position` | `code, volume, available, cost_price, market_value` | 持仓状态 |

## 五、分阶段计划表

| 阶段 | 目标 | 具体任务 | 产物 | 验证标准 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| P0 | 固化接口边界 | 定义 `Signal`、`OrderIntent`、`BrokerAdapter`、`DataPortal` 数据结构 | `trading/models.py` | 单元测试验证字段、日期、金额精度 | 最高 |
| P1 | 回测引擎拆分 | 从现有 `backtest_service.py` 拆出数据、撮合、组合、分析四层 | `backtest_engine/` 包 | 2026-04-24 人工池案例仍返回 4 笔交易 | 最高 |
| P2 | 日线组合回测 | 支持现金、持仓、最大持仓数、等权买入、逐日权益曲线 | `portfolio.py`、`analyzer.py` | 输出逐日权益、回撤、胜率、盈亏比 | 最高 |
| P3 | A 股撮合规则 | 加入 T+1、100 股整数手、涨跌停、停牌、ST 禁买 | `execution.py` | 涨停不可买、跌停不可卖、非整手自动修正 | 最高 |
| P4 | 分时数据模型 | 增加 1 分钟线读取、缓存和回放能力 | `minute_data_portal.py` | 指定代码/日期能读取完整分钟线 | 高 |
| P5 | 分时买点确认 | 在日线候选上叠加 VWAP、分时均线、量能、回撤过滤 | `intraday_entry.py` | 同一候选能输出买/不买原因 | 高 |
| P6 | 模拟券商 | 实现 `SimBrokerAdapter`，模拟委托/成交/撤单 | `broker_sim.py` | 不连券商也能完整跑模拟盘 | 高 |
| P7 | 人工确认执行 | 前端/控制台展示 `OrderIntent`，用户手动下单 | `execution_mode=confirm_manual` | 每笔意图必须人工确认 | 高 |
| P8 | 成交流水导入 | 手动录入或 CSV 导入实际成交，和 `OrderIntent` 关联 | `trade_journal.py` | 每笔成交可追溯到信号和意图 | 高 |
| P9 | QMT 只读预留 | 保留 QMT / miniQMT 只读适配结构，不作为当前必需项 | `broker_qmt.py` | 默认 disabled，不影响主流程 | 中 |
| P10 | QMT 真实接入 | 未来满足资金和权限后读取资产、持仓、行情、委托状态 | `execution_mode=readonly` | 只读模式不下单，能打印账户快照 | 低 |
| P11 | 自动交易评估 | 资金和权限满足后，再评估 `auto` 模式 | `execution_mode=auto` | 触发硬风控时拒单并记录原因 | 低 |

## 六、推荐目录结构

```text
web/backend/services/
  backtest_engine/
    data_portal.py
    signal_source.py
    execution.py
    portfolio.py
    analyzer.py
  trading/
    models.py
    risk.py
    intraday_entry.py
    broker_base.py
    broker_sim.py
    broker_manual.py
    broker_qmt.py
    trade_journal.py
```

## 七、券商适配器设计

### 统一接口

```python
class BrokerAdapter:
    def connect(self) -> None:
        ...

    def get_account(self) -> dict:
        ...

    def get_positions(self) -> list[dict]:
        ...

    def place_order(self, intent: OrderIntent) -> dict:
        ...

    def cancel_order(self, order_id: str) -> dict:
        ...

    def sync_orders(self) -> list[dict]:
        ...

    def sync_trades(self) -> list[dict]:
        ...
```

### 当前 20 万资金阶段实现原则

- `broker_sim.py`：用于模拟委托、成交、撤单，是当前主线。
- `broker_manual.py`：用于记录人工确认和手动成交，是当前可落地实盘闭环。
- `broker_qmt.py`：只保留接口或只读占位，不在当前资金阶段启用真实下单。
- `OrderIntent` 是系统输出的最高自动化边界；超过这个边界必须由用户确认或导入实际成交。

### QMT 预留原则

- `broker_qmt.py` 未来只负责把统一对象翻译成 QMT / miniQMT 调用，不写策略判断。
- QMT 连接参数、账户 ID、客户端路径写入本地配置，不提交真实账户信息。
- QMT 权限满足前，配置必须保持 `enabled: false`。
- 未来启用前先跑 `readonly` 模式，确认账户、持仓、行情、委托查询可用。
- 执行模式必须显式区分：
  - `readonly`：只读，不生成订单。
  - `paper`：生成模拟订单。
  - `confirm_manual`：生成意图，由用户在券商客户端手动下单。
  - `confirm_broker`：未来券商权限满足后，人工确认再调用券商接口。
  - `auto`：未来资金和权限满足后才评估，且硬风控生效。

### 本地配置建议

```yaml
qmt:
  enabled: false
  mode: readonly
  reserved_only: true
  account_id: ""
  client_path: ""
  session_id: 10086
  max_order_amount: 10000
  max_daily_buy_amount: 30000
  max_positions: 5
  allow_auto_trade: false
```

## 八、分时买入规则建议

| 规则 | 默认值 | 作用 |
| --- | --- | --- |
| 开盘冷静期 | 9:35 前不买 | 避免集合竞价和开盘尖峰 |
| 涨停保护 | 距涨停价小于 1% 不追 | 避免无法成交和高位炸板 |
| VWAP 过滤 | 价格站上当日 VWAP | 确认分时资金承接 |
| 分时均线 | 价格站上 5/10 分钟均线 | 避免弱反弹 |
| 量能确认 | 当前 5 分钟成交量高于前均值 | 避免无量假突破 |
| 回撤限制 | 从日内高点回撤超过阈值不买 | 避免冲高回落 |
| 日线风控 | 跌破日线关键线不买 | 保持和回测逻辑一致 |

## 九、低 token 成本方案

实时交易链路不调用大模型。大模型只消费压缩摘要：

```json
{
  "date": "2026-05-07",
  "signals": 154,
  "order_intents": 8,
  "submitted": 3,
  "rejected": 5,
  "top_reject_reasons": ["near_limit_up", "weak_intraday", "position_limit"]
}
```

这样可以让 LLM 只做复盘解释，不读取完整 K 线、分时线、账户流水和长日志。

## 十、实盘安全开关

| 开关 | 默认 | 说明 |
| --- | --- | --- |
| `qmt.enabled` | `false` | 总开关，当前保持关闭 |
| `qmt.mode` | `readonly` | 默认只读 |
| `qmt.reserved_only` | `true` | QMT 仅预留 |
| `qmt.allow_auto_trade` | `false` | 自动交易二次开关 |
| `max_order_amount` | 小额 | 单笔最大买入金额 |
| `max_daily_buy_amount` | 小额 | 单日最大买入金额 |
| `max_positions` | 低数量 | 最大持仓数 |
| `kill_switch` | 可随时触发 | 一键停止下单和撤单 |

## 十一、测试计划

| 测试 | 内容 |
| --- | --- |
| 单元测试 | `Signal`、`OrderIntent`、撮合规则、风控规则 |
| 回归测试 | 2026-04-24 人工池同日信号仍能生成后续交易 |
| 模拟盘测试 | `SimBrokerAdapter` 完整走订单、成交、持仓 |
| 人工确认测试 | `OrderIntent` 能展示、确认、取消，并记录人工成交 |
| QMT 只读测试 | 未来权限满足后读取账户、持仓、委托，不下单 |
| QMT 确认下单测试 | 未来资金和权限满足后才执行，小金额、手动确认、可撤单 |
| 故障测试 | 行情缺失、订单拒绝、重复提交、未来 QMT 断线 |

## 十二、参考资料

- QMT Python API 文档：https://qmt.ptradeapi.com/QMT_Python_API_Doc.html
- QMT 文档 PDF：https://www.glsc.com.cn/qmt/doc/20191024.pdf
- 银河星耀数智 TGW 数据服务：https://pypi.org/project/tgw/

说明：实际交易接口以本机券商客户端、账户权限和券商提供版本为准；当前 20 万资金阶段以模拟盘、人工确认和成交复盘为主，QMT / miniQMT 只定义预留边界。
