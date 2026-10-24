# Windows 正式扫描准确性与提速验收

日期：2026-10-24；目标交易日：2026-10-23；分支：`codex/strategy-scan-profile`，基线 `467bded`。

## 验收结果

最终版本完成 5155 股 × 5 策略的精确对照：25775 个终态逐字段一致、零异常，输入内容指纹前后不变。打包后的 0.2.1 桌面从界面执行“更新数据 + 自动重建策略”，发布 122 条信号、120 只股票。桌面 API、SQLite、JSON 镜像和真实 Codex MCP 明细一致。

正式运行：`20261024_232627_8dd30264`，状态 `done`；8 个进程、每批 16 股，扫描 5155/5155。应用使用内置 CPython 3.14.9 和原项目数据，Windows 进程保护为 `job_object`。

## 耗时

| 范围 | 耗时 | 口径 |
| --- | ---: | --- |
| 旧桌面完整后端作业 | 718 秒，11 分 58 秒 | 旧 run `20261023_234606_76b96d71`；无完整阶段细分 |
| 最终修正后串行计算 | 560.60 秒 | 同一输入、5155 股、五策略、完整终态 |
| 最终修正后多进程计算 | 215.02 秒 | 相对本轮串行 2.61 倍，全部业务字段相等 |
| 新桌面完整后端作业 | 256.86 秒，4 分 16.86 秒 | 相对旧后端约 2.80 倍，耗时减少 64.2% |
| 新桌面点击至 SSE 结束 | 260.09 秒，4 分 20.09 秒 | 包含界面发起与响应开销 |

新桌面阶段：行情缓存检查 1.57 秒；扫描准备 16.81 秒、计算 231.79 秒、输入复核 5.07 秒、数据库发布 0.047 秒；扫描合计 253.81 秒。合计与分项不能重复相加。

新旧完整作业均命中行情缓存。本次走完真实更新入口，但没有重新从网络补齐历史行情，不能将该时间作为首次全量下载耗时。未在本轮调用付费模型或新建复盘。

诊断轮曾测得串行 512.19 秒、多进程 313.55 秒；512 股限制数学库线程试验未证明显著收益，因此没有加入该改动。本机执行时间有波动，资源争用/调度原因尚未充分确认。保留所有实测，早期 62.78 秒原型不替代正式成绩，不承诺其他机器相同耗时。

## 正确性及保留边界

- 保留五策略公式、参数和 float64 精度。B1/B2/Zettaranc 的真实计算异常向上传播；正常空窗口、NaN 和阈值过滤保持原规则。
- 历史扫描先按目标日截断，再补足最多 320 根；新股有效历史不足仍按原最低样本规则处理。无效日期、非空文件读取失败显式报错。
- B2 合法 `damage_zone=None` 不再导致序列化失败。与旧 121 条相比，只恢复 `300987 川网传媒 / B2 / 2026-09-17` 历史信号，其余旧命中字段一致。这不是 10 月 23 日的新触发。
- 每股每策略必须有命中、未命中、跳过或异常终态。注册缺失、异常、终态缺失/重复或输入变化均阻止发布。
- 行情写入、扫描、配置更新和攻击日扫描共享作业租约；所选策略一次完整发布。行情局部失败保留旧快照。
- SQLite 事务同时发布快照和信号，零命中分组替换旧命中；JSON 为兼容镜像。提交前取消不发布，提交后断连保留已发布运行的成功状态。
- 原首页搜索切换、趋势线、策略结果、跟踪、回测、复盘和 Agent 入口保留。本轮未修改前端源码，未重复执行前端构建。

| 策略 | 命中 | 未命中 | 跳过 | 异常 |
| --- | ---: | ---: | ---: | ---: |
| B1 | 6 | 4977 | 172 | 0 |
| B2 | 16 | 4967 | 172 | 0 |
| 碗形 | 0 | 4983 | 172 | 0 |
| 砖型 | 100 | 4883 | 172 | 0 |
| Zettaranc | 0 | 4983 | 172 | 0 |

172 只股票由现有公共过滤规则跳过，仍有逐股逐策略终态；跳过不等于策略异常。

## 证据与测试

- 全量对照：`output/scan-production/final-full-market/`，包含完整结果、逐字段比较、参数和内容清单。
- 输入 SHA256：`226dc0848074aaaad4d2ca796b3f068df90c0fa4e073575f57a915b72f29b5df`。
- 全部业务结果 SHA256：`b8ba8bf3b721ae016660d6cb4f49f1f9e3bae0665b41b7f18f33bfa85f1d66c8`。
- 正式逐股审计：`data/scan_runs/20261024_232627_8dd30264-all.json`，业务结果哈希与对照相同。
- 界面及阶段计时：`output/scan-production/desktop-run.json`、`desktop-events.sse`；截图 `desktop-before.png`、`desktop-complete.png`、`desktop-inspect.png`。
- 全量发布核对：`output/scan-production/desktop-publication-verification.json`；SQLite `quick_check=ok`。
- 真实已连接 MCP 状态：`output/scan-production/mcp-status.json`，同一 run/date/122 条/零异常。
- 按真实 Codex 配置启动 stdio 后读取全部明细：`output/scan-production/mcp-readonly-verification.json`、`mcp-result-pages.json`；3 页共 122 条，所有字段与桌面相等，另核对 688613、300987。

旧原型没有完整 outcomes 和内容 SHA256，不能声称旧版本所有阴性结果已证明正确；严格全终态等价以修正后串行和多进程为准。

最终 Python 专项组合 251 项通过，覆盖异常、历史窗口、五策略、仓储、发布/取消/断连、系统状态、Agent、每日流程、TXT 及桌面生命周期；包括本地 B2 样例、显式内置解释器离线回测和历史 dry-run。之后新增只读 MCP 接口 9 项独立测试通过，两个集合不重叠。

`npm --prefix desktop run check`：3 项通过。应用实际启动及完整扫描验证后端导入路径；真实 stdio 验证新增 MCP 导入与调用。`git diff --check` 通过。桌面成功路径已实测，异常/取消/回收由专项测试验证，没有在正式用户作业中刻意制造崩溃。

## Windows 交付与 MCP

0.2.1 安装版：`desktop/release/A-share-Quant-Setup-0.2.1.exe`；便携版：`desktop/release/A-share-Quant-0.2.1.exe`。两种发行文件已生成，包内含 CPython 3.14.9 x64 和依赖，不要求用户配置 Python。最终打包后按用户要求停止追加验证，未执行最终安装重开复验；此前已完成打包桌面的实际启动和完整扫描。

启动前已通过 SQLite backup 保存一致性备份，位于本地 `output/scan-production/before-install-private/`，同时保留配置和复盘。该目录含私人数据，不纳入发行内容。安装种子不覆盖已连接项目的配置和 data。

新增只读工具 `quant_strategy_results(strategy='all', trade_date=None, code=None, offset=0, limit=50)`，每页最多 200；返回发布编号、评估日期、原信号日期和原文，不建立研究、不调用模型。已有 MCP 连接需重新连接后发现新增工具；原 `quant_status` 已可读到新发布版本，现有配置无需改 Python 路径。

本轮额外新建研究尝试被当前会话工具层的 `approval_policy=never` 拒绝，未执行，也未从其他入口重放。全部信号一致性通过只读工具完成；未重新执行付费供应商研究或自动交易。

## 复验

```powershell
& 'C:\Users\Rome\AppData\Local\Programs\A-share Quant\resources\python\python.exe' scripts/verify_strategy_equivalence.py --date 2026-10-23 --count 0 --workers 8 --batch-size 16 --legacy-results output/scan-profile/process8-full/results.json --output output/scan-production/recheck-new-directory
```

输出目录必须不存在。验证期间不要修改行情、策略、参数或服务源码。正式完整流程从桌面“数据更新”选择日期和五策略后执行，按发布 run_id 核对结果。
