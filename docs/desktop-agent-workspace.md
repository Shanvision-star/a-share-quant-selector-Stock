# 桌面量化工作台与研究 Agent

基线：根仓库 6786e7f / origin/web，前端独立仓库 9c89efb。两仓库均在 codex/apple-quant-workspace 隔离分支开发。

## 范围与验收

本次属于视图层、Agent 层和本地运行入口的代码缺口。复用全部现有路由、业务服务、CSV、SQLite 和 Markdown 复盘库。系统思维与 agent.md 的规则及人工确认交易边界保持有效。

| 工作 | 验收 |
| --- | --- |
| 白色工作台 | 所有原有导航仍可达，浅色 K 线可读，必要标签与可访问名称保留；支持窄屏和减少动态效果 |
| 研究 Agent | 从真实策略、跟踪、复盘取证；结构化输入输出，持久化运行身份、版本、来源、失败和用量；明确离线整理与模型模式 |
| 数据整理 | 人工确认后追加复盘，幂等且不覆盖原文；导出可审计 JSON；历史可恢复 |
| Codex 接入 | HTTP、JSON CLI、stdio MCP 共用同一后端契约；不提供任意 shell、文件路径或自动交易工具 |
| 桌面运行 | Electron 启动现有工作区 Python 服务、随机回环端口、实例认证与退出清理；保留浏览器入口 |

## 技术决定

桌面使用 Electron；当前环境具备 Node/Python，没有 Rust。此版本是现有工作区的桌面客户端，需选择包含 .venv 与已构建前端的项目目录，不把数据和 Python 环境复制到安装包。Python 独立分发、macOS 签名、公网多用户部署属于后续交付范围。

研究工作流先按任务收集有界证据，再交给配置中的模型形成结构化报告。它不接管交易规则、确认订单、更新全市场数据或执行代码。保留现有跟踪 LLM 接口。未配置模型时只能明确选择本地整理，不伪装模型结果。运行结果不做持仓或收益承诺。

运行记录保存在现有 SQLite 新增的 Agent 表中，证据保存为运行时快照以便追溯。取消阻止后续步骤和报告发布；已发送的模型请求可能仍消耗 token。服务重启将遗留任务标记中断。

## 已查阅的官方依据

- https://docs.langchain.com/llms.txt
- https://docs.langchain.com/oss/python/langgraph/workflows-agents （固定证据工作流足以覆盖本期，不引入 DAG 框架）
- https://modelcontextprotocol.io/docs/develop/build-server
- https://github.com/modelcontextprotocol/python-sdk
- https://www.electronjs.org/docs/latest/tutorial/security
- https://v2.tauri.app/develop/sidecar （评估项，本期未使用）

## 启动与打包

在项目根目录：

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
npm --prefix web/frontend ci
npm --prefix web/frontend run build
npm --prefix desktop ci
npm --prefix desktop start
```

`Open-Desktop.cmd` 优先使用 `desktop/release/A-share-Quant-0.1.0.exe`，缺少打包文件时使用开发入口。`npm --prefix desktop run dist` 生成 Windows 便携客户端。首次在其他路径启动便携包时选择现有项目根目录。`QUANT_WORKSPACE`、`QUANT_PYTHON` 可显式指定工作区和解释器。关闭桌面会结束其本地服务；长任务应在退出前完成。现有浏览器入口仍为 `python scripts/run_web_backend.py --host 127.0.0.1 --port 8001`。

桌面服务绑定随机的 `127.0.0.1` 端口。Electron 主进程为同源请求附加实例令牌，页面没有 Node / shell 权限。`data/desktop-runtime.json` 保存本机工具发现信息和凭证，位于被 Git 忽略的数据目录，退出时移除；Windows 文件访问继承项目目录的 ACL。不要复制该文件到工单或对外分享。`data/desktop-backend.log` 保存启动日志。

## Agent 契约

输入 schema：`question`（1–2000 字符）、`task`（candidates / tracking / reviews）、`mode`（local / model）、可选六位 `code`、ISO `trade_date`、`limit`（1–50，默认20）。日期分别匹配策略交易日、跟踪信号日、复盘日期。证据正文每篇最多4000字符，总快照最多48000字节，截断有标记；这是有界研究，不是全量组合审计。

输出 schema：`summary`、`findings[{text,source_ids}]`、`next_steps`、`limitations`。校验 JSON 格式及引用标识；引用校验不等同于逐条事实验证。记录 `agent_name=quant_research`、`prompt_version=1.0.0`、输入、时间、状态、来源快照与 SHA256、工具事件、provider/model、tokens、latency_ms。模型 API 不返回金额，`cost=null`；本地整理 `cost=0`。取消后不发布结果，已发生的模型用量在返回时仍记账。失败不会降级成虚假的模型成功。

| HTTP | 用途 |
| --- | --- |
| GET `/api/agent/capabilities` | 模型配置状态（不返回凭证） |
| POST `/api/agent/runs` | 返回202和 run_id，后台执行 |
| GET `/api/agent/runs?limit=30` | 最近运行 |
| GET `/api/agent/runs/{run_id}` | 输入、报告、完整来源、事件与用量 |
| POST `/api/agent/runs/{run_id}/cancel` | 取消未完成运行 |
| POST `/api/agent/runs/{run_id}/review` | `{review_date,confirmed:true}`，在文档锁内幂等追加；未确认409 |

DeepSeek 复用 `config/llm.yaml` 的 `provider` 与 `deepseek` 字段。研究 Agent 固定最多2400输出 tokens、最多120秒超时和2个并发、8个在途任务；不提供任意工具执行。原有 Tracking LLM 的 mock / deepseek / codex_cli 配置继续有效；新研究 Agent 不隐式启动 Codex CLI，Codex 从 MCP 获取证据后可用自身模型处理。

## Codex 调用

JSON CLI 默认发现运行中的桌面实例，否则连接 `http://127.0.0.1:8001`。可通过 `QUANT_API_URL` 与 `QUANT_API_TOKEN` 指定实例；只接受回环 HTTP 地址。

```powershell
.venv/Scripts/python.exe scripts/quant_tools.py capabilities
.venv/Scripts/python.exe scripts/quant_tools.py status
.venv/Scripts/python.exe scripts/quant_tools.py run "检查跟踪日期" --task tracking --limit 10
.venv/Scripts/python.exe scripts/quant_tools.py runs
.venv/Scripts/python.exe scripts/quant_tools.py get <run_id>
.venv/Scripts/python.exe scripts/quant_tools.py cancel <run_id>
.venv/Scripts/python.exe scripts/quant_tools.py save-review <run_id> 2026-10-23 --confirm
```

安装 MCP：`.venv/Scripts/python.exe -m pip install -r requirements-agent.txt`。Codex MCP 配置示例（将路径替换为实际绝对路径；未修改全局 Codex 配置）：

```toml
[mcp_servers.ashare_quant]
command = 'D:\your-project\.venv\Scripts\python.exe'
args = ['D:\your-project\scripts\quant_mcp.py']
```

提供 `quant_status`、`quant_capabilities`、`quant_research`、`quant_runs`、`quant_run`、`quant_cancel`、`quant_save_review`。读操作附带 readOnlyHint，保存工具必须明确传入 confirmed；stdio stdout 仅用于协议。调用会创建可追溯任务，复盘正文只在确认保存时改变。当前只有运行创建、取消、复盘追加这三类写操作，不暴露交易、删除或任意文件写入。

## 验证记录（2026-10-23）

- 前端 vue-tsc + Vite 构建、原有105项 Vitest 回归与新增2项 Agent 竞态/失败反馈回归通过；后端87项检查覆盖研究状态、取消竞争、引用失败、复盘幂等、认证、SPA路径边界及原有复盘/跟踪契约。
- MCP：真实 stdio 握手、7个工具发现、本地研究创建与结果读取通过。
- 真实模型：独立 DeepSeek `deepseek-chat` smoke 成功；运行 `925dac4b323d4609a599e6a59809ddf1`，1720输入 + 615输出 = 2335 tokens，4158ms，金额未返回。它仅核对3条历史记录，不证明策略投资效果。
- 浏览器：11个业务路由可达、首页真实 K 线、Agent任务、JSON下载、保存确认；390/768/1024宽度无文档横溢；检查到已有 Element Plus underline 弃用警告，无页面 JavaScript异常。
- 桌面开发入口和最终 Windows 便携包均实际启动：12个导航链接、Node未暴露；无凭证 API 返回401，有凭证返回200；退出后端口关闭、发现文件移除。便携包 SHA256：`1236c8e3eecba372eb6502adacc8ee0aab91b9897c9620d526c5a00873a9eeb4`。
- 视觉收尾：参数页5个策略区块实际加载；个股 K 线加载完成；Agent打开时为图表留出732px，关闭后原策略列表恢复；任务切换不再被初始历史恢复覆盖；Esc关闭并归还键盘焦点。桌面源文件和构建输出在当前工作区，外观与 Agent 面板仍使用同一 Vue 构建。
- 未做：全市场数据重下载、参数保存覆盖、真实订单、钉钉发送、生产发布、macOS/Linux安装包、签名发行或完整Python打包。未修改主线权限规则、Week历史文档与用户全局记忆。前端没有 lint 脚本，类型检查与构建已执行，不将格式化算作 lint。
