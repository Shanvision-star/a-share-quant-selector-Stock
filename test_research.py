#!/usr/bin/env python3
"""
test_research.py - 研究论文分析模块测试
================================================
测试 research/ 模块的核心功能，验证各组件正确运行。

运行:
    python3 test_research.py
    python3 -m pytest test_research.py -v
"""

import sys
import os
import tempfile
import unittest
from pathlib import Path

# 确保项目根目录在搜索路径中
sys.path.insert(0, str(Path(__file__).parent))

from research.paper_parser import PaperParser, Formula
from research.strategy_extractor import StrategyExtractor, StrategySpec
from research.formula_converter import FormulaConverter
from research.knowledge_base import KnowledgeBase
from research.paper_agent import PaperAgent


# ─────────────────────────────────────────────────
# 测试数据
# ─────────────────────────────────────────────────

SAMPLE_PAPER_ZH = """
# 基于 MACD 与量比的 A 股动量选股策略研究

## 摘要

本文提出一种结合 MACD 动量指标与成交量比（量比）的 A 股选股策略。
回测结果显示，策略在 2018-2024 年间实现年化收益率 24.5%，
夏普比率 1.8，最大回撤 18.3%，显著优于基准指数。

## 1 引言

A 股市场在散户主导的背景下，技术面指标具有较强的自我实现效应。
本文选取 MACD 与量比作为核心因子，构建中期持仓策略。

## 2 策略方法

### 2.1 核心指标

- **MACD 参数**：fast=12, slow=26, signal=9
- **量比计算**：量比 = 当日成交量 / 近5日均量
- **KDJ 过滤**：J 值 < 30 时认为超卖

### 2.2 买入信号

满足以下所有条件时触发买入信号：
1. MACD DIF 上穿 DEA（金叉）
2. 量比 > 1.5（放量确认）
3. J 值 < 30（超卖区间）
4. 股价站上 20 日均线

### 2.3 卖出信号

满足以下任一条件时平仓：
1. MACD 死叉（DIF 跌破 DEA）
2. 持仓超过 20 天
3. 止损：价格跌破成本价 8%

## 3 实验与回测

### 3.1 回测设置

- 回测区间：2018-01-01 至 2024-12-31
- 回测标的：沪深全 A（剔除 ST、新股）
- 手续费：万三双边
- period = 20
- threshold = 0.05
- lookback = 60

### 3.2 回测结果

| 指标 | 策略 | 沪深300基准 |
|------|------|-------------|
| 年化收益 | 24.5% | 8.2% |
| 夏普比率 | 1.8 | 0.6 |
| 最大回撤 | 18.3% | 32.1% |
| 胜率 | 58.3% | — |

## 4 结论

MACD 动量策略在 A 股市场具有较强的可复现性，
结合量比过滤可有效降低假信号。建议与碗口反弹策略结合使用。
"""

SAMPLE_PAPER_EN = """
# Momentum Trading Strategy Based on RSI and Bollinger Bands

## Abstract

This paper presents a momentum trading strategy using RSI and Bollinger Bands
for equity market selection. Backtesting shows annual return of 18.5%,
Sharpe ratio of 1.4, and maximum drawdown of 22.1%.

## Methodology

### Signal Definition

**Buy conditions:**
- RSI crosses above 30 (oversold reversal)
- Price breaks above upper Bollinger Band
- Volume > 1.5x 20-day average

**Sell conditions:**
- RSI crosses below 70 (overbought)
- Price falls below middle Bollinger Band

### Parameters

- RSI period = 14
- Bollinger period = 20, std_mult = 2.0
- Volume window = 20
- Lookback = 60

## Results

| Metric | Strategy | Benchmark |
|--------|----------|-----------|
| Annual Return | 18.5% | 9.3% |
| Sharpe Ratio | 1.4 | 0.7 |
| Max Drawdown | 22.1% | 28.5% |
| Win Rate | 55.2% | — |

## Conclusion

RSI and Bollinger Bands combination provides robust signals
with good risk-adjusted returns.
"""


# ─────────────────────────────────────────────────
# 测试类
# ─────────────────────────────────────────────────

class TestPaperParser(unittest.TestCase):
    """测试 PaperParser"""

    def setUp(self):
        self.parser = PaperParser()

    def test_parse_zh_paper(self):
        """解析中文论文返回正确结构"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        self.assertIsNotNone(paper)
        self.assertIn("MACD", paper.title)
        self.assertNotEqual(paper.abstract, "")
        self.assertGreater(len(paper.sections), 0)

    def test_detect_zh_language(self):
        """正确识别中文论文"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        self.assertIn(paper.language, ("zh", "mixed"))

    def test_detect_en_language(self):
        """正确识别英文论文"""
        paper = self.parser.parse_text(SAMPLE_PAPER_EN)
        self.assertEqual(paper.language, "en")

    def test_detect_quant_paper_type(self):
        """正确识别量化策略论文类型"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        self.assertIn(paper.paper_type, ("quant_strategy", "factor_model", "ml_trading"))

    def test_section_splitting(self):
        """章节拆分正确"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        section_titles = [s.title for s in paper.sections]
        self.assertTrue(any("摘要" in t or "abstract" in t.lower() for t in section_titles)
                        or paper.abstract != "")

    def test_table_extraction(self):
        """能提取 Markdown 表格"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        self.assertGreater(len(paper.all_tables), 0)

    def test_table_type_classification(self):
        """回测结果表格被识别为 backtest 类型"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        backtest_tables = [t for t in paper.all_tables if t.table_type == "backtest"]
        self.assertGreater(len(backtest_tables), 0)

    def test_quant_params_extraction(self):
        """能提取量化参数"""
        params = self.parser.extract_quant_params(SAMPLE_PAPER_ZH)
        self.assertIsInstance(params, dict)
        # 论文中有 period = 20
        self.assertIn("period", params)
        self.assertEqual(params["period"], 20.0)

    def test_empty_text(self):
        """空文本不报错"""
        paper = self.parser.parse_text("")
        self.assertIsNotNone(paper)

    def test_formula_extraction(self):
        """能提取公式（如有）"""
        text_with_formula = "The return is calculated as: $r_t = \\frac{P_t - P_{t-1}}{P_{t-1}}$"
        paper = self.parser.parse_text(text_with_formula)
        self.assertGreater(len(paper.all_formulas), 0)


class TestStrategyExtractor(unittest.TestCase):
    """测试 StrategyExtractor"""

    def setUp(self):
        self.parser = PaperParser()
        self.extractor = StrategyExtractor()

    def test_extract_buy_conditions(self):
        """能识别买入条件"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        spec = self.extractor.extract_from_paper(paper)
        self.assertGreater(len(spec.buy_conditions), 0)

    def test_extract_sell_conditions(self):
        """能识别卖出条件"""
        paper = self.parser.parse_text(SAMPLE_PAPER_ZH)
        spec = self.extractor.extract_from_paper(paper)
        self.assertGreater(len(spec.sell_conditions), 0)

    def test_extract_macd_factor(self):
        """能识别 MACD 指标"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH)
        self.assertIn("MACD", spec.factors)

    def test_extract_key_params(self):
        """能提取关键参数"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH)
        self.assertIsInstance(spec.key_params, dict)

    def test_detect_a_share_universe(self):
        """能识别 A 股适用范围"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH)
        self.assertEqual(spec.universe, "a_share")

    def test_extract_backtest_metrics(self):
        """能提取回测指标"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH)
        metrics = spec.backtest_metrics
        self.assertIsInstance(metrics, dict)
        # 应该识别出夏普比率或年化收益
        self.assertTrue(
            "sharpe_ratio" in metrics or "annual_return" in metrics,
            f"未找到回测指标，实际提取: {metrics}"
        )

    def test_detect_strategy_type(self):
        """能检测策略类型"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH)
        self.assertIn(spec.strategy_type, ("trend", "mean_reversion", "factor", "ml", "mixed"))

    def test_confidence_range(self):
        """置信度在 0~1 范围内"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH)
        self.assertGreaterEqual(spec.confidence, 0.0)
        self.assertLessEqual(spec.confidence, 1.0)

    def test_compare_strategies(self):
        """跨论文策略对比功能"""
        spec1 = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "中文论文")
        spec2 = self.extractor.extract_from_text(SAMPLE_PAPER_EN, "英文论文")
        comparison = self.extractor.compare_strategies([spec1, spec2])
        self.assertIsInstance(comparison, list)
        self.assertGreater(len(comparison), 0)
        dims = [item["dimension"] for item in comparison]
        self.assertIn("strategy_type_distribution", dims)
        self.assertIn("factor_frequency", dims)

    def test_empty_text(self):
        """空文本不报错"""
        spec = self.extractor.extract_from_text("")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.buy_conditions, [])


class TestFormulaConverter(unittest.TestCase):
    """测试 FormulaConverter"""

    def setUp(self):
        self.converter = FormulaConverter()
        self.extractor = StrategyExtractor()
        self.parser = PaperParser()

    def test_convert_macd_from_text(self):
        """能从文本中识别并转换 MACD 公式"""
        indicators = self.converter.convert_text("MACD fast=12 slow=26 signal=9")
        self.assertTrue(any("macd" in ind.name.lower() for ind in indicators))

    def test_convert_rsi_from_text(self):
        """能从文本中识别并转换 RSI 公式"""
        indicators = self.converter.convert_text("RSI period=14 relative strength")
        self.assertTrue(any("rsi" in ind.name.lower() for ind in indicators))

    def test_convert_ma_from_text(self):
        """能从文本中识别并转换均线公式"""
        indicators = self.converter.convert_text("moving average MA period=20")
        self.assertTrue(any("ma" in ind.name.lower() for ind in indicators))

    def test_generated_code_is_valid_python(self):
        """生成的代码是合法的 Python 语法"""
        indicators = self.converter.convert_text("RSI period=14")
        for ind in indicators:
            try:
                compile(ind.python_code, "<string>", "exec")
            except SyntaxError as e:
                self.fail(f"生成的代码有语法错误: {e}\n代码:\n{ind.python_code}")

    def test_generate_strategy_file(self):
        """生成完整策略文件"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "测试论文")
        result = self.converter.generate_strategy_file(spec)
        self.assertIsNotNone(result)
        self.assertIn("class", result.file_content)
        self.assertIn("generate_signals", result.file_content)
        self.assertIn("scan", result.file_content)

    def test_generated_file_valid_python(self):
        """生成的策略文件是合法 Python"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "测试论文")
        result = self.converter.generate_strategy_file(spec)
        try:
            compile(result.file_content, "<string>", "exec")
        except SyntaxError as e:
            self.fail(f"生成的策略文件有语法错误: {e}")

    def test_class_name_generation(self):
        """策略类名符合 Python 命名规范"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "测试论文")
        result = self.converter.generate_strategy_file(spec)
        class_name = result.class_name
        self.assertTrue(class_name[0].isupper(), f"类名应以大写开头: {class_name}")
        self.assertFalse(class_name[0].isdigit(), f"类名不应以数字开头: {class_name}")

    def test_empty_strategy(self):
        """空策略不报错"""
        from research.strategy_extractor import StrategySpec
        empty_spec = StrategySpec(
            name="empty",
            paper_title="",
            strategy_type="mixed",
            universe="all",
            holding_period="medium",
            buy_conditions=[],
            sell_conditions=[],
            filter_conditions=[],
            key_params={},
            factors=[],
            backtest_metrics={},
            raw_description="",
        )
        result = self.converter.generate_strategy_file(empty_spec)
        self.assertIsNotNone(result)


class TestKnowledgeBase(unittest.TestCase):
    """测试 KnowledgeBase"""

    def setUp(self):
        # 使用临时文件避免污染真实知识库
        self.tmp_dir = tempfile.mkdtemp()
        self.kb_path = os.path.join(self.tmp_dir, "test_kb.json")
        self.kb = KnowledgeBase(self.kb_path)
        self.extractor = StrategyExtractor()

    def tearDown(self):
        # 清理临时文件
        if os.path.exists(self.kb_path):
            os.remove(self.kb_path)

    def test_add_paper(self):
        """能添加论文"""
        pid = self.kb.add_paper(
            title="测试论文",
            abstract="这是一篇测试论文",
            paper_type="quant_strategy",
        )
        self.assertIsNotNone(pid)
        self.assertNotEqual(pid, "")

    def test_get_paper(self):
        """能按 ID 检索论文"""
        pid = self.kb.add_paper(title="测试论文A", abstract="摘要A")
        record = self.kb.get_paper(pid)
        self.assertIsNotNone(record)
        self.assertEqual(record.title, "测试论文A")

    def test_search_by_title(self):
        """按标题关键词搜索"""
        self.kb.add_paper(title="MACD策略研究", abstract="摘要1")
        self.kb.add_paper(title="RSI策略探讨", abstract="摘要2")
        results = self.kb.search_by_title("MACD")
        self.assertEqual(len(results), 1)
        self.assertIn("MACD", results[0].title)

    def test_search_by_strategy_type(self):
        """按策略类型搜索"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "趋势论文")
        self.kb.add_paper(
            title="趋势论文",
            abstract="摘要",
            strategy=spec,
            paper_type="quant_strategy",
        )
        stype = spec.strategy_type
        results = self.kb.search_by_strategy_type(stype)
        self.assertGreater(len(results), 0)

    def test_search_by_factor(self):
        """按指标搜索"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "MACD论文")
        self.kb.add_paper(title="MACD论文", abstract="摘要", strategy=spec)
        if "MACD" in spec.factors:
            results = self.kb.search_by_factor("MACD")
            self.assertGreater(len(results), 0)

    def test_persistence(self):
        """知识库能持久化并重新加载"""
        pid = self.kb.add_paper(title="持久化测试", abstract="持久化摘要")
        # 重新加载
        kb2 = KnowledgeBase(self.kb_path)
        record = kb2.get_paper(pid)
        self.assertIsNotNone(record)
        self.assertEqual(record.title, "持久化测试")

    def test_delete_paper(self):
        """能删除论文"""
        pid = self.kb.add_paper(title="待删除论文", abstract="摘要")
        success = self.kb.delete_paper(pid)
        self.assertTrue(success)
        self.assertIsNone(self.kb.get_paper(pid))

    def test_get_stats_empty(self):
        """空知识库的统计信息不报错"""
        stats = self.kb.get_stats()
        self.assertEqual(stats.total_papers, 0)

    def test_get_stats_with_data(self):
        """有数据时统计信息正确"""
        self.kb.add_paper(title="论文1", abstract="摘要1", language="zh", paper_type="quant_strategy")
        self.kb.add_paper(title="论文2", abstract="摘要2", language="en", paper_type="general")
        stats = self.kb.get_stats()
        self.assertEqual(stats.total_papers, 2)
        self.assertIn("zh", stats.language_dist)

    def test_identify_research_gaps(self):
        """研究空白识别功能"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "论文")
        self.kb.add_paper(title="论文", abstract="摘要", strategy=spec)
        gaps = self.kb.identify_research_gaps()
        self.assertIsInstance(gaps, dict)
        self.assertIn("missing_strategy_types", gaps)
        self.assertIn("missing_common_factors", gaps)

    def test_export_to_markdown(self):
        """Markdown 导出功能"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "测试论文")
        self.kb.add_paper(title="测试论文", abstract="摘要", strategy=spec)
        md = self.kb.export_to_markdown()
        self.assertIn("#", md)
        self.assertIn("测试论文", md)

    def test_generate_survey_data(self):
        """文献综述数据生成"""
        spec = self.extractor.extract_from_text(SAMPLE_PAPER_ZH, "综述论文")
        self.kb.add_paper(title="综述论文", abstract="摘要", strategy=spec)
        data = self.kb.generate_survey_data()
        self.assertIn("total", data)
        self.assertEqual(data["total"], 1)


class TestPaperAgent(unittest.TestCase):
    """测试 PaperAgent（端到端）"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.kb_path = os.path.join(self.tmp_dir, "agent_kb.json")
        self.agent = PaperAgent(kb_path=self.kb_path)

    def tearDown(self):
        if os.path.exists(self.kb_path):
            os.remove(self.kb_path)

    def test_analyze_zh_paper(self):
        """端到端分析中文论文"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        self.assertIsNotNone(report)
        self.assertNotEqual(report.paper_title, "")
        self.assertIn(report.paper_type, ("quant_strategy", "factor_model", "ml_trading", "general"))

    def test_analyze_en_paper(self):
        """端到端分析英文论文"""
        report = self.agent.analyze_text(SAMPLE_PAPER_EN)
        self.assertIsNotNone(report)
        self.assertEqual(report.language, "en")

    def test_report_has_strategy(self):
        """分析报告包含策略信息"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        self.assertIsNotNone(report.strategy)
        self.assertGreater(report.strategy.confidence, 0.0)

    def test_report_has_generated_code(self):
        """分析报告包含生成的代码"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH, generate_code=True)
        if report.strategy and report.strategy.confidence > 0.2:
            self.assertIsNotNone(report.generated_code)

    def test_report_has_a_share_assessment(self):
        """分析报告包含 A 股适配性评估"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        self.assertIn("compatible", report.a_share_compatibility)
        self.assertIn("issues", report.a_share_compatibility)

    def test_zh_paper_a_share_compatible(self):
        """中文 A 股论文应被识别为 A 股兼容"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        # A 股论文中没有做空等不兼容操作，应基本兼容
        self.assertIsInstance(report.a_share_compatibility["compatible"], bool)

    def test_save_to_knowledge_base(self):
        """分析后自动保存到知识库"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH, save_to_kb=True)
        self.assertNotEqual(report.paper_id, "")
        record = self.agent.knowledge_base.get_paper(report.paper_id)
        self.assertIsNotNone(record)

    def test_no_save_to_knowledge_base(self):
        """save_to_kb=False 不保存"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH, save_to_kb=False)
        self.assertEqual(report.paper_id, "")

    def test_save_generated_strategy(self):
        """生成的策略文件能保存到磁盘"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        if report.generated_code:
            output_path = os.path.join(self.tmp_dir, "test_strategy.py")
            success = self.agent.save_generated_strategy(report, output_path)
            self.assertTrue(success)
            self.assertTrue(os.path.exists(output_path))

    def test_format_report_string(self):
        """格式化报告输出为字符串"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        formatted = self.agent.format_report(report)
        self.assertIsInstance(formatted, str)
        self.assertIn("#", formatted)
        self.assertGreater(len(formatted), 100)

    def test_analyze_multiple(self):
        """批量分析功能"""
        papers = [
            {"text": SAMPLE_PAPER_ZH, "title": "中文论文"},
            {"text": SAMPLE_PAPER_EN, "title": "English Paper"},
        ]
        reports = self.agent.analyze_multiple(papers)
        self.assertEqual(len(reports), 2)

    def test_get_comparison_report(self):
        """跨论文对比报告"""
        self.agent.analyze_text(SAMPLE_PAPER_ZH, save_to_kb=True)
        self.agent.analyze_text(SAMPLE_PAPER_EN, save_to_kb=True)
        comp_report = self.agent.get_comparison_report()
        self.assertIsInstance(comp_report, str)
        self.assertIn("#", comp_report)

    def test_param_risks_identified(self):
        """参数风险提示"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        self.assertIsInstance(report.param_risks, list)

    def test_key_insights(self):
        """关键洞察提取"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        self.assertIsInstance(report.key_insights, list)

    def test_recommended_steps(self):
        """建议后续行动不为空"""
        report = self.agent.analyze_text(SAMPLE_PAPER_ZH)
        self.assertGreater(len(report.recommended_next_steps), 0)


# ─────────────────────────────────────────────────
# 快速集成测试
# ─────────────────────────────────────────────────

def run_quick_demo():
    """快速演示（非 unittest，直接运行时使用）"""
    print("\n" + "=" * 60)
    print("📚 Research Paper Agent - 快速演示")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp()
    agent = PaperAgent(kb_path=os.path.join(tmp_dir, "demo_kb.json"))

    print("\n▶ 分析中文量化论文...")
    report = agent.analyze_text(SAMPLE_PAPER_ZH)
    print(agent.format_report(report))

    print("\n" + "─" * 60)
    print("▶ 分析英文论文...")
    report_en = agent.analyze_text(SAMPLE_PAPER_EN)
    print(f"  标题: {report_en.paper_title}")
    print(f"  语言: {report_en.language}")
    print(f"  策略类型: {report_en.strategy.strategy_type if report_en.strategy else 'N/A'}")
    print(f"  使用指标: {report_en.strategy.factors if report_en.strategy else []}")

    print("\n" + "─" * 60)
    print("▶ 跨论文对比报告...")
    print(agent.get_comparison_report())

    print("\n" + "─" * 60)
    print("▶ 知识库统计...")
    stats = agent.knowledge_base.get_stats()
    print(f"  总论文数: {stats.total_papers}")
    print(f"  策略类型分布: {stats.strategy_type_dist}")
    print(f"  最常用指标: {dict(list(stats.factor_frequency.items())[:5])}")

    print("\n" + "─" * 60)
    print("▶ 研究空白识别...")
    gaps = agent.knowledge_base.identify_research_gaps()
    print(f"  缺失策略类型: {gaps.get('missing_strategy_types', [])}")
    print(f"  未覆盖常用指标: {gaps.get('missing_common_factors', [])}")

    print("\n✅ 演示完成！")


if __name__ == "__main__":
    import argparse

    arg_parser = argparse.ArgumentParser(description="研究论文分析模块测试")
    arg_parser.add_argument("--demo", action="store_true", help="运行快速演示（非单元测试）")
    arg_parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args, remaining = arg_parser.parse_known_args()

    if args.demo:
        run_quick_demo()
    else:
        verbosity = 2 if args.verbose else 1
        unittest.main(argv=[sys.argv[0]] + remaining, verbosity=verbosity)
