# B1 代码变更回溯（昨晚至今）

> 时间范围：昨晚至 2026-04-02 当前工作区状态
> 目的：用于回溯学习阶段型 B1 的新增策略、结构改造和运行逻辑

---

## 1. 变更总览

本轮改动围绕 4 个目标展开：

1. 将 B1 从历史相似度匹配扩展到阶段型案例验证与前瞻扫描。
2. 统一短期趋势线与知行多空线计算口径，避免策略间定义分叉。
3. 提升全量扫描可用性：进度可视、性能可控、异常可自动回退。
4. 打通结果输出链路：钉钉消息 + K 线图 + 通达信 TXT 导出。

---

## 2. 新增策略与模块

### 2.1 新增阶段型 B1 分析器

- 新文件：strategy/b1_case_analyzer.py
- 核心能力：
  - 固定日期回溯验证（6 阶段完整验证，面向案例模板）
  - 动态前瞻扫描（阶段 1-5 通过即预警，阶段 6 待确认）

#### 阶段型案例（掌阅科技）

- anchor_date: 2025-11-17（低位 KDJ 触发）
- reference_low_date: 2025-10-17（支撑低点）
- breakout_date: 2025-11-21（突破）
- washout_end_date: 2025-12-17（洗盘结束）
- setup_date/case_date: 2026-02-06（回踩多空线）
- buy_date: 2026-02-09（大阳确认）

### 2.2 新增前瞻扫描脚本

- 新文件：run_b1_scan.py
- 作用：
  - 全市场扫描阶段型 B1 预警
  - 实时显示扫描进度（百分比、速度、ETA、命中数、异常数）
  - 导出通达信 TXT
  - 触发钉钉推送（文字 + K 线图）

---

## 3. 配置与案例库扩展

### 3.1 B1 案例库扩展

- 文件：strategy/pattern_config.py
- 变化：
  - B1 常规案例扩展为 12 个（含 航天发展、掌阅科技）
  - 新增 B1_STAGE_CASES（阶段型案例配置）

### 3.2 B1 运行参数新增

- 文件：config/strategy_params.yaml
- 新增关键项：
  - auto_fallback_to_classic: true
  - max_candidates: 400
  - match_workers: 0（自动）
  - prefilter_by_j: true

### 3.3 文档同步到 12 案例

- 文件：README.md、B1_PATTERN_MATCH.md
- 变化：
  - 统一为 12 个历史案例
  - 说明掌阅科技 case_date=2026-02-06，buy_date=2026-02-09

---

## 4. 结构改造（核心）

### 4.1 双线定义统一（短期趋势线 + 知行多空线）

- 文件：utils/technical.py
- 新增：
  - evaluate_zhixing_snapshot
  - calculate_zhixing_state
- 调整：
  - calculate_zhixing_trend 改为顺序无关计算，修复倒序/正序口径偏差。

### 4.2 主策略与特征提取统一复用

- 文件：strategy/bowl_rebound.py
  - 改为使用 calculate_zhixing_state，避免单独重复逻辑。
- 文件：strategy/pattern_feature_extractor.py
  - 改为使用 calculate_zhixing_state + evaluate_zhixing_snapshot。

### 4.3 B1 库接入阶段型与前瞻扫描

- 文件：strategy/pattern_library.py
- 增强点：
  - 引入 B1_STAGE_CASES 与 B1CaseAnalyzer
  - find_best_match 返回：
    - best_stage_case（固定日期回溯命中）
    - pre_signal（阶段 1-5 前瞻信号）
  - 模板股票限制：固定日期阶段匹配仅对 603533 执行，避免全市场硬套日期。

---

## 5. 主流程逻辑变更

- 文件：quant_system.py

### 5.1 进度显示增强

- 新增统一进度打印函数：
  - 文本进度条
  - 当前阶段名
  - 阶段耗时 + 总耗时
  - 速度 + ETA
- 覆盖流程：
  - 基础选股
  - 3 天回溯扫描
  - B1 匹配

### 5.2 性能优化

- B1 候选压平去重
- 按 J 值低位预筛后裁剪候选（max_candidates）
- B1 并发匹配（match_workers 自动/配置）

### 5.3 容错与自动回退

- 新增异常判定：OOM、Series 适配异常、shape/index 类错误。
- B1 过程异常时自动回退到原始选股通知流程（classic），避免任务中断。

### 5.4 阶段型结果入榜与排序

- 匹配结果新增字段：
  - stage_case_*（回溯命中）
  - pre_signal_*（前瞻预警）
- 排序优先级增加阶段型命中维度。

---

## 6. 输出链路增强

### 6.1 钉钉消息增强

- 文件：utils/dingtalk_notifier.py
- 新增：send_b1_pre_signal_results_with_charts
- 输出内容：
  - 汇总消息（命中数、策略说明）
  - 个股详情（anchor/setup/当前J/多空线偏离/支撑价）
  - 个股 K 线图发送
- 增加发送统计日志（成功/失败计数）。

### 6.2 通达信 TXT 导出增强

- 文件：utils/tdx_exporter.py
- 新增：export_b1_pre_signal_tdx
- 导出路径：data/txt/B1-zykj-match/
- 文件名规范：策略名_YYYYMMDD_HHMM.txt

### 6.3 终端展示优化

- run_b1_scan.py 命中输出改为：股票代码 + 中文名称
- 钉钉发送状态改为可见日志：未配置、成功、失败原因。

---

## 7. 关键问题与修复记录

1. 阶段分析报错：float() argument ... not 'Series'
- 原因：重复列导致行取值变成 Series。
- 修复：去重列 + 覆盖写入指标列 + 标量转换保护。

2. 全市场错误套用掌阅科技固定日期
- 原因：模板未限制执行对象。
- 修复：固定日期模板仅对 603533 执行，其他股票跳过。

3. Windows 控制台编码异常
- 现象：UnicodeEncodeError（gbk）
- 修复：关键日志改为 ASCII 安全输出。

4. 缓存一致性问题
- 修复：案例缓存增加 version + signature 校验，避免旧缓存吞新配置。

5. run_b1_scan.py 进度不可见
- 修复：加实时进度、心跳日志、flush 输出，并修复脚本缩进问题。

---

## 8. 当前策略口径（实盘）

1. 固定日期阶段模板：用于 603533 案例回溯验证，不用于全市场硬匹配。
2. 全市场选股使用动态前瞻规则：阶段 1-5 通过即预警，阶段 6 待确认。
3. setup_window_days 当前为 2，且采用“至少 N-1 天满足”容错口径。
4. 时间口径均为交易日，不是自然日。

---

## 9. 你最常用的运行指令

```powershell
# 全流程（含B1）
.\.venv\Scripts\python.exe .\main.py run --b1-match

# 前瞻阶段型扫描（推荐）
.\.venv\Scripts\python.exe -u .\run_b1_scan.py
```

---

## 10. 建议下一个回溯点

1. 为前瞻信号新增“量能确认”阈值，降低假信号。
2. 增加阶段 5 参数分档（严格/标准/宽松）并记录命中率变化。
3. 给 run_b1_scan.py 增加扫描结果 CSV，便于统计命中后 N 日收益。

---

## 11. 按文件逐条 Diff 学习索引

> 使用方法：按下面顺序阅读，每个文件先看“改了什么”，再对照“为什么改”。

### 11.1 策略定义层（先看）

1. strategy/pattern_config.py
- 改了什么：
  - B1 常规案例扩充到 12 个。
  - 新增 B1_STAGE_CASES（掌阅科技阶段型模板）。
  - 新增性能/容错配置：auto_fallback_to_classic、max_candidates、match_workers、prefilter_by_j。
- 为什么改：
  - 把“案例配置”和“运行开关”集中在一个地方，方便回测与调参。

2. config/strategy_params.yaml
- 改了什么：
  - 新增 B1 运行参数（自动回退、候选裁剪、并发、J值预筛）。
- 为什么改：
  - 将策略参数外置，避免每次调参都改 Python 代码。

### 11.2 指标计算层（核心口径）

3. utils/technical.py
- 改了什么：
  - 新增 evaluate_zhixing_snapshot。
  - 新增 calculate_zhixing_state。
  - 重写 calculate_zhixing_trend 为顺序无关计算。
- 为什么改：
  - 统一短期趋势线与知行多空线口径，消除倒序/正序数据导致的偏差。

4. strategy/bowl_rebound.py
- 改了什么：
  - 由手写分类切换为统一调用 calculate_zhixing_state。
- 为什么改：
  - 保证主策略与 B1 对“靠近双线/回落碗中”定义一致。

5. strategy/pattern_feature_extractor.py
- 改了什么：
  - 特征提取改用 calculate_zhixing_state + evaluate_zhixing_snapshot。
- 为什么改：
  - 保证 B1 相似度特征和主策略指标来自同一口径。

### 11.3 阶段型策略层（本轮重点）

6. strategy/b1_case_analyzer.py
- 改了什么：
  - 新增固定日期回溯 analyze（6阶段）。
  - 新增动态前瞻 scan_pre_signal（阶段1-5）。
  - 修复 Series->float 异常与重复列问题。
  - setup_window_days 调整为 2，且采用“至少 N-1 天满足”容错。
- 为什么改：
  - 兼顾“案例复盘验证”与“启动前选股预警”。

7. strategy/pattern_library.py
- 改了什么：
  - 接入阶段型案例与前瞻扫描输出。
  - 固定日期模板仅对 603533 执行。
  - 缓存增加版本与签名校验。
  - 日志改为 ASCII 安全输出。
- 为什么改：
  - 避免全市场硬套掌阅科技日期；提升缓存一致性与 Windows 兼容性。

### 11.4 主流程与性能层（可用性）

8. quant_system.py
- 改了什么：
  - 新增统一进度输出（阶段名、进度条、速度、ETA、阶段耗时、总耗时）。
  - B1 匹配支持候选裁剪与并发处理。
  - 新增 B1 异常自动回退 classic 流程。
  - 结果字段扩展：stage_case_*、pre_signal_*。
- 为什么改：
  - 提速并保证任务不中断；输出更适合实盘监控。

### 11.5 输出与通知层（落地使用）

9. utils/dingtalk_notifier.py
- 改了什么：
  - 新增 send_b1_pre_signal_results_with_charts。
  - 个股详情增加阶段型字段。
  - 增强发送统计日志（成功/失败计数）。
- 为什么改：
  - 让阶段型 B1 结果能直接进入消息链路，便于盘后复盘。

10. utils/tdx_exporter.py
- 改了什么：
  - 新增 export_b1_pre_signal_tdx。
  - 输出目录固定为 data/txt/B1-zykj-match。
  - 文件名包含策略名+时间戳。
- 为什么改：
  - 直接导入通达信观察，减少人工整理。

11. run_b1_scan.py
- 改了什么：
  - 新增独立扫描脚本。
  - 增加实时进度、心跳日志、flush 输出。
  - 输出“代码+中文名”，并接入 TXT 导出与钉钉推送。
- 为什么改：
  - 便于单独跑阶段型前瞻扫描，不依赖主流程命令。

### 11.6 文档同步层（最后看）

12. README.md / B1_PATTERN_MATCH.md / B1_STAGE_STRATEGY.md
- 改了什么：
  - 统一案例数与阶段型说明。
  - 补充交易日口径、前瞻扫描口径、推送与导出规则。
- 为什么改：
  - 保证“代码行为”和“文档说明”一致，避免误用。

### 11.7 建议学习顺序

1. 先看 strategy/pattern_config.py + config/strategy_params.yaml（知道开关和参数）。
2. 再看 utils/technical.py（理解双线口径）。
3. 看 strategy/b1_case_analyzer.py（理解阶段逻辑）。
4. 看 strategy/pattern_library.py（理解如何接入 B1 总流程）。
5. 看 quant_system.py（理解实盘执行、提速和回退）。
6. 最后看 run_b1_scan.py + dingtalk_notifier.py + tdx_exporter.py（理解输出落地）。
