# 下一步实施计划（Next Plan）

> 创建时间：2026-04-26  
> 当前分支：`web`  
> 已完成基线：Phase 0 全部 Quick Win + 裸 except 清理 + 死代码删除（commit `858f84d`，待 push）

---

## 0. 当前状态快照

| 项 | 状态 |
|---|---|
| Phase 0 — 修 P0 + 裸 except + 死代码 | ✅ 已完成（本地 commit） |
| `git push origin web` | ⏳ 待网络恢复后执行 |
| Phase 1 — 清理 submodule 膨胀 | ❌ 未开始 |
| Phase 2 — 安全与可观测性 | ❌ 未开始 |
| Phase 3 — 架构内聚（拆 god class + Repository + 测试） | ❌ 未开始 |
| Phase 4 — 性能与体验 | ❌ 未开始 |

---

## 1. 路线选择

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
- [ ] `web/backend/main.py`
  - 把 `allow_origins=["*"]` 改成读取 `WEB_CORS_ORIGINS` 环境变量（逗号分隔白名单），未设置时只允许 `http://localhost:5173,http://127.0.0.1:5173`
  - 把 `@app.on_event("startup")` 替换为 `lifespan` 异步上下文管理器
  - 预热失败必须 `logger.exception(...)`，不能再 `pass`

#### 2.2 配置安全校验
- [ ] `quant_system.py::_load_config`
  - 读到 `data_dir` 后用 `Path(data_dir).resolve()` 校验必须是相对路径或落在 `project_root` 内
  - 不通过则 `raise ValueError`
- [ ] `web/backend/routers/config_api.py`
  - POST 端点改用 Pydantic 模型严格定义可写字段（白名单）
  - 拒绝写入 `data_dir`、`dingtalk.secret` 等敏感键

#### 2.3 输入校验
- [ ] `web/backend/routers/stock.py`、`strategy.py`、`kline.py` 的 list/history 接口
  - 添加 `limit: int = Query(100, ge=1, le=500)` 上限
  - `code` 参数加 `pattern=r"^\d{6}$"`
- [ ] `web/backend/routers/manual_selection.py` POST/DELETE 用 Pydantic body 模型

#### 2.4 日志统一
- [x] `quant_system.py`、`utils/akshare_fetcher.py`、`strategy/*.py` 业务路径的 `print` 替换为 `logging.getLogger(__name__)`，保留进度类输出
- [x] `web/backend/main.py` 增加可选 JSON 日志格式（环境变量 `WEB_LOG_FORMAT=json`）

实施备注：保留 CLI 阶段标题、进度条、结果摘要和 SSE 进度相关输出；仅收敛缓存、异常、后台刷新、策略库构建等后台诊断日志。

#### 2.5 修复 Bug 7（reload_params 不去重）
- [ ] `strategy/strategy_registry.py::reload_params`
  - 按 `id(strategy_class)` 去重，避免 B1CaseAnalyzer/B1CaseStrategy 别名重复实例化

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
| Bug 5 | startup 预热静默吞错 | Phase 2 §2.1 |
| Bug 6 | CORS 不安全 | Phase 2 §2.1 |
| Bug 7 | reload_params 实例不去重 | Phase 2 §2.5 |
| Bug 8 | data_dir 路径未校验 | Phase 2 §2.2 |
| 宽泛 except Exception 157 处 | 业务日志收敛 | Phase 2 §2.4 |
| 巨文件超 800 行 | quant_system / akshare_fetcher / b2_strategy | Phase 3 §4.4 |
| Windows GBK emoji 风险 | CLI/注册器输出 | Phase 2 §2.4 兼办 |
| `tests/` 空目录 | 测试基线 | Phase 3 §4.5 |
| 根目录测试脚本散落 | 移入 `tests/` | Phase 1 §收尾 |
| `EmQuantAPI.py` 等厂商 SDK 散在根目录 | 移入 `vendor/em_quant/` | Phase 1 §收尾 |
| `utils/debug_b2_verbose.py` | 移入 `scripts/debug/` | Phase 1 §收尾 |

---

## 7. 推荐起步顺序

1. **网络恢复后**：`git push origin web` 把 Phase 0 推上去
2. **Phase 1**：清理 submodule + 移动散落文件（半天，1 个 PR）
3. **Phase 2**：CORS/lifespan/路径校验/日志/Bug 7（1–2 天，4 个 PR）
4. **决策点**：评估业务节奏，选择是否进入 Phase 3 大步路线

---

## 8. 不在计划内（已确认无需做）

- 整体重写 / 切换到数据库存储（CSV 仍是 source of truth）
- 引入 Celery 或外部任务队列（schedule 已够用）
- 整体迁移到 Vue 3 之外的前端框架
