# utils/backtrack_analyzer.py
class BacktrackAnalyzer:
    def __init__(self):
        pass

    def filter_stocks(self, stock_list, j_max=20, max_drop=5, debug=False):
        """
        股票回溯筛选：KDJ-J值超卖 + 股价相对趋势线回落不超过指定比例
        :param stock_list: 待筛选股票列表，格式[(code, name, j_val, close, trend), ...]
        :param j_max: KDJ-J值上限，默认20（超卖区）
        :param max_drop: 最大向下回落比例(%)，默认5
        :param debug: 是否开启调试模式，打印每只股票筛选细节，默认False
        :return: 符合条件的股票字典列表，格式[{"code":xxx, "name":xxx, "j":xxx, "偏离%":xxx, "close":xxx}, ...]
        """
        # 初始化统计变量，定位筛选无结果原因
        total = len(stock_list)
        j_exceed = 0  #J值超标数量
        drop_exceed = 0  # 回落幅度超标数量
        error_count = 0  # 数据异常数量
        result = []

        print(f"🔍 筛选条件：J≤{j_max} | 向下回落 ≤ {max_drop}%")
        print(f"📊 待筛选股票总数：{total} 只")

        # 核心筛选逻辑
        for item in stock_list:
            try:
                # 解包股票数据，做非空校验
                code, name, j_val, close, trend = item
                if not all([code, name, j_val, close, trend]) or trend == 0:
                    error_count += 1
                    if debug:
                        print(f"⚠️  {code}-{name} 数据为空/趋势线为0，跳过")
                    continue

                # 1. KDJ-J值筛选
                if j_val > j_max:
                    j_exceed += 1
                    if debug:
                        print(f"❌  {code}-{name} J值={round(j_val,2)} > {j_max}，超标")
                    continue

                # 2. 股价回落幅度筛选（相对趋势线）
                deviation = (close - trend) / trend * 100  # 偏离度(%)
                if deviation < -max_drop:
                    drop_exceed += 1
                    if debug:
                        print(f"❌  {code}-{name} 偏离度={round(deviation,2)}% < -{max_drop}%，回落超标")
                    continue

                # 符合所有条件，加入结果集
                result.append({
                    "code": code,
                    "name": name,
                    "j": round(j_val, 2),
                    "偏离%": round(deviation, 2),
                    "close": round(close, 2)
                })
                if debug:
                    print(f"✅  {code}-{name} 符合条件 | J={round(j_val,2)} | 偏离度={round(deviation,2)}%")

            except Exception as e:
                error_count += 1
                if debug:
                    print(f"⚠️  股票{item}处理异常：{str(e)[:50]}，跳过")
                continue

        # 打印首轮筛选统计
        print(f"\n📈 首轮筛选统计：J值超标{j_exceed}只 | 回落超标{drop_exceed}只 | 数据异常{error_count}只")
        print(f"🎯 首轮筛选完成：符合条件 {len(result)} 只")

        # 自动兜底逻辑：首轮无结果时，放宽阈值二次筛选（J≤30 | 回落≤10%）
        if len(result) == 0 and total > error_count:
            print("\n==============================================")
            print("❌ 【回溯结果】无符合条件股票，自动执行兜底筛选")
            print("🔍 兜底筛选条件：J≤30 | 向下回落 ≤ 10%")
            print("==============================================")
            # 调用自身，使用兜底阈值重新筛选
            result = self.filter_stocks(stock_list, j_max=30, max_drop=10, debug=debug)

        # 最终无结果提示
        if len(result) == 0 and total > 0:
            print("\n❌ 【回溯结果】无符合条件股票")

        return result