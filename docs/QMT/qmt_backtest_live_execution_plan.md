# QMT 回测与实盘量化执行落地计划

日期：2026-05-07

目标：在现有日线选股系统基础上，建设可回测、可模拟、可接入银河证券 QMT / miniQMT 的低成本量化执行链路。

## 一、项目约束

| 项目 | 约束 |
| --- | --- |
| 券商账户 | 银河证券账户，已开通 QMT；如果实际客户端是 miniQMT，只要能使用 `xtquant`，项目适配层保持一致 |
| 交易接口 | 以本机 QMT / miniQMT 的 `xtdata`、`xttrader`、账户权限和客户端版本为准 |
| 资金规模 | 当前按 30 万现金以下的小资金执行方案设计，默认小仓位、低频率、强风控 |
| 策略来源 | 现有 B1、B2、碗底、砖型图日线选股结果 |
| 买入触发 | 日线选股后，盘中接入分时线/盘口做二次确认 |
| LLM 使用 | 不进入实时交易循环，只用于总结、复盘、文档和参数解释 |
| 实盘开关 | 默认只读/模拟，不默认自动实盘 |
| 风控底线 | 单票仓位、单日买入金额、最大持仓数、停牌/涨跌停/ST 禁买必须硬编码兜底 |

## 二、QMT 与 miniQMT 的项目定位

| 项目 | QMT | miniQMT | 本项目建议 |
| --- | --- | --- | --- |
| 形态 | 完整量化终端 | 轻量客户端/API 通道 | 优先兼容 miniQMT，完整 QMT 可复用同一适配层 |
| 项目依赖 | 可用作终端和接口 | 更适合作为外部 Python 程序的交易通道 | 策略、回测、风控留在本项目 |
| 主要接口 | 迅投体系接口 | `xtdata` 行情 + `xttrader` 交易 | 统一封装为 `QmtBrokerAdapter` |
| 回测 | 可能自带平台能力 | 通常不作为本项目回测核心 | 回测引擎自研，QMT 只做真实行情/交易 |
| 适合 30 万以下资金 | 能用但偏重 | 更轻、更容易落地 | 推荐 miniQMT 或 QMT 的轻量 Python 接入模式 |

结论：代码里不要写死完整 QMT，也不要写死 miniQMT。统一称为 `QmtBrokerAdapter`，只要本机可以通过 `xtquant` 访问行情和交易，就接入同一套适配层。

## 三、总体架构

```text
日线数据更新
  -> 策略选股缓存
  -> 标准 Signal
  -> 分时买点监控
  -> OrderIntent 下单意图
  -> SimBroker / QmtBroker
  -> 订单回报与持仓同步
  -> 回测/模拟/实盘统一报告
```

核心原则：

- 策略只产生 `Signal`，不直接下单。
- 分时模块把 `Signal` 转成 `OrderIntent`。
- 风控模块决定 `OrderIntent` 是否允许进入券商适配层。
- `QmtBrokerAdapter` 只负责调用 QMT / miniQMT，不写策略判断。
- 回测、模拟盘、实盘尽量复用同一套买卖规则。

## 四、核心对象

| 对象 | 字段 | 说明 |
| --- | --- | --- |
| `Signal` | `code, signal_date, strategy, score, reason, metadata` | 日线策略输出，不代表一定买入 |
| `MinuteBar` | `code, datetime, open, high, low, close, volume, amount` | 分时买入确认数据 |
| `OrderIntent` | `code, side, target_amount, limit_price, reason, risk_tags` | 经过分时规则和风控后的下单意图，还不是券商委托 |
| `Order` | `order_id, code, side, price, volume, status` | QMT 或模拟券商返回的委托 |
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
| P6 | 模拟券商 | 实现 `SimBrokerAdapter`，模拟 QMT 委托/成交/撤单 | `broker_sim.py` | 不连 QMT 也能完整跑模拟盘 | 高 |
| P7 | QMT 只读接入 | 连接 QMT / miniQMT，读取资产、持仓、行情、委托状态 | `broker_qmt.py` | 只读模式不下单，能打印账户快照 | 高 |
| P8 | QMT 手动确认下单 | 生成订单后前端/控制台确认，再调用 QMT 下单 | `execution_mode=confirm` | 每笔订单必须人工确认 | 中 |
| P9 | QMT 自动小资金 | 打开自动模式，但限制单票金额、日买入金额和持仓数 | `execution_mode=auto` | 触发硬风控时拒单并记录原因 | 中 |
| P10 | 监控与复盘 | 订单、成交、持仓、错误统一入库，生成日报 | `trade_journal` 表和报告页 | 每天可追溯策略到订单到成交 | 中 |

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
    broker_qmt.py
    trade_journal.py
```

## 七、QMT / miniQMT 适配器设计

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

### 实现原则

- `broker_qmt.py` 只负责把统一对象翻译成 QMT / miniQMT 调用，不写策略判断。
- QMT 连接参数、账户 ID、客户端路径写入本地配置，不提交真实账户信息。
- 实盘前先跑 `readonly` 模式，确认账户、持仓、行情、委托查询可用。
- 真实下单必须有 `execution_mode`：
  - `readonly`：只读，不生成订单。
  - `paper`：生成模拟订单。
  - `confirm`：人工确认后下单。
  - `auto`：自动下单，但硬风控生效。

### 本地配置建议

```yaml
qmt:
  enabled: false
  mode: readonly
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
| `qmt.enabled` | `false` | 总开关 |
| `qmt.mode` | `readonly` | 默认只读 |
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
| QMT 只读测试 | 读取银河 QMT / miniQMT 账户、持仓、委托，不下单 |
| QMT 确认下单测试 | 小金额、手动确认、可撤单 |
| 故障测试 | QMT 断线、行情缺失、订单拒绝、重复提交 |

## 十二、参考资料

- QMT Python API 文档：https://qmt.ptradeapi.com/QMT_Python_API_Doc.html
- QMT 文档 PDF：https://www.glsc.com.cn/qmt/doc/20191024.pdf
- 银河星耀数智 TGW 数据服务：https://pypi.org/project/tgw/

说明：实际交易接口以本机银河证券 QMT / miniQMT 客户端、账户权限和券商提供版本为准；本文档只定义项目内的适配边界和落地顺序。
