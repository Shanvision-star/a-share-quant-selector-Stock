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


def build_strategy_txt_dir(folder_name: str) -> Path:
    output_dir = TXT_OUTPUT_DIR / folder_name
    ensure_dir(output_dir)
    return output_dir


def sanitize_filename_part(value: str) -> str:
    text = str(value).strip()
    if not text:
        return "unknown"
    invalid_chars = '<>:"/\\|?*'
    sanitized = "".join("_" if char in invalid_chars else char for char in text)
    sanitized = sanitized.replace(" ", "_")
    return sanitized.strip("._") or "unknown"

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

    # 导出所有匹配结果（不再限制为前30），保持去重并排序输出以便复现性
    unique_codes = sorted(list(dict.fromkeys(codes)))
    filepath = TXT_OUTPUT_DIR / f"tdx_B1_matched_{get_datetime_str()}.txt"
    with open(filepath, "w", encoding="gbk") as f:
        for code in unique_codes:
            tdx_code = to_tdx_format(code)
            if tdx_code:
                f.write(tdx_code + "\n")
    print(f"✅ B1匹配结果已导出（不限制数量）：{filepath}")


def export_b1_pre_signal_tdx(pre_signal_list, max_count=None, strategy_name="阶段型B1前瞻扫描"):
    """导出阶段型B1预警结果为通达信可导入TXT。"""
    codes = [
        clean_stock_code(item.get("stock_code", item.get("code", "")))
        for item in pre_signal_list
        if clean_stock_code(item.get("stock_code", item.get("code", "")))
    ]
    if not codes:
        print("📝 阶段型B1预警无股票，不生成TXT")
        return None

    if max_count and max_count > 0:
        codes = codes[:max_count]

    output_dir = build_strategy_txt_dir("B1-zykj-match")
    filename = f"{sanitize_filename_part(strategy_name)}_{get_datetime_str()}.txt"
    filepath = output_dir / filename
    with open(filepath, "w", encoding="gbk") as f:
        for code in codes:
            tdx_code = to_tdx_format(code)
            if tdx_code:
                f.write(tdx_code + "\n")

    print(f"✅ 阶段型B1预警结果已导出：{filepath}")
    return filepath

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


# ====================== 5. B2 图形匹配导出（通达信可用） ======================
def export_b2_match_tdx(matched_list):
    """
    将 B2 图形匹配结果导出为通达信可直接导入的 TXT 文件。

    支持两种结果格式：
      - B2 规则扫描结果（含 code 字段）
      - B2 图形匹配结果（含 code 字段 + similarity_score 可选）

    文件生成位置：data/txt/B2-match/tdx_B2_matched_YYYYMMDD_HHMM.txt
    """
    codes = [
        clean_stock_code(item.get("code", ""))
        for item in matched_list
        if clean_stock_code(item.get("code", ""))
    ]
    if not codes:
        print("📝 B2匹配无股票，不生成TXT")
        return None

    unique_codes = sorted(list(dict.fromkeys(codes)))  # 去重保序
    output_dir = build_strategy_txt_dir("B2-match")
    filepath = output_dir / f"tdx_B2_matched_{get_datetime_str()}.txt"

    with open(filepath, "w", encoding="gbk") as f:
        for code in unique_codes:
            tdx_code = to_tdx_format(code)
            if tdx_code:
                f.write(tdx_code + "\n")

    print(f"✅ B2匹配结果已导出（{len(unique_codes)} 只）：{filepath}")
    return str(filepath)


def export_b2_pattern_match_detail_txt(matched_list, stock_names=None):
    """
    将 B2 图形匹配结果（含相似度）导出为人类可读的详细 TXT 文件。

    输出格式示例：
      相似度排行  2026-04-06 14:30

      #1  688663 星环科技  相似度=82.5%
          形态类型    : 横盘突破型
          匹配案例    : 星环科技 (b2p_case_001)
          B1 触发日   : 2025-12-14  J值=0.67
          B2 突破日   : 2025-12-15  涨幅=5.1%  量比=1.94x
          止损价      : 46.50（B2突破日最低价）
          分项得分    : 趋势78% KDJ80% 量能85% 形态72%

    文件生成位置：data/txt/B2-match/B2图形匹配结果_YYYYMMDD_HHMM.txt
    """
    if stock_names is None:
        stock_names = {}

    output_dir = build_strategy_txt_dir("B2-match")
    now = Path.__class__(Path)  # just get datetime
    from datetime import datetime as _dt
    now_str = _dt.now().strftime("%Y%m%d_%H%M")
    filepath = output_dir / f"B2图形匹配结果_{now_str}.txt"
    now_label = _dt.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"B2 完美图形匹配结果  {now_label}\n",
        f"共命中 {len(matched_list)} 只（按相似度排序）\n",
        "=" * 60 + "\n",
        "\n",
    ]

    for i, r in enumerate(matched_list, 1):
        code   = r.get("code", "")
        name   = r.get("name", stock_names.get(code, code))
        score  = r.get("similarity_score", "-")
        plabel = r.get("matched_b2_pattern_label", r.get("pattern_label", "-"))
        case_n = r.get("matched_b2_case_name", r.get("matched_case_name", "-"))
        case_d = r.get("matched_b2_case_date", "-")
        b1_d   = r.get("b1_date", "-")
        j_val  = r.get("j_at_b1", "-")
        b2_d   = r.get("b2_date", "-")
        pct    = r.get("b2_pct_chg", "-")
        vol_r  = r.get("b2_vol_ratio", "-")
        stop   = r.get("stop_loss_price", "-")
        c_s    = r.get("consolidation_start", "-")
        c_e    = r.get("consolidation_end", "-")
        c_hi   = r.get("consolidation_high", "-")
        big_n  = r.get("big_up_count", "-")
        bd     = r.get("similarity_breakdown", {})

        lines += [
            f"#{i}  {code} {name}  相似度={score}%\n",
            f"    形态类型    : {plabel}\n",
            f"    匹配案例    : {case_n} ({case_d})\n",
            f"    B1 触发日   : {b1_d}  J值={j_val}\n",
            f"    B2 突破日   : {b2_d}  涨幅={pct}%  量比={vol_r}x\n",
            f"    整理区间    : {c_s} ~ {c_e}  区间高={c_hi}\n",
            f"    大阳线      : {big_n} 根\n",
            f"    止损价      : {stop}\n",
        ]
        if bd:
            lines.append(
                f"    分项得分    : 趋势{bd.get('trend_structure', '-')}% "
                f"KDJ{bd.get('kdj_state', '-')}% "
                f"量能{bd.get('volume_pattern', '-')}% "
                f"形态{bd.get('price_shape', '-')}%\n"
            )
        lines.append("\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"✅ B2图形匹配详细TXT已导出：{filepath}")
    return str(filepath)
