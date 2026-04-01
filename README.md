# A-Share Quant Selector

基于 Python + akshare 的A股量化选股系统，实现碗口反弹策略，支持K线图可视化、Web管理界面和钉钉自动通知。源代码作者github项目地址如下：https://github.com/Dzy-HW-XD/a-share-quant-selector

## 📋 TODO 清单

- [ ] **TODO 1**: 尝试大模型的近似能力
- [ ] **TODO 2**: 更新砖型图选股逻辑
- [ ] **TODO 3**: 补充B1、砖型图完美图形库

---

## ✨ 核心功能

- 📈 **碗口反弹策略** - 基于KDJ、趋势线和成交量异动的智能选股
- 🚫 **自动过滤风险股** - 自动跳过 ST/*ST、退市、异常股票
- 🎯 **B1完美图形匹配** - 基于12个历史成功案例的三维相似度匹配排序（双线+量比+形态）
- 🚀 **B1阶段型前瞻扫描** - 基于掌阅科技模板抽象的阶段1-5预警，提前发现潜在启动个股
- 🥣 **智能分类** - 自动将选股结果分类为：回落碗中、靠近多空线、靠近短期趋势线
- 📊 **K线图可视化** - 为每只入选股票生成K线图（含趋势线和成交量），发送到钉钉
- 🔔 **自动通知** - 选股结果和K线图自动推送到钉钉群
- 🌐 **Web管理** - 可视化查看股票数据、K线图、KDJ指标
- 🔄 **智能更新** - 自动判断是否需要更新数据（15点前检查最近已收盘交易日，15点后检查当天数据）
- ⏱️ **智能限流** - 内置钉钉API限流保护，自动退避重试，避免触发频率限制

## 🚀 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/Dzy-HW-XD/a-share-quant-selector.git
cd a-share-quant-selector

# 2. 安装依赖
pip3 install -r requirements.txt

# 3. 配置钉钉通知（可选）
# 编辑 config/config.yaml 填写 webhook 和 secret

# 4. 首次全量抓取数据
python3 main.py init

# 5. 执行选股（自动更新数据、选股、发送钉钉）
python3 main.py run

# 6. 并发选股（加速处理，按机器线程数自动扩展）
python3 main.py run --workers 10

# 7. 快速测试（只处理前500只股票）
python3 main.py run --max-stocks 500

# 7. 启动Web界面
python3 main.py web
```

## 📊 策略说明

### 碗口反弹策略 (BowlReboundStrategy)

#### 选股条件
1. **上升趋势** - 知行短期趋势线 > 知行多空线
2. **异动放量阳线** - 近期(M天内)存在放量阳线（成交量>=前日*N倍，且收盘价>开盘价）
3. **剔除最大阴量** - 回顾期内成交量最大的一天如果是阴线，直接剔除
4. **KDJ低位** - J值 <= 阈值，处于超卖区域

#### 分类标记（优先级从高到低）

| 分类 | 图标 | 条件 | 参数 |
|------|------|------|------|
| **回落碗中** | 🥣 | 价格位于知行短期趋势线和知行多空线之间 | - |
| **靠近多空线** | 📊 | 价格距离知行多空线 ±duokong_pct% | `duokong_pct`: 默认3% |
| **靠近短期趋势线** | 📈 | 价格距离知行短期趋势线 ±short_pct% | `short_pct`: 默认2% |

### B1完美图形匹配 (B1 Pattern Match)

B1完美图形匹配功能基于12个历史成功案例，对选股结果进行三维相似度匹配排序，帮助识别具有相似突破特征的股票。

📖 **[查看详细匹配逻辑 →](B1_PATTERN_MATCH.md)**

#### 案例库（12个历史成功案例）

> 注：下表中的日期为"选股系统选出的买入日期"，不是突破日。

| 案例 | 股票名称 | 代码 | 选出日期 | 特征描述 |
|------|----------|------|----------|----------|
| 案例1 | 华纳药厂 | 688799 | 2025-05-12 | 杯型整理+缩量+J值低位 |
| 案例2 | 宁波韵升 | 600366 | 2025-08-06 | 回落短期趋势线+量能平稳+J值中位 |
| 案例3 | 微芯生物 | 688321 | 2025-06-20 | 平台整理+缩量后放量+J值低位 |
| 案例4 | 方正科技 | 600601 | 2025-07-23 | 靠近多空线+量能平稳+J值中位 |
| 案例5 | 国轩高科 | 002074 | 2025-08-04 | 靠近短期趋势线+量能平稳+J值低位 |
| 案例6 | 野马电池 | 605378 | 2025-08-01 | 持续缩量+J值深度低位+趋势下行 |
| 案例7 | 光电股份 | 600184 | 2025-07-10 | 缩量后放量+J值低位+趋势上行 |
| 案例8 | 新瀚新材 | 301076 | 2025-08-01 | 缩量后放量+价格接近短期趋势线+J值中位 |
| 案例9 | 昂利康 | 002940 | 2025-07-11 | 价格接近短期趋势线+缩量+顶部未放量 |
| 案例10 | 航天发展 | 000547 | 2025-11-12 | 航天军工+量能异动+趋势突破 |
| 案例11 | 澄天伟业 | 300689 | 2025-07-15 | 低位蓄势+双线靠拢+量能修复 |
| 案例12 | 掌阅科技 | 603533 | 2026-02-06 | 阶段型B1 setup窗口，买点确认日为2026-02-09 |

### B1阶段策略（前瞻扫描）

B1阶段策略用于“启动前预警”，不是只做事后复盘。

- 固定模板（603533）用于案例验证：确认6阶段完整结构。
- 动态扫描用于全市场选股：重点筛出阶段1-5成立、阶段6待确认的标的。
- 时间口径全部按交易日计数（不是自然日）。

📖 **[查看阶段策略详解 →](B1_STAGE_STRATEGY.md)**

#### 匹配维度（三维相似度）

| 维度 | 权重 | 说明 |
|------|------|------|
| **双线结构** | 30% | 知行短期趋势线与多空线的相对位置、斜率、发散程度 |
| **量比特征** | 25% | 成交量变化模式（缩量后放量、持续放量等） |
| **价格形态** | 25% | 归一化价格曲线相似度（DTW算法） |
| **KDJ状态** | 20% | J值位置、金叉状态、趋势方向 |

#### 输出结果

匹配结果按相似度从高到低排序，钉钉通知包含：
- 每只股票的相似度百分比
- 匹配的历史案例名称和日期
- 分项得分（双线/量比/形态/KDJ）
- 策略分类、价格、J值等信息

#### 风险过滤说明

**自动剔除的股票类型：**

| 过滤条件 | 说明 |
|----------|------|
| **ST/*ST股票** | 名称以 ST 或 *ST 开头的股票 |
| **退市风险股** | 名称包含"退"、"退市"、"已退"等关键词 |
| **数据异常股** | 成交量为0、收盘价异常、J值均值超过80的股票 |
| **最大量是阴量** | 回顾期内成交量最大的一天是阴线（新增强力过滤）|

> **关于"最大量是阴量"过滤**：
> - 如果在 M 天回顾期内，成交量最大的一天是阴线（收盘价 < 开盘价），则该股票会被直接剔除
> - 这通常意味着大资金在出逃，属于弱势信号，剔除后可提高选股质量

#### 技术指标定义

**知行短期趋势线**
```
EMA(EMA(CLOSE, 10), 10)
```
对收盘价连续做两次10日指数移动平均

**知行多空线**
```
(MA(CLOSE, 14) + MA(CLOSE, 28) + MA(CLOSE, 57) + MA(CLOSE, 114)) / 4
```
四条均线平均值

## 🛠️ 技术栈

- **Python 3.8+** - 核心语言
- **akshare** - A股实时/历史数据获取
- **pandas/numpy** - 数据处理与技术指标计算
- **matplotlib** - K线图生成
- **Flask** - Web管理界面
- **钉钉机器人** - 消息推送

## 📁 项目结构

```
a-share-quant-selector-Stock/  # 项目根目录
├── main.py                  # 🔥 命令行入口（CLI）
├── quant_system.py          # 🧠 核心业务逻辑（数据更新、选股、回溯、B1匹配）
├── README.md                # 📖 项目说明文档（功能介绍、命令用法、策略说明）
├── web_server.py            # 🌐 Web服务模块（Flask实现，支持可视化管理界面）
├── config/                  # ⚙️ 配置文件目录
│   ├── config.yaml          # 系统核心配置（钉钉Webhook/Secret、数据目录、定时调度时间等）
│   └── strategy_params.yaml # 策略参数配置（KDJ阈值、MA周期、形态匹配权重/容差等）
├── strategy/                # 🧠 策略引擎核心目录
│   ├── __init__.py
│   ├── BowlReboundStrategy.py  # 核心业务策略（碗口反弹策略，选股核心逻辑）
│   ├── strategy_registry.py    # 策略注册器（自动扫描加载strategy目录下的策略）
│   ├── pattern_config.py       # B1形态匹配配置（相似度阈值、回看天数、权重分配等）
│   └── pattern_library.py      # B1形态匹配库（12个历史案例管理、三维相似度比对核心）
├── utils/                   # 🛠️ 工具模块目录（全功能支撑）
│   ├── __init__.py
│   ├── akshare_fetcher.py      # 📊 数据抓取模块（akshare封装，全量/增量更新股票数据）
│   ├── csv_manager.py          # 📁 数据存储模块（线程安全的CSV文件读写，股票数据管理）
│   ├── dingtalk_notifier.py    # 🔔 钉钉通知模块（文本/Markdown/图片推送，内置限流保护）
│   ├── tdx_exporter.py         # 📤 通达信导出模块（选股结果转为通达信可导入TXT格式）
│   ├── kline_chart.py          # 📈 K线图生成模块（基础版，含趋势线/多空线/成交量绘制）
│   ├── kline_chart_fast.py     # ⚡ 快速K线图生成模块（优先加载，提升绘图效率）
│   └── backtrack_analyzer.py   # ✅ 回溯筛选模块（KDJ超卖+股价回落幅度二次筛选）
├── data/                    # 📊 数据存储目录（自动生成）
│   ├── stock_names.json        # 🏷️ 股票名称映射缓存（代码→名称键值对）
│   └── [股票代码].csv          # 📈 个股历史数据文件（含K线数据+技术指标，如688799.csv）
├── output/                  # 📤 导出文件目录（自动生成）
│   ├── strategy_BowlRebound.txt # 策略选股结果（通达信格式，碗口反弹策略输出）
│   └── b1_top30.txt            # B1形态匹配结果（TOP30高相似度股票，通达信格式）
└── requirements.txt         # 📦 依赖包清单（Python 3.8+，含akshare、pandas、matplotlib等）
```

## 📝 命令说明（完整）

### 先看这里：按执行步骤操作（不混排）

#### A. Linux/macOS 按步骤执行

| 步骤 | 命令 | 说明 |
|------|------|------|
| 1. 创建并激活虚拟环境 | `python3 -m venv .venv && source .venv/bin/activate` | 首次部署建议执行；已激活可跳过。 |
| 2. 安装依赖 | `pip3 install -r requirements.txt` | 安装项目运行所需 Python 包。 |
| 3. 初始化历史数据（首次） | `python3 main.py init` | 首次全量抓取；已有数据可跳过。 |
| 4. 日常执行主流程 | `python3 main.py run` | 更新数据 + 选股 + 通知。 |
| 5. 日常执行（B1匹配） | `python3 main.py run --b1-match` | 在主流程后追加 B1 完美图形匹配。 |
| 6. 阶段型B1前瞻扫描 | `python3 -u run_b1_scan.py` | 启动前预警扫描，实时显示进度。 |
| 7. 快速验证（小样本） | `python3 main.py run --max-stocks 500 --b1-match` | 小规模验证参数与流程是否正常。 |
| 8. 启动 Web 管理界面 | `python3 main.py web` | 本地查看数据与图形。 |

#### B. Windows 按步骤执行

| 步骤 | 命令 | 说明 |
|------|------|------|
| 1. 创建虚拟环境（首次） | `python -m venv .venv` | 首次部署建议执行；已有可跳过。 |
| 2. 激活虚拟环境 | `.\.venv\Scripts\Activate.ps1` | 激活后再安装和运行。 |
| 3. 安装依赖 | `pip install -r requirements.txt` | 安装项目运行所需 Python 包。 |
| 4. 初始化历史数据（首次） | `.\.venv\Scripts\python.exe .\main.py init` | 首次全量抓取；已有数据可跳过。 |
| 5. 日常执行主流程 | `.\.venv\Scripts\python.exe .\main.py run` | 更新数据 + 选股 + 通知。 |
| 6. 日常执行（B1匹配） | `.\.venv\Scripts\python.exe .\main.py run --b1-match` | 在主流程后追加 B1 完美图形匹配。 |
| 7. 阶段型B1前瞻扫描 | `.\.venv\Scripts\python.exe -u .\run_b1_scan.py` | 启动前预警扫描，实时显示进度。 |
| 8. 快速验证（小样本） | `.\.venv\Scripts\python.exe .\main.py run --max-stocks 500 --b1-match` | 小规模验证参数与流程是否正常。 |
| 9. 启动 Web 管理界面 | `.\.venv\Scripts\python.exe .\main.py web` | 本地查看数据与图形。 |

> 说明：上面是“按步骤”的推荐流程；后面的章节保留“完整参数命令表”，用于进阶调参。

### 一、Linux/macOS 命令

#### 1）主程序命令（main.py）

| 命令 | 说明 |
|------|------|
| `python3 main.py init` | 首次初始化历史数据，写入 `data/` 目录。 |
| `python3 main.py run` | 标准完整流程：更新数据 + 选股 + 通知。 |
| `python3 main.py run --max-stocks 500` | 快速测试，仅处理前 500 只股票。 |
| `python3 main.py run --workers 10` | 并发加速选股，适合多核机器。 |
| `python3 main.py run --category all` | 分类过滤运行：输出全部分类。 |
| `python3 main.py run --category bowl_center` | 分类过滤运行：仅输出回落碗中。 |
| `python3 main.py run --category near_duokong` | 分类过滤运行：仅输出靠近多空线。 |
| `python3 main.py run --category near_short_trend` | 分类过滤运行：仅输出靠近短期趋势线。 |
| `python3 main.py backtest` | 执行默认 3 天回溯扫描。 |
| `python3 main.py backtest --backtest-days 3 --k-threshold 20 --trend-drop-pct 5` | 自定义回溯参数，验证低位 K 值与趋势线回落条件。 |
| `python3 main.py web` | 启动 Web 服务（默认地址与端口）。 |
| `python3 main.py web --host 0.0.0.0 --port 5000` | 自定义 Web 服务监听地址与端口。 |
| `python3 main.py schedule` | 启动内置定时调度循环。 |
| `python3 main.py run --config config/config.yaml` | 指定配置文件运行（测试/生产隔离）。 |
| `python3 main.py --version` | 输出 Python、akshare、pandas、系统版本信息。 |

#### 2）B1完美图形匹配命令（重点）

| 命令 | 说明 |
|------|------|
| `python3 main.py run --b1-match` | 运行基础选股后，追加 B1 完美图形匹配（推荐日常使用）。 |
| `python3 main.py run --b1-match --lookback-days 30` | 指定 B1 匹配回看 30 个交易日。回看天数越大，能覆盖更长整理段，但也可能引入更多非目标形态。 |
| `python3 main.py run --b1-match --min-similarity 70` | 指定最低相似度 70%。相似度按百分比计算（0-100），低于 70% 的结果不展示。 |
| `python3 main.py run --b1-match --lookback-days 30 --min-similarity 70` | 回看 30 个交易日 + 相似度至少 70%，适合实盘中等偏严格筛选。 |

#### 3）阶段型B1前瞻扫描命令（run_b1_scan.py）

| 命令 | 说明 |
|------|------|
| `python3 run_b1_scan.py` | 执行全市场阶段型 B1 前瞻扫描。 |
| `python3 -u run_b1_scan.py` | 无缓冲实时输出，显示进度/速度/ETA/命中/异常。 |

### 二、Windows 命令

#### 1）主程序命令（main.py）

| 命令 | 说明 |
|------|------|
| `.\.venv\Scripts\python.exe .\main.py init` | 首次初始化历史数据，写入 `data/` 目录。 |
| `.\.venv\Scripts\python.exe .\main.py run` | 标准完整流程：更新数据 + 选股 + 通知。 |
| `.\.venv\Scripts\python.exe .\main.py run --max-stocks 500` | 快速测试，仅处理前 500 只股票。 |
| `.\.venv\Scripts\python.exe .\main.py run --workers 10` | 并发加速选股，适合多核机器。 |
| `.\.venv\Scripts\python.exe .\main.py run --category all` | 分类过滤运行：输出全部分类。 |
| `.\.venv\Scripts\python.exe .\main.py run --category bowl_center` | 分类过滤运行：仅输出回落碗中。 |
| `.\.venv\Scripts\python.exe .\main.py run --category near_duokong` | 分类过滤运行：仅输出靠近多空线。 |
| `.\.venv\Scripts\python.exe .\main.py run --category near_short_trend` | 分类过滤运行：仅输出靠近短期趋势线。 |
| `.\.venv\Scripts\python.exe .\main.py backtest` | 执行默认 3 天回溯扫描。 |
| `.\.venv\Scripts\python.exe .\main.py backtest --backtest-days 3 --k-threshold 20 --trend-drop-pct 5` | 自定义回溯参数，验证低位 K 值与趋势线回落条件。 |
| `.\.venv\Scripts\python.exe .\main.py web` | 启动 Web 服务（默认地址与端口）。 |
| `.\.venv\Scripts\python.exe .\main.py web --host 0.0.0.0 --port 5000` | 自定义 Web 服务监听地址与端口。 |
| `.\.venv\Scripts\python.exe .\main.py schedule` | 启动内置定时调度循环。 |
| `.\.venv\Scripts\python.exe .\main.py run --config config/config.yaml` | 指定配置文件运行（测试/生产隔离）。 |
| `.\.venv\Scripts\python.exe .\main.py --version` | 输出 Python、akshare、pandas、系统版本信息。 |

#### 2）B1完美图形匹配命令（重点）

| 命令 | 说明 |
|------|------|
| `.\.venv\Scripts\python.exe .\main.py run --b1-match` | 运行基础选股后，追加 B1 完美图形匹配（推荐日常使用）。 |
| `.\.venv\Scripts\python.exe .\main.py run --b1-match --lookback-days 30` | 指定 B1 匹配回看 30 个交易日。回看天数越大，能覆盖更长整理段，但也可能引入更多非目标形态。 |
| `.\.venv\Scripts\python.exe .\main.py run --b1-match --min-similarity 70` | 指定最低相似度 70%。相似度按百分比计算（0-100），低于 70% 的结果不展示。 |
| `.\.venv\Scripts\python.exe .\main.py run --b1-match --lookback-days 30 --min-similarity 70` | 回看 30 个交易日 + 相似度至少 70%，适合实盘中等偏严格筛选。 |

#### 3）阶段型B1前瞻扫描命令（run_b1_scan.py）

| 命令 | 说明 |
|------|------|
| `.\.venv\Scripts\python.exe .\run_b1_scan.py` | 执行全市场阶段型 B1 前瞻扫描。 |
| `.\.venv\Scripts\python.exe -u .\run_b1_scan.py` | 无缓冲实时输出（推荐），显示进度/速度/ETA/命中/异常。 |

阶段扫描完成后自动执行：
- 推送命中股票到钉钉（代码 + 中文名 + 关键信息 + K 线图）
- 导出通达信 TXT 到 `data/txt/B1-zykj-match/`
- 文件名包含策略名与选股时间，便于回溯

### 三、关键参数注释（与代码参数一致）

| 参数 | 作用 | 默认值 |
|------|------|--------|
| `--max-stocks` | 限制处理股票数量（用于快速测试） | `None`（不限制，全市场） |
| `--workers` | 并发线程数（选股/匹配加速） | `None`（自动按系统策略分配） |
| `--category` | 分类过滤（`all/bowl_center/near_duokong/near_short_trend`） | `all` |
| `--b1-match` | 启用 B1 完美图形匹配 | `False`（不传则关闭） |
| `--lookback-days` | B1 匹配回看交易日天数 | `None`（读取配置默认 `25`） |
| `--min-similarity` | B1 最低相似度阈值（百分比，0-100） | `None`（读取配置默认 `60`） |
| `--backtest-days` | 回溯天数（连续 K 条件窗口） | `3` |
| `--k-threshold` | 回溯 K 值阈值 | `20.0` |
| `--trend-drop-pct` | 短期趋势线最大容忍回落百分比（如 5=最多回落5%） | `5.0` |
| `--host` | Web 服务监听地址 | `0.0.0.0` |
| `--port` | Web 服务端口 | `5000` |
| `--config` | 指定配置文件路径 | `config/config.yaml` |

### 四、参数含义示例（天数 / 百分比）

- `lookback_days=25`：向前取最近 25 个交易日做 B1 形态匹配，不含周末和休市日。
- `min_similarity=60`：最低相似度 60%，即综合得分低于 60% 的股票会被过滤。
- `min_similarity=70`：更严格阈值，命中数量通常下降，但形态一致性更高。
- `trend-drop-pct=5`：回溯筛选时，股价相对短期趋势线最多允许下探 5%。
- `duokong_pct=3`：分类“靠近多空线”时，要求股价与多空线偏离在 ±3% 内。
- `short_pct=2`：分类“靠近短期趋势线”时，要求股价与短期趋势线偏离在 ±2% 内。

### 五、配置文件参数位置

编辑 config/strategy_params.yaml 中 B1PatternMatch 可调整：
- min_similarity: 默认最小相似度阈值
- lookback_days: 默认回看天数
- weights: 四维相似度权重
- tolerances: 各项特征容差

### 智能更新逻辑

`python3 main.py run` 会自动判断是否需要更新数据：

1. **15点前** - 检查本地是否已同步到最近已收盘交易日
2. **15点后** - 检查每只股票是否有当天数据
3. **如果本地已有最新交易日数据** - 跳过网络更新，直接使用
4. **否则** - 执行增量更新

## ⚙️ 策略配置

编辑 `config/strategy_params.yaml` 调整参数：

```yaml
# 碗口反弹策略
BowlReboundStrategy:
  N: 2.4            # 成交量倍数（放量阳线判断）
  M: 20             # 回溯天数（查找关键K线）
  CAP: 4000000000   # 流通市值门槛（40亿）
  J_VAL: 0          # J值上限（KDJ超卖阈值）
  M1: 14            # MA周期1（多空线计算）
  M2: 28            # MA周期2（多空线计算）
  M3: 57            # MA周期3（多空线计算）
  M4: 114           # MA周期4（多空线计算）
  duokong_pct: 3    # 距离多空线百分比（分类用）
  short_pct: 2      # 距离短期趋势线百分比（分类用）

# B1完美图形匹配
B1PatternMatch:
  min_similarity: 60      # 最小相似度阈值（只显示>=此值的股票）
  lookback_days: 25       # 回看天数（匹配时使用的数据天数）
  top_n_results: 15       # 展示Top N个匹配结果（钉钉通知中显示的数量）
  weights:                # 四维相似度权重
    trend_structure: 0.30 # 双线结构
    kdj_state: 0.20       # KDJ状态
    volume_pattern: 0.25  # 量能特征
    price_shape: 0.25     # 价格形态
  tolerances:             # 匹配容差参数
    trend_ratio: 0.10     # 趋势比值容差（±10%）
    price_bias: 10        # 价格偏离容差（±10%）
    trend_spread: 10      # 趋势发散容差（±10%）
    j_value: 30           # J值差异容差（±30）
    drawdown: 15          # 回撤幅度容差（±15%）
```

## ⏱️ 钉钉限流保护

系统内置智能限流器，防止触发钉钉 API 频率限制（错误码 660026）：

| 限制项 | 默认值 | 说明 |
|--------|--------|------|
| 每分钟最大消息数 | 20 条 | 达到限制后自动等待 |
| 最小发送间隔 | 2 秒 | 每条消息间隔至少 2 秒 |
| 重试次数 | 3 次 | 遇到限速错误时指数退避重试 |

**退避策略**：
- 第 1 次重试：等待 1 秒
- 第 2 次重试：等待 4 秒  
- 第 3 次重试：等待 8 秒

## 📱 钉钉通知格式

### 普通选股结果

选股结果发送到钉钉的格式：

```
🎯 BowlReboundStrategy:
N: 2.4 (成交量倍数)
M: 20 (回溯天数)
CAP: 4000000000 (40亿市值门槛)
J_VAL: 0 (J值上限)
duokong_pct: 3
short_pct: 2
M1: 14 (MA周期)
M2: 28 (MA周期)
M3: 57 (MA周期)
M4: 114 (MA周期)

⏰ 2026-03-02 15:30

🥣 回落碗中: 2 只
📊 靠近多空线: 1 只
📈 靠近短期趋势线: 0 只
📈 共选出: 3 只

---

### 📊 000001 平安银行
**分类**: 🥣 回落碗中
**价格**: 10.85 | **J值**: -7.65
**关键K线日期**: 02-28
**入选理由**: 回落碗中

[K线图图片]
```

K线图包含：
- 20天K线（涨红跌绿）
- 短期趋势线（蓝色）
- 多空线（绿色）
- 成交量（红绿柱）

### B1完美图形匹配结果

使用 `--b1-match` 参数时的钉钉通知格式：

```
## 📊 选股结果（按B1完美图形相似度排序）

⏰ 时间: 2026-03-05 21:30
📈 策略筛选: 15 只 | 📊 B1 Top匹配: 8 只
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🥇 **000001** 平安银行  **相似度: 85%**
   📈 匹配案例: 华纳药厂 (2025-05-12)
   📊 分项: 趋势28% | KDJ18% | 量能22% | 形态17%
   💰 策略: 🥣 回落碗中 | 价格: 10.85 | J值: -7.65

🥈 **000002** 万科A  **相似度: 78%**
   📈 匹配案例: 宁波韵升 (2025-08-06)
   📊 分项: 趋势25% | KDJ16% | 量能20% | 形态17%
   💰 策略: 📊 靠近多空线 | 价格: 15.20 | J值: 12.50

...

---
**B1匹配逻辑**: 基于双线+量比+形态三维相似度
**案例来源**: 12个历史成功案例（含航天发展、澄天伟业、掌阅科技）
```

**格式说明**：
- 每个股票之间有空行分隔
- 股票信息包含：排名、代码名称、相似度
- 匹配信息包含：匹配的案例名称和日期
- 分项得分：趋势/KDJ/量能/形态四个维度
- 策略信息：分类、价格、J值

## 🌐 Web界面

访问 `http://localhost:5000` 可查看：

- 📊 **系统概览** - 股票数量、最新数据日期
- 📈 **股票列表** - 所有股票基本信息，支持搜索
- 🎯 **选股结果** - 执行选股并查看信号详情
- ⚙️ **策略配置** - 在线修改策略参数

## ⏰ 定时任务

添加到 crontab 实现每日自动选股：

```bash
# 编辑 crontab
crontab -e

# 添加以下行（每天15:05执行，仅工作日）
5 15 * * 1-5 cd /root/quant-csv && /usr/bin/python3 main.py run >> /var/log/quant-csv/run.log 2>&1
```

## 🔧 扩展新策略

### 扩展选股策略

1. 在 `strategy/` 目录创建新文件，继承 `BaseStrategy`
2. 实现 `calculate_indicators()` 和 `select_stocks()` 方法
3. 在 `config/strategy_params.yaml` 添加参数
4. 系统自动识别并执行

示例：
```python
from strategy.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self, params=None):
        super().__init__("我的策略", params)
    
    def calculate_indicators(self, df):
        # 计算指标
        return df
    
    def select_stocks(self, df, stock_name=''):
        # 选股逻辑
        return signals
```

### 扩展B2/B3完美图形（预留）

系统已为B2、B3等新型完美图形预留扩展空间：

1. **创建新配置** - 在 `pattern_config.py` 添加 `B2_PERFECT_CASES` 配置
2. **创建新库类** - 参照 `B1PatternLibrary` 创建 `B2PatternLibrary` 类
3. **添加命令参数** - 在 `main.py` 添加 `--b2-match` 参数
4. **注册通知方法** - 在 `dingtalk_notifier.py` 添加 `send_b2_match_results()` 方法

B1和B2可以共存，用户可以根据需要选择使用哪种完美图形进行匹配。

## 🤖 开发团队

本项目使用多Agent协作开发：

| Agent | 职责 |
|-------|------|
| **Main** | 项目经理，协调Agent，技术兜底 |
| **Developer** | 代码实现、单元测试、自测报告 |
| **QA** | 集成测试、问题诊断、验收把关 |
| **Release** | Git推送、版本管理 |

## ⚠️ 免责声明

本项目仅供学习和研究使用，不构成任何投资建议。股市有风险，投资需谨慎。

## 📄 License

MIT License

---

**GitHub**: https://github.com/Dzy-HW-XD/a-share-quant-selector
