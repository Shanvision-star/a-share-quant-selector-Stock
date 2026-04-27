"""
研究论文分析模块 - 量化策略论文智能解析
================================================
本模块填补现有 PDF/论文 Agent 工具的缺口，专为量化金融研究设计：

【现有工具的不足】
  1. MinerU / DeepXIV / PaperLume    - 仅解析 PDF 结构，无量化策略识别
  2. PaperQA2 / Resophy              - 通用学术 RAG，无金融领域特化
  3. Deep-Read-Agent / GPT-Researcher - 多智能体研究，但缺乏公式→代码转换
  4. PaSa / Paper-Reading-Agent      - 缺乏 A 股市场知识与实盘数据对接

【本模块实现的核心缺口功能】
  1. PaperParser         - 结构化解析论文章节/公式/表格，专为量化论文优化
  2. StrategyExtractor   - 从论文中提取可执行的量化交易策略信号
  3. FormulaConverter    - 将学术公式转换为可运行的 Python 指标代码
  4. KnowledgeBase       - 跨论文增量知识库，支持策略对比与检索
  5. PaperAgent          - 端到端流水线：论文输入 → 策略代码 → 回测就绪

使用示例:
  from research import PaperAgent
  agent = PaperAgent()
  result = agent.analyze_text(paper_text)
  print(result.summary)
  print(result.strategies)
"""

from research.paper_parser import PaperParser
from research.strategy_extractor import StrategyExtractor
from research.formula_converter import FormulaConverter
from research.knowledge_base import KnowledgeBase
from research.paper_agent import PaperAgent

__all__ = [
    "PaperParser",
    "StrategyExtractor",
    "FormulaConverter",
    "KnowledgeBase",
    "PaperAgent",
]
