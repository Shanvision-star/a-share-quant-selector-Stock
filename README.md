# a-share-quant-selector-Stock Web Frontend

本目录是项目的前端模块（Vue 3 + TypeScript + Vite + Element Plus），
用于承接根目录 README 的业务主线：

1. 数据更新
2. 策略执行与结果回看
3. 参数调节与复盘
4. 通达信 TXT 文件生成/历史下载

说明：
本 README 保留原项目“核心功能 -> 快速开始 -> 项目结构”的文档逻辑，
并按当前前端代码结构补充注释化说明，方便直接开发和联调。

## 核心功能（前端视角）

- 首页总览：缓存状态、今日命中摘要、股票列表（支持列点击排序）
	- 文件：`src/views/HomeView.vue`
- 策略结果工作台：历史结果查询、运行记录、作业事件、结果分页排序
	- 文件：`src/views/StrategyResultsView.vue`
- 通达信 TXT 文件库：按策略和日期生成、按日期回溯历史、下载文件
	- 页面承载：`src/views/StrategyResultsView.vue`
	- 独立组件：`src/components/TxtLibraryPanel.vue`
- 参数设置：策略参数旋钮调节 + 案例库展示
	- 文件：`src/views/SettingsView.vue`
- 股票详情：K 线、技术指标、策略结果联动
	- 文件：`src/views/StockDetail.vue`
- 数据更新流程页：更新数据与重建缓存
	- 文件：`src/views/UpdateView.vue`

## TODO 清单（沿用原项目主线）

- [ ] TODO 1: 尝试大模型近似能力（已落地 B1 阶段策略，持续优化）
- [ ] TODO 2: 砖型图选股逻辑迭代
- [ ] TODO 3: 补充 B1 / 砖型图案例库

## 快速开始（前后端联调）

在仓库根目录执行：

```bash
# 1) 启动后端 FastAPI（监听 8001）
cd web
npm run backend

# 2) 新开终端，启动前端 Vite（监听 5173）
cd web
npm run dev
```

访问地址：

- 前端开发地址：`http://127.0.0.1:5173`
- 后端 API 地址：`http://127.0.0.1:8001`

代理规则：

- Vite 代理：`/api -> http://localhost:8001`
- 配置文件：`vite.config.ts`

## 构建与预览

在仓库根目录执行：

```bash
cd web
npm run build
npm run serve
```

## 路由与页面映射（注释）

路由配置文件：`src/router/index.ts`

- `/` -> `HomeView.vue`
	- 首页总览、股票列表、进入策略结果/TXT 模块入口
- `/strategy-results` -> `StrategyResultsView.vue`
	- 工作台主页面（含运行记录与 TXT 文件库）
- `/stocks/:code` -> `StockDetail.vue`
	- 单股票详情与 K 线复盘
- `/update` -> `UpdateView.vue`
	- 数据更新与缓存重建入口
- `/settings` -> `SettingsView.vue`
	- 策略参数与案例展示
- `/backtest` -> `BacktestView.vue`
- `/artemis` -> `ArtemisView.vue`

## 目录结构（注释）

```text
web/frontend/
├─ src/
│  ├─ api/                # 前端 API 封装（统一走 /api）
│  ├─ components/         # 复用组件（含 TxtLibraryPanel）
│  ├─ router/             # 路由定义
│  ├─ stores/             # Pinia 状态管理
│  ├─ views/              # 页面级组件
│  └─ main.ts             # 前端入口
├─ package.json           # 前端依赖与脚本
└─ vite.config.ts         # 开发服务器与代理配置
```

## 脚本说明

前端本地脚本（本目录 `package.json`）：

- `npm run dev`：启动 Vite 开发环境
- `npm run build`：TypeCheck + 生产构建
- `npm run preview`：本地预览构建结果

包装脚本（`web/package.json`，推荐从仓库根目录使用）：

- `npm run backend`：启动后端
- `npm run dev`：进入 frontend 并启动前端
- `npm run build`：进入 frontend 构建
- `npm run serve`：进入 frontend 预览

## 开发约定

- 所有后端请求统一通过 `src/api/index.ts` 发起。
- 不要在页面中硬编码后端域名，统一使用 `/api` 代理。
- 页面入口尽量放在 `views`，可复用能力抽到 `components`。
- 复杂页面（如策略工作台）优先拆成小组件，保持单文件可读性。

## 与根 README 的关系

- 根目录 `README.md`：项目全局说明（策略原理、运行方式、整体结构）。
- 当前文件：前端开发与联调说明（页面映射、模块职责、工程约定）。

建议：
新增前端模块时，先更新本 README 的“路由映射”和“目录结构”两节，
确保团队成员能快速定位功能入口。
