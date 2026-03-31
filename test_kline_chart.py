#!/usr/bin/env python3
"""
K线图功能测试脚本
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, '/root/quant-csv')

from utils.kline_chart import generate_kline_chart

print("=" * 60)
print("K线图功能测试")
print("=" * 60)

# 测试1: 模块导入测试
print("\n[TEST 1] 模块导入测试...")
try:
    from utils.kline_chart import generate_kline_chart
    print("✅ K线图模块导入成功")
except Exception as e:
    print(f"❌ 模块导入失败: {e}")
    sys.exit(1)

# 测试2: 生成测试数据
print("\n[TEST 2] 生成测试数据...")
try:
    # 生成模拟K线数据
    np.random.seed(42)
    dates = pd.date_range(end=datetime.now(), periods=20, freq='D')
    
    base_price = 10.5
    test_data = []
    for i in range(20):
        # 生成合理的OHLC数据
        open_price = base_price + np.random.randn() * 0.1
        close_price = open_price + np.random.randn() * 0.15
        high_price = max(open_price, close_price) + abs(np.random.randn()) * 0.05
        low_price = min(open_price, close_price) - abs(np.random.randn()) * 0.05
        volume = 500000 + np.random.randint(0, 300000)
        
        test_data.append({
            'date': dates[i],
            'open': round(open_price, 2),
            'close': round(close_price, 2),
            'high': round(high_price, 2),
            'low': round(low_price, 2),
            'volume': volume,
            'short_term_trend': round(base_price + i * 0.02, 2),
            'bull_bear_line': round(base_price - 0.3 + i * 0.015, 2),
        })
        base_price = close_price
    
    test_df = pd.DataFrame(test_data)
    print(f"✅ 测试数据生成成功: {len(test_df)} 条记录")
    print(f"   日期范围: {test_df['date'].min()} ~ {test_df['date'].max()}")
except Exception as e:
    print(f"❌ 测试数据生成失败: {e}")
    sys.exit(1)

# 测试3: 生成K线图
print("\n[TEST 3] 生成K线图...")
try:
    test_params = {
        'N': 2.4,
        'M': 20,
        'CAP': 4000000000,
        'J_VAL': 30,
        'duokong_pct': 3,
        'short_pct': 2
    }
    
    key_dates = [test_df.iloc[5]['date'], test_df.iloc[12]['date']]
    
    output_path = generate_kline_chart(
        stock_code='000001',
        stock_name='Test Stock',
        df=test_df,
        category='bowl_center',
        params=test_params,
        key_candle_dates=key_dates,
        output_dir='/tmp/kline_charts'
    )
    
    if Path(output_path).exists():
        file_size = Path(output_path).stat().st_size / 1024
        print(f"✅ K线图生成成功")
        print(f"   文件路径: {output_path}")
        print(f"   文件大小: {file_size:.1f} KB")
    else:
        print(f"❌ 文件未生成")
        sys.exit(1)
except Exception as e:
    print(f"❌ K线图生成失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试4: 测试不同分类
print("\n[TEST 4] 测试不同分类...")
categories = ['bowl_center', 'near_duokong', 'near_short_trend']
for cat in categories:
    try:
        path = generate_kline_chart(
            stock_code='000002',
            stock_name='Test Stock 2',
            df=test_df,
            category=cat,
            params=test_params,
            key_candle_dates=key_dates,
            output_dir='/tmp/kline_charts'
        )
        print(f"   ✅ {cat}: {Path(path).name}")
    except Exception as e:
        print(f"   ❌ {cat}: {e}")

# 测试5: 测试DingTalkNotifier集成
print("\n[TEST 5] 测试DingTalkNotifier集成...")
try:
    from utils.dingtalk_notifier import DingTalkNotifier, KLINE_CHART_AVAILABLE
    
    if KLINE_CHART_AVAILABLE:
        print("✅ K线图模块已在DingTalkNotifier中可用")
    else:
        print("⚠️ K线图模块在DingTalkNotifier中不可用")
    
    # 检查新方法是否存在
    notifier = DingTalkNotifier()
    if hasattr(notifier, 'send_image'):
        print("✅ send_image 方法已添加")
    else:
        print("❌ send_image 方法未找到")
        
    if hasattr(notifier, 'send_stock_selection_with_charts'):
        print("✅ send_stock_selection_with_charts 方法已添加")
    else:
        print("❌ send_stock_selection_with_charts 方法未找到")
        
except Exception as e:
    print(f"❌ DingTalkNotifier测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成!")
print("=" * 60)
print(f"\n生成的图表文件:")
for f in sorted(Path('/tmp/kline_charts').glob('*.png'))[-5:]:
    print(f"  - {f.name} ({f.stat().st_size/1024:.1f} KB)")
