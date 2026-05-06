# 下一步实施计划：K线交互修复 + 统一作业按策略筛选 + 参数保存失败排查

日期：2026-04-26
关联：本次已完成"人工选股池仓库 + 回测候选/买入点匹配"（见 `docs/copilotchat/plan.md` 与本次提交）。

---

## 任务 A：K 线副图双击放大 + 成交量图框过大

### 目的
- 解决 `KlineChart.vue` 中副图（成交量、还原成交量、KDJ、MACD）双击不响应或放大后布局错位的问题。
- 解决 tooltip 浮层尺寸过大导致遮挡 K 线的问题。
- 让用户能像专业行情软件那样：单击副图标签或双击副图区域 → 放大该副图并自动收起其他副图；再次双击 → 恢复默认比例。

### 现象（来自截图）
1. 成交量副图区域内出现两条几乎贴底的水平虚线，主成交量柱体被挤压到边缘（"成交量显示异常"）。
2. tooltip 框尺寸较大，覆盖大量 K 线（"图框显示太大 缩小图框"）。
3. 双击副图区域无效，需点击文字标签才能放大。

### 实现步骤

#### 步骤 A1：修复成交量副图 Y 轴范围
**目的**：异常的水平虚线根因是 ECharts 副图 Y 轴 `min/max` 未约束，少量异常或 0 值把整个轴拉伸，正常柱体被压扁。

**实现**：
- 文件 `web/frontend/src/components/KlineChart.vue`
- 在 `getVolumeYAxis()`（或对应配置生成函数）里：
  - `min: 0` 显式设置。
  - `max` 用当前可见区间最大成交量的 `1.05 倍`，而不是依赖 ECharts 自动计算。
  - 配合 `dataZoom` 的 `xAxisIndex` 联动，使缩放时副图同步重算 max。
  - 同时去掉默认 `splitLine`（或减半），避免出现"两条贴底虚线"。

#### 步骤 A2：副图双击命中区域改造
**目的**：当前最大化只绑定在标签元素上，用户期望"在副图柱体区域内双击"也能触发。

**实现**：
- 给 chart 容器外层 wrapper 绑定 `dblclick`，事件回调里：
  1. 用 `chart.convertFromPixel({ gridIndex: i }, [x, y])` 反查鼠标命中的副图索引。
  2. 调用 `togglePanel(panelIndex)`：放大目标副图。
- 新增 `getEffectivePanelRatios()`：
  - 默认模式：返回原 `panelRatios`。
  - 最大化模式：主图固定 48%，目标副图占 `1 - 0.48 - minOthers * (n-1)`，其余副图各 `minOthers`（如 1.5%）。
  - 返回的比例数组用于：grid 高度、标签 top、分割线 top —— 三处共用同一份，避免溢出。

#### 步骤 A3：精简 Tooltip
**目的**：tooltip 占用面积过大，遮挡 K 线主体。

**实现**：
- 修改 `formatter` 函数：
  - 改为两列网格布局（左列字段名右列数值），CSS `font-size: 11px; line-height: 1.4`。
  - 换行符 `<br>` 改为 `<div>`，去掉多余空行。
  - `padding: 6px 8px`、`backgroundColor: rgba(20,30,45,0.9)`。
- `position` 用函数式：`(point, params, dom, rect, size) => [smartX, smartY]`，使 tooltip 在光标右侧/左侧动态切换，避免覆盖关键 K 线。

### 验证
1. 打开任意股票详情页，查看成交量副图：柱体撑满、无诡异虚线。
2. 双击成交量柱体区域 → 成交量副图放大，主图压缩到 48%；再双击 → 恢复。
3. tooltip 高度比当前缩短约 40%，不再遮挡 1/3 主图区域。
4. `cd web/frontend && npm run build` 通过。

---

## 任务 B：统一作业页"按策略筛选执行"

### 目的
- 当前 `UpdateView.vue` 的"统一作业 - 数据更新 + 策略重建"按钮会无差别跑全部策略（B1/B2/Bowl）。用户希望能选择只对单个或多个策略执行重建，缩短当日补跑时间。

### 现象（来自截图）
- 截图右侧标注："添加策略选择功能 可以分别只对单个策略进行选股"。

### 实现步骤

#### 步骤 B1：后端接口扩展
**目的**：让现有 `/api/update/*` 或 `/api/strategy/rebuild` 接口接收"策略子集"参数。

**实现**：
- 文件 `web/backend/routers/update.py`（或 `strategy.py` 中的重建路由）。
- 找到当前同时跑 B1/B2/Bowl 的入口函数，新增可选参数 `strategies: list[str] = Query(default_factory=lambda: ['b1','b2','bowl'])`。
- 调用底层时按列表过滤：仅传入选中的策略给 `StrategyRegistry.run_strategies(...)`。
- 保持向后兼容：未传 `strategies` 时维持原行为（跑全部）。

#### 步骤 B2：前端 UI
**目的**：在执行按钮上方放一个多选框组，让用户勾选要跑的策略。

**实现**：
- 文件 `web/frontend/src/views/UpdateView.vue`。
- 在"盘中允许快路径"下方插入 `el-checkbox-group`：
  ```
  策略选择：☐ B1  ☐ B2  ☐ 碗底反弹   [全选/反选]
  ```
- 默认全选；本地状态 `selectedStrategies = ref(['b1','b2','bowl'])`。
- 点击"执行该日期：更新数据 + 自动重建策略"时，把 `selectedStrategies.value` 拼到请求参数里。
- "仅更新数据" 按钮不受影响。

#### 步骤 B3：进度展示兼容
**目的**：当前 SSE 进度面板按"策略名 - 阶段"展示，需要支持只显示选中的策略。

**实现**：
- 文件 `web/backend/routers/update.py` 推 SSE 事件时，事件 `strategy` 字段已经是单策略级，前端 `updateJob` store 不需要改；只需在 UI 顶部小字提示"本次仅执行：B1, B2"即可。

### 验证
1. 勾选只跑 B1，点击执行 → 后端日志只跑 B1Strategy；前端进度面板只出现 B1 相关阶段。
2. 不勾选任何策略 → 按钮置灰禁用，给出"至少选择一个策略"提示。
3. 默认全选行为与原来一致，回归测试通过。

---

## 任务 C：策略参数 `CAP` / `b2_must_follow_b1_days` 保存失败

### 目的
- 截图显示两条错误提示：
  1. `保存失败: 参数 CAP 不能大于 1000`（B1Strategy 的市值门槛上限被卡死）。
  2. `保存失败: 未知参数: b2_must_follow_b1_days`（B2Strategy 新参数未注册）。
- 修复后端参数校验、注册逻辑，让前端滑块到了 1000 仍可保存，并让 `b2_must_follow_b1_days` 在 `config/strategy_params.yaml` 中正确落库。

### 根因假设（待代码验证）
- `CAP` 上限：在某个 schema/校验函数里硬编码 `<= 1000`，但前端 slider `max=1000` 已经包含等号边界，触发误报。
- `b2_must_follow_b1_days`：`B2Strategy` 类的 `parameter_schema()` 里没有声明该字段；后端 `config_service` 收到时按白名单过滤直接报"未知参数"。

### 实现步骤

#### 步骤 C1：定位校验代码
**目的**：找到参数白名单与上下限定义点。

**实现**：
- 全局搜索：`'CAP'`, `'b2_must_follow_b1_days'`, `unknown parameter`, `参数 CAP`, `不能大于`。
- 重点检查文件：
  - `strategy/base_strategy.py`（基类 schema 接口）
  - `strategy/b2_strategy.py`、`strategy/bowl_rebound.py`、`strategy/b1_case_analyzer.py`
  - `web/backend/services/config_service.py`（保存逻辑）
  - `web/backend/routers/config_api.py`

#### 步骤 C2：修复 `CAP` 边界
**实现**：
- 把 `if value > 1000` 改为 `if value > 1000:` 仍允许等于，或将上限改成 `<= 1000` 等价 `< 1001`。
- 与前端滑块 `max=1000` 统一。
- 在错误信息中带上"当前值 / 允许上限"，方便用户排查。

#### 步骤 C3：注册 `b2_must_follow_b1_days`
**实现**：
- 在 `B2Strategy` 的 `parameter_schema()` 增加：
  ```
  'b2_must_follow_b1_days': {
      'type': 'int', 'min': 1, 'max': 30, 'default': 2,
      'label': 'B2 必须紧跟 B1 的天数',
  }
  ```
- 在 `config/strategy_params.yaml` 的 `B2Strategy` 节添加默认值 `b2_must_follow_b1_days: 2`。
- 在 `B2Strategy.run()` / 信号判定里读取该字段，未读到时 fallback `2`。
- 检查 `config_service.save_strategy_params()` 是否依据 schema 白名单过滤；若是，则注册 schema 后即可通过。

#### 步骤 C4：增加单元测试
**目的**：避免未来再次出现"参数白名单漏注册"。

**实现**：
- 新增 `tests/test_strategy_params_save.py`：
  - 模拟 `POST /api/config/strategy-params` 保存 `CAP=1000`，期望 200。
  - 保存 `b2_must_follow_b1_days=2`，期望 200，且重新 GET 能读到。
- `pytest tests/test_strategy_params_save.py -q` 通过。

### 验证
1. 设置页将 B1 的 `CAP` 拖到 1000 → 点保存 → 提示成功，刷新后值仍为 1000。
2. B2 案例库为某条用例配置 `b2_must_follow_b1_days=3` → 保存成功；后端日志显示 B2 扫描时使用 3 而非 2。
3. 已有自动化（如 `python main.py run --b1-match`）仍正常运行。

---

## 实施顺序与依赖
1. 任务 C 风险最低、影响面小 → 先做。
2. 任务 B 需要小幅后端改动 → 第二做。
3. 任务 A 涉及 ECharts 配置较复杂 → 最后做，可独立验证。

每个任务做完都跑：
- `python main.py run --b1-match --max-stocks 5` 烟测策略链路。
- `cd web/frontend && npm run build` 类型检查。
- 手动浏览器验证对应页面。
