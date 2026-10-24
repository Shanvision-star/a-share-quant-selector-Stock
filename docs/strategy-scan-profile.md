# 全市场扫描 11 分 58 秒的定位与加速验证

历史剖析日期：2026-10-24。分支：`codex/strategy-scan-profile`，原型基于已交付桌面分支的 `62bdc11`。本文保留原型阶段的测量与判断；后续正式接入的准确性、完整桌面耗时和发行状态见 [0.2.1 正式桌面扫描验收](desktop-scan-production-acceptance.md)。

## 后续实现状态

本分支已将 Windows `spawn` 进程池接入正式扫描入口，加入目标日期截断后补足最多 320 根的历史读取、每股每策略终态、异常阻止发布、输入内容指纹和完整性检查。五策略公式、阈值和指标精度不变；B2 合法空 `damage_zone` 的序列化错误修复与调度变化分别验收。

完整快照与信号由父进程在 SQLite 事务中发布，桌面、系统状态和 Codex MCP 使用同一权威版本，JSON 保留为兼容镜像。Windows Job Object 负责回收后端子进程，绑定受限时记录并降级串行。0.2.1 打包桌面完整后端作业已实测 256.86 秒，122 条信号与真实 MCP 明细一致；下面的 62.78 秒、121 条和 31 项测试均是历史原型证据，不替代正式验收。

## 原型阶段结论与范围

当时定位到的瓶颈主要在本地策略计算和线程调度。使用桌面自带 Python 验证多进程原型：5155 只股票、原有五种策略、相同目标日和 320 根历史窗口，扫描 62.78 秒，121 条信号与当时已保存的全市场快照逐字段一致。

**这是只读计算原型的结果，测量当时尚未接入桌面正式扫描入口。** 62.78 秒包含子进程启动、计算和退出，另有主进程初始化 2.69 秒；不包含行情更新、SSE 推送、正式 JSON/SQLite 写入、Agent 分析和复盘。原型阶段没有修改策略公式、生产调度、原始行情、正式结果或安装包，也没有安装新依赖。

因此，不能宣称桌面完整流程已经从 718 秒降到 63 秒。已经证实的是：同样策略的计算部分有明显的多核加速空间，替换行情源不是当前第一优先级。

## 718 秒记录能证明什么

真实桌面作业 `20261023_234606_76b96d71`：2026-10-23 23:46:06 开始，23:58:04 完成，状态 `done`，5155 只股票，121 条信号。上一轮运行证据记录行情阶段缓存命中，主要工作为策略重建。此前腾讯批量报价单独探测为约 1.20 秒，但这个接口耗时不能代替完整历史补齐的耗时。

本次只读查询 SQLite 发现，这个 run 的事件表只留下一个 `job_complete`，没有分阶段或分策略时钟。因此不能把 718 秒精确拆成网络、计算、推送、入库各自的秒数，更不能用样本比例反推旧运行的每一秒。

之前界面出现的 `timeout of 120000ms exceeded` 来自 Zettaranc 的独立攻击日扫描请求。当时两个独立计算入口缺少统一计算资源调度；HTTP 超时也不会自动终止同步后端计算。这是原型阶段发现的并发风险，后续实现已加入共享作业租约。现有证据不足以量化它对上述 718 秒的影响，不把它当作已证明的主因。

原型测量时的代码定位（不是当前实现说明）：

- `web/backend/services/strategy_service.py`：`build_strategy_result_snapshot` 固定使用最多 8 个线程，每股一个 Future，执行本地五策略。
- `web/backend/services/data_service.py`：统一更新任务的重建回调每增加 5% 更新作业汇总，未持久化详细阶段耗时。
- `web/backend/routers/zettaranc.py`、`web/backend/services/zettaranc_attack_scanner.py`：独立攻击日扫描。
- `web/frontend/src/api/zettaranc.ts`、`web/frontend/src/views/ZettarancView.vue`：120 秒请求超时及提示来源。

## 相同输入下的调度比较

环境：本机 i7-12700K，12 物理核 / 20 逻辑处理器；桌面内置 Python 3.14.9，GIL 实测开启，Pandas 3.0.2，NumPy 2.4.4。

512 只样本采用固定随机种子，并包含当前全部 119 只命中股票、000717、688613 和已知告警股票 300987。每轮独立顺序运行，未同时执行本任务的其他 CPU 基准。输入 CSV 的大小和修改时间指纹前后及各模式间一致。无法据此保证整机完全无其他负载。

| 模式 | 扫描秒数 | 主进程初始化秒数 | 输出一致 |
| --- | ---: | ---: | --- |
| 串行 | 47.24 | 3.30 | 基准 |
| 8 线程，每股一个任务 | 43.25 | 3.68 | 是 |
| 4 进程，每批 16 只 | 11.62 | 2.30 | 是 |
| 8 进程，每批 16 只 | 9.47 | 1.91 | 是 |
| 8 进程，全市场 5155 只 | 62.78 | 2.69 | 与正式快照 121 条信号一致 |

进程模式用 Python 标准库 `ProcessPoolExecutor` 和 Windows `spawn`；每个子进程只初始化一次策略，任务只传代码批次和日期，结果交回父进程。未安装 Joblib。扫描计时包括进程池建立及退出，不包括父进程初始化和基准报告落盘。

512 只的四种调度结果排序后 SHA-256 相同：

`5913be37ee1b520f5f29b6d52d16b7717c15c668da159a4834fcf9b944a913ee`

8 线程扫描的进程 CPU 时间为 43.88 秒，墙钟 43.25 秒，平均约占用 1.01 个 CPU 核心，而非 8 核。加上 GIL 开启及函数剖析结果，支持“大量 Python/Pandas 操作受单进程执行限制”的判断。8 线程相对串行只有约 8% 时间下降；同一轮样本的 8 进程相对 8 线程约快 4.57 倍。

这些是单轮测量，受文件缓存、CPU 调度及其他负载影响，不是长期延迟保证。不能将样本倍数或原型全市场时间直接作为桌面端到端 SLA。

## 剩余计算热点

另做 512 只串行分阶段计时，不启用 cProfile，合计 36.08 秒。该计时用于定位计算结构，和前述独立串行轮次存在暖缓存、系统负载等运行条件差异，不把差值归因于代码优化。

| 阶段 | 秒数 | 该样本时间占比 |
| --- | ---: | ---: |
| 读取 CSV 与日期裁剪 | 2.46 | 6.8% |
| 共享基础指标 | 2.09 | 5.8% |
| B1 | 6.05 | 16.8% |
| B2 | 10.43 | 28.9% |
| 碗形 | 4.26 | 11.8% |
| 砖型 | 6.03 | 16.7% |
| Zettaranc | 4.75 | 13.2% |

五种策略计算合计约 87.4%；读取与裁剪约 6.8%。本地 CSV 并非零成本，但仅换成 Parquet/Polars 无法消除绝大多数时间。

80 只固定随机股票的 cProfile 用于定位函数调用，75 只有效：

- `calculate_zhixing_position_state` 调用 298 次，约每个有效股票 4 次；参数相同的状态有进一步复用机会。
- `calculate_zhixing_trend` 调用 150 次；共享基础线之外，砖型策略还会重算同参数基础线。
- B2 的 `analyze_prepared` / `_check_b1_precondition` 各调用 219 次，来自多个模板。应按模板参数核查共享边界，不能无条件共用判断。
- Pandas `iloc`/行列访问、逐列赋值、Series/DataFrame 创建、复制占用明显；80 只触发约 1677 万次函数调用。不是都耗在数学公式本身。
- 之前 KDJ 和砖型 SMA 的数组化已生效；它们不是当前唯一或最大的剩余热点。

cProfile 会增加开销，上述累计函数耗时存在嵌套，不能相加或当作 718 秒的原始耗时分配。

原型阶段 300987 触发既有 B2 `NoneType.get` 告警，旧业务层捕获后继续。原型与旧结果一致只证明当时的调度等价，不证明既有策略缺陷已解决，也不等于全面审计了行情质量。后续已修复合法空 `damage_zone` 的序列化问题；严格比较全部命中、未命中、跳过和错误终态的证据单独记录在正式验收中。

## GitHub 成熟实现如何借鉴

| 项目 / 官方资料 | 适合借鉴的部分 | 本项目决策 |
| --- | --- | --- |
| [Joblib](https://github.com/joblib/joblib)、[Loky](https://github.com/joblib/loky) | 跨进程计算、可复用进程池、减少反复创建工作进程；Joblib 官方文档也说明进程通信有序列化成本 | 第一优先级。已用标准库验证同类方案；当前 Python 已有进程池，不必先引入新框架 |
| [VectorBT](https://github.com/polakowo/vectorbt)、[指标缓存实现](https://github.com/polakowo/vectorbt/blob/master/vectorbt/indicators/nb.py) | 数组计算、Numba 编译热点、按参数缓存重复的滚动指标 | 第二优先级。提取计算方法，保留本项目策略条件、初值、日期与输出结构；不直接替换完整交易框架 |
| [Polars](https://github.com/pola-rs/polars) | Rust 多线程列式执行、惰性查询和批量 Parquet 读取 | 后续需要更大历史回测时再考虑；当前样本读取阶段占比低，迁移全部存储的收益优先级较低 |

[Joblib 并行文档](https://joblib.readthedocs.io/en/latest/user_guide/parallel.html)区分了受 GIL 限制的 Python 计算与释放 GIL 的编译扩展；线程并不对所有计算都无效。本项目的判断来自本机测量，不是一概否定线程。

[Python 3.14 进程池文档](https://docs.python.org/3.14/library/concurrent.futures.html#processpoolexecutor)说明可序列化函数/数据、可导入主模块和分批任务等约束。正式接入时必须在桌面启动入口验证这些条件。

[Numba 官方兼容表](https://numba.readthedocs.io/en/stable/user/installing.html#version-support-information)显示当前版本支持本机 Python/NumPy 版本范围；但桌面尚未安装 Numba，本次没有做编译、冷启动、精度或打包验证，不据此承诺额外收益。

## 原型阶段建议与后续边界

以下是当时提出的实施顺序。第 1、2 项中的正式调度、共享租约、输入快照、取消及发布检查已落地；逐策略更细耗时、额外指标复用、Numba 和增量缓存不应据此视为全部完成。

1. **先把策略计算搬到受控进程池。** 父进程管理 run、SSE、缓存及 SQLite；子进程只读行情并返回结果。按机器资源限制工作进程，4/8 进程作为已测候选，保留串行回退。统一更新、手动重建和 Zettaranc 独立扫描的计算资源，避免叠加占满机器。
2. **同时补齐运行观测和故障边界。** 保存读取、共享指标、各策略、汇总写入的时间；进程任务需完整参数/代码版本快照；取消、超时、子进程崩溃或桌面退出不得留下假完成状态，也不得用不完整结果覆盖旧缓存。前端等待与后台任务生命周期分开处理。
3. **再做低风险复用和热点数组化。** 砖型复用同参数知行线；知行状态按完整参数键缓存；核查 B2 模板之间可复用的历史检查；针对真正热点移植数组/Numba 内核。保留缺失值、初值、浮点运算和历史裁剪语义，逐股逐字段对比。
4. **按需加入增量复用。** 缓存键包含行情内容/版本、目标日、窗口、策略参数、策略与案例版本。只跳过输入未变股票。新交易日通常全市场都变化，不能宣称增量缓存每天只需分析少数股票；同日重复重建才是明确收益场景。

正式验收从桌面点击启动，记录完整墙钟时间，验证实时进度与取消/失败行为，再从桌面和真实 Codex MCP 回读同一新 run；并核对 Windows 发行包及内置解释器。原型阶段没有完成这些检查；后续执行状态以 [正式桌面扫描验收](desktop-scan-production-acceptance.md) 为准。

## 历史原型复现入口与证据

在项目根目录使用桌面自带 Python，无需用户配置 Python。以下脚本使用当前工作区代码重跑，因此历史窗口与异常修正后，结果可能与本文原始 SHA256 不同；当前严格逐股逐策略验收使用正式验收文档中的 `scripts/verify_strategy_equivalence.py`。

```powershell
$quantPython = "$env:LOCALAPPDATA\Programs\A-share Quant\resources\python\python.exe"
& $quantPython scripts/benchmark_strategy_scan.py --date 2026-10-23 --mode serial --count 512 --output output/scan-profile/recheck-serial
& $quantPython scripts/benchmark_strategy_scan.py --date 2026-10-23 --mode process --workers 8 --batch-size 16 --count 512 --compare output/scan-profile/recheck-serial/results.json --output output/scan-profile/recheck-process
& $quantPython scripts/benchmark_strategy_scan.py --date 2026-10-23 --mode process --workers 8 --batch-size 16 --count 0 --output output/scan-profile/recheck-full
```

输出目录必须不存在，防止覆盖前次证据。全市场模式只在目标日与正式快照一致时比较快照；`--compare` 对比完整单股输出。输入文件发生变化、进程任务失败或结果不一致时，脚本非零退出。只读原型不写正式行情/策略缓存、不触发模型或交易。

本机证据在 `output/scan-profile/`：四种 512 只调度模式的 `report.json` / `results.json`、`process8-full/`、`stages512/report.json`、`profile80/profile.txt` / `profile.pstats`、`historical-run.json`。输出是本地诊断产物，未提交 Git。

原型阶段验证：上述基准、等价比较和输入状态检查均成功；桌面内置 Python 的脚本导入和 `--help` 检查通过；`pytest tests/test_market_performance_regression.py tests/test_b2_strategy_regression.py -q` 为 31 passed、1 deselected，`git diff --check` 通过。该阶段未修改前端，无前端构建；未执行新的桌面完整更新、Agent/复盘或正式 MCP 新结果验收。
