"""
KnowledgeBase - 跨论文增量知识库
================================================
【填补的缺口】
现有工具（PaperQA2/Resophy/GPT-Researcher）在多论文场景下的局限：
  - PaperQA2：基于 RAG，每次查询重新检索，无持久化知识图谱
  - Resophy：单篇精读为主，跨论文关联弱
  - GPT-Researcher：爬取后生成综述，但不保存结构化策略知识
  - PaSa：中文优化但无策略对比数据库
  - 所有工具都缺少"策略演化追踪"功能

本模块实现以下缺失功能：
  1. 持久化策略知识存储（JSON 文件，无需数据库）
  2. 跨论文策略检索（按指标/类型/市场/回测指标）
  3. 策略演化追踪（同类策略的历史改进记录）
  4. 研究趋势分析（哪类策略论文最多、哪些指标最常用）
  5. 知识库统计报告生成
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

from research.strategy_extractor import StrategySpec


# ─────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────

@dataclass
class PaperRecord:
    """知识库中的单篇论文记录"""
    paper_id: str               # 唯一标识（自动生成）
    title: str
    abstract: str
    added_at: str               # ISO 格式时间戳
    paper_type: str             # "quant_strategy" / "factor_model" / "ml_trading" / "general"
    language: str               # "zh" / "en" / "mixed"
    strategy: Optional[Dict]    # StrategySpec 序列化为字典
    tags: List[str]             # 自定义标签
    source_url: str = ""        # 论文来源 URL（如有）
    notes: str = ""             # 用户备注


@dataclass
class KnowledgeBaseStats:
    """知识库统计信息"""
    total_papers: int
    strategy_type_dist: Dict[str, int]
    factor_frequency: Dict[str, int]
    universe_dist: Dict[str, int]
    language_dist: Dict[str, int]
    top_papers_by_confidence: List[str]
    latest_added: str


class KnowledgeBase:
    """
    量化论文增量知识库

    核心优势（相比现有工具）：
      1. 完全离线，无需 LLM API 调用
      2. 结构化存储，支持精确查询（不依赖向量相似度）
      3. 策略演化追踪：同类策略按时间排序，可观察研究趋势
      4. 研究空白识别：统计哪些指标/市场/策略类型覆盖不足
      5. 一键生成文献综述数据，供 GPT/Claude 生成综述时使用

    数据存储：JSON 文件，与项目其他 CSV/JSON 文件格式一致
    """

    DEFAULT_DB_PATH = "data/research_knowledge_base.json"

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化知识库

        参数:
            db_path: 知识库 JSON 文件路径，默认 data/research_knowledge_base.json
        """
        self.db_path = Path(db_path or self.DEFAULT_DB_PATH)
        self._records: Dict[str, PaperRecord] = {}
        self._load()

    # ── 写入操作 ──────────────────────────────────

    def add_paper(
        self,
        title: str,
        abstract: str,
        strategy: Optional[StrategySpec] = None,
        paper_type: str = "general",
        language: str = "zh",
        tags: Optional[List[str]] = None,
        source_url: str = "",
        notes: str = "",
    ) -> str:
        """
        向知识库添加一篇论文

        参数:
            title:       论文标题
            abstract:    摘要
            strategy:    提取的策略规格（可选）
            paper_type:  论文类型
            language:    语言
            tags:        自定义标签列表
            source_url:  来源 URL
            notes:       备注

        返回:
            paper_id（字符串）
        """
        paper_id = self._generate_id(title)
        strategy_dict = self._serialize_strategy(strategy) if strategy else None

        record = PaperRecord(
            paper_id=paper_id,
            title=title,
            abstract=abstract,
            added_at=datetime.now().isoformat(),
            paper_type=paper_type,
            language=language,
            strategy=strategy_dict,
            tags=tags or [],
            source_url=source_url,
            notes=notes,
        )
        self._records[paper_id] = record
        self._save()
        return paper_id

    def update_paper(self, paper_id: str, **kwargs) -> bool:
        """更新论文记录的指定字段"""
        if paper_id not in self._records:
            return False
        record = self._records[paper_id]
        for k, v in kwargs.items():
            if hasattr(record, k):
                setattr(record, k, v)
        self._save()
        return True

    def delete_paper(self, paper_id: str) -> bool:
        """从知识库删除一篇论文"""
        if paper_id not in self._records:
            return False
        del self._records[paper_id]
        self._save()
        return True

    # ── 查询操作 ──────────────────────────────────

    def get_paper(self, paper_id: str) -> Optional[PaperRecord]:
        """按 ID 获取论文记录"""
        return self._records.get(paper_id)

    def search_by_title(self, keyword: str) -> List[PaperRecord]:
        """按标题关键词搜索（不区分大小写）"""
        kw = keyword.lower()
        return [r for r in self._records.values() if kw in r.title.lower()]

    def search_by_strategy_type(self, strategy_type: str) -> List[PaperRecord]:
        """
        按策略类型搜索（现有工具缺失功能）
        strategy_type: "trend" / "mean_reversion" / "factor" / "ml" / "mixed"
        """
        results = []
        for r in self._records.values():
            if r.strategy and r.strategy.get("strategy_type") == strategy_type:
                results.append(r)
        return results

    def search_by_factor(self, factor: str) -> List[PaperRecord]:
        """
        按指标/因子搜索（现有工具缺失功能）
        例：search_by_factor("MACD") 返回所有使用 MACD 的策略论文
        """
        factor_upper = factor.upper()
        results = []
        for r in self._records.values():
            if r.strategy:
                factors = r.strategy.get("factors", [])
                if factor_upper in [f.upper() for f in factors]:
                    results.append(r)
        return results

    def search_by_universe(self, universe: str) -> List[PaperRecord]:
        """按适用市场搜索（"a_share" / "us_stock" / "all"）"""
        results = []
        for r in self._records.values():
            if r.strategy and r.strategy.get("universe") == universe:
                results.append(r)
        return results

    def search_by_tag(self, tag: str) -> List[PaperRecord]:
        """按自定义标签搜索"""
        tag_lower = tag.lower()
        return [r for r in self._records.values() if any(t.lower() == tag_lower for t in r.tags)]

    def get_top_by_confidence(self, n: int = 10) -> List[PaperRecord]:
        """
        返回策略提取置信度最高的 N 篇论文（现有工具缺失功能）
        帮助快速定位质量最高、最值得阅读的论文
        """
        records_with_strategy = [
            r for r in self._records.values()
            if r.strategy and "confidence" in r.strategy
        ]
        records_with_strategy.sort(
            key=lambda r: r.strategy.get("confidence", 0),
            reverse=True,
        )
        return records_with_strategy[:n]

    def get_all_papers(self) -> List[PaperRecord]:
        """返回所有论文记录"""
        return list(self._records.values())

    # ── 分析功能 ──────────────────────────────────

    def get_stats(self) -> KnowledgeBaseStats:
        """
        生成知识库统计信息（现有工具缺失功能）
        用于研究趋势分析和研究空白识别
        """
        records = list(self._records.values())
        if not records:
            return KnowledgeBaseStats(
                total_papers=0,
                strategy_type_dist={},
                factor_frequency={},
                universe_dist={},
                language_dist={},
                top_papers_by_confidence=[],
                latest_added="",
            )

        # 策略类型分布
        type_dist: Dict[str, int] = {}
        for r in records:
            stype = r.strategy.get("strategy_type", "unknown") if r.strategy else "no_strategy"
            type_dist[stype] = type_dist.get(stype, 0) + 1

        # 因子频率
        factor_freq: Dict[str, int] = {}
        for r in records:
            if r.strategy:
                for f in r.strategy.get("factors", []):
                    factor_freq[f] = factor_freq.get(f, 0) + 1

        # 市场分布
        universe_dist: Dict[str, int] = {}
        for r in records:
            uni = r.strategy.get("universe", "unknown") if r.strategy else "unknown"
            universe_dist[uni] = universe_dist.get(uni, 0) + 1

        # 语言分布
        lang_dist: Dict[str, int] = {}
        for r in records:
            lang_dist[r.language] = lang_dist.get(r.language, 0) + 1

        # 置信度最高的论文
        top_papers = [r.title for r in self.get_top_by_confidence(5)]

        # 最近添加
        latest = max((r.added_at for r in records), default="")

        return KnowledgeBaseStats(
            total_papers=len(records),
            strategy_type_dist=type_dist,
            factor_frequency=factor_freq,
            universe_dist=universe_dist,
            language_dist=lang_dist,
            top_papers_by_confidence=top_papers,
            latest_added=latest,
        )

    def identify_research_gaps(self) -> Dict[str, Any]:
        """
        识别研究空白（现有工具完全缺失的功能）

        分析知识库中覆盖不足的领域：
          - 哪些策略类型论文较少
          - 哪些技术指标被较少研究
          - 哪些市场（如 A 股）覆盖不足
          - 哪些持仓周期（如日内交易）缺乏研究

        返回:
            research_gaps 字典，包含各维度的空白分析
        """
        stats = self.get_stats()
        gaps: Dict[str, Any] = {}

        # 策略类型空白
        all_types = {"trend", "mean_reversion", "factor", "ml", "mixed"}
        covered_types = set(stats.strategy_type_dist.keys())
        gaps["missing_strategy_types"] = list(all_types - covered_types)

        # 低覆盖策略类型（少于总数的10%）
        total = max(stats.total_papers, 1)
        gaps["underrepresented_types"] = {
            k: v for k, v in stats.strategy_type_dist.items()
            if v / total < 0.1
        }

        # 因子空白（常见因子但未出现在知识库）
        common_factors = {"MA", "EMA", "RSI", "MACD", "BOLL", "KDJ", "ATR", "VOLUME", "MOMENTUM"}
        covered_factors = set(stats.factor_frequency.keys())
        gaps["missing_common_factors"] = list(common_factors - covered_factors)

        # A 股覆盖情况
        a_share_count = stats.universe_dist.get("a_share", 0)
        gaps["a_share_coverage"] = {
            "count": a_share_count,
            "percentage": a_share_count / total,
            "gap": a_share_count < total * 0.3,  # A 股论文不足30%视为空白
        }

        return gaps

    def generate_survey_data(self) -> Dict[str, Any]:
        """
        生成文献综述数据（可供 LLM 直接使用）

        输出结构化的文献综述原材料：
          - 按策略类型分组的论文列表
          - 主要回测指标汇总
          - 研究趋势时间线
          - 参数范围统计

        这使得本工具可与 GPT-Researcher/PaSa 等综述生成工具联动
        """
        records = list(self._records.values())
        if not records:
            return {"error": "知识库为空"}

        # 按策略类型分组
        by_type: Dict[str, List[Dict]] = {}
        for r in records:
            stype = r.strategy.get("strategy_type", "general") if r.strategy else "general"
            entry = {
                "title": r.title,
                "abstract": r.abstract[:200],
                "factors": r.strategy.get("factors", []) if r.strategy else [],
                "backtest_metrics": r.strategy.get("backtest_metrics", {}) if r.strategy else {},
                "confidence": r.strategy.get("confidence", 0) if r.strategy else 0,
            }
            by_type.setdefault(stype, []).append(entry)

        # 时间线（按添加时间排序）
        timeline = [
            {"date": r.added_at[:10], "title": r.title, "type": r.paper_type}
            for r in sorted(records, key=lambda x: x.added_at)
        ]

        return {
            "total": len(records),
            "by_strategy_type": by_type,
            "timeline": timeline,
            "stats": asdict(self.get_stats()),
            "research_gaps": self.identify_research_gaps(),
        }

    def export_to_markdown(self) -> str:
        """
        导出知识库为 Markdown 文献综述（现有工具缺失功能）

        生成可直接用于论文写作的 Markdown 格式文献综述：
          - 按策略类型分章节
          - 每篇论文列出关键策略和指标
          - 汇总回测指标对比表
        """
        records = list(self._records.values())
        if not records:
            return "# 知识库为空\n"

        lines = [
            "# 量化策略论文知识库导出",
            f"\n> 共 {len(records)} 篇论文，导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "\n---\n",
        ]

        # 按策略类型分组
        groups: Dict[str, List[PaperRecord]] = {}
        for r in records:
            stype = r.strategy.get("strategy_type", "通用") if r.strategy else "通用"
            groups.setdefault(stype, []).append(r)

        type_zh = {
            "trend": "趋势跟踪策略",
            "mean_reversion": "均值回归策略",
            "factor": "因子选股策略",
            "ml": "机器学习策略",
            "mixed": "混合策略",
            "通用": "通用/其他",
        }

        for stype, recs in sorted(groups.items()):
            lines.append(f"## {type_zh.get(stype, stype)}\n")
            for r in recs:
                lines.append(f"### {r.title}")
                if r.abstract:
                    lines.append(f"\n> {r.abstract[:150]}...\n")
                if r.strategy:
                    factors = r.strategy.get("factors", [])
                    if factors:
                        lines.append(f"- **使用指标**: {', '.join(factors)}")
                    metrics = r.strategy.get("backtest_metrics", {})
                    if metrics:
                        metric_str = "、".join(f"{k}: {v}" for k, v in metrics.items())
                        lines.append(f"- **回测指标**: {metric_str}")
                    conf = r.strategy.get("confidence", 0)
                    lines.append(f"- **提取置信度**: {conf:.0%}")
                if r.tags:
                    lines.append(f"- **标签**: {', '.join(r.tags)}")
                lines.append("")

        # 汇总统计
        stats = self.get_stats()
        lines.append("\n---\n## 综合统计\n")
        lines.append("### 策略类型分布")
        for k, v in stats.strategy_type_dist.items():
            lines.append(f"- {type_zh.get(k, k)}: {v} 篇")
        lines.append("\n### 最常用指标")
        sorted_factors = sorted(stats.factor_frequency.items(), key=lambda x: x[1], reverse=True)
        for f, cnt in sorted_factors[:10]:
            lines.append(f"- {f}: {cnt} 次")

        return "\n".join(lines)

    # ── 持久化 ────────────────────────────────────

    def _load(self) -> None:
        """从 JSON 文件加载知识库"""
        if not self.db_path.exists():
            self._records = {}
            return
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._records = {}
            for pid, record_dict in data.items():
                self._records[pid] = PaperRecord(**record_dict)
        except (json.JSONDecodeError, TypeError, KeyError):
            self._records = {}

    def _save(self) -> None:
        """将知识库保存到 JSON 文件"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {pid: asdict(record) for pid, record in self._records.items()}
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _generate_id(self, title: str) -> str:
        """根据标题和时间生成唯一 ID"""
        import hashlib
        ts = datetime.now().isoformat()
        raw = f"{title}_{ts}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def _serialize_strategy(self, strategy: StrategySpec) -> Dict:
        """将 StrategySpec 序列化为可 JSON 存储的字典"""
        from dataclasses import asdict as _asdict
        d = _asdict(strategy)
        return d
