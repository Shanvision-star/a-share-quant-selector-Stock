"""
PaperParser - 论文结构化解析器
================================================
【填补的缺口】
现有工具（MinerU/DeepXIV/PaperQA2）可以解析通用 PDF 结构，
但缺少面向量化金融论文的专项解析：
  - 自动识别"买卖信号定义"章节
  - 提取参数表（lookback/threshold/period 等量化参数）
  - 识别回测结果表格（夏普率/最大回撤/年化收益）
  - 解析策略流程图中的条件逻辑
  - 双语（中英文）量化术语归一化

功能：
  - 将论文文本按章节拆分
  - 识别并提取公式块
  - 识别回测指标表格
  - 识别参数定义段落
  - 提取摘要/方法/实验/结论等标准节
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict


# ─────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────

@dataclass
class Formula:
    """论文中的公式"""
    raw: str                    # 原始公式文本
    label: Optional[str]        # 公式编号，如 "(1)"
    description: str = ""       # 上下文描述（公式前后文字）
    variables: List[str] = field(default_factory=list)  # 识别出的变量名


@dataclass
class Table:
    """论文中的表格"""
    caption: str                # 表格标题
    headers: List[str]          # 列名
    rows: List[List[str]]       # 数据行
    table_type: str = "general" # "backtest" / "parameter" / "general"


@dataclass
class Section:
    """论文章节"""
    title: str
    level: int              # 1=一级标题，2=二级标题
    content: str
    formulas: List[Formula] = field(default_factory=list)
    tables: List[Table] = field(default_factory=list)
    section_type: str = "general"  # "abstract" / "methodology" / "experiment" / "conclusion" / "signal"


@dataclass
class ParsedPaper:
    """解析后的完整论文"""
    title: str
    abstract: str
    sections: List[Section]
    all_formulas: List[Formula]
    all_tables: List[Table]
    raw_text: str
    language: str = "zh"  # "zh" / "en" / "mixed"
    paper_type: str = "general"  # "quant_strategy" / "factor_model" / "ml_trading" / "general"


# ─────────────────────────────────────────────────
# 章节识别规则
# ─────────────────────────────────────────────────

# 中文标准章节关键词
_ZH_SECTION_MAP: Dict[str, str] = {
    "摘要": "abstract",
    "abstract": "abstract",
    "引言": "introduction",
    "介绍": "introduction",
    "introduction": "introduction",
    "方法": "methodology",
    "策略": "methodology",
    "模型": "methodology",
    "methodology": "methodology",
    "method": "methodology",
    "model": "methodology",
    "strategy": "methodology",
    "信号": "signal",
    "选股": "signal",
    "买入": "signal",
    "卖出": "signal",
    "signal": "signal",
    "factor": "signal",
    "因子": "signal",
    "实验": "experiment",
    "回测": "experiment",
    "结果": "experiment",
    "experiment": "experiment",
    "backtest": "experiment",
    "result": "experiment",
    "performance": "experiment",
    "结论": "conclusion",
    "总结": "conclusion",
    "conclusion": "conclusion",
    "summary": "conclusion",
    "参考": "reference",
    "reference": "reference",
}

# 量化论文识别关键词（中英文）
_QUANT_KEYWORDS = [
    "alpha", "beta", "sharpe", "夏普", "drawdown", "回撤", "annualized", "年化",
    "factor", "因子", "momentum", "动量", "mean reversion", "均值回归",
    "backtest", "回测", "trading strategy", "交易策略", "signal", "信号",
    "technical indicator", "技术指标", "moving average", "均线", "KDJ", "MACD",
    "RSI", "布林", "bollinger", "trend", "趋势", "breakout", "突破",
    "volume", "成交量", "position sizing", "仓位", "portfolio", "组合",
    "A股", "a-share", "沪深", "上证", "深证",
]


class PaperParser:
    """
    量化金融论文结构化解析器

    相比通用工具（MinerU/DeepXIV），本解析器增加了：
      1. 量化论文类型自动识别
      2. 交易信号章节优先提取
      3. 回测结果表格专项解析
      4. 量化参数自动识别（period/threshold/lookback等）
      5. 中英文混合论文支持
    """

    # 公式识别正则（覆盖 LaTeX 行内/行间，以及纯文本公式）
    FORMULA_PATTERNS = [
        re.compile(r"\$\$(.+?)\$\$", re.DOTALL),          # LaTeX 显示公式
        re.compile(r"\$([^$\n]+?)\$"),                      # LaTeX 行内公式
        re.compile(r"\\begin\{equation\}(.+?)\\end\{equation\}", re.DOTALL),
        re.compile(r"\\begin\{align\}(.+?)\\end\{align\}", re.DOTALL),
        re.compile(r"(?<!\w)([A-Za-z_]\w*\s*=\s*[A-Za-z0-9_()\[\]+\-*/^. ]+)(?!\w)"),  # 简单赋值公式
    ]

    # 章节标题识别正则
    SECTION_PATTERNS = [
        re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE),               # Markdown 标题
        re.compile(r"^(\d+\.?\d*)\s+([A-Z\u4e00-\u9fff][^\n]{2,60})$", re.MULTILINE),  # 编号标题
        re.compile(r"^([一二三四五六七八九十]+[、.]\s*)([^\n]{2,40})$", re.MULTILINE),     # 中文编号
    ]

    # 量化参数识别正则
    PARAM_PATTERNS = re.compile(
        r"(?:period|window|lookback|threshold|factor|n|k|alpha|lambda|gamma)"
        r"\s*[=:≈]\s*(\d+\.?\d*)",
        re.IGNORECASE,
    )

    # 回测指标关键词
    BACKTEST_METRIC_KEYWORDS = [
        "sharpe", "夏普", "return", "收益", "drawdown", "回撤",
        "win rate", "胜率", "calmar", "sortino", "information ratio", "信息比",
        "alpha", "beta", "annual", "年化",
    ]

    def parse_text(self, text: str, title: str = "") -> ParsedPaper:
        """
        解析论文纯文本，返回结构化 ParsedPaper 对象

        参数:
            text:  论文全文（可以是 Markdown/纯文本）
            title: 论文标题（可选，若文中可识别则自动提取）

        返回:
            ParsedPaper 完整结构化结果
        """
        text = self._normalize_text(text)
        title = title or self._extract_title(text)
        language = self._detect_language(text)
        paper_type = self._detect_paper_type(text)

        sections = self._split_sections(text)
        all_formulas = self._extract_all_formulas(text)
        all_tables = self._extract_all_tables(text)
        abstract = self._extract_abstract(text, sections)

        # 给每个 section 分配类型和关联公式/表格
        for sec in sections:
            sec.section_type = self._classify_section(sec.title)
            sec.formulas = self._extract_all_formulas(sec.content)
            sec.tables = self._extract_all_tables(sec.content)

        return ParsedPaper(
            title=title,
            abstract=abstract,
            sections=sections,
            all_formulas=all_formulas,
            all_tables=all_tables,
            raw_text=text,
            language=language,
            paper_type=paper_type,
        )

    # ── 内部方法 ──────────────────────────────────

    def _normalize_text(self, text: str) -> str:
        """基础文本清洗：统一换行/空格"""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 压缩超过3个连续空行为2个
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    def _extract_title(self, text: str) -> str:
        """从文本头部提取论文标题"""
        lines = text.strip().splitlines()
        for line in lines[:10]:
            line = line.strip().lstrip("#").strip()
            if 5 < len(line) < 120 and not line.startswith("摘要") and not line.lower().startswith("abstract"):
                return line
        return "未知标题"

    def _detect_language(self, text: str) -> str:
        """检测论文语言"""
        zh_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        en_count = len(re.findall(r"[a-zA-Z]", text))
        if zh_count > en_count * 0.3:
            return "zh" if zh_count > en_count else "mixed"
        return "en"

    def _detect_paper_type(self, text: str) -> str:
        """判断论文类型（量化策略/因子模型/机器学习交易/通用）"""
        text_lower = text.lower()
        score = sum(1 for kw in _QUANT_KEYWORDS if kw.lower() in text_lower)
        if score >= 5:
            if any(kw in text_lower for kw in ["machine learning", "deep learning", "lstm", "神经网络"]):
                return "ml_trading"
            if any(kw in text_lower for kw in ["factor", "因子", "alpha", "beta"]):
                return "factor_model"
            return "quant_strategy"
        return "general"

    def _split_sections(self, text: str) -> List[Section]:
        """将论文按标题拆分为章节列表"""
        sections: List[Section] = []
        # 尝试 Markdown 标题
        md_pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        matches = list(md_pattern.finditer(text))

        if matches:
            for i, m in enumerate(matches):
                level = len(m.group(1))
                title = m.group(2).strip()
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                content = text[start:end].strip()
                sections.append(Section(title=title, level=level, content=content))
        else:
            # fallback：按空行分段，取首行为标题
            paras = re.split(r"\n{2,}", text)
            for para in paras:
                para = para.strip()
                if not para:
                    continue
                lines = para.splitlines()
                title = lines[0].strip()
                content = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
                sections.append(Section(title=title, level=1, content=content))

        return sections

    def _classify_section(self, title: str) -> str:
        """根据标题判断章节类型"""
        title_lower = title.lower().strip()
        for keyword, stype in _ZH_SECTION_MAP.items():
            if keyword in title_lower:
                return stype
        return "general"

    def _extract_abstract(self, text: str, sections: List[Section]) -> str:
        """提取摘要文本"""
        for sec in sections:
            if sec.section_type == "abstract":
                return sec.content
        # fallback：搜索"摘要"关键词
        m = re.search(r"(?:摘\s*要|abstract)[：:：\s]*([^\n#]{50,800})", text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
        # 取前300字符作为摘要代替
        return text[:300].strip()

    def _extract_all_formulas(self, text: str) -> List[Formula]:
        """从文本中提取所有公式"""
        formulas: List[Formula] = []
        seen: set = set()
        for pattern in self.FORMULA_PATTERNS:
            for m in pattern.finditer(text):
                raw = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
                raw = raw.strip()
                if not raw or raw in seen:
                    continue
                seen.add(raw)
                # 提取上下文
                start = max(0, m.start() - 80)
                end = min(len(text), m.end() + 80)
                context = text[start:end].replace("\n", " ")
                # 提取变量
                variables = re.findall(r"\b([A-Za-z_]\w*)\b", raw)
                variables = [v for v in variables if len(v) <= 10]
                formulas.append(Formula(
                    raw=raw,
                    label=None,
                    description=context,
                    variables=variables,
                ))
        return formulas

    def _extract_all_tables(self, text: str) -> List[Table]:
        """从 Markdown 文本中提取表格"""
        tables: List[Table] = []
        # Markdown 表格
        table_pattern = re.compile(
            r"(\|.+\|\n\|[-: |]+\|\n(?:\|.+\|\n?)+)",
            re.MULTILINE,
        )
        for m in table_pattern.finditer(text):
            raw_table = m.group(1)
            lines = [l.strip() for l in raw_table.strip().splitlines() if l.strip()]
            if len(lines) < 2:
                continue
            headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
            rows = []
            for line in lines[2:]:  # 跳过分隔行
                row = [cell.strip() for cell in line.strip("|").split("|")]
                rows.append(row)

            # 判断表格类型
            table_type = self._classify_table(headers, rows)

            # 尝试从上文找标题（表格前30字符）
            caption_start = max(0, m.start() - 100)
            caption_text = text[caption_start:m.start()]
            cap_m = re.search(r"(?:表|Table)[^\n]*$", caption_text, re.IGNORECASE)
            caption = cap_m.group(0).strip() if cap_m else ""

            tables.append(Table(
                caption=caption,
                headers=headers,
                rows=rows,
                table_type=table_type,
            ))
        return tables

    def _classify_table(self, headers: List[str], rows: List[List[str]]) -> str:
        """根据表头和行数据判断表格类型"""
        header_str = " ".join(headers).lower()
        # 合并所有行的第一列（通常是指标名称列）
        row_str = " ".join(row[0] for row in rows if row).lower()
        combined = header_str + " " + row_str
        if any(kw in combined for kw in self.BACKTEST_METRIC_KEYWORDS):
            return "backtest"
        if any(kw in combined for kw in ["param", "参数", "period", "window", "threshold", "value"]):
            return "parameter"
        return "general"

    def extract_quant_params(self, text: str) -> Dict[str, float]:
        """
        专项提取量化策略参数（period/window/threshold/lookback 等）
        这是现有工具缺失的功能：将论文中散落的参数整合为可直接用于回测的字典

        返回示例: {"period": 20, "threshold": 0.05, "lookback": 60}
        """
        params: Dict[str, float] = {}
        for m in self.PARAM_PATTERNS.finditer(text):
            # 从匹配本身提取参数名（避免回溯到上下文导致错误关联）
            full_match = m.group(0)
            name_m = re.match(
                r"(period|window|lookback|threshold|factor|n|k|alpha|lambda|gamma)",
                full_match, re.IGNORECASE
            )
            if name_m:
                key = name_m.group(1).lower()
                try:
                    params[key] = float(m.group(1))
                except ValueError:
                    pass
        return params
