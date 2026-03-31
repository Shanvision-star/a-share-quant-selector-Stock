# utils/tdx_exporter.py
from pathlib import Path
from datetime import datetime

def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)

# ====================== 通达信标准格式转换（核心） ======================
def to_tdx_format(code: str) -> str:
    """
    通达信官方识别格式
    沪市(6)：SHXXXXXX
    深市(0/3)：SZXXXXXX
    北证(8)：BJXXXXXX
    """
    code = str(code).strip()
    if len(code) != 6:
        return ""
    if code.startswith("6"):
        return f"SH{code}"
    elif code.startswith(("0", "3")):
        return f"SZ{code}"
    elif code.startswith("8"):
        return f"BJ{code}"
    return ""

# 清洗股票代码（只保留6位数字）
def clean_stock_code(code: str) -> str:
    code = str(code).strip()
    digits = "".join([c for c in code if c.isdigit()])
    return digits if len(digits) == 6 else ""

# ====================== 可移植自动路径（随便复制到任何电脑） ======================
BASE_DIR = Path(__file__).parent.parent
TXT_OUTPUT_DIR = BASE_DIR / "data" / "txt"
ensure_dir(TXT_OUTPUT_DIR)

# 时间戳
def get_datetime_str():
    return datetime.now().strftime("%Y%m%d_%H%M")

# ====================== 1. 策略结果导出（通达信可用） ======================
def export_strategy_tdx(stock_code_list, strategy_name):
    valid_codes = [clean_stock_code(code) for code in stock_code_list if clean_stock_code(code)]
    if not valid_codes:
        print(f"📝 {strategy_name} 无股票，不生成TXT")
        return []

    time_str = get_datetime_str()
    filepath = TXT_OUTPUT_DIR / f"tdx_{strategy_name}_{time_str}.txt"

    # 编码=GBK | 每行1个代码 | 纯通达信格式
    with open(filepath, "w", encoding="gbk") as f:
        for code in valid_codes:
            tdx_code = to_tdx_format(code)
            if tdx_code:
                f.write(tdx_code + "\n")

    print(f"✅ 策略选股已导出：{filepath}")
    return valid_codes

# ====================== 2. 总汇总导出（通达信可用） ======================
def export_total_tdx(all_valid_codes):
    unique_codes = sorted(list(set([clean_stock_code(c) for c in all_valid_codes if clean_stock_code(c)])))
    if not unique_codes:
        print("📝 总汇总无股票，不生成TXT")
        return

    filepath = TXT_OUTPUT_DIR / f"tdx_total_{get_datetime_str()}.txt"
    with open(filepath, "w", encoding="gbk") as f:
        for code in unique_codes:
            tdx_code = to_tdx_format(code)
            if tdx_code:
                f.write(tdx_code + "\n")
    print(f"✅ 策略总汇总已导出：{filepath}")

# ====================== 3. B1匹配导出（通达信可用） ======================
def export_b1_match_tdx(matched_list):
    codes = [clean_stock_code(item.get("stock_code", "")) for item in matched_list if clean_stock_code(item.get("stock_code", ""))]
    if not codes:
        return

    filepath = TXT_OUTPUT_DIR / f"tdx_B1_Top30_{get_datetime_str()}.txt"
    with open(filepath, "w", encoding="gbk") as f:
        for code in codes[:30]:
            tdx_code = to_tdx_format(code)
            if tdx_code:
                f.write(tdx_code + "\n")
    print(f"✅ B1匹配前30只已导出：{filepath}")

# ====================== 4. ✅ 回溯筛选导出（通达信100%识别） ======================
def export_backtrack_tdx(backtrack_result):
    codes = [clean_stock_code(item["code"]) for item in backtrack_result if clean_stock_code(item["code"])]
    if not codes:
        print("📝 回溯筛选无股票，不生成TXT")
        return

    filepath = TXT_OUTPUT_DIR / f"tdx_Backtrack_KDJ5%_{get_datetime_str()}.txt"
    # 严格GBK编码 + 纯通达信格式
    with open(filepath, "w", encoding="gbk") as f:
        for code in codes:
            tdx_code = to_tdx_format(code)
            if tdx_code:
                f.write(tdx_code + "\n")
    print(f"✅ 回溯筛选结果已导出：{filepath}")