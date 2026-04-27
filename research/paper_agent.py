"""
PaperAgent - 端到端论文分析智能体
================================================
【填补的缺口】
现有工具的核心问题：各环节割裂，无法形成"论文→可用策略代码"的完整流水线

  - MinerU/DeepXIV：  停在 PDF→文本层
  - PaperQA2/Resophy：停在 问答/理解层
  - Deep-Read-Agent：  停在 批判性分析层
  - GPT-Researcher：   停在 综述生成层
  - Paper-Reading-Agent: 停在 总结/PPT 生成层
  - 所有工具都缺少：   文本→结构化策略→可运行代码→回测验证 的完整闭环

本模块作为最终编排层，将以上所有组件串联为完整流水线：
  1. 接受论文文本/章节
  2. 自动解析结构（PaperParser）
  3. 提取量化策略（StrategyExtractor）
  4. 转换公式为代码（FormulaConverter）
  5. 存入增量知识库（KnowledgeBase）
  6. 输出分析报告 + 策略代码文件

额外特有功能（全部现有工具均未实现）：
  A. 策略可行性评估：基于现有策略库对比，评估策略的新颖性
  B. 参数敏感性提示：识别论文中参数定义不清晰的风险点
  C. A 股适配检查：检查策略是否适合 A 股市场特性（T+1、涨跌停等）
  D. 研究空白报告：结合知识库，输出当前覆盖不足的研究方向
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

from research.paper_parser import PaperParser, ParsedPaper
from research.strategy_extractor import StrategyExtractor, StrategySpec
from research.formula_converter import FormulaConverter, GeneratedStrategy
from research.knowledge_base import KnowledgeBase


# ─────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────

@dataclass
class AnalysisReport:
    """完整的论文分析报告"""
    paper_title: str
    analyzed_at: str
    paper_type: str
    language: str
    abstract_summary: str
    strategy: Optional[StrategySpec]
    generated_code: Optional[GeneratedStrategy]
    paper_id: str                           # 知识库 ID
    a_share_compatibility: Dict[str, Any]   # A 股适配性评估
    novelty_assessment: Dict[str, Any]      # 新颖性评估
    param_risks: List[str]                  # 参数风险提示
    key_insights: List[str]                 # 关键洞察
    recommended_next_steps: List[str]       # 建议后续行动


# ─────────────────────────────────────────────────
# A 股特殊规则检查
# ─────────────────────────────────────────────────

# A 股市场特性（现有论文阅读工具完全未考虑）
_A_SHARE_CONSTRAINTS = {
    "t_plus_1": "A 股实行 T+1 交收，当日买入不能当日卖出",
    "price_limit": "A 股存在涨跌停限制（主板±10%，创业板±20%，科创板±20%）",
    "st_rules": "ST 股票有特殊限制，需从策略标的中排除",
    "auction_period": "集合竞价期间无法按市价成交",
    "margin_constraints": "融资融券有门槛，不能直接做空个股",
    "liquidity": "中小盘股流动性差，大仓位冲击成本高",
    "trading_hours": "A 股交易时间 9:30-15:00，不支持夜盘",
}

# 与 A 股不兼容的策略关键词
_INCOMPATIBLE_WITH_A_SHARE = [
    "short selling", "做空", "short position",
    "intraday reversal",
    "options", "期权",
    "high frequency", "高频",
    "market making", "做市",
]


class PaperAgent:
    """
    端到端论文分析智能体

    用法：
        agent = PaperAgent()
        report = agent.analyze_text(paper_text)
        print(report.strategy)
        print(report.generated_code.file_content)

        # 保存策略代码文件
        agent.save_generated_strategy(report, "strategy/my_new_strategy.py")

        # 查看知识库统计
        print(agent.knowledge_base.get_stats())
    """

    def __init__(self, kb_path: Optional[str] = None):
        """
        初始化 PaperAgent

        参数:
            kb_path: 知识库路径（默认 data/research_knowledge_base.json）
        """
        self.parser = PaperParser()
        self.extractor = StrategyExtractor()
        self.converter = FormulaConverter()
        self.knowledge_base = KnowledgeBase(kb_path)

    # ── 主要分析入口 ──────────────────────────────

    def analyze_text(
        self,
        text: str,
        title: str = "",
        tags: Optional[List[str]] = None,
        source_url: str = "",
        generate_code: bool = True,
        save_to_kb: bool = True,
    ) -> AnalysisReport:
        """
        分析论文文本（主要入口）

        参数:
            text:          论文全文（Markdown 或纯文本）
            title:         论文标题（可选，自动提取）
            tags:          自定义标签
            source_url:    论文来源 URL
            generate_code: 是否生成策略代码（默认 True）
            save_to_kb:    是否保存到知识库（默认 True）

        返回:
            AnalysisReport 完整分析报告
        """
        # Step 1: 结构化解析
        paper = self.parser.parse_text(text, title)

        # Step 2: 策略提取
        strategy = self.extractor.extract_from_paper(paper)

        # Step 3: 代码生成
        generated_code = None
        if generate_code and strategy.confidence > 0.2:
            generated_code = self.converter.generate_strategy_file(strategy)

        # Step 4: A 股适配性评估
        a_share_compat = self._assess_a_share_compatibility(paper, strategy)

        # Step 5: 新颖性评估
        novelty = self._assess_novelty(strategy)

        # Step 6: 参数风险识别
        param_risks = self._identify_param_risks(strategy)

        # Step 7: 关键洞察提取
        insights = self._extract_insights(paper, strategy)

        # Step 8: 建议后续行动
        next_steps = self._recommend_next_steps(strategy, a_share_compat, novelty)

        # Step 9: 保存到知识库
        paper_id = ""
        if save_to_kb:
            paper_id = self.knowledge_base.add_paper(
                title=paper.title,
                abstract=paper.abstract,
                strategy=strategy if strategy.confidence > 0.1 else None,
                paper_type=paper.paper_type,
                language=paper.language,
                tags=tags or [],
                source_url=source_url,
            )

        return AnalysisReport(
            paper_title=paper.title,
            analyzed_at=datetime.now().isoformat(),
            paper_type=paper.paper_type,
            language=paper.language,
            abstract_summary=paper.abstract[:300],
            strategy=strategy,
            generated_code=generated_code,
            paper_id=paper_id,
            a_share_compatibility=a_share_compat,
            novelty_assessment=novelty,
            param_risks=param_risks,
            key_insights=insights,
            recommended_next_steps=next_steps,
        )

    def analyze_multiple(
        self,
        papers: List[Dict[str, str]],
        generate_code: bool = False,
    ) -> List[AnalysisReport]:
        """
        批量分析多篇论文（现有工具支持不足）

        参数:
            papers: [{"text": "...", "title": "...", "url": "..."}] 列表
            generate_code: 是否为每篇论文生成代码

        返回:
            AnalysisReport 列表
        """
        reports = []
        for paper_dict in papers:
            report = self.analyze_text(
                text=paper_dict.get("text", ""),
                title=paper_dict.get("title", ""),
                source_url=paper_dict.get("url", ""),
                generate_code=generate_code,
                save_to_kb=True,
            )
            reports.append(report)
        return reports

    def save_generated_strategy(self, report: AnalysisReport, output_path: str) -> bool:
        """
        将生成的策略代码保存为 Python 文件

        参数:
            report:      analyze_text() 返回的报告
            output_path: 输出文件路径（如 strategy/new_strategy.py）

        返回:
            True 表示成功
        """
        if not report.generated_code:
            return False
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report.generated_code.file_content)
        return True

    def get_comparison_report(self) -> str:
        """
        生成跨论文策略对比报告（现有工具缺失功能）

        基于知识库中所有论文的策略，生成：
          1. 策略类型分布
          2. 最常用指标
          3. 回测指标对比
          4. 参数范围汇总
          5. 研究空白

        返回:
            Markdown 格式的对比报告字符串
        """
        records = self.knowledge_base.get_all_papers()
        if not records:
            return "# 知识库为空，请先分析论文\n"

        specs = []
        for r in records:
            if r.strategy:
                # 从字典重建 StrategySpec
                try:
                    from research.strategy_extractor import SignalCondition
                    spec = StrategySpec(
                        name=r.strategy.get("name", r.title),
                        paper_title=r.title,
                        strategy_type=r.strategy.get("strategy_type", "mixed"),
                        universe=r.strategy.get("universe", "all"),
                        holding_period=r.strategy.get("holding_period", "medium"),
                        buy_conditions=[],
                        sell_conditions=[],
                        filter_conditions=[],
                        key_params=r.strategy.get("key_params", {}),
                        factors=r.strategy.get("factors", []),
                        backtest_metrics=r.strategy.get("backtest_metrics", {}),
                        raw_description="",
                        confidence=r.strategy.get("confidence", 0),
                    )
                    specs.append(spec)
                except Exception:
                    continue

        comparison = self.extractor.compare_strategies(specs)
        gaps = self.knowledge_base.identify_research_gaps()

        lines = [
            "# 量化策略跨论文对比报告",
            f"\n> 分析论文数量: {len(records)}，包含策略: {len(specs)}",
            f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "---\n",
        ]

        for item in comparison:
            dim = item["dimension"]
            data = item["data"]
            lines.append(f"## {dim}\n")
            if isinstance(data, dict):
                for k, v in data.items():
                    lines.append(f"- **{k}**: {v}")
            lines.append("")

        lines.append("## 研究空白分析\n")
        for k, v in gaps.items():
            lines.append(f"### {k}")
            lines.append(f"```\n{v}\n```\n")

        return "\n".join(lines)

    # ── 内部评估方法 ──────────────────────────────

    def _assess_a_share_compatibility(
        self, paper: ParsedPaper, strategy: StrategySpec
    ) -> Dict[str, Any]:
        """
        评估策略与 A 股市场的兼容性（全部现有工具缺失的功能）

        返回兼容性分析字典：
          - compatible: bool
          - issues: list（不兼容点列表）
          - warnings: list（需注意点列表）
          - suggestions: list（适配建议）
        """
        issues = []
        warnings = []
        suggestions = []

        text = paper.raw_text.lower()

        # 检查不兼容特性
        for kw in _INCOMPATIBLE_WITH_A_SHARE:
            if kw.lower() in text:
                issues.append(f"策略提及 '{kw}'，A 股不支持或限制该操作")

        # 检查持仓周期
        if strategy.holding_period == "intraday":
            issues.append("日内交易策略需注意 A 股 T+1 规则，无法当日高频换手")

        # 检查市场
        if strategy.universe in ("us_stock",):
            warnings.append("论文基于美股数据，迁移到 A 股需重新验证")
            suggestions.append("建议使用 A 股数据重新回测，注意涨跌停板过滤")

        # A 股特有提示
        if "volume" in [f.upper() for f in strategy.factors]:
            warnings.append("成交量指标在 A 股适用，但需注意涨跌停日成交量异常")

        if not issues:
            suggestions.append("策略基本兼容 A 股市场，建议添加 ST 股票过滤和涨跌停处理")

        # 始终添加 A 股通用建议
        suggestions.append("建议在买入信号中增加'非涨停'条件，防止无法成交")

        return {
            "compatible": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "suggestions": suggestions,
            "a_share_constraints": list(_A_SHARE_CONSTRAINTS.keys()),
        }

    def _assess_novelty(self, strategy: StrategySpec) -> Dict[str, Any]:
        """
        评估策略相对知识库的新颖性（现有工具缺失功能）

        返回:
          - is_novel: bool
          - similar_papers: list（知识库中相似策略的论文标题）
          - overlap_factors: list（与已有策略重叠的指标）
          - novel_factors: list（未在知识库中出现的新指标）
        """
        existing_records = self.knowledge_base.get_all_papers()
        all_existing_factors: set = set()
        similar_papers = []

        for r in existing_records:
            if r.strategy:
                existing_factors = set(r.strategy.get("factors", []))
                all_existing_factors.update(existing_factors)
                # 判断策略相似度（因子重叠 >= 50%）
                strategy_factors = set(strategy.factors)
                if strategy_factors and existing_factors:
                    overlap = len(strategy_factors & existing_factors) / len(strategy_factors)
                    if overlap >= 0.5:
                        similar_papers.append(r.title)

        new_factors = [f for f in strategy.factors if f not in all_existing_factors]
        overlap_factors = [f for f in strategy.factors if f in all_existing_factors]

        return {
            "is_novel": len(similar_papers) == 0 or len(new_factors) > 0,
            "similar_papers": similar_papers[:5],
            "overlap_factors": overlap_factors,
            "novel_factors": new_factors,
            "knowledge_base_size": len(existing_records),
        }

    def _identify_param_risks(self, strategy: StrategySpec) -> List[str]:
        """识别参数风险（过拟合/模糊定义/不合理范围等）"""
        risks = []
        params = strategy.key_params

        # 参数过多可能过拟合
        if len(params) > 8:
            risks.append(f"参数数量较多（{len(params)} 个），注意过拟合风险")

        # 参数值范围检查
        if "period" in params:
            p = params["period"]
            if p < 3:
                risks.append(f"period={p} 过小，可能对噪声敏感")
            elif p > 250:
                risks.append(f"period={p} 超过一年，策略反应过慢")

        if "threshold" in params:
            t = params["threshold"]
            if t > 1:
                risks.append(f"threshold={t} 大于1，请确认单位（是否应为百分比）")

        # 买卖信号不对称
        if strategy.buy_conditions and not strategy.sell_conditions:
            risks.append("仅定义了买入条件，缺少卖出/止损条件（论文中可能未明确）")

        # 低置信度提示
        if strategy.confidence < 0.3:
            risks.append(f"策略提取置信度较低（{strategy.confidence:.0%}），建议人工核对原文")

        return risks

    def _extract_insights(self, paper: ParsedPaper, strategy: StrategySpec) -> List[str]:
        """提取论文关键洞察"""
        insights = []

        # 从摘要提取
        if paper.abstract:
            insights.append(f"核心贡献: {paper.abstract[:150].strip()}")

        # 回测指标洞察
        if strategy.backtest_metrics:
            for k, v in strategy.backtest_metrics.items():
                insights.append(f"回测表现: {k} = {v}")

        # 策略类型洞察
        type_map = {
            "trend": "趋势跟踪，适合单边行情，震荡市效果差",
            "mean_reversion": "均值回归，适合震荡行情，趋势市易亏损",
            "factor": "因子选股，持仓周期通常为月度再平衡",
            "ml": "机器学习策略，需注意样本外泛化能力",
        }
        if strategy.strategy_type in type_map:
            insights.append(f"策略特性: {type_map[strategy.strategy_type]}")

        # 因子数量
        if strategy.factors:
            insights.append(f"使用指标: {', '.join(strategy.factors[:5])}")

        return insights

    def _recommend_next_steps(
        self,
        strategy: StrategySpec,
        a_share_compat: Dict,
        novelty: Dict,
    ) -> List[str]:
        """生成建议后续行动"""
        steps = []

        if strategy.confidence > 0.5:
            steps.append("置信度较高，可直接基于生成的代码骨架开发策略")
        else:
            steps.append("置信度较低，建议阅读原文方法章节后手动完善买卖条件")

        if not a_share_compat["compatible"]:
            steps.append(f"需修改策略以兼容 A 股规则: {', '.join(a_share_compat['issues'][:2])}")

        if novelty["novel_factors"]:
            steps.append(f"论文中的新指标 {novelty['novel_factors']} 值得深入研究")

        if strategy.backtest_metrics:
            steps.append("将论文回测结果与系统本地回测对比，验证策略可复现性")

        steps.append("使用 main.py backtest 命令在历史数据上验证提取的参数")
        steps.append("将验证通过的策略注册到 strategy_registry.py")

        return steps

    # ── 报告输出 ──────────────────────────────────

    def format_report(self, report: AnalysisReport) -> str:
        """将分析报告格式化为可读的 Markdown 字符串"""
        lines = [
            f"# 📄 论文分析报告",
            f"\n**标题**: {report.paper_title}",
            f"**分析时间**: {report.analyzed_at[:19]}",
            f"**论文类型**: {report.paper_type}",
            f"**语言**: {report.language}",
            f"**知识库ID**: {report.paper_id or '未保存'}",
            "\n---\n",
            "## 摘要",
            f"\n{report.abstract_summary}\n",
        ]

        if report.strategy:
            s = report.strategy
            lines += [
                "## 提取的量化策略",
                f"\n- **策略名称**: {s.name}",
                f"- **策略类型**: {s.strategy_type}",
                f"- **适用市场**: {s.universe}",
                f"- **持仓周期**: {s.holding_period}",
                f"- **提取置信度**: {s.confidence:.0%}",
                f"- **使用指标**: {', '.join(s.factors) or '未识别'}",
            ]

            if s.backtest_metrics:
                lines.append("\n### 论文中的回测指标")
                for k, v in s.backtest_metrics.items():
                    lines.append(f"- {k}: {v}")

            if s.buy_conditions:
                lines.append(f"\n### 买入条件 ({len(s.buy_conditions)} 条)")
                for c in s.buy_conditions[:3]:
                    lines.append(f"- [{c.indicator}|{c.direction}] {c.description[:80]}")

            if s.sell_conditions:
                lines.append(f"\n### 卖出条件 ({len(s.sell_conditions)} 条)")
                for c in s.sell_conditions[:3]:
                    lines.append(f"- [{c.indicator}|{c.direction}] {c.description[:80]}")

        if report.a_share_compatibility:
            compat = report.a_share_compatibility
            status = "✅ 兼容" if compat["compatible"] else "⚠️ 存在兼容性问题"
            lines += [
                "\n## A 股适配性评估",
                f"\n**状态**: {status}",
            ]
            if compat.get("issues"):
                lines.append("\n**问题**:")
                for issue in compat["issues"]:
                    lines.append(f"- ❌ {issue}")
            if compat.get("warnings"):
                lines.append("\n**警告**:")
                for w in compat["warnings"]:
                    lines.append(f"- ⚠️ {w}")
            if compat.get("suggestions"):
                lines.append("\n**建议**:")
                for s in compat["suggestions"][:3]:
                    lines.append(f"- 💡 {s}")

        if report.param_risks:
            lines += ["\n## 参数风险提示\n"]
            for risk in report.param_risks:
                lines.append(f"- ⚠️ {risk}")

        if report.key_insights:
            lines += ["\n## 关键洞察\n"]
            for insight in report.key_insights:
                lines.append(f"- 💡 {insight}")

        if report.recommended_next_steps:
            lines += ["\n## 建议后续行动\n"]
            for i, step in enumerate(report.recommended_next_steps, 1):
                lines.append(f"{i}. {step}")

        if report.generated_code:
            lines += [
                "\n## 生成的策略代码",
                f"\n**策略类名**: `{report.generated_code.class_name}`",
                f"**使用指标**: {len(report.generated_code.indicators)} 个自动生成的指标函数",
                "\n> 使用 `agent.save_generated_strategy(report, 'strategy/xxx.py')` 保存代码文件",
            ]

        return "\n".join(lines)
