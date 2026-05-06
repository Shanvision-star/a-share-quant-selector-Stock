# 下一步实施计划（Next Plan）

> 创建时间：2026-04-26  
> 当前分支：`web`  
> 已完成基线：Phase 0 Quick Win（commit `858f84d`）+ Phase 2 Web 加固（commit `16aaaa9`）+ Phase 2.4 日志统一（commit `4795e32`），均为本地提交，待 push

---

## 0. 当前状态快照

| 项 | 状态 |
|---|---|
| Phase 0 — 修 P0 + 裸 except + 死代码 | ✅ 已完成（本地 commit） |
| Phase 2.1 — FastAPI CORS / lifespan / startup 日志 | ✅ 已完成（本地 commit `16aaaa9`） |
| Phase 2.2 — data_dir 路径安全 | ✅ 已完成（本地 commit `16aaaa9`） |
| Phase 2.3 — K 线 code 输入校验 | ✅ 已完成（本地 commit `16aaaa9`） |
| Phase 2.4 — 日志统一 + JSON 日志 | ✅ 已完成（本地 commit `4795e32`） |
| Phase 2.5 — reload_params 去重 | ✅ 已完成（本地 commit `16aaaa9`） |
| `git push origin web` | ⏳ 待网络恢复后执行 |
| Phase 1 — 清理 `web/frontend` submodule 膨胀 | ⏸️ 暂停：此前已确认不动 `web/frontend` |
| Phase 2 剩余项 — config_api 白名单、stock/strategy 路由分页校验 | ✅ 已完成（待提交） |
| 测试基线 — reload 去重、data_dir 校验、非法 code/limit 422 | ✅ 已完成（待提交，`17 passed`） |
| Phase 3 — 架构内聚（拆 god class + Repository + 测试） | ❌ 未开始 |
| Phase 4 — 性能与体验 | ❌ 未开始 |

---

## 1. 执行计划与边界（当前优先级）

这部分是接下来真正执行时的“工作包边界”。原则是：先把脏工作区分拣干净，再补 Phase 2 剩余安全边界，再建立测试基线，最后才进入 Phase 3 大拆分。每一步只提交本步骤文件，禁止把回测、人工选股、脚本、前端子仓库和 Phase 2 安全修复混在同一个提交里。

### 1.1 工作包 A：整理当前脏工作区

**目标**：把当前未提交改动按业务主题拆开，形成可 review、可回滚的独立任务。

**执行状态（2026-04-27）**：已完成分组，不处理 `web/frontend`，不回滚用户已有改动。

| 主题 | 文件范围 | 本轮处理 |
|---|---|---|
| Phase 2 / 文档 | `docs/copilotchat/next_plan.md`、Phase 2 校验与测试相关文件 | ✅ 本轮继续处理 |
| 回测 | `web/backend/routers/backtest.py`、`web/backend/services/backtest_service.py`、`docs/copilotchat/backtest_updates_20260426.md` | ⏸️ 独立任务，暂不混入 Phase 2 |
| 人工选股池 | `web/backend/routers/manual_selection.py`、`web/backend/services/manual_selection_service.py` | ⏸️ 独立任务，暂不混入 Phase 2 |
| 统一作业/策略筛选 | `web/backend/routers/update.py`、`web/backend/services/data_service.py`、`web/backend/services/sqlite_service.py` | ⏸️ 独立任务，暂不混入 Phase 2 |
| 数据脚本 | `scripts/backfill_history.py`、`scripts/diagnose_data_coverage.py`、`scripts/extend_history_baostock.py` | ⏸️ 独立任务，暂不混入 Phase 2 |
| 配置调参 | `config/strategy_params.yaml` | ⏸️ 保留现状，不纳入 Phase 2 |
| 前端子仓库 | `web/frontend` dirty | ⏸️ 明确不处理 |
| 待确认 | `.superpowers` | ⏸️ 不纳入提交 |

**执行步骤**：
1. 用 `git status --short` 和 `git diff --name-only` 建立脏文件清单。
2. 按来源分组：
  - 回测 API / 回测服务：`web/backend/routers/backtest.py`、`web/backend/services/backtest_service.py` 等。
  - 人工选股池：`web/backend/routers/manual_selection.py`、`web/backend/services/manual_selection_service.py`、SQLite schema 变更等。
  - 统一作业/策略筛选：`web/backend/routers/update.py`、`web/backend/services/data_service.py` 等。
  - 数据脚本：`scripts/backfill_history.py`、`scripts/diagnose_data_coverage.py`、`scripts/extend_history_baostock.py`。
  - 文档记录：`docs/copilotchat/*.md`。
  - 前端子仓库：`web/frontend` dirty 状态，仅记录，不处理。
3. 每组先写一句任务说明：目的、涉及文件、验证方式、是否依赖前端。
4. 只在明确归属后分批提交；无法确认归属的文件保持未暂存。

**边界约束**：
- 不修改 `web/frontend`，除非后续明确授权处理前端子仓库。
- 不把文档、脚本、后端 API、SQLite schema 放进同一个“杂项提交”。
- 不回滚用户已有改动；只分拣、记录、在确认归属后提交。
- 不在这个工作包里修新 bug，发现问题只写入对应任务说明。

**验收标准**：
- 每个脏文件都有归属：回测、人工选股、统一作业、脚本、文档、前端子仓库、待确认。
- 暂存区只包含当前准备提交的那一组文件。
- 每组提交前能列出对应验证命令或手工验证路径。

**按业务主题拆分的好处**：
1. **Review 更快**： reviewer 看到“config 白名单”就只审安全边界，不需要同时理解回测引擎、SQLite schema 和脚本。
2. **回滚更安全**：如果回测服务有问题，只回滚回测提交，不会把已经修好的 CORS、日志、输入校验一起撤掉。
3. **验证更精确**：每个主题有自己的验证命令；API 校验跑 422 测试，脚本跑 dry-run，回测跑样例参数，不会用一个大而泛的测试掩盖问题。
4. **冲突更少**：前端子仓库、后端安全、策略扫描、数据脚本彼此改动频率不同，拆开后合并冲突更容易定位。
5. **学习路径更清楚**：一次只看一个业务主题，能分清“为什么要改”和“改动影响哪条链路”，比看一个混合大 diff 更容易复盘。

### 1.2 工作包 B：补完 Phase 2 剩余边界校验

**目标**：把 Web API 的可写配置、分页参数、股票代码参数都收口到明确白名单，避免非法输入进入业务层。

**执行状态（2026-04-27）**：已完成。`config_api.py` 增加敏感键拒绝，`ConfigUpdateRequest` 禁止额外顶层字段，`strategy.py` 历史结果 code 查询增加六位数字校验；`stock.py` 分页上限已有测试覆盖。

**执行步骤**：
1. `web/backend/routers/config_api.py`
  - 用 Pydantic 模型定义允许写入的配置字段。
  - 明确拒绝 `data_dir`、`dingtalk.secret`、路径类配置、未知键。
  - 返回 400/422 时给出清晰错误信息，不泄露敏感值。
2. `web/backend/routers/stock.py`
  - 列表/历史类接口增加 `limit: int = Query(..., ge=1, le=500)`。
  - 股票代码参数统一 `pattern=r"^\d{6}$"`。
3. `web/backend/routers/strategy.py`
  - 结果列表、历史结果、按 code 查询等接口增加分页上限。
  - 所有 `code` 参数统一六位数字校验。
4. 保持现有响应结构，避免前端调用字段变化。

**边界约束**：
- 只做 API 输入边界，不改策略扫描逻辑、不改缓存结构、不改前端页面。
- 不修改已完成的日志统一提交内容，除非发现 Phase 2 校验必须依赖的错误。
- 不引入新的配置存储格式；继续使用现有 YAML/JSON/SQLite 约定。

**验收标准**：
- 非法 code（如 `abc`、`00001`、`0000011`）返回 422。
- 超大 `limit` 返回 422 或被明确限制。
- 写入敏感配置被拒绝。
- 原有合法请求响应结构不变。

### 1.3 工作包 C：补测试基线

**目标**：先保护已修复的安全边界和注册器行为，再进入大拆分。

**执行状态（2026-04-27）**：已完成首批测试基线，`pytest tests/test_strategy_registry.py tests/test_quant_config.py tests/test_web_validation.py -q` 结果为 `17 passed`。

**优先测试**：
1. `tests/test_strategy_registry.py`
  - 覆盖 `reload_params` 对别名策略按类对象去重。
  - 断言同一个策略类不会因为多个注册名重复实例化。
2. `tests/test_quant_config.py`
  - 覆盖 `data_dir` 合法相对路径。
  - 覆盖 `data_dir` 指向项目外路径时抛出 `ValueError`。
3. `tests/test_web_validation.py`
  - 覆盖 K 线非法 code 返回 422。
  - Phase 2 剩余校验完成后，补 stock/strategy 非法 code 和 limit 测试。

**边界约束**：
- 测试只验证当前已存在行为和 Phase 2 边界，不借测试机会重构实现。
- 优先使用小样本、mock、临时目录，避免依赖全量行情数据和外部网络。
- 不追求一次达到 80% 全仓覆盖；先建立关键路径回归网。

**验收标准**：
- 新增测试能在本地 `.venv` 下独立运行。
- 测试失败时能明确指出是注册器、配置路径还是 API 参数校验问题。
- Phase 3 开始前，这三类测试必须稳定通过。

### 1.4 工作包 D：测试稳定后进入 Phase 3 拆分

**目标**：在测试保护下拆 `QuantSystem`、`AKShareFetcher`、`B2Strategy`，降低 god class 和巨文件维护成本。

**执行顺序**：
1. 先拆 `QuantSystem` 的编排职责：数据更新、策略运行、通知导出、调度分别下沉到 service。
2. 再拆 `AKShareFetcher`：历史行情、实时行情、市值缓存、Baostock fallback 分模块。
3. 最后拆 `B2Strategy`：指标计算、信号判定、图形匹配、导出通知分模块。
4. 每拆一个模块都保留原入口兼容层，CLI 和 Web 调用不一次性改完。

**边界约束**：
- Phase 3 不能在 Phase 2 剩余边界校验未完成、测试基线未通过时启动。
- 每次只拆一个职责，不同时改业务规则。
- 保持 CSV/JSON 数据源不变，不引入数据库替换行情存储。
- 保持现有 CLI 命令和 Web API 响应结构兼容。

**验收标准**：
- 每个拆分 PR 都能通过测试基线。
- `python main.py run --help`、关键策略扫描烟测、Web API smoke test 可运行。
- 拆分后原模块保留兼容门面，外部调用不需要一次性迁移。

### 1.5 提交边界建议

| 提交 | 内容 | 不包含 |
|---|---|---|
| Commit A | 脏工作区分组文档或单组已确认改动 | Phase 2 校验、测试、Phase 3 重构 |
| Commit B | `config_api.py` 白名单 | stock/strategy 分页、回测、人工选股 |
| Commit C | `stock.py` / `strategy.py` 参数校验 | config 白名单、测试之外的业务改动 |
| Commit D | reload/data_dir/code 422 测试基线 | 架构拆分 |
| Commit E+ | Phase 3 单模块拆分 | 新业务功能、前端子仓库清理 |

---

## 1.6 路线选择

### 🟢 小步快跑路线（推荐，3 天内完成可见收益）

```
Phase 1 (0.5d) ──▶ Phase 2 (1-2d) ──▶ 评估是否进入 Phase 3
   清理 submodule         安全 + 日志 + 校验
```

**优点**：风险低、易回滚、每步独立 PR；上线即生效。  
**适合场景**：当前业务仍在迭代，不希望大改架构。

### 🟡 大步路线

```
Phase 3 (3-5d, 多 PR) ──▶ Phase 4
   拆 QuantSystem / Repository 抽象 / 测试基线 / CI
```

**优点**：彻底解决可维护性问题，长期收益最大。  
**风险**：跨模块改动多，需严格按 PR 切分；必须先有测试基线。  
**前置**：Phase 1 + Phase 2 仍建议先做，否则 god class 拆分时会和未规整的日志/校验代码冲突。

---

## 2. Phase 1 — 清理 `web/frontend` submodule 膨胀

**目标**：让 submodule 只包含纯前端文件，仓库体积大幅缩小，前后端边界清晰。

**当前决策**：暂不执行。此前已选择不改 `web/frontend` 这个嵌套仓库/子项目，避免把前端脏状态和后端 Phase 2 加固混在一起。后续只有在明确授权清理前端子仓库时再启动本阶段。

### 步骤
1. 进入 submodule：`cd web/frontend && git checkout web`（先解决之前 exit 128 的脏状态）
2. 在 submodule 中删除非前端文件：
   - `main.py`、`quant_system.py`、`web_server.py`、`run_b1_scan.py`
   - `utils/`、`strategy/`、`web/`、`scripts/`、`config/`、`docs/`、`__pycache__/`
   - `requirements.txt`、`README*.md`、`market_cap_cache.json`、`temp_file`
   - `test_dingtalk.py`、`test_kline_chart.py`
   - `B1_CHANGELOG_20260402.md`、`B1_STAGE_STRATEGY.md`、`~changelog.md`、`quant.sh`
3. 仅保留：`index.html`、`src/`、`public/`、`package.json`、`package-lock.json`、`vite.config.ts`、`tsconfig*.json`、`.gitignore`、`.gitattributes`、`README.md`（前端版本）、`dist/` 不入库
4. 在 submodule 的 `.gitignore` 显式 ignore：`dist/`、`node_modules/`、`.vscode/`、`*.py`、`__pycache__/`
5. submodule 提交并 push 到 frontend 仓库自己的 `web` 分支
6. 主仓库 `git add web/frontend && git commit -m "chore: bump frontend submodule pointer after cleanup"`

### 验证
- `du -sh web/frontend` 显著减小（预计 < 50MB，原可能 > 200MB）
- `cd web && npm run dev` 能正常启动
- `cd web && npm run build` 能正常输出 dist/

### 工作量
0.5 天

---

## 3. Phase 2 — 安全与可观测性

**目标**：FastAPI 生产可用 + 关键路径有结构化日志 + 输入校验到位。

### 任务清单

#### 2.1 FastAPI 安全加固
- [x] `web/backend/main.py`
  - 把 `allow_origins=["*"]` 改成读取 `WEB_CORS_ORIGINS` 环境变量（逗号分隔白名单），未设置时只允许 `http://localhost:5173,http://127.0.0.1:5173`
  - 把 `@app.on_event("startup")` 替换为 `lifespan` 异步上下文管理器
  - 预热失败必须 `logger.exception(...)`，不能再 `pass`

#### 2.2 配置安全校验
- [x] `quant_system.py::_load_config`
  - 读到 `data_dir` 后用 `Path(data_dir).resolve()` 校验必须是相对路径或落在 `project_root` 内
  - 不通过则 `raise ValueError`
- [ ] `web/backend/routers/config_api.py`
  - POST 端点改用 Pydantic 模型严格定义可写字段（白名单）
  - 拒绝写入 `data_dir`、`dingtalk.secret` 等敏感键

#### 2.3 输入校验
- [ ] `web/backend/routers/stock.py`、`strategy.py`、`kline.py` 的 list/history 接口
  - 添加 `limit: int = Query(100, ge=1, le=500)` 上限
  - `code` 参数加 `pattern=r"^\d{6}$"`
- [x] `web/backend/routers/kline.py`
  - 个股 code 路径参数已增加 `pattern=r"^\d{6}$"`
- [ ] `web/backend/routers/manual_selection.py` POST/DELETE 用 Pydantic body 模型

#### 2.4 日志统一
- [x] `quant_system.py`、`utils/akshare_fetcher.py`、`strategy/*.py` 业务路径的 `print` 替换为 `logging.getLogger(__name__)`，保留进度类输出
- [x] `web/backend/main.py` 增加可选 JSON 日志格式（环境变量 `WEB_LOG_FORMAT=json`）

实施备注：保留 CLI 阶段标题、进度条、结果摘要和 SSE 进度相关输出；仅收敛缓存、异常、后台刷新、策略库构建等后台诊断日志。

#### 2.5 修复 Bug 7（reload_params 不去重）
- [x] `strategy/strategy_registry.py::reload_params`
  - 按 `id(strategy_class)` 去重，避免 B1CaseAnalyzer/B1CaseStrategy 别名重复实例化

### 2.6 已修改内容与技术路线说明

本轮已提交内容集中在“边界安全”和“可观测性”，没有改策略算法本身，也没有触碰 `web/frontend`。这样做的原因是：先把输入、配置、日志这些基础设施收稳，再进入大规模拆分，风险更低，也更容易定位后续问题。

| 文件 | 已修改内容 | 技术路线 | 为什么这样做 |
|---|---|---|---|
| `web/backend/main.py` | CORS 白名单、FastAPI lifespan、startup 预热异常日志、`WEB_LOG_FORMAT=json` | Web 入口只负责全局运行时配置；日志格式用环境变量切换，默认保持文本日志 | 生产部署需要限制跨域来源；lifespan 是 FastAPI 推荐的新生命周期入口；JSON 日志便于以后接入日志采集系统，同时不影响本地开发 |
| `quant_system.py` | `data_dir` 路径解析与边界校验；B1 图形库初始化/匹配异常改为 logger | 在配置加载边界做校验；业务异常进入模块 logger，CLI 结果输出继续 `print` | `data_dir` 是文件系统边界，必须防止写到项目外；CLI 用户仍需要直观看到进度和结果，所以不能把所有输出机械替换成日志 |
| `utils/akshare_fetcher.py` | 缓存读写、接口降级、Baostock 冷却、后台市值刷新、并发异常改为 logger | 抓取器内部诊断走 `logging.getLogger(__name__)`；进度回调和 SSE 消息保持原逻辑 | 抓取器同时服务 CLI 和 Web。诊断日志应该可过滤、可分级；进度事件是用户体验的一部分，不能随意改动 |
| `strategy/pattern_config.py` | YAML 配置加载失败改为 logger warning | 配置读取失败保留 fallback，但记录原因 | 策略默认值能保证系统继续运行，但失败原因必须可追踪 |
| `strategy/pattern_matcher.py` | `fastdtw` 缺失提示改为 logger warning | 可选依赖缺失不阻断运行，只降低匹配实现级别 | 这是运行环境诊断，不是用户操作结果，用日志更合适 |
| `strategy/pattern_library.py` | B1 案例库构建、缓存、匹配异常改为 logger | 案例库生命周期事件统一日志化 | 构建/缓存问题常发生在后台或 Web 启动阶段，日志比散落 print 更容易定位 |
| `strategy/b2_pattern_library.py` | B2 案例库构建、规则扫描、相似度评分日志化 | 扫描阶段输出从 stdout 转为结构化日志 | B2 扫描链路长，日志分级后更适合排查“是规则没命中，还是案例库为空，还是相似度阈值过滤” |
| `strategy/b2_strategy.py` | TXT 导出提示改为 logger，并去掉重复输出 | 导出成功/失败都归入策略模块日志 | 避免 CLI 中重复刷屏，也让 Web 后台运行时能看到导出路径 |
| `strategy/strategy_registry.py` | `reload_params` 按策略类对象去重 | 用 `id(strategy_class)` 消除别名重复实例化 | 当前注册器存在别名策略，按名称去重不够稳定；按类对象去重更贴近真实实例化成本 |
| `web/backend/routers/kline.py` | 股票代码 path 参数校验 | API 边界用 Pydantic/FastAPI 参数校验先拦截非法输入 | 错误越早返回越便宜，也能减少后续文件读取和数据处理路径的异常 |

关键原则：

1. **入口统一配置，模块只声明 logger**：`web/backend/main.py` 配置日志格式；业务模块只使用 `logging.getLogger(__name__)`，避免每个文件各自配置日志导致重复输出。
2. **保留用户可见进度输出**：CLI 阶段标题、进度条、结果摘要、Web SSE 进度事件都保留原行为，避免“可观测性优化”变成用户体验回退。
3. **先做边界，再做重构**：CORS、路径、输入校验属于系统边界；这些稳定后，再拆 `QuantSystem`、`AKShareFetcher`、`B2Strategy` 这种大文件，回归成本会低很多。
4. **用小提交控制风险**：`858f84d`、`16aaaa9`、`4795e32` 分别对应 Phase 0、Phase 2 安全、Phase 2.4 日志，方便单独 review 和回滚。

### 验证
- `curl -X POST http://localhost:5000/api/config -d '{"data_dir":"/etc"}'` 应返回 400/422
- 启动时人为破坏 `stock_metric_snapshot`，日志应有完整 traceback
- 浏览器从非白名单域名请求应被 CORS 拦截

### 工作量
1–2 天，按 2.1 / 2.2 / 2.3+2.4 / 2.5 拆 4 个 PR。

---

## 4. Phase 3 — 架构内聚（大步路线主体）

**目标**：拆 god class、统一缓存抽象、补测试、加 CI。  
**前置**：Phase 1 + Phase 2 完成（否则 god class 拆分时会卡在未整理的日志/校验上）。

### 4.1 拆 `QuantSystem`（保留兼容门面）
新增模块：
- `services/data_pipeline.py`：`init_data` / `update_data` / `daily_update` / 数据新鲜度校验
- `services/strategy_runner.py`：`run_full` / `run_with_b1_match` / `run_with_b2_*` / `run_backtest_3day`
- `services/notification.py`：钉钉相关
- `services/scheduler.py`：定时任务

`QuantSystem` 退化为 DI 装配门面，CLI 和 Web 都依赖具体 service。

### 4.2 Repository 抽象
新增 `storage/`：
- `stock_repository.py`：CSV 读写
- `cache_repository.py`：JSON 缓存原子写（temp file + `os.replace`）+ schema version
- `strategy_run_repository.py`：SQLite 持久化

迁移 `market_cap_cache.json`、`b1_pattern_library_cache.json`、`b2_pattern_match_cache.json`、`stock_list_metrics_cache.json`、`web_strategy_results.json` 到统一 `cache_repository`。

### 4.3 策略注册器稳健化
- `auto_register_from_directory` 改用 `importlib.import_module(f"strategy.{module_name}")`
- 移除 `sys.path.insert` 副作用
- `strategy/__init__.py` 维护显式 `STRATEGIES` 列表，自动发现仅做补充
- 保留按类对象去重

### 4.4 拆分巨文件
- `utils/akshare_fetcher.py` 2239 行 → `utils/fetcher/{ak_history.py, ak_spot.py, baostock_fallback.py, market_cap_cache.py}`
- `strategy/b2_strategy.py` 1666 行 → `strategy/b2/{indicators.py, signals.py, pattern.py}`
- `quant_system.py` 1401 行 → 拆成 services（见 4.1）

### 4.5 测试基线（pytest，目标关键路径 ≥ 60%）
- [ ] `tests/test_strategy_registry.py`：注册表 lock、reload、去重
- [ ] `tests/test_csv_manager.py`：读写、缺失文件、坏行容错
- [ ] `tests/test_market_cap_cache.py`：原子写、过期判定、并发锁
- [ ] `tests/test_backtrace_analyzer.py`：Phase 0 修复的回归用例
- [ ] `tests/test_web_routers.py`：用 `httpx.AsyncClient` 跑 `/api/health`、`/api/strategy/results`、422 校验路径
- [ ] `tests/test_data_pipeline_progress.py`：mock fetcher 验证 SSE 事件结构

### 4.6 CI
新增 `.github/workflows/ci.yml`：
```yaml
- ruff check .
- pytest -q --cov=. --cov-fail-under=60
- cd web && npm ci && npm run build
```

### 工作量
3–5 天，每个子任务独立 PR：
- PR-1: 4.5 测试基线（先于拆分动手）
- PR-2: 4.3 注册器修复
- PR-3: 4.2 Repository
- PR-4: 4.1 拆 QuantSystem
- PR-5: 4.4 拆巨文件
- PR-6: 4.6 CI

---

## 5. Phase 4 — 性能与体验（按需）

- [ ] `market_cap_cache` 改 SQLite 单表
- [ ] SSE 事件统一封装 `web/backend/services/events.py`，CRLF 兼容
- [ ] `KlineChart` ECharts formatter null 守卫
- [ ] AKShare fast-path 增加 per-stock 进度事件
- [ ] `web_strategy_results.json` 加 `unique_total` 字段
- [ ] 前端策略结果页相应字段展示

工作量 2–3 天。

---

## 6. 残留 P1/P2 Bug 跟踪表

| ID | 描述 | 计划阶段 |
|---|---|---|
| Bug 5 | startup 预热静默吞错 | ✅ 已修复：Phase 2 §2.1 |
| Bug 6 | CORS 不安全 | ✅ 已修复：Phase 2 §2.1 |
| Bug 7 | reload_params 实例不去重 | ✅ 已修复：Phase 2 §2.5 |
| Bug 8 | data_dir 路径未校验 | ✅ 已修复：Phase 2 §2.2 |
| 宽泛 except Exception 157 处 | ✅ 已完成第一轮日志收敛：Phase 2 §2.4；后续随功能改动继续收敛 |
| 巨文件超 800 行 | quant_system / akshare_fetcher / b2_strategy | Phase 3 §4.4 |
| Windows GBK emoji 风险 | CLI/注册器输出 | 部分缓解：后台诊断转 logging；CLI 用户进度输出暂保留 |
| `tests/` 空目录 | 测试基线 | Phase 3 §4.5 |
| 根目录测试脚本散落 | 移入 `tests/` | Phase 1 §收尾 |
| `EmQuantAPI.py` 等厂商 SDK 散在根目录 | 移入 `vendor/em_quant/` | Phase 1 §收尾 |
| `utils/debug_b2_verbose.py` | 移入 `scripts/debug/` | Phase 1 §收尾 |

---

## 7. 推荐起步顺序

1. **先 push 本地已完成提交**：网络恢复后执行 `git push origin web`，把 `858f84d`、`16aaaa9`、`4795e32` 推到远端。
2. **整理当前脏工作区**：先决定回测、人工选股、脚本类未提交改动是否进入单独任务；不要和 Phase 2 后端加固混在一个提交里。
3. **补完 Phase 2 剩余边界校验**：优先做 `web/backend/routers/config_api.py` 的 Pydantic 白名单，拒绝写入 `data_dir`、钉钉密钥等敏感键；再补 `stock.py`、`strategy.py` 的分页上限和 code 校验。
4. **补测试基线再拆架构**：先写 `tests/test_strategy_registry.py`、`tests/test_quant_config.py`、`tests/test_web_validation.py`，覆盖本轮已修的 reload 去重、data_dir 校验、非法 code 返回 422。
5. **进入 Phase 3 拆分**：测试基线稳定后，再拆 `QuantSystem`、`AKShareFetcher`、`B2Strategy`，避免大重构时没有回归保护。
6. **`web/frontend` 继续暂停**：除非明确授权清理嵌套前端仓库，否则不处理 Phase 1 submodule 清理。

---

## 8. 不在计划内（已确认无需做）

- 整体重写 / 切换到数据库存储（CSV 仍是 source of truth）
- 引入 Celery 或外部任务队列（schedule 已够用）
- 整体迁移到 Vue 3 之外的前端框架
