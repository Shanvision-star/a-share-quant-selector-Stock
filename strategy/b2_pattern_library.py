"""
B2 完美图形匹配库 — 对规则命中的候选股进行相似度打分
==========================================================================

本模块基于 B1PatternLibrary 的相似度计算框架，针对 B2 突破形态实现专属的
特征提取和匹配逻辑。

B2 图形匹配流程：
  1. 离线建库：从配置中的历史成功案例预计算 B2 突破前特征向量（默认40天窗口）
  2. 在线扫描：与 B2PatternLibrary（规则扫描版）联动
               对规则命中的候选股提取 B2 突破前特征
  3. 相似度计算：4维加权相似度
                 趋势结构 25% + KDJ状态 25% + 量能模式 35% + 价格形态 15%
  4. 排序输出：按相似度从高到低排序，高分候选更可能延续历史强势形态

与 B1PatternLibrary 的区别：
  - 案例来源：B2历史案例（横盘突破/灾后重建/平行重炮三分类）
  - 特征窗口：B2突破日前 40 天（覆盖整理期 + B1信号期，排除突破当天）
  - 量能权重更高（35%）：缩量整理是 B2 最核心特征
  - 价格权重较低（15%）：B2 价格形态本身多样
  - 输出包含 B2 规则扫描全部字段 + 相似度打分结果
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategy.pattern_config import (
    B2_PATTERN_CASES,
    B2_SIMILARITY_WEIGHTS,
    B2_MIN_SIMILARITY_SCORE,
    B2_PATTERN_LOOKBACK_DAYS,
    B2_PATTERN_TOP_N,
)
from strategy.pattern_feature_extractor import PatternFeatureExtractor
from strategy.pattern_matcher import PatternMatcher

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent

# 三分类中文标签映射
_PATTERN_LABELS = {
    "sideways_breakout":  "横盘突破型",
    "post_crash_rebuild": "灾后重建型",
    "parallel_artillery": "平行重炮型",
}


class B2PatternMatchLibrary:
    """
    B2 完美图形匹配库（相似度版）

    职责：
      - 预计算历史 B2 案例特征向量（缓存到 JSON 文件）
      - 对已通过规则扫描的 B2 候选股进行多维相似度评分
      - 返回按相似度排序的结果列表

    与 B2PatternLibrary（规则扫描版）的区别：
      - 规则扫描版：6步逻辑判断是否为 B2 形态（是/否二分）
      - 本类：对通过规则的候选，计算其与历史案例的形态相似度（0-100分连续）
    """

    CACHE_FILE = BASE_DIR / "data" / "b2_pattern_match_cache.json"
    CACHE_VERSION = 1

    def __init__(self, csv_manager):
        self.csv_manager = csv_manager
        self.extractor = PatternFeatureExtractor()
        # 使用 B2 专属权重（量能权重更高）
        self.matcher = PatternMatcher(weights=B2_SIMILARITY_WEIGHTS)
        self.cases = {}  # {case_id: {"meta": {...}, "features": {...}}}

        if not self._load_from_cache():
            self._build_library()

    # ──────────────── 缓存管理 ────────────────────────────────────────────────

    def _expected_signatures(self) -> dict:
        """生成案例配置签名，用于缓存一致性校验（案例变化时自动失效）。"""
        return {
            case["id"]: {
                "code": case["code"],
                "b2_date": case["b2_date"],
                "lookback_days": case["lookback_days"],
            }
            for case in B2_PATTERN_CASES
        }

    def _load_from_cache(self) -> bool:
        """尝试从缓存文件加载特征向量，校验通过则直接使用，返回是否成功。"""
        if not self.CACHE_FILE.exists():
            return False
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("version") != self.CACHE_VERSION:
                return False
            if cache.get("signatures") != self._expected_signatures():
                return False
            self.cases = cache.get("cases", {})
            print(f"[B2Match] 从缓存加载案例库: {len(self.cases)} 个案例")
            return bool(self.cases)
        except Exception as e:
            logger.warning("[B2Match] 缓存加载失败: %s", e)
            return False

    def _save_to_cache(self):
        """将案例特征向量序列化到本地 JSON 文件，加速下次启动。"""
        try:
            cache = {
                "version": self.CACHE_VERSION,
                "signatures": self._expected_signatures(),
                "cases": self.cases,
                "updated_at": datetime.now().isoformat(),
            }
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, default=str)
            print(f"[B2Match] 案例特征已缓存到 {self.CACHE_FILE}")
        except Exception as e:
            logger.warning("[B2Match] 缓存保存失败: %s", e)

    # ──────────────── 案例库构建 ──────────────────────────────────────────────

    def _build_library(self):
        """从本地 CSV 构建 B2 图形案例特征库。"""
        print("[B2Match] 构建 B2 图形特征库...")
        for case in B2_PATTERN_CASES:
            try:
                df = self.csv_manager.read_stock(case["code"])
                if df is None or df.empty:
                    print(f"  [WARN] 跳过 {case['name']}({case['code']}): 无 CSV 数据，"
                          f"请确认 data/ 目录中有该股票历史数据")
                    continue

                window_df = self._extract_b2_window(df, case["b2_date"], case["lookback_days"])
                if window_df.empty or len(window_df) < 10:
                    print(f"  [WARN] 跳过 {case['name']}: {case['b2_date']} 前数据不足 10 行")
                    continue

                features = self.extractor.extract(window_df)
                self.cases[case["id"]] = {
                    "meta": case,
                    "features": features,
                }
                pattern_label = _PATTERN_LABELS.get(case["pattern_type"], case["pattern_type"])
                print(f"  [OK] {case['name']} ({case['code']}) [{pattern_label}] 特征提取完成")

            except Exception as e:
                print(f"  [ERROR] {case['name']} 处理失败: {e}")

        if self.cases:
            self._save_to_cache()
            print(f"[B2Match] 案例库构建完成: {len(self.cases)} 个案例\n")
        else:
            print("[B2Match] 警告: 案例库为空（请检查历史案例数据是否存在）\n")

    # ──────────────── 特征窗口提取 ────────────────────────────────────────────

    def _extract_b2_window(
        self, df: pd.DataFrame, b2_date: str, lookback_days: int
    ) -> pd.DataFrame:
        """
        提取 B2 突破日之前 lookback_days 天的数据窗口。

        设计原则：
          - 不包含 B2 突破当天（大阳线会扭曲特征向量，导致错误高分）
          - 返回倒序 DataFrame（最新在前），与 PatternFeatureExtractor.extract() 期望输入一致

        Args:
            df           : CSVManager.read_stock() 返回的倒序 DataFrame
            b2_date      : B2 突破日期字符串（YYYY-MM-DD）
            lookback_days: 向前回溯天数（默认 40，覆盖整理期 + B1信号期）

        Returns:
            倒序 DataFrame，长度 <= lookback_days
        """
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["date"]):
            df["date"] = pd.to_datetime(df["date"])
        b2_dt = pd.to_datetime(b2_date)
        # df 为降序（最新在前），过滤后 head() 取最近的 lookback_days 行
        filtered = df[df["date"] < b2_dt]
        return filtered.head(lookback_days)

    # ──────────────── 单股相似度计算 ──────────────────────────────────────────

    def find_best_match(
        self,
        stock_code: str,
        stock_df: pd.DataFrame,
        b2_date: str,
        lookback_days: int = None,
    ) -> dict:
        """
        为单只 B2 候选股计算与案例库的相似度。

        Args:
            stock_code  : 股票代码
            stock_df    : 完整股票 DataFrame（倒序，CSVManager 格式）
            b2_date     : 候选股的 B2 突破日期（由规则扫描得出）
            lookback_days: 回看天数，None 时使用全局配置值

        Returns:
            {
                "best_match": {case_id, case_name, similarity_score, breakdown, ...} | None,
                "all_matches": [...],  # 按相似度排序的全部案例比较结果
                "candidate_features": {...},
            }
        """
        days = lookback_days or B2_PATTERN_LOOKBACK_DAYS

        if not self.cases:
            return {"best_match": None, "all_matches": [], "candidate_features": {}}

        window_df = self._extract_b2_window(stock_df, b2_date, days)
        if window_df.empty or len(window_df) < 8:
            return {"best_match": None, "all_matches": [], "candidate_features": {}}

        candidate_features = self.extractor.extract(window_df)
        matches = []

        for case_id, case_data in self.cases.items():
            try:
                similarity = self.matcher.match(candidate_features, case_data["features"])
                matches.append({
                    "case_id":           case_id,
                    "case_name":         case_data["meta"]["name"],
                    "case_code":         case_data["meta"]["code"],
                    "case_b2_date":      case_data["meta"]["b2_date"],
                    "pattern_type":      case_data["meta"]["pattern_type"],
                    "pattern_label":     _PATTERN_LABELS.get(case_data["meta"]["pattern_type"], "-"),
                    "tags":              case_data["meta"].get("tags", []),
                    "similarity_score":  similarity["total_score"],
                    "breakdown":         similarity["breakdown"],
                })
            except Exception as e:
                logger.warning("[B2Match] %s vs %s 比较失败: %s", stock_code, case_id, e)

        matches.sort(key=lambda x: x["similarity_score"], reverse=True)
        best_match = matches[0] if matches else None

        return {
            "best_match":          best_match,
            "all_matches":         matches,
            "candidate_features":  candidate_features,
        }

    # ──────────────── 批量相似度评分 ──────────────────────────────────────────

    def scan_with_match(
        self,
        b2_results: list,
        stock_data_dict: dict,
        min_similarity: float = None,
    ) -> list:
        """
        对 B2 规则扫描结果进行相似度打分与排序。

        典型用法：
            rule_lib = B2PatternLibrary()
            b2_hits = rule_lib.scan_all(stock_list, csv_manager)
            match_lib = B2PatternMatchLibrary(csv_manager)
            matched = match_lib.scan_with_match(b2_hits, rule_lib._stock_data_dict)

        Args:
            b2_results      : B2PatternLibrary.scan_all() 返回的命中列表
            stock_data_dict : {code: DataFrame}，scan_all 期间保存的原始数据
            min_similarity  : 最低相似度阈值（低于此值过滤）

        Returns:
            带相似度分数的结果列表，按相似度从高到低排序
        """
        if not b2_results:
            return []

        threshold = min_similarity if min_similarity is not None else B2_MIN_SIMILARITY_SCORE
        matched_results = []

        print(f"\n[B2Match] 开始相似度评分，共 {len(b2_results)} 只 B2 候选...", flush=True)

        for b2_item in b2_results:
            code    = b2_item.get("code", "")
            b2_date = b2_item.get("b2_date", "")
            name    = b2_item.get("name", code)

            if not code or not b2_date:
                continue

            df = stock_data_dict.get(code)
            if df is None or df.empty:
                continue

            try:
                match_result = self.find_best_match(code, df, b2_date)
                best = match_result.get("best_match")

                if best is None or best["similarity_score"] < threshold:
                    logger.debug(
                        "[B2Match] %s %s 相似度 %.1f < 阈值 %.1f，跳过",
                        code, name, best["similarity_score"] if best else 0, threshold
                    )
                    continue

                # 合并 B2 规则扫描结果 + 相似度结果
                merged = {
                    **b2_item,
                    "similarity_score":         best["similarity_score"],
                    "matched_b2_case_id":        best["case_id"],
                    "matched_b2_case_name":      best["case_name"],
                    "matched_b2_case_code":      best["case_code"],
                    "matched_b2_case_date":      best["case_b2_date"],
                    "matched_b2_pattern_type":   best["pattern_type"],
                    "matched_b2_pattern_label":  best["pattern_label"],
                    "similarity_breakdown":      best["breakdown"],
                    "all_case_matches":          match_result.get("all_matches", []),
                }
                matched_results.append(merged)

            except Exception as e:
                logger.warning("[B2Match] 评分 %s 失败: %s", code, e)

        # 按相似度从高到低排序
        matched_results.sort(key=lambda x: x["similarity_score"], reverse=True)

        print(
            f"[B2Match] 相似度评分完成，{len(matched_results)} 只达到阈值 {threshold}%\n",
            flush=True,
        )
        return matched_results

    # ──────────────── 完整扫描流程（规则扫描 + 图形匹配） ─────────────────────

    def run_full_scan(
        self,
        stock_list: list,
        progress_callback=None,
        min_similarity: float = None,
    ) -> dict:
        """
        完整 B2 图形匹配流程：规则扫描 → 相似度评分 → 排序

        步骤：
          1. 调用 B2PatternLibrary.scan_all() 执行全市场规则扫描
          2. 对命中股票提取 B2 前特征窗口，计算与案例库的相似度
          3. 按相似度排序，返回最终匹配列表

        Args:
            stock_list       : 待扫描股票代码列表
            progress_callback: 进度回调 fn(done, total, code)
            min_similarity   : 最低相似度阈值

        Returns:
            {
                "b2_hits"        : 规则扫描全部命中列表（不含相似度）
                "matched"        : 相似度过滤后排序列表（含相似度字段）
                "stock_data_dict": 命中股票原始 DataFrame 字典
            }
        """
        # 延迟导入，避免循环引用
        from strategy.b2_strategy import B2PatternLibrary as B2RuleLibrary

        print("[B2Match] 阶段1 - B2 规则扫描...", flush=True)
        rule_lib = B2RuleLibrary()
        b2_hits = rule_lib.scan_all(self.csv_manager.list_all_stocks()
                                    if stock_list is None else stock_list,
                                    self.csv_manager,
                                    progress_callback)
        stock_data_dict = getattr(rule_lib, "_stock_data_dict", {})

        if not b2_hits:
            print("[B2Match] 规则扫描无命中，流程结束", flush=True)
            return {"b2_hits": [], "matched": [], "stock_data_dict": {}}

        print(f"[B2Match] 规则扫描命中 {len(b2_hits)} 只", flush=True)

        if not self.cases:
            print("[B2Match] 案例库为空，跳过相似度评分，直接返回规则扫描结果", flush=True)
            return {"b2_hits": b2_hits, "matched": b2_hits, "stock_data_dict": stock_data_dict}

        print("[B2Match] 阶段2 - 相似度评分...", flush=True)
        matched = self.scan_with_match(b2_hits, stock_data_dict, min_similarity)

        return {
            "b2_hits":         b2_hits,
            "matched":         matched,
            "stock_data_dict": stock_data_dict,
        }
