"""
完美图形库管理 - 预计算案例特征，支持动态扩展
"""
import json
import pandas as pd
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategy.pattern_config import B1_PERFECT_CASES, B1_STAGE_CASES, SIMILARITY_WEIGHTS, MIN_SIMILARITY_SCORE
from strategy.b1_case_analyzer import B1CaseStrategy
from strategy.pattern_feature_extractor import PatternFeatureExtractor
from strategy.pattern_matcher import PatternMatcher


BASE_DIR = Path(__file__).resolve().parent.parent


class B1PatternLibrary:
    """
    B1完美图形库
    - 预计算历史成功案例的特征向量
    - 支持序列化/反序列化（缓存）
    - 支持动态添加新案例
    - 为B2、B3等扩展预留空间
    """
    
    CACHE_FILE = BASE_DIR / "data" / "b1_pattern_library_cache.json"
    CACHE_VERSION = 2
    
    def __init__(self, csv_manager):
        self.csv_manager = csv_manager
        self.extractor = PatternFeatureExtractor()
        self.matcher = PatternMatcher(SIMILARITY_WEIGHTS)
        self.case_analyzer = B1CaseStrategy()
        self.cases = {}  # {case_id: {meta, features}}
        
        # 尝试从缓存加载，否则重新计算
        if not self._load_from_cache():
            self._build_library()

    def _expected_case_signatures(self):
        """返回当前配置的案例签名，用于缓存一致性校验。"""
        return {
            case["id"]: {
                "code": case["code"],
                "breakout_date": case["breakout_date"],
                "lookback_days": case["lookback_days"],
            }
            for case in B1_PERFECT_CASES
        }
    
    def _build_library(self):
        """从本地CSV构建案例库"""
        print("[BUILD] 构建B1完美图形库...")
        
        for case in B1_PERFECT_CASES:
            try:
                df = self.csv_manager.read_stock(case["code"])
                
                if df.empty:
                    print(f"  [WARN] 跳过 {case['name']}({case['code']}): 无数据")
                    continue
                
                # 提取突破日期窗口的数据
                window_df = self._extract_window(df, case["breakout_date"], case["lookback_days"])
                
                if window_df.empty or len(window_df) < 10:
                    print(f"  [WARN] 跳过 {case['name']}: 日期 {case['breakout_date']} 附近数据不足")
                    continue
                
                # 提取特征
                features = self.extractor.extract(window_df)
                
                self.cases[case["id"]] = {
                    "meta": case,
                    "features": features,
                }
                print(f"  [OK] {case['name']} - 特征提取完成")
                
            except Exception as e:
                print(f"  [ERROR] {case['name']} 处理失败: {e}")
                continue
        
        # 保存缓存
        if self.cases:
            self._save_to_cache()
            print(f"[DONE] 案例库构建完成: {len(self.cases)} 个案例")
        else:
            print("[WARN] 没有成功加载任何案例")
    
    def _extract_window(self, df: pd.DataFrame, breakout_date: str, lookback_days: int):
        """提取突破日期前lookback天的数据（不包含突破当天）"""
        df = df.copy()
        
        # 确保date列是datetime
        if not pd.api.types.is_datetime64_any_dtype(df['date']):
            df['date'] = pd.to_datetime(df['date'])
        
        breakout_dt = pd.to_datetime(breakout_date)
        
        # 取突破日期之前的数据（不包含突破当天）
        # 这样才能捕捉到"突破前"的整理形态
        mask = df['date'] < breakout_dt
        filtered = df[mask]
        
        # 取breakout_date之前lookback_days天
        return filtered.head(lookback_days)
    
    def find_best_match(self, stock_code: str, stock_df: pd.DataFrame, lookback_days: int = 25) -> dict:
        """
        为单只股票找到最匹配的B1完美图形案例
        
        Args:
            stock_code: 股票代码
            stock_df: 股票数据
            lookback_days: 回看天数，默认25天
        """
        if not self.cases:
            return {
                "stock_code": stock_code,
                "best_match": None,
                "all_matches": [],
                "candidate_features": {},
                "best_stage_case": None,
                "stage_case_matches": [],
            }
        
        # 提取候选股特征（使用指定回看天数）
        candidate_features = self.extractor.extract(stock_df, lookback_days=lookback_days)
        
        # 与所有案例对比
        matches = []
        for case_id, case_data in self.cases.items():
            try:
                similarity = self.matcher.match(
                    candidate_features,
                    case_data["features"]
                )
                
                matches.append({
                    "case_id": case_id,
                    "case_name": case_data["meta"]["name"],
                    "case_date": case_data["meta"]["breakout_date"],
                    "case_code": case_data["meta"]["code"],
                    "similarity_score": similarity["total_score"],
                    "breakdown": similarity["breakdown"],
                    "tags": case_data["meta"].get("tags", []),
                })
            except Exception as e:
                print(f"  [WARN] 匹配 {case_id} 失败: {e}")
                continue
        
        # 按相似度排序
        matches.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        # 返回最佳匹配和所有匹配
        best_match = matches[0] if matches else None
        stage_case_matches = self._analyze_stage_cases(stock_code, stock_df)
        best_stage_case = stage_case_matches[0] if stage_case_matches else None

        # 前瞻扫描：全市场阶段1-5扫描，不依赖固定日期，买点尚未出现时提前预警
        pre_signal = self._scan_b1_pre_signal(stock_code, stock_df)

        return {
            "stock_code": stock_code,
            "best_match": best_match,
            "all_matches": matches,
            "candidate_features": candidate_features,
            "best_stage_case": best_stage_case,
            "stage_case_matches": stage_case_matches,
            "pre_signal": pre_signal,
        }

    def _analyze_stage_cases(self, stock_code: str, stock_df: pd.DataFrame) -> list:
        """分析阶段型B1案例，作为相似度匹配之外的补充命中。"""
        stage_matches = []

        for stage_case in B1_STAGE_CASES:
            # 阶段型案例包含固定历史日期时，只对模板股票本身执行，
            # 避免在全市场扫描中对无关股票进行“按日期硬匹配”。
            template_code = stage_case.get("code")
            if template_code and str(template_code) != str(stock_code):
                continue

            try:
                analysis = self.case_analyzer.analyze(stock_df, stage_case.get("analysis_config"))
                if not analysis.get("passed"):
                    continue

                summary = self.case_analyzer.summarize(analysis)
                stage_matches.append({
                    "case_id": stage_case["id"],
                    "case_name": stage_case["name"],
                    "case_code": stage_case["code"],
                    "case_date": stage_case.get("case_date", stage_case["buy_date"]),
                    "buy_date": stage_case["buy_date"],
                    "lookback_days": stage_case.get("lookback_days"),
                    "description": stage_case.get("description", ""),
                    "tags": stage_case.get("tags", []),
                    "analysis": analysis,
                    "summary": summary,
                })
            except Exception as e:
                print(f"  [WARN] 阶段型B1分析 {stock_code} -> {stage_case['name']} 失败: {e}")

        stage_matches.sort(
            key=lambda item: (
                item.get("summary", {}).get("support_lookback_days") or 0,
                item.get("summary", {}).get("anchor_lookback_days") or 0,
            ),
            reverse=True,
        )
        return stage_matches

    def _scan_b1_pre_signal(self, stock_code: str, stock_df) -> dict:
        """
        全市场前瞻扫描：动态查找B1阶段1-5结构（不依赖固定日期）。
        阶段6(大阳买点)尚未发生时就能提前预警，这样才能在启动前介入。

        与 _analyze_stage_cases 的区别：
          - 不需要模板固定日期，适用于所有股票
          - 只要阶段1-5全通过就返回预买入信号
          - 阶段6标记为"待确认(pending)"
        """
        try:
            result = self.case_analyzer.scan_pre_signal(stock_df, lookback_days=80)
            return result
        except Exception as e:
            return {
                'detected': False,
                'stage_passed': {},
                'anchor_date': None,
                'anchor_j': None,
                'setup_window_start': None,
                'current_j': None,
                'current_dist_pct': None,
                'support_price': None,
                'pending': 'buy_signal',
                'message': f'scan_error: {e}',
            }

        """
        批量匹配多只股票
        stocks_data: [{code, df, stock_info}, ...]
        """
        results = []
        
        for stock in stocks_data:
            try:
                match_result = self.find_best_match(stock["code"], stock["df"])
                
                if match_result["best_match"]:
                    results.append({
                        "stock_code": stock["code"],
                        "stock_name": stock.get("name", ""),
                        **match_result,
                        **stock.get("info", {}),
                    })
            except Exception as e:
                print(f"  [WARN] 匹配 {stock['code']} 失败: {e}")
                continue
        
        # 按相似度排序
        results.sort(key=lambda x: x["best_match"]["similarity_score"] if x.get("best_match") else 0, reverse=True)
        
        return results
    
    def add_case(self, case_config: dict):
        """动态添加新案例"""
        try:
            # 重新计算该案例特征
            df = self.csv_manager.read_stock(case_config["code"])
            window_df = self._extract_window(
                df, 
                case_config["breakout_date"], 
                case_config.get("lookback_days", 25)
            )
            features = self.extractor.extract(window_df)
            
            self.cases[case_config["id"]] = {
                "meta": case_config,
                "features": features,
            }
            
            # 更新缓存
            self._save_to_cache()
            print(f"[OK] 新增案例: {case_config['name']}")
            
        except Exception as e:
            print(f"[ERROR] 添加案例失败: {e}")
    
    def remove_case(self, case_id: str):
        """移除案例"""
        if case_id in self.cases:
            del self.cases[case_id]
            self._save_to_cache()
            print(f"[OK] 移除案例: {case_id}")
    
    def list_cases(self):
        """列出所有案例"""
        return [
            {
                "id": case_id,
                "name": data["meta"]["name"],
                "code": data["meta"]["code"],
                "date": data["meta"]["breakout_date"],
            }
            for case_id, data in self.cases.items()
        ]
    
    def _save_to_cache(self):
        """序列化案例库到缓存"""
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

            cache_cases = {}
            for case_id, case_data in self.cases.items():
                cache_cases[case_id] = {
                    "meta": case_data["meta"],
                    "features": self._serialize_features(case_data["features"]),
                }

            cache_data = {
                "_meta": {
                    "version": self.CACHE_VERSION,
                    "case_signatures": self._expected_case_signatures(),
                },
                "cases": cache_cases,
            }
            
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"[WARN] 缓存保存失败: {e}")
    
    def _load_from_cache(self) -> bool:
        """从缓存加载案例库"""
        if not self.CACHE_FILE.exists():
            return False
        
        try:
            with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            meta = cache_data.get("_meta", {})
            cache_cases = cache_data.get("cases")
            if cache_cases is None:
                return False

            if meta.get("version") != self.CACHE_VERSION:
                return False

            if meta.get("case_signatures") != self._expected_case_signatures():
                return False
            
            for case_id, data in cache_cases.items():
                self.cases[case_id] = {
                    "meta": data["meta"],
                    "features": self._deserialize_features(data["features"]),
                }
            
            print(f"[CACHE] 从缓存加载案例库: {len(self.cases)} 个案例")
            return True
            
        except Exception as e:
            print(f"[WARN] 缓存加载失败: {e}，将重新构建")
            return False
    
    def _serialize_features(self, features: dict) -> dict:
        """序列化特征（处理numpy数组）"""
        serialized = {}
        for key, value in features.items():
            if isinstance(value, dict):
                serialized[key] = self._serialize_features(value)
            elif isinstance(value, list):
                serialized[key] = value
            elif isinstance(value, np.ndarray):
                serialized[key] = value.tolist()
            elif isinstance(value, (np.integer, np.floating)):
                serialized[key] = float(value)
            elif isinstance(value, (bool, np.bool_)):
                serialized[key] = bool(value)
            elif isinstance(value, str):
                serialized[key] = value
            else:
                serialized[key] = value
        return serialized
    
    def _deserialize_features(self, features: dict) -> dict:
        """反序列化特征"""
        deserialized = {}
        for key, value in features.items():
            if isinstance(value, dict):
                deserialized[key] = self._deserialize_features(value)
            elif isinstance(value, list):
                deserialized[key] = np.array(value)
            else:
                deserialized[key] = value
        return deserialized
    
    def clear_cache(self):
        """清除缓存，强制重新构建"""
        if self.CACHE_FILE.exists():
            self.CACHE_FILE.unlink()
        self.cases = {}
        print("[CACHE] 缓存已清除")
