# B2 策略 — 代码注释与逻辑说明

说明：本文件为 `strategy/b2_strategy.py` 的独立文档说明（仅文档，不改动代码）。用于记录文件目的、核心逻辑、主要类/函数接口、运行方式与输出位置，便于后续回溯与优化。

## 文件位置
- 源代码：`strategy/b2_strategy.py`
- 文档（本文件）：`docs/b2_strategy_code_notes.md`

## 简要目的
- 检测“B2 型经典形态/突破”类选股信号。
- 对匹配结果生成供通达信导入的 TXT（TDX）与普通 TXT 清单。
- 触发钉钉（DingTalk）通知并附带 K 线图（按配置）。

## 核心逻辑（高层次，按步骤）
1. 数据准备：读取每只股票的日线 CSV（`data/00/` 或其他分组目录）。
2. 形态检测：对每只股票运行一系列判定函数：
   - 是否满足 B2 突破条件（例如突破压制、放量配合、短期 KDJ 条件等）。
   - 是否处于合并/盘整区间（用于排除早期突破或非清晰形态）。
   - 回溯/最低点限制条件（如“回溯日未跌破某历史低点的 5%”等可选判据）。
3. 打分/阈值：对满足的候选股票计算分数，超过阈值则判为匹配结果。
4. 导出结果：生成策略专属 TXT 到 `data/txt/B2-match/`，并生成可供通达信导入的格式文件（TDX）。
5. 通知：通过 `utils/dingtalk_notifier.py` 发送消息（分段 Markdown）并上传/附带生成的 K 线图片（如配置）。

## 主要类 / 函数说明
- `B2PatternLibrary`：保存典型样例/模板（完美案例）；用于对照与调参说明。
- `B2CaseAnalyzer`：主分析器，入口方法通常为 `analyze(stock_df)` 或 `analyze_all(stock_list)`。
  - 关键内部方法：
    - `_detect_b2_breakout(df)`：判断是否发生突破/确认信号（返回布尔或带分值的结果）。
    - `_identify_consolidation(df)`：判断是否处于盘整/筑顶（用于排除）。
    - `_score_candidate(df)`：对候选进行加权评分并判断是否超过阈值。
    - `_export_txt(matches, out_dir)`：将匹配股票输出为简单 TXT 列表（供人工查看）。
    - `_export_tdx_txt(matches, out_path)`：生成通达信导入格式文件（TDX）。
    - `notify_and_export(matches, notifier, config)`：协调导出 + 通知流程，打印 `EXPORTED_TXT:` 前缀以便控制台/监控识别。

## 重要参数与配置位置
- 策略参数：`strategy/pattern_config.py` 中的 `B2_DEFAULT_PARAMS` 与 `B2_PERFECT_CASES`。
- 通知配置：查看 `config/config.yaml`（钉钉 webhook、图片开关、消息限长策略等）。
- 输出目录：默认写入 `data/txt/B2-match/`（普通 TXT）和 `data/txt/tdx_*`（TDX 导入文件）。

## 运行命令示例
- 使用项目虚拟环境（Windows PowerShell）：

```powershell
# 运行 B2 策略扫描（示例，按需调整 --max-stocks）
.\.venv\Scripts\python.exe .\main.py run --b2-match --max-stocks 1000

# 不更新数据，直接运行（如有独立脚本）
.\.venv\Scripts\python.exe -u .\run_b2_scan.py
```

- 在类 Unix 终端（bash）示例：

```bash
python3 main.py run --b2-match --max-stocks 1000
```

## 输出示例与控制台约定
- 成功导出后，程序会打印一行前缀：

```
EXPORTED_TXT: <绝对路径或相对路径到生成的 TXT 文件>
```

- 该前缀用于外部控制面板或日志解析器快速识别导出动作；若控制面板未检测到，请确认它是否监听 stdout 或轮询 `data/txt/B2-match/`。

## 已知注意点（实现细节与历史 bug）
- 避免 `float(Series)` 错误：在读取或计算单值字段时，代码中使用了标量提取保护（例如 `val = float(series.iloc[0])`）以防止将整个 `Series` 传入 `float()`。
- 钉钉通知：消息会按长度分段发送并重试，确保 `pandas` 在 `utils/dingtalk_notifier.py` 中已导入以支持 DataFrame 到表格的转换（已修复历史 NameError）。
- 不要在文档生成时删除或替换代码：本文件仅为注释/说明，代码保留在 `strategy/b2_strategy.py` 中以便版本控制与可执行性。

## 开发建议与后续工作项
- 若需控制面板即时识别，请告知控制面板是如何检测导出（stdout 前缀 vs 文件监控 vs webhook），我可以：
  - 强化 `EXPORTED_TXT:` 行并在写文件后 `flush()` stdout；或
  - 在导出成功后额外 `touch` 一个 `.ready` 文件供监控轮询；或
  - 触发一个 HTTP webhook（若控制面板支持）。
- 建议为关键函数（例如 `_detect_b2_breakout`）添加单元测试，覆盖边界场景（极端成交量、缺失交易日、退市/停牌）。

---

如果你希望我把相同风格的文档自动生成到其他策略文件（例如 `strategy/b1_case_analyzer.py`、`strategy/bowl_rebound.py`），我可以按此模板批量生成。