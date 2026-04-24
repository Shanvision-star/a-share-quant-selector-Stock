# 前端加载优化与参数持久化改造记录（2026-04-24）

## 1. 背景与目标

本次改造聚焦两个核心痛点：

1. **页面加载慢**：请求并发与状态管理耦合较高，存在重复请求、过期请求回写、后端部分重操作阻塞事件循环等问题。  
2. **参数易丢失**：设置页仅依赖当前页面状态，切换页面、刷新或关闭标签页时，未保存参数可能丢失。

目标是：

- 建立“可回溯、可扩展”的前后端分层；
- 保留“手动保存”语义，同时避免未保存修改被意外丢失；
- 降低请求与模块耦合，提升页面稳定性与性能可预测性。

---

## 2. 本次改造最终解决了什么问题

1. **设置页参数不再因切页/刷新/关页而静默丢失**（未保存时会有明确拦截提醒）。  
2. **配置写入具备 revision 乐观锁**，并发修改冲突可被检测（409），避免“后保存覆盖先保存”。  
3. **前端请求治理完善**：同 key 旧请求会取消，过期请求结果不再污染当前 UI。  
4. **股票列表接口耗时逻辑进一步下沉到服务层 + 线程池**，减少异步路由线程被同步 I/O 卡住的风险。  
5. **关键链路补齐自动化测试**，后续回归与改动成本明显降低。

---

## 3. 分步骤实现方法、逻辑与技术点

## Step 1：建立前端测试基线（TDD 起点）

- 新增 Vitest 运行能力，落地首批 store/request 单测。
- 目的：先有可执行回归，再做状态和请求层改造，降低改造风险。

**技术**：Vitest、Pinia store 单测、最小可行 TDD 循环。

---

## Step 2：配置接口 revision 化（后端契约升级）

- `/api/config` 增加 `revision` 返回值；
- `POST /api/config` 增加 `expected_revision` 入参；
- 版本冲突返回 `409`，前端据此刷新冲突策略数据。

实现逻辑：

1. 读取配置并计算稳定 revision（哈希）。
2. 写入前对比 `expected_revision` 与当前 revision。
3. 一致才允许写入；不一致返回冲突。

**技术**：FastAPI、Pydantic 契约约束、乐观锁（Optimistic Concurrency Control）。

---

## Step 3：设置页草稿态 + 离开保护

- 引入 `settingsDraft` store，拆分“服务端状态”和“本地草稿状态”；
- 路由切换时进行未保存拦截；
- 后续补齐 `beforeunload` 保护，覆盖刷新/关页场景；
- 409 冲突后不再粗暴全量覆盖草稿，仅刷新冲突策略，保留其他未保存编辑。

实现逻辑：

1. 页面加载时把后端配置复制到本地草稿。
2. 编辑只改草稿，不改服务端基线。
3. 点击保存时携带 `expected_revision`。
4. 保存成功后 `markSaved` 更新基线与 revision。
5. 冲突时局部刷新，尽量减少用户编辑损失。

**技术**：Vue 3 + Pinia、路由守卫、`beforeunload` 事件保护。

---

## Step 4：请求管理与跨页查询状态共享

- 新增 `requestManager`：同 key 新请求会主动取消旧请求；
- 新增 `queryState`：Home / StrategyResults 共用筛选、分页等查询状态；
- 持久化反序列化增加校验，避免脏数据污染页面状态；
- SSE/异步错误处理改为显式可见，减少静默失败。

实现逻辑：

1. 为关键请求分配 request key。
2. 启动新请求时取消旧 controller。
3. 响应落地前校验“是否仍是当前请求”。
4. 仅当前请求可更新页面状态。

**技术**：AbortController、去重取消、运行时数据校验、错误可观测化。

---

## Step 5：股票列表服务下沉与性能护栏

- 将列表编排逻辑从 `router` 下沉到 `stock_list_service`；
- 异步路由内重 I/O / 重计算路径统一放入 `run_in_threadpool`；
- 修复缓存并发与快照应用竞态，完善锁与事件信号逻辑。

实现逻辑：

1. 路由只做参数接收与委派。
2. 服务层负责过滤、排序、分页、快照策略。
3. 重操作线程池化，防止事件循环被阻塞。
4. 缓存/快照状态通过锁和事件保证一致性。

**技术**：FastAPI 线程池委派、并发锁、事件信号、服务层解耦设计。

---

## Step 6：K 线请求过期取消 + 文档同步

- `getKline` 支持 `AbortSignal`；
- `KlineChart` 使用稳定请求 key 管理同类请求；
- 旧请求失败不再覆盖新请求状态（避免“过期错误回写”）。

实现逻辑：

1. 新渲染开始时取消上一轮同类请求。
2. 响应与错误处理前检查请求是否仍“当前有效”。
3. 无效请求直接丢弃，不触发 UI 误更新。

**技术**：Axios `signal`、组件内请求序号/当前请求校验、防竞态 UI 更新。

---

## 4. 关键修改文件清单（按职责）

| 领域 | 关键文件 |
|---|---|
| 配置 revision 契约 | `web/backend/services/config_service.py`, `web/backend/routers/config_api.py`, `web/backend/models/schemas.py`, `web/backend/services/strategy_service.py`, `strategy/strategy_registry.py` |
| 设置页草稿与防丢 | `web/frontend/src/stores/settingsDraft.ts`, `web/frontend/src/views/SettingsView.vue`, `web/frontend/src/router/index.ts`, `web/frontend/src/composables/beforeUnloadGuard.ts` |
| 请求治理与共享状态 | `web/frontend/src/api/requestManager.ts`, `web/frontend/src/stores/queryState.ts`, `web/frontend/src/views/HomeView.vue`, `web/frontend/src/views/StrategyResultsView.vue`, `web/frontend/src/api/index.ts` |
| 列表服务下沉与并发 | `web/backend/services/stock_list_service.py`, `web/backend/routers/stock.py` |
| K线请求取消 | `web/frontend/src/components/KlineChart.vue`, `web/frontend/src/components/klineRequest.ts`, `web/frontend/src/api/index.ts` |
| 测试 | `web/backend/tests/test_config_api_revision.py`, `web/backend/tests/test_stock_list_service.py`, `web/frontend/src/stores/__tests__/settingsDraft.spec.ts`, `web/frontend/src/stores/__tests__/queryState.spec.ts`, `web/frontend/src/api/__tests__/requestManager.spec.ts`, `web/frontend/src/api/__tests__/klineApi.spec.ts`, `web/frontend/src/components/__tests__/klineRequest.spec.ts`, `web/frontend/src/composables/__tests__/beforeUnloadGuard.spec.ts` |
| 文档 | `README.md`, `docs/technical_documentation.md`, `docs/superpowers/specs/2026-04-23-frontend-architecture-performance-params-design.md`, `docs/superpowers/plans/2026-04-23-frontend-load-settings-persistence-performance-plan.md` |

---

## 5. 回溯建议（如何快速定位改动）

本次改动涉及 **根仓（backend/docs）** 与 **`web/frontend` 嵌套仓** 两条提交线，建议按任务顺序回溯：

- 根仓关键提交：`6f71f52`、`ddd0c4b`、`dfc091e`、`6107f2b`、`ff4af9e`、`bd66b75`、`631f392`、`b2f8d90`、`bbc15c6`、`8cee7ef`
- 前端仓关键提交：`02e3e34`、`20ede95`、`b0444e4`、`c362bc7`、`47084a9`、`48b57c5`、`02a312e`、`36279e4`、`c338808`

可先从“提交信息 + 对应测试文件”双线阅读，最快理解“为什么这样改”。

---

## 6. 本次实践中使用到的核心技术方法

1. **TDD/回归优先**：先写失败测试，再实现，再回归。  
2. **乐观锁防并发覆盖**：revision + expected_revision。  
3. **请求取消与去重**：AbortController + request key。  
4. **状态分层**：服务端基线状态 vs 前端草稿状态。  
5. **后端分层解耦**：Router（薄）-> Service（厚）职责划分。  
6. **并发一致性控制**：锁、快照状态机、线程池隔离重操作。  
7. **错误显式化**：避免静默吞错，提升诊断效率。

---

## 7. 后续维护注意事项

1. 新增设置项时，优先接入 `settingsDraft`，不要绕过草稿层直接改服务端对象。  
2. 新的高频请求建议统一走 `requestManager`，并定义稳定 request key。  
3. `/api/config` 调用方必须传 `expected_revision`。  
4. 后端异步路由里若存在磁盘扫描/重计算，优先评估是否需要线程池化。  
5. 根仓与嵌套前端仓有独立提交历史，回滚和 cherry-pick 时要双仓同步考虑。

