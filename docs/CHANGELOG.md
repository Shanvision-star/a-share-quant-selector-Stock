# Changelog

所有 notable 修改都记录在此文件。

## [Unreleased]

### 重构
- **策略重构**: 将多个独立策略合并为「碗口反弹策略（分类标记版）」
  - 原来：4个独立策略（BowlReboundStrategy + 3个新策略）
  - 现在：1个策略，选股后按三种类型分类标记
  - 分类优先级：回落碗中 > 靠近多空线 > 靠近短期趋势线

### 新增功能
- 添加 `--version` 参数支持，可查看系统版本、Python版本、依赖库版本等信息
- 添加 `--category` 命令行参数，支持按分类筛选股票:
  - `bowl_center` - 只显示回落碗中的股票
  - `near_duokong` - 只显示靠近多空线的股票
  - `near_short_trend` - 只显示靠近短期趋势线的股票
  - `all` - 显示全部（默认）

### 策略逻辑改进
- **放量必须是阳线**: 关键K线判定增加 `close > open` 条件
- **新增分类参数**:
  - `duokong_pct`: 靠近多空线百分比阈值（默认3%）
  - `short_pct`: 靠近短期趋势线百分比阈值（默认2%）

### 修改文件
- `strategy/bowl_rebound.py` - 重构为分类标记版，增加分类逻辑
- `strategy/__init__.py` - 只保留 BowlReboundStrategy
- `main.py` - 添加 `--category` 参数支持，简化策略调用
- `config/strategy_params.yaml` - 添加 `duokong_pct` 和 `short_pct` 参数
- `README.md` - 更新策略说明和命令说明

### 删除文件
- `strategy/near_duokong.py` - 合并到 bowl_rebound.py
- `strategy/near_short_trend.py` - 合并到 bowl_rebound.py
- `strategy/bowl_center.py` - 合并到 bowl_rebound.py

## [2024-02-10]

## [2024-02-10]

### 配置变更
- **策略参数调整** (`config/strategy_params.yaml`):
  - `J_VAL`: 30 → 20 (更严格的超卖条件)
  - `M1`: 5 → 14
  - `M2`: 10 → 28
  - `M3`: 20 → 57
  - `M4`: 30 → 114

- **定时任务时间** (`config/config.yaml`):
  - `schedule.time`: "15:05" → "15:15"

### 功能改进
- 运行选股时输出当前策略参数
- 修复知行多空线文档注释，明确计算公式

## [2024-02-09]

### 新增功能
- 碗口反弹策略选股系统
- 钉钉自动通知
- Web管理界面
- KDJ指标计算与显示
- 自动过滤退市/ST股票

### 技术实现
- 基于akshare获取A股数据
- 使用腾讯接口获取股票列表
- CSV格式存储历史数据
- Flask提供Web服务

## [2026-04-11]

### 新增功能
- **Changelog 自动化**: 添加脚本以自动生成 changelog，支持以下功能：
  - 提取版本标签和 PR 信息。
  - 验证和格式化 changelog 条目。
  - 过滤无关更改（如测试、CI 更新）。

### 优化
- **提交规范**: 强制执行提交信息模板，确保所有提交信息包含类型（如 `fix:`、`feat:`）。
- **PR 描述模板**: 要求 PR 描述中包含 changelog 条目，支持中英文双语。

### 文件更新
- `scripts/changelog_generator.py` - 新增脚本以支持 changelog 自动化。
- `docs/git_push_guide.md` - 更新提交和 PR 描述规范。
