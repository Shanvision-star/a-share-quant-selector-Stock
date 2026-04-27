# PDF解析与论文阅读Agent现有工具差距分析及本项目实现

## 一、现有工具综合分析

### 工具清单

| 工具 | 类别 | 核心能力 | 主要局限 |
|------|------|----------|----------|
| MinerU | PDF解析引擎 | 公式/表格/图片无损解析 | 仅输出文本，无策略识别 |
| DeepXIV | arXiv专用解析 | 自动拆分章节，Token节流 | arXiv专用，无金融领域知识 |
| PaperLume/pdf-plumber | 工业级解析 | 高精度文本抽取 | 通用工具，无量化专业知识 |
| PaperQA2 | 学术RAG Agent | 迭代检索，页码引用 | 通用学术问答，无策略提取 |
| Resophy | 代理式阅读器 | 全文通读，Zotero联动 | 停在理解层，无代码生成 |
| Deep-Read-Agent | 自动化分析 | 搜索→下载→批判分析 | 停在批判分析层 |
| agent-papers-cli | CLI工具 | 终端批量读文献 | 无策略提取，无代码输出 |
| GPT-Researcher | 多智能体研究 | 批量爬PDF，生成综述 | 综述为自然语言，无结构化输出 |
| PaSa | 字节多智能体 | 中文论文优化，流派对比 | 缺乏代码生成，无回测集成 |
| Paper-Reading-Agent | 分工式Agent | 解析/总结/批判/PPT | 停在PPT生成，无实盘对接 |

---

## 二、核心缺口（所有工具均未实现）

### 缺口1：量化金融领域专项解析

**问题**：所有工具均为通用学术工具，缺乏量化金融领域特化：
- 无法识别"买入信号定义"章节
- 无法提取 `period=20` 等量化参数
- 无法分类回测结果表格（夏普/回撤/年化收益）
- 无法区分公式类型（均线/动量/因子/风险度量）

**本项目实现**：`research/paper_parser.py`
- `PaperParser.parse_text()` 自动识别量化论文类型
- `extract_quant_params()` 提取 period/window/threshold/lookback 等参数
- `_classify_table()` 识别回测结果表格 vs 参数表格
- 支持中英文混合论文，自动检测语言

---

### 缺口2：可执行交易信号提取

**问题**：没有工具能将论文中的策略描述转化为结构化信号定义：
- 无法从"MACD金叉时买入"识别出买入条件
- 无法提取止损/止盈规则
- 无法识别量比/换手率等成交量条件
- 输出为自然语言，不可直接用于策略开发

**本项目实现**：`research/strategy_extractor.py`
- `StrategyExtractor.extract_from_paper()` 提取结构化 `StrategySpec`
- 自动识别买入/卖出/过滤条件，每条件包含：指标名、方向、阈值、置信度
- 因子映射：论文描述 → 标准指标名（MACD/RSI/KDJ/BOLL等）
- A股适用范围自动识别（"A股"/"沪深" → universe="a_share"）
- 跨论文策略对比：`compare_strategies()` 输出因子频率/参数范围/回测对比

---

### 缺口3：论文公式 → Python代码转换

**问题**：所有工具停留在"理解公式"层面，没有工具能：
- 将 `SMA(close, n) = Σclose / n` 转换为 `pd.Series.rolling().mean()`
- 将 MACD/RSI/KDJ/布林带等公式生成完整的 pandas/numpy 实现
- 生成继承项目 `BaseStrategy` 的策略类骨架
- 生成可直接运行（含测试入口）的策略文件

**本项目实现**：`research/formula_converter.py`
- `FormulaConverter.convert_text()` 识别文本中的公式类型并生成代码
- 内置10种常见量化公式模板（MA/EMA/MACD/RSI/BOLL/KDJ/ATR/动量/量比/换手率）
- `generate_strategy_file()` 生成完整策略类（含 `compute_indicators` / `generate_signals` / `scan` 方法）
- 生成的类继承 `BaseStrategy`，与现有选股框架直接兼容
- 生成文件包含自测代码，可直接 `python strategy/xxx.py` 验证

---

### 缺口4：跨论文增量知识库

**问题**：现有工具在多论文场景下：
- PaperQA2 基于RAG，无持久化结构化知识图谱
- GPT-Researcher 生成综述后不保存策略结构
- 无工具追踪"同类策略的研究演化"
- 无工具识别"哪些策略类型/市场/指标研究不足"

**本项目实现**：`research/knowledge_base.py`
- `KnowledgeBase` 持久化JSON存储，无需数据库
- 多维度检索：`search_by_strategy_type()` / `search_by_factor()` / `search_by_universe()`
- `identify_research_gaps()` 识别研究空白（缺失策略类型/指标/市场覆盖）
- `generate_survey_data()` 生成结构化综述数据，可直接喂给 GPT-Researcher 等工具
- `export_to_markdown()` 一键导出 Markdown 格式文献综述

---

### 缺口5：A股市场特性适配检查

**问题**：所有现有工具均无 A股市场特性意识：
- 不检查策略是否包含 A股不支持的操作（做空/日内反转/期权）
- 不提醒 T+1 规则对日内策略的限制
- 不提醒涨跌停对成交量指标的影响
- 不提醒 ST股票、新股、流动性等 A股特有过滤需求

**本项目实现**：`research/paper_agent.py` 中的 `_assess_a_share_compatibility()`
- 自动检测策略是否包含 A股不兼容操作
- 针对日内策略提示 T+1 限制
- 对美股策略提示需重新验证
- 针对量比指标提示涨跌停日异常

---

### 缺口6：论文→策略代码的端到端流水线

**问题**：现有工具各环节割裂：
```
MinerU/DeepXIV → 文本
PaperQA2/Resophy → 理解/问答
Deep-Read-Agent → 批判分析
GPT-Researcher/PaSa → 综述
Paper-Reading-Agent → PPT
                     ↓ 断层（所有工具止步于此）
可运行策略代码 ← 未实现
回测验证 ← 未实现
实盘部署 ← 未实现
```

**本项目实现**：`research/paper_agent.py`
- `PaperAgent.analyze_text()` 端到端流水线：
  - 输入：论文文本
  - 输出：`AnalysisReport`（含策略代码 + A股适配评估 + 参数风险 + 后续建议）
- `save_generated_strategy()` 一步保存策略文件到 `strategy/` 目录
- `get_comparison_report()` 跨论文策略对比 Markdown 报告
- 与 `main.py` 集成：`python main.py research --paper-file paper.txt --research-output strategy/new.py`

---

## 三、功能对比矩阵

| 功能 | MinerU | DeepXIV | PaperQA2 | GPT-Researcher | PaSa | **本项目** |
|------|--------|---------|----------|----------------|------|------------|
| PDF结构解析 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅（文本输入）|
| 量化论文类型识别 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| 买卖信号提取 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| 量化参数提取 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| 公式→Python代码 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| 策略类代码生成 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| 跨论文增量知识库 | ❌ | ❌ | 部分 | 部分 | ❌ | **✅** |
| 研究空白识别 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| A股适配性检查 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| 回测框架集成 | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| 中文A股论文优化 | 部分 | ❌ | ❌ | ❌ | ✅ | **✅** |

---

## 四、使用方法

### 命令行（集成到 main.py）

```bash
# 查看知识库统计
python main.py research

# 分析单篇论文
python main.py research --paper-file paper.txt --paper-title "策略标题"

# 分析并生成策略代码
python main.py research --paper-file paper.txt --research-output strategy/my_strategy.py

# 使用自定义知识库路径
python main.py research --paper-file paper.txt --kb-path data/my_kb.json
```

### Python API

```python
from research import PaperAgent

agent = PaperAgent()

# 分析论文
with open("paper.txt") as f:
    text = f.read()

report = agent.analyze_text(text, title="我的策略论文")

# 查看分析报告
print(agent.format_report(report))

# 保存生成的策略代码
agent.save_generated_strategy(report, "strategy/new_strategy.py")

# 批量分析多篇论文
papers = [{"text": text1, "title": "论文1"}, {"text": text2, "title": "论文2"}]
reports = agent.analyze_multiple(papers)

# 跨论文对比报告
print(agent.get_comparison_report())

# 知识库查询
kb = agent.knowledge_base
trend_papers = kb.search_by_strategy_type("trend")
macd_papers = kb.search_by_factor("MACD")
gaps = kb.identify_research_gaps()
survey_md = kb.export_to_markdown()
```

---

## 五、与现有工具联动方案

本模块设计为与现有工具互补，而非替代：

```
MinerU/DeepXIV → 解析PDF为文本 → PaperAgent.analyze_text() → 策略代码
                                                            ↓
GPT-Researcher/PaSa → knowledge_base.generate_survey_data() → LLM生成综述
                                                            ↓
本项目 main.py backtest → 验证提取的策略参数
                        ↓
strategy_registry.py → 注册通过验证的新策略
```

---

## 六、文件结构

```
research/
├── __init__.py           # 模块入口，导出所有公共类
├── paper_parser.py       # 论文结构化解析（章节/公式/表格/参数提取）
├── strategy_extractor.py # 量化策略提取（买卖信号/因子/参数/回测指标）
├── formula_converter.py  # 公式→Python代码转换 + 策略类生成
├── knowledge_base.py     # 跨论文增量知识库（持久化/检索/统计/综述导出）
└── paper_agent.py        # 端到端编排Agent（流水线入口 + A股适配评估）

test_research.py          # 55个单元测试（全部通过）
```
