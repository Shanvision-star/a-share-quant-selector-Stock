#!/usr/bin/env python3
"""
钉钉通知测试工具

用法:
    python3 tests/test_dingtalk.py              # 使用模拟数据测试
    python3 tests/test_dingtalk.py --real       # 执行真实选股并发送
    python3 tests/test_dingtalk.py --category bowl_center  # 只测试特定分类
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.dingtalk_notifier import DingTalkNotifier
import yaml


def load_dingtalk_config():
    """加载钉钉配置"""
    try:
        with open('config/config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        webhook = config.get('dingtalk', {}).get('webhook_url')
        secret = config.get('dingtalk', {}).get('secret')
        
        if not webhook:
            print("❌ 错误：未配置钉钉 webhook")
            print("请编辑 config/config.yaml 添加钉钉配置")
            return None, None
        
        return webhook, secret
    except Exception as e:
        print(f"❌ 读取配置失败: {e}")
        return None, None


def get_mock_results():
    """获取模拟选股结果"""
    return {
        'BowlReboundStrategy': [
            {
                'code': '000001',
                'name': '平安银行',
                'signals': [{
                    'date': datetime.now(),
                    'close': 10.5,
                    'J': 25.3,
                    'category': 'bowl_center',
                    'reasons': ['回落碗中'],
                    'key_candle_date': datetime(2026, 2, 10)
                }]
            },
            {
                'code': '000002',
                'name': '万科A',
                'signals': [{
                    'date': datetime.now(),
                    'close': 15.2,
                    'J': 28.1,
                    'category': 'near_duokong',
                    'reasons': ['靠近多空线(±3%)'],
                    'key_candle_date': datetime(2026, 2, 9)
                }]
            },
            {
                'code': '000333',
                'name': '美的集团',
                'signals': [{
                    'date': datetime.now(),
                    'close': 58.3,
                    'J': 22.5,
                    'category': 'near_short_trend',
                    'reasons': ['靠近短期趋势线(±2%)'],
                    'key_candle_date': datetime(2026, 2, 8)
                }]
            }
        ]
    }, {'000001': '平安银行', '000002': '万科A', '000333': '美的集团'}


def run_real_selection(category='all', max_stocks=None):
    """执行真实选股"""
    from main import QuantSystem
    
    print("🔄 正在执行真实选股...")
    quant = QuantSystem()
    
    # 更新数据
    print("📊 更新股票数据...")
    quant.update_data(max_stocks=max_stocks)
    
    # 执行选股
    print("🎯 执行选股策略...")
    results, stock_names = quant.select_stocks(category=category)
    
    return results, stock_names


def send_test_dingtalk(category='all', real=False, max_stocks=None):
    """
    发送测试钉钉消息
    
    :param category: 分类筛选
    :param real: 是否执行真实选股
    :param max_stocks: 限制处理的股票数量（用于测试）
    """
    # 加载钉钉配置
    webhook, secret = load_dingtalk_config()
    if not webhook:
        return False
    
    # 获取选股结果
    if real:
        results, stock_names = run_real_selection(category, max_stocks)
        if not results or not any(results.values()):
            print("⚠️ 没有选出股票，无法发送通知")
            return False
    else:
        results, stock_names = get_mock_results()
        print("ℹ️ 使用模拟数据进行测试")
    
    # 发送钉钉通知
    print(f"\n📤 正在发送钉钉通知（筛选: {category}）...")
    notifier = DingTalkNotifier(webhook, secret)
    success = notifier.send_stock_selection(results, stock_names, category_filter=category)
    
    if success:
        print("\n✅ 钉钉通知发送成功！")
        print("请查看钉钉群确认消息")
        return True
    else:
        print("\n❌ 钉钉通知发送失败")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='钉钉通知测试工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 tests/test_dingtalk.py                    # 模拟数据测试
  python3 tests/test_dingtalk.py --real             # 真实选股测试
  python3 tests/test_dingtalk.py --real --max-stocks 100   # 只处理100只股票
  python3 tests/test_dingtalk.py --real --category bowl_center  # 只测试碗中分类
        """
    )
    
    parser.add_argument(
        '--real',
        action='store_true',
        help='执行真实选股（否则使用模拟数据）'
    )
    
    parser.add_argument(
        '--category',
        choices=['all', 'bowl_center', 'near_duokong', 'near_short_trend'],
        default='all',
        help='分类筛选（默认all）'
    )
    
    parser.add_argument(
        '--max-stocks',
        type=int,
        default=None,
        help='限制处理的股票数量（用于快速测试）'
    )
    
    args = parser.parse_args()
    
    success = send_test_dingtalk(
        category=args.category,
        real=args.real,
        max_stocks=args.max_stocks
    )
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
