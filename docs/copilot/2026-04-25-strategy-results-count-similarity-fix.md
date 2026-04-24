# 策略结果页“列表数量不匹配 + 相似度显示缺失”问题分析与修复说明

## 1. 问题现象

用户反馈两个问题：

1. 从策略结果页进入个股详情后，右侧“策略选股列表”数量与实际选股数量不一致。  
   典型现象：实际约 130+，但右侧仅显示 50。
2. 策略结果相关页面的“相似度”显示异常（大量为 `-` 或显示不符合预期）。

---

## 2. 根因定位

## 根因 A：列表仅保存了当前分页数据（默认 50）

- 在 `StrategyResultsView.vue` 中，点击行进入详情时，调用 `strategyListStore.setList(...)` 只使用了当前页 `results.value`。
- `results.value` 来自接口分页参数 `per_page=50`，导致 store 里天然只有 50 条。
- `StockDetail.vue` 右侧列表直接读取该 store，因此会稳定复现“只显示 50”。

## 根因 B：相似度显示逻辑对数值格式不够鲁棒

- 旧逻辑直接 `row.similarity_score * 100`，并通过 truthy 判断控制显示。
- 当后端值为 `0`、`0~1` 小数、`0~100` 百分制或空值混用时，展示不稳定（如 `0` 被判空、或百分制再乘 100 放大）。

---

## 3. 修复方案与实现步骤

## 步骤 1：抽出可复用工具层

新增 `web/frontend/src/utils/strategyResults.ts`，统一处理：

1. **分页全量拉取**：`fetchAllStrategyResultItems(...)`
2. **按股票去重**：`buildUniqueStrategyList(...)`
3. **相似度格式化**：`formatSimilarityPercent(...)`

这样避免把分页拼接、去重、格式化散落在多个页面组件里。

## 步骤 2：修复 StrategyResultsView 详情跳转前的数据来源

文件：`web/frontend/src/views/StrategyResultsView.vue`

- 点击股票时仍先用当前页快速写入 store（保证跳转体验）。
- 然后异步调用全量分页拉取，将完整筛选结果回填 store，避免右侧列表被 50 条上限截断。
- 相似度列改为统一调用 `formatSimilarityPercent(...)`。

## 步骤 3：修复 StockDetail 默认列表加载与展示

文件：`web/frontend/src/views/StockDetail.vue`

- 默认加载策略列表时，不再只取单页，而是通过工具函数拉取全部分页结果再去重。
- 右侧列表新增相似度展示（与结果页使用同一格式化逻辑）。

## 步骤 4：补充类型与测试

1. `web/frontend/src/stores/strategyList.ts`  
   为 `StrategyResultItem` 增加 `similarity_score?: number | null`。
2. 新增测试 `web/frontend/src/utils/__tests__/strategyResults.spec.ts`：  
   - 验证分页全量拉取（130 条场景）  
   - 验证按 code 去重保留首项  
   - 验证相似度格式化兼容 0/小数/百分值/空值

---

## 4. 关键代码变更清单

1. `web/frontend/src/utils/strategyResults.ts`（新增）
2. `web/frontend/src/utils/__tests__/strategyResults.spec.ts`（新增）
3. `web/frontend/src/views/StrategyResultsView.vue`（修改）
4. `web/frontend/src/views/StockDetail.vue`（修改）
5. `web/frontend/src/stores/strategyList.ts`（修改）

---

## 5. 技术点总结

本次修复主要用到：

1. **前端分页聚合**（客户端多页拉取 + 终止条件控制）
2. **请求后数据规范化**（去重与统一格式化）
3. **组件间状态复用**（Pinia store 作为结果页与详情页桥梁）
4. **单元测试回归保障**（Vitest 覆盖核心逻辑）

---

## 6. 修复结果

1. 从策略结果页进入详情后，右侧“策略选股列表”不再固定 50 条，能够对齐实际筛选结果总量（去重后）。  
2. 相似度显示逻辑兼容多种后端数值格式：`null/undefined -> '-'`，`0 -> 0%`，`0.73 -> 73%`，`73 -> 73%`。  
3. 改动经过对应单测与前端全量测试/构建验证，未引入现有前端回归。

---

## 7. 后续可选优化建议

1. 若数据量进一步增大，可将“全量分页拉取”迁移为专门接口（一次返回用于详情侧栏的精简字段）。  
2. 若后端未来统一相似度单位（固定 0~1 或 0~100），可将前端格式化逻辑进一步简化。  
3. 可增加一个 E2E 用例：验证“策略结果页 -> 个股详情”后右侧列表数量与接口 total/unique_total 一致。

