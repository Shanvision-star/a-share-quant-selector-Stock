B2 策略文档
=============

概述
----
本文档说明项目中 `strategy/b2_strategy.py` 的设计、运行方法、配置项、导出路径与常见问题排查。

算法流程（6 步）
----------------
1. B1 前提检查：短期趋势贴合、多空线方向、KDJ J 值处于低位（超卖）
2. 大阳线验证：统计近若干日内是否存在>=N根大阳线且换手率/涨幅满足阈值
3. 整理区间识别：识别突破前的整理箱体（高/低/起止日期）
4. B2 突破检测：当日突破箱顶并放量且涨幅满足最低阈值
5. 放量确认：当日成交量相比近N日均量要达到设定倍数
6. 站稳多空线：突破后连续 M 日全部在多空线上方

主要文件与类
--------------
- `strategy/b2_strategy.py`
  - `B2CaseAnalyzer`：主分析类，方法 `analyze(code, df, case_cfg)` 返回匹配结果或 None。
- `strategy/pattern_config.py`
  - `B2_PERFECT_CASES`：案例库条目，包含 name/id/整理区间等元信息。
  - `B2_DEFAULT_PARAMS`：默认参数（与 `DEFAULT_PARAMS` 保持一致）。
- `utils/dingtalk_notifier.py`
  - 负责发送钉钉消息与图片；上层可调用 `send_b2_match_results()` 以推送匹配结果。
- `quant_system.py` / `run_b2_scan.py`
  - 调度脚本，负责批量扫描、导出 TXT 并调用通知器。

配置项（常用）
-------------
- `DEFAULT_PARAMS`（`b2_strategy.py`）或 `B2_DEFAULT_PARAMS`：
  - `b1_kdj_threshold`：B1 前提 J 值阈值（默认 13）
  - `b1_pre_lookback`：B1 搜索的回溯天数
  - `b1_big_up_pct`：定义“大阳线”的最低涨幅（%）
  - `vol_mean_days`：计算均量的天数
  - `vol_multiplier`：放量倍数阈值
  - `b2_min_pct`：突破日最小涨幅要求（%）
  - `export_txt_dir`：TXT 导出目录（默认 `data/txt/B2-match`）

运行说明
---------
- 单次快速扫描（推荐虚拟环境）:

```powershell
# 在仓库根目录下运行（Windows）
.\.venv\Scripts\python.exe .\run_b2_scan.py

# 或通过主流程运行 B2 匹配（支持并发）
.\.venv\Scripts\python.exe .\main.py run --b2-match --max-stocks 1000
```

- 保证实时日志输出到控制台（避免缓冲），在 Python 命令中使用 `-u`：

```powershell
python -u main.py run --b2-match
```

导出与通知
-----------
- 导出：匹配结果会被写为 TXT（可导入通达信）到 `data/txt/B2-match`，文件名带时间戳。
- 通知：若启用，`utils/dingtalk_notifier.py` 会把匹配结果以 Markdown 或图片的形式发送到钉钉群，消息内也会包含 TXT 下载或附加说明。

控制面板未显示 TXT 的排查建议
---------------------------
1. 确认文件已写入：在仓库根目录运行：

```powershell
dir data\txt\B2-match /O:-D
```

2. 确认控制面板监听方式：
   - 若控制面板监听 DingTalk 消息，检查 `utils/dingtalk_notifier.py` 是否发送成功（查看日志/重试信息）。
   - 若控制面板轮询文件夹，确认导出目录与控制面板配置一致，且有足够权限读取新文件。
3. 运行时开启无缓冲输出（`-u`）或确保程序在写文件后 `print()` 输出生成路径并 `flush()`，以便面板可以即时收到 stdout 日志。

常见问题
--------
- "程序没有输出但文件已生成": 检查是否在后台进程或日志被重定向到文件。
- "钉钉消息未发送": 检查网络、access_token、钉钉 API 限频与重试逻辑。

后续工作建议
-----------
- 若希望控制面板直接监听到“生成 TXT”事件，可在 `quant_system` 的导出流程里增加一条明确的 stdout 日志，例如：

```python
print(f"EXPORTED_TXT:{export_path}", flush=True)
```

  然后在控制面板中检测以 `EXPORTED_TXT:` 前缀的日志行。

- 将策略说明摘要放入项目主页 `README.md` 的 docs 索引，方便快速查阅。

如需我把 README 中加入指向本文档的链接，我可以继续修改并提交。