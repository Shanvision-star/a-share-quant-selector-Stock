"""
B1完美图形配置管理
新增案例只需在这里添加配置，无需改代码
为后续B2、B3等扩展预留空间

配置优先级：
1. 首先读取 config/strategy_params.yaml 中的 B1PatternMatch 配置
2. 如果YAML中未配置，使用本文件中的默认值
"""

import yaml
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_yaml_config():
    """从YAML配置文件加载B1PatternMatch配置"""
    config_path = BASE_DIR / "config" / "strategy_params.yaml"
    
    if not config_path.exists():
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get('B1PatternMatch', {})
    except Exception as e:
        print(f"⚠️ 加载B1PatternMatch配置失败: {e}，使用默认值")
        return {}


# 加载YAML配置
_yaml_config = _load_yaml_config()

# B1完美图形案例配置（12个历史成功案例，其中含1个阶段型案例）
# 注：日期为"选股系统选出的买入日期"，不是突破日
B1_PERFECT_CASES = [
    {
        "id": "case_001",
        "name": "华纳药厂",
        "code": "688799",
        "breakout_date": "2025-05-12",
        "lookback_days": 25,
        "tags": ["科创板", "医药"],
        "description": "杯型整理+缩量+J值低位",
    },
    {
        "id": "case_002",
        "name": "宁波韵升",
        "code": "600366",
        "breakout_date": "2025-08-06",
        "lookback_days": 25,
        "tags": ["主板", "稀土永磁"],
        "description": "回落短期趋势线+量能平稳+J值中位",
    },
    {
        "id": "case_003",
        "name": "微芯生物",
        "code": "688321",
        "breakout_date": "2025-06-20",
        "lookback_days": 25,
        "tags": ["科创板", "医药"],
        "description": "平台整理+缩量后放量+J值低位",
    },
    {
        "id": "case_004",
        "name": "方正科技",
        "code": "600601",
        "breakout_date": "2025-07-23",
        "lookback_days": 25,
        "tags": ["主板", "科技"],
        "description": "靠近多空线+量能平稳+J值中位",
    },
    {
        "id": "case_005",
        "name": "澄天伟业",
        "code": "300689",
        "breakout_date": "2025-07-15",
        "lookback_days": 25,
        "tags": ["创业板", "芯片"],
        "description": "持续缩量+价格震荡+J值低位",
    },
    {
        "id": "case_006",
        "name": "国轩高科",
        "code": "002074",
        "breakout_date": "2025-08-04",
        "lookback_days": 25,
        "tags": ["中小板", "新能源"],
        "description": "靠近短期趋势线+量能平稳+J值低位",
    },
    {
        "id": "case_007",
        "name": "野马电池",
        "code": "605378",
        "breakout_date": "2025-08-01",
        "lookback_days": 25,
        "tags": ["主板", "电池"],
        "description": "持续缩量+J值深度低位+趋势下行",
    },
    {
        "id": "case_008",
        "name": "光电股份",
        "code": "600184",
        "breakout_date": "2025-07-10",
        "lookback_days": 25,
        "tags": ["主板", "军工"],
        "description": "缩量后放量+J值低位+趋势上行",
    },
    {
        "id": "case_009",
        "name": "新瀚新材",
        "code": "301076",
        "breakout_date": "2025-08-01",
        "lookback_days": 25,
        "tags": ["创业板", "化工"],
        "description": "缩量后放量+价格接近短期趋势线+J值中位",
    },
    {
        "id": "case_010",
        "name": "昂利康",
        "code": "002940",
        "breakout_date": "2025-07-11",
        "lookback_days": 25,
        "tags": ["中小板", "医药"],
        "description": "价格接近短期趋势线+缩量+顶部未放量",
    },
    {
        "id": "case_011",
        "name": "航天发展",
        "code": "000547",
        "breakout_date": "2025-11-12",
        "lookback_days": 25,
        "tags": ["主板", "军工"],
        "description": "航天军工+量能异动+趋势突破",
    },
]

# B1阶段型案例配置
# 这类案例用于表达多阶段完美图形，不参与原始特征向量库缓存，
# 但会在B1匹配结果中作为补充命中信息输出。
B1_STAGE_CASES = [
    {
        "id": "stage_case_001",
        "name": "掌阅科技",
        "code": "603533",
        "case_date": "2026-02-06",
        "buy_date": "2026-02-09",
        "lookback_days": 80,
        "tags": ["主板", "文化传媒", "阶段型B1"],
        "description": "低位KDJ触发+护盘+三连涨+洗盘守低+回踩知行多空线后大阳启动",
        "analysis_config": {
            "anchor_date": "2025-11-17",
            "reference_low_date": "2025-10-17",
            "breakout_date": "2025-11-21",
            "washout_end_date": "2025-12-17",
            "revisit_date": "2026-02-06",
            "setup_window_days": 3,
            "buy_date": "2026-02-09",
            "anchor_kdj_field": "J",
            "anchor_kdj_max": 13,
            "no_break_days": 3,
            "guard_reference_field": "open",
            "guard_compare_field": "low",
            "breakout_min_pct": 4.0,
            "breakout_min_streak": 3,
            "washout_compare_field": "close",
            "revisit_line_field": "bull_bear_line",
            "revisit_band_pct": 3.0,
            "revisit_kdj_field": "J",
            "revisit_kdj_max": 20.0,
            "buy_compare_field": "close",
            "buy_trigger_min_pct": 9.5,
            "buy_breakout_lookback_days": 5,
            "short_pct": 2.0,
            "duokong_pct": 3.0,
            "M1": 14,
            "M2": 28,
            "M3": 57,
            "M4": 114,
        },
    },
]

# 相似度权重配置（优先从YAML读取，否则使用默认值）
_default_weights = {
    "trend_structure": 0.30,    # 知行趋势线结构
    "kdj_state": 0.20,          # KDJ动能状态
    "volume_pattern": 0.25,     # 量能特征
    "price_shape": 0.25,        # 价格形态
}
SIMILARITY_WEIGHTS = _yaml_config.get('weights', _default_weights)

# 匹配阈值（低于此值不显示）
MIN_SIMILARITY_SCORE = _yaml_config.get('min_similarity', 60.0)

# 回看天数（默认25天）
DEFAULT_LOOKBACK_DAYS = _yaml_config.get('lookback_days', 25)

# Top N 结果展示（优先从YAML读取）
TOP_N_RESULTS = _yaml_config.get('top_n_results', 15)

# B1匹配性能与容错开关
# auto_fallback_to_classic: B1阶段出错时自动回退到原始选股模式
# max_candidates: B1匹配最大候选数（按J值升序优先）
# match_workers: B1并发匹配线程数（0表示自动）
# prefilter_by_j: 是否在裁剪候选前按J值升序预筛
AUTO_FALLBACK_TO_CLASSIC = _yaml_config.get('auto_fallback_to_classic', True)
B1_MATCH_MAX_CANDIDATES = _yaml_config.get('max_candidates', 400)
B1_MATCH_WORKERS = _yaml_config.get('match_workers', 0)
B1_PREFILTER_BY_J = _yaml_config.get('prefilter_by_j', True)

# 匹配容差参数（优先从YAML读取）
_default_tolerances = {
    "trend_ratio": 0.10,    # 趋势比值容差（±10%）
    "price_bias": 10,       # 价格偏离容差（±10%）
    "trend_spread": 10,     # 趋势发散容差（±10%）
    "j_value": 30,          # J值差异容差（±30）
    "drawdown": 15,         # 回撤幅度容差（±15%）
}
MATCH_TOLERANCES = _yaml_config.get('tolerances', _default_tolerances)
