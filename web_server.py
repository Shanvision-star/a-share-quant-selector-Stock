"""
Web 服务器 - A股量化选股系统前端
"""
from flask import Flask, render_template, jsonify, request, send_from_directory
import json
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from strategy.strategy_registry import get_registry

app = Flask(__name__, 
            template_folder='web/templates',
            static_folder='web/static')

# 全局实例
csv_manager = CSVManager("data")
registry = get_registry("config/strategy_params.yaml")

# 加载策略
registry.auto_register_from_directory("strategy")


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/stocks')
def get_stocks():
    """获取股票列表"""
    try:
        stocks = csv_manager.list_all_stocks()
        
        # 加载股票名称
        names_file = Path("data/stock_names.json")
        stock_names = {}
        if names_file.exists():
            with open(names_file, 'r', encoding='utf-8') as f:
                stock_names = json.load(f)
        
        # 获取每只股票的基本信息 - 支持分页
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 500))  # 默认每页500只
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_stocks = stocks[start_idx:end_idx]
        
        stock_list = []
        for code in paginated_stocks:
            df = csv_manager.read_stock(code)
            if not df.empty:
                latest = df.iloc[0]
                stock_list.append({
                    'code': code,
                    'name': stock_names.get(code, '未知'),
                    'latest_price': round(latest['close'], 2),
                    'latest_date': latest['date'].strftime('%Y-%m-%d'),
                    'market_cap': round(latest.get('market_cap', 0) / 1e8, 2),  # 总市值，单位：亿
                    'data_count': len(df)
                })
        
        return jsonify({
            'success': True, 
            'data': stock_list, 
            'total': len(stocks),
            'page': page,
            'per_page': per_page,
            'total_pages': (len(stocks) + per_page - 1) // per_page
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/stock/<code>')
def get_stock_detail(code):
    """获取单只股票详情"""
    try:
        df = csv_manager.read_stock(code)
        if df.empty:
            return jsonify({'success': False, 'error': '股票不存在'})
        
        # 计算KDJ指标
        from utils.technical import KDJ
        kdj_df = KDJ(df, n=9, m1=3, m2=3)
        
        # 转换为列表格式
        data = []
        for i, (_, row) in enumerate(df.head(100).iterrows()):  # 返回最近100条
            data.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'open': round(row['open'], 2),
                'high': round(row['high'], 2),
                'low': round(row['low'], 2),
                'close': round(row['close'], 2),
                'volume': int(row['volume']),
                'amount': round(row['amount'] / 1e4, 2),  # 万元
                'turnover': round(row.get('turnover', 0), 2),
                'market_cap': round(row.get('market_cap', 0) / 1e8, 2),  # 总市值，单位：亿
                'K': round(kdj_df.iloc[i]['K'], 2),
                'D': round(kdj_df.iloc[i]['D'], 2),
                'J': round(kdj_df.iloc[i]['J'], 2)
            })
        
        return jsonify({'success': True, 'code': code, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/select')
def run_selection():
    """执行选股"""
    try:
        stock_codes = csv_manager.list_all_stocks()
        
        # 加载股票名称
        names_file = Path("data/stock_names.json")
        stock_names = {}
        if names_file.exists():
            with open(names_file, 'r', encoding='utf-8') as f:
                stock_names = json.load(f)
        
        # 构建数据字典
        stock_data = {}
        for code in stock_codes:
            df = csv_manager.read_stock(code)
            if not df.empty and len(df) >= 60:
                stock_data[code] = (stock_names.get(code, '未知'), df)
        
        # 执行选股
        results = {}
        for strategy_name, strategy in registry.strategies.items():
            signals = []
            for code, (name, df) in stock_data.items():
                result = strategy.analyze_stock(code, name, df)
                if result:
                    signals.append({
                        'code': result['code'],
                        'name': result.get('name', stock_names.get(code, '未知')),
                        'signals': result['signals']
                    })
            results[strategy_name] = signals
        
        return jsonify({'success': True, 'data': results, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/strategies')
def get_strategies():
    """获取策略列表"""
    try:
        strategies = []
        for name, strategy in registry.strategies.items():
            strategies.append({
                'name': name,
                'params': strategy.params
            })
        return jsonify({'success': True, 'data': strategies})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/stats')
def get_stats():
    """获取系统统计信息"""
    try:
        stocks = csv_manager.list_all_stocks()
        
        # 计算数据日期范围
        dates = []
        for code in stocks[:50]:  # 采样
            df = csv_manager.read_stock(code)
            if not df.empty:
                dates.append(df.iloc[0]['date'])
        
        latest_date = max(dates).strftime('%Y-%m-%d') if dates else '-'
        
        return jsonify({
            'success': True,
            'data': {
                'total_stocks': len(stocks),
                'latest_date': latest_date,
                'strategies': len(registry.strategies)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置"""
    try:
        config_file = Path("config/strategy_params.yaml")
        if config_file.exists():
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return jsonify({'success': True, 'data': config})
        return jsonify({'success': False, 'error': '配置文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/config', methods=['POST'])
def update_config():
    """更新配置"""
    try:
        import yaml
        new_config = request.json
        
        config_file = Path("config/strategy_params.yaml")
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(new_config, f, allow_unicode=True)
        
        # 重新加载策略
        global registry
        registry = get_registry("config/strategy_params.yaml")
        registry.auto_register_from_directory("strategy")
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/backtest', methods=['POST'])
def run_backtest():
    """
    执行回测
    Request JSON:
      stock_code   - 股票代码
      start_date   - 开始日期 YYYY-MM-DD
      end_date     - 结束日期 YYYY-MM-DD
      hold_days    - 持仓天数（默认5）
      stop_loss_pct- 止损百分比（默认10）
    """
    try:
        data = request.json or {}
        stock_code = data.get('stock_code', '').strip()
        start_date = data.get('start_date', '')
        end_date = data.get('end_date', '')
        hold_days = max(1, int(data.get('hold_days', 5)))
        stop_loss_pct = float(data.get('stop_loss_pct', 10.0))

        if not stock_code:
            return jsonify({'success': False, 'error': '请输入股票代码'})

        # 读取股票数据
        df = csv_manager.read_stock(stock_code)
        if df.empty:
            return jsonify({'success': False, 'error': f'股票 {stock_code} 数据不存在，请先初始化数据'})

        # 加载股票名称
        names_file = Path("data/stock_names.json")
        stock_names = {}
        if names_file.exists():
            with open(names_file, 'r', encoding='utf-8') as f:
                stock_names = json.load(f)
        stock_name = stock_names.get(stock_code, '未知')

        # 计算技术指标（一次性在全量数据上计算，避免重复计算）
        from strategy.bowl_rebound import BowlReboundStrategy
        strategy = BowlReboundStrategy()
        df_indicators = strategy.calculate_indicators(df)
        # 确保 date 列是 datetime 类型
        df_indicators['date'] = pd.to_datetime(df_indicators['date'])

        # 解析日期范围
        start_dt = pd.to_datetime(start_date) if start_date else df_indicators['date'].min()
        end_dt = pd.to_datetime(end_date) if end_date else df_indicators['date'].max()

        period_df = df_indicators[
            (df_indicators['date'] >= start_dt) & (df_indicators['date'] <= end_dt)
        ]
        if period_df.empty:
            return jsonify({'success': False, 'error': '指定日期范围内没有数据'})

        # 按日期升序排列，逐日回测
        period_dates = sorted(period_df['date'].tolist())

        trades = []
        occupied_until = None  # 当前持仓到期日期

        for signal_date in period_dates:
            # 持仓期间跳过
            if occupied_until is not None and signal_date <= occupied_until:
                continue

            # 取截至 signal_date 的历史数据（降序，与策略期望格式一致）
            hist_df = df_indicators[df_indicators['date'] <= signal_date]
            if len(hist_df) < 60:
                continue

            # 运行策略选股逻辑
            signals = strategy.select_stocks(hist_df, stock_name)
            if not signals:
                continue

            # 找下一个交易日作为入场日
            future_df = df_indicators[
                df_indicators['date'] > signal_date
            ].sort_values('date', ascending=True)

            if future_df.empty:
                continue

            entry_row = future_df.iloc[0]
            entry_price = float(entry_row['open'])
            entry_date = entry_row['date']

            # 持仓期候选行（升序）
            hold_candidates = future_df.head(hold_days)

            actual_exit_row = hold_candidates.iloc[-1]
            stopped = False

            for _, hrow in hold_candidates.iterrows():
                low_pct = (float(hrow['low']) - entry_price) / entry_price * 100
                if low_pct <= -stop_loss_pct:
                    actual_exit_row = hrow
                    stopped = True
                    break

            exit_price = float(actual_exit_row['close'])
            exit_date = actual_exit_row['date']
            return_pct = (exit_price - entry_price) / entry_price * 100
            hold_actual = int((exit_date - entry_date).days)

            signal_info = signals[0]
            trades.append({
                'signal_date': signal_date.strftime('%Y-%m-%d'),
                'entry_date': entry_date.strftime('%Y-%m-%d'),
                'entry_price': round(entry_price, 2),
                'exit_date': exit_date.strftime('%Y-%m-%d'),
                'exit_price': round(exit_price, 2),
                'return_pct': round(return_pct, 2),
                'hold_days': hold_actual,
                'stopped': stopped,
                'category': signal_info.get('category', ''),
                'reasons': signal_info.get('reasons', []),
            })

            occupied_until = exit_date

        # 计算汇总指标
        if trades:
            returns = [t['return_pct'] for t in trades]
            win_trades = [r for r in returns if r > 0]
            win_rate = len(win_trades) / len(trades) * 100
            avg_return = sum(returns) / len(returns)
            # 累计收益（简单叠加，非复利）
            total_return = sum(returns)
            max_win = max(returns)
            max_loss = min(returns)
        else:
            win_rate = avg_return = total_return = max_win = max_loss = 0.0

        return jsonify({
            'success': True,
            'data': {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'start_date': start_dt.strftime('%Y-%m-%d'),
                'end_date': end_dt.strftime('%Y-%m-%d'),
                'trades': trades,
                'metrics': {
                    'total_trades': len(trades),
                    'win_rate': round(win_rate, 1),
                    'avg_return': round(avg_return, 2),
                    'total_return': round(total_return, 2),
                    'max_win': round(max_win, 2),
                    'max_loss': round(max_loss, 2),
                }
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


def run_web_server(host='0.0.0.0', port=5000, debug=False):
    """启动Web服务器"""
    print(f"🌐 启动Web服务器: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_web_server(debug=True)


# --- Replay / 复盘图示 区域 ---
@app.route('/replay')
def replay_ui():
    """复盘图示页面：可以粘贴或拖拽K线图像，并保存展示"""
    return render_template('replay.html')


@app.route('/api/replay/upload', methods=['POST'])
def replay_upload():
    """接收上传的图片（multipart/form-data, field name 'image'）并保存到 data/replay 。"""
    try:
        upload_dir = Path('data/replay')
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 支持文件字段 'image' 或者二进制粘贴（作为文件）
        if 'image' in request.files:
            f = request.files['image']
            filename = f.filename or f"replay_{int(datetime.now().timestamp())}.png"
            save_path = upload_dir / filename
            f.save(str(save_path))
        else:
            # 也支持 base64 字符串（json 字段 'data'）
            payload = request.get_json(silent=True) or {}
            b64 = payload.get('data')
            if not b64:
                return jsonify({'success': False, 'error': '没有找到图片数据'})
            import base64
            header, _, data = b64.partition(',')
            ext = 'png' if 'png' in header else 'jpg'
            filename = f"replay_{int(datetime.now().timestamp())}.{ext}"
            save_path = upload_dir / filename
            with open(save_path, 'wb') as out:
                out.write(base64.b64decode(data))

        return jsonify({'success': True, 'url': f"/replay_images/{filename}"})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/replay_images/<path:filename>')
def replay_images(filename):
    """Serve uploaded replay images from data/replay."""
    upload_dir = Path('data/replay')
    return send_from_directory(str(upload_dir), filename)
