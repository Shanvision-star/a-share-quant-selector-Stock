"""
策略模块

自动注册所有策略类
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入策略
from strategy.b1_case_analyzer import B1CaseAnalyzer, B1CaseStrategy
from strategy.bowl_rebound import BowlReboundStrategy

# 策略类映射
STRATEGIES = {
    'B1CaseStrategy': B1CaseStrategy,
    'B1CaseAnalyzer': B1CaseAnalyzer,
    'BowlReboundStrategy': BowlReboundStrategy,
}

__all__ = [
    'B1CaseStrategy',
    'B1CaseAnalyzer',
    'BowlReboundStrategy',
    'STRATEGIES'
]
