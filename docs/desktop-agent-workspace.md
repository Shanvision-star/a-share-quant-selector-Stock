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
| 桌面运行 | Electron 内置 Python、独立可写工作区、随机回环端口、实例认证与退出保护；保留浏览器和原项目入口 |

## 技术决定

桌面使用 Electron，0.2.0 内置 CPython 3.14.9 x64 与生产依赖。安装后创建 Electron userData 下的 `workspace`，仅安装经过 SHA256 清单校验的应用代码和缺失的干净默认配置；保留已有配置与 data。打包白名单不含用户行情、SQLite、复盘或密钥。“连接现有项目”保留原数据目录；打包版仍使用内置解释器。macOS/Linux、签名与公网多用户部署不在本期范围。

研究工作流先收集有界证据，再交给已配置模型或 Codex 形成结构化报告。记录检查只做日期、缺失字段与截断范围检查，不回答自由分析问题。Codex 分析以独立子运行存储，不覆盖父证据。更新、回测与跟踪使用另一个经确认的白名单操作入口；不接管交易规则、确认订单或执行任意代码。保留原跟踪 LLM 接口。

运行记录保存在现有 SQLite 新增的 Agent 表中，证据保存为运行时快照以便追溯。取消阻止后续步骤和报告发布；已发送的模型请求可能仍消耗 token。服务重启将遗留任务标记中断。

## 每日自动流程（2026-10-23 增补）

- Original：更新、保存复盘和加入跟踪逐次确认，没有每日闭环。
- Revised：用户可明确授权固定目标列表的每日全市场更新、模型研究、复盘追加与观察刷新。当前用户已授权每日 18:30 执行，脚本将该范围内的受控调用标为 `confirmed=true`。
- Reason / Impact：将已授权操作自动化，复用原业务记录与权限检查。`tracking_refresh` 只更新观察日期、收盘与报告关联，不推进模拟持仓、不确认 OrderIntent、不发送通知到外部聊天。

新增 `market` 研究任务从有界真实日线取证，必须给出股票代码和目标交易日。目标日日线缺失时报告失败，不调用模型替代数据。`quant_daily_status` 和桌面每日任务卡展示同一个 `data/daily-agent/latest.json`。执行、恢复、运行条件与验证方法见 [每日自动流程](daily-market-agent.md)。

## 已查阅的官方依据

- https://docs.langchain.com/llms.txt
- https://docs.langchain.com/oss/python/langgraph/workflows-agents （固定证据工作流足以覆盖本期，不引入 DAG 框架）
- https://modelcontextprotocol.io/docs/develop/build-server
- https://github.com/modelcontextprotocol/python-sdk
- https://www.electronjs.org/docs/latest/tutorial/security
- https://v2.tauri.app/develop/sidecar （评估项，本期未使用）
- https://docs.python.org/3.14/using/windows.html#the-embeddable-package
- https://www.python.org/downloads/release/python-3149/
- https://www.electronjs.org/docs/latest/api/app#appquit

## 启动与打包

最终用户打开安装包或便携版即可；以下仅供开发者从源码重新构建，需 Windows x64、CPython 3.14 与 Node：

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -r requirements-agent.txt
npm --prefix web/frontend ci
npm --prefix web/frontend run build
npm --prefix desktop ci
.venv/Scripts/python.exe scripts/build_desktop_runtime.py
npm --prefix desktop run dist
```

生产依赖版本锁位于 `desktop/requirements-runtime.lock`；构建脚本校验官方 Python 压缩包与 certifi wheel 的固定 SHA256，生成运行时清单。已有构建环境可用 `--app-only` 只刷新应用，或 `--python-only` 只刷新解释器；更换依赖时才用 `--lock` 重建锁文件并审核变更。

输出为 `desktop/release/A-share-Quant-Setup-0.2.0.exe`（安装版）和 `A-share-Quant-0.2.0.exe`（便携版）。`Open-Desktop.cmd` 优先使用便携版；开发模式仍可执行 `npm --prefix desktop start`。`QUANT_WORKSPACE` 指定项目目录，`QUANT_PYTHON` 只影响开发模式。现有浏览器入口仍为 `python scripts/run_web_backend.py --host 127.0.0.1 --port 8001`。

关闭窗口或菜单退出均经过页面未保存保护；若有活动任务，默认继续工作。确认退出会记录本实例研究中断并关闭其后端。远端已发送模型请求可能继续计费用量；不声称远端任务被撤回。安装包未签名，Windows 可能提示未知发布者。卸载配置不主动删除用户工作区。

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
| POST `/api/agent/runs/{run_id}/analysis` | `request_id,source_hashes,report,author,provider,model,prompt_version`；校验父来源后建立子运行 |
| POST `/api/agent/actions` | `request_id,action,parameters,confirmed:true`；action 只允许 update / backtest / tracking |
| GET `/api/agent/actions/{action_id}` | 查询真实业务 ID、状态和事件 |
| GET `/api/agent/requests/{kind}/{request_id}` | 查询幂等提交状态；中断不自动重放 |
| GET `/api/agent/active` | 当前研究、数据更新和回测活动任务 |
| POST `/api/agent/shutdown` | `{confirmed:true}`，标记本进程未完成研究中断，供桌面收尾 |

DeepSeek 复用 `config/llm.yaml` 的 `provider` 与 `deepseek` 字段。研究 Agent 固定最多2400输出 tokens、最多120秒超时和2个并发、8个在途任务；不提供任意工具执行。原有 Tracking LLM 的 mock / deepseek / codex_cli 配置继续有效；新研究 Agent 不隐式启动 Codex CLI，Codex 从 MCP 获取证据后可用自身模型处理。

`external` 是已存结果的 mode，不是研究创建参数。外部 author/provider/model 是提交方声明，不能当作身份认证或真实模型调用证明；不伪造 tokens、latency 或金额。结构化报告保存时合并股票索引与原复盘正文，重复保存不重复追加。外部分析要求完整 source ID→SHA256 映射；内容或引用不符拒绝并记录原因。

受控操作先发现 `capabilities.action_schemas` 再构造参数，必须显式确认；每分钟最多12条新操作，同类在途任务互斥。`request_id` 与 payload 绑定；重试相同请求返回原任务，换 payload 拒绝。`queued/running` 只表示受理，必须查询终态；更新遇到 partial 即失败，后续 done 不能覆盖。退出后保留 request/业务记录，不能把中断请求直接重放成重复操作。

重启后读取受控操作或活动任务时，确认拥有进程已退出的未完成回测会同时恢复业务记录与操作记录为 `failed`，错误说明任务中断，并留下 `owner_interrupted` 事件。已完成结果及其他仍活跃实例保持不变；再次执行必须使用新的 `request_id`。Zettaranc 原有回测入口及历史扩展脚本的依赖也包含在独立发行包中。

## Codex 调用

桌面菜单“复制 Codex MCP 配置”生成当前工作区与内置解释器的绝对路径，粘贴到 Codex MCP 配置后启用即可。无需为 MCP 另装 Python。桌面必须运行，工具通过发现文件连接当前实例；配置本身不包含令牌。更换工作区、安装目录或升级便携版后重新复制配置。

JSON CLI 默认发现运行中的桌面实例，否则连接 `http://127.0.0.1:8001`。可用 `QUANT_RUNTIME_FILE` 指向其他工作区的发现文件，或通过 `QUANT_API_URL` 与 `QUANT_API_TOKEN` 指定实例；只接受回环 HTTP 地址。以下是源码开发环境示例，打包用户可用菜单配置中的 Python 和 scripts 绝对路径：

```powershell
.venv/Scripts/python.exe scripts/quant_tools.py capabilities
.venv/Scripts/python.exe scripts/quant_tools.py status
.venv/Scripts/python.exe scripts/quant_tools.py run "检查跟踪日期" --task tracking --limit 10
.venv/Scripts/python.exe scripts/quant_tools.py runs
.venv/Scripts/python.exe scripts/quant_tools.py get <run_id>
.venv/Scripts/python.exe scripts/quant_tools.py cancel <run_id>
.venv/Scripts/python.exe scripts/quant_tools.py save-review <run_id> 2026-10-23 --confirm
.venv/Scripts/python.exe scripts/quant_tools.py submit-analysis <run_id> analysis.json
.venv/Scripts/python.exe scripts/quant_tools.py action action.json
.venv/Scripts/python.exe scripts/quant_tools.py action-get <action_id>
.venv/Scripts/python.exe scripts/quant_tools.py active
.venv/Scripts/python.exe scripts/quant_tools.py request-state action <request_id>
```

源码 MCP 配置示例（打包用户直接复制桌面菜单中的配置；本项目不自动改全局 Codex 配置）：

```toml
[mcp_servers.ashare_quant]
command = 'D:\your-project\.venv\Scripts\python.exe'
args = ['D:\your-project\scripts\quant_mcp.py']

[mcp_servers.ashare_quant.env]
QUANT_RUNTIME_FILE = 'D:\your-project\data\desktop-runtime.json'
```

共12个工具：原有 `quant_status`、`quant_capabilities`、`quant_research`、`quant_runs`、`quant_run`、`quant_cancel`、`quant_save_review`，新增 `quant_submit_analysis`、`quant_action`、`quant_action_get`、`quant_active_tasks`、`quant_request_state`。闭环顺序：读取能力 → 按股取证 → 查询完成报告与来源 → Codex 分析回写 → 明确确认后保存复盘/加入跟踪 → 查询业务终态 → 后续按股检查跟踪与复盘。stdio stdout 仅用于协议，不暴露交易、删除或任意文件写入。

## 0.1 历史验证记录（2026-10-23，范围以当时版本为准）

以下是旧版本证据，不是 0.2.0 独立发行的验收记录；其中“完整 Python 打包未做”等限制仅描述旧版本。

- 前端 vue-tsc + Vite 构建、原有105项 Vitest 回归与新增2项 Agent 竞态/失败反馈回归通过；后端87项检查覆盖研究状态、取消竞争、引用失败、复盘幂等、认证、SPA路径边界及原有复盘/跟踪契约。
- MCP：真实 stdio 握手、7个工具发现、本地研究创建与结果读取通过。
- 真实模型：独立 DeepSeek `deepseek-chat` smoke 成功；运行 `925dac4b323d4609a599e6a59809ddf1`，1720输入 + 615输出 = 2335 tokens，4158ms，金额未返回。它仅核对3条历史记录，不证明策略投资效果。
- 浏览器：11个业务路由可达、首页真实 K 线、Agent任务、JSON下载、保存确认；390/768/1024宽度无文档横溢；检查到已有 Element Plus underline 弃用警告，无页面 JavaScript异常。
- 桌面开发入口和最终 Windows 便携包均实际启动：12个导航链接、Node未暴露；无凭证 API 返回401，有凭证返回200；退出后端口关闭、发现文件移除。便携包 SHA256：`1236c8e3eecba372eb6502adacc8ee0aab91b9897c9620d526c5a00873a9eeb4`。
- 视觉收尾：参数页5个策略区块实际加载；个股 K 线加载完成；Agent打开时为图表留出732px，关闭后原策略列表恢复；任务切换不再被初始历史恢复覆盖；Esc关闭并归还键盘焦点。桌面源文件和构建输出在当前工作区，外观与 Agent 面板仍使用同一 Vue 构建。
- 未做：全市场数据重下载、参数保存覆盖、真实订单、钉钉发送、生产发布、macOS/Linux安装包、签名发行或完整Python打包。未修改主线权限规则、Week历史文档与用户全局记忆。前端没有 lint 脚本，类型检查与构建已执行，不将格式化算作 lint。
