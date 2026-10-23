# 桌面 Codex 策略分析

## 操作

1. 工作台选择股票，打开 Agent。
2. 研究任务选“策略研究”，运行模式选“Codex 分析”。
3. 输入要检查的策略条件或问题并运行。
4. 完成后可“保存复盘”、导出 JSON、加入观察跟踪。面板“历史”可以重新打开已保存的运行。

研究运行自动保存于 `data/web_strategy_cache.db` 的 `workspace_agent_runs` 表；复盘由现有 `data/review_library` Markdown 仓储保存，并保留原文和版本。同一运行重复追加到同一天不会产生重复正文。“停止”阻止报告发布；已发出的模型请求可能仍消耗用量。

## 调用与证据边界

- `mode=local` 做固定记录检查；`mode=model` 调用原 DeepSeek 配置；`mode=codex` 显式启动本机 Codex。后者复用 Codex 登录态，不需要额外配置 Python 或 DeepSeek 密钥。
- Codex CLI 优先使用现有 `codex_cli.command`，否则依次发现当前应用的 `CODEX_CLI_PATH`、Windows Codex 最新版本目录和系统 PATH，避免误用旧启动器。模型优先取现有 `codex_cli.model`，否则读取本机 Codex 配置的模型名；不把全局配置或密钥放入提示词。
- 使用 `codex exec --ephemeral --ignore-user-config --sandbox read-only --output-schema`，研究工作目录为临时目录，关闭 Shell 和联网搜索；保留已有 execpolicy 规则。未给模型提供可写 MCP 工具。
- `S1` 是正式策略记录及信号指标；`S2` 是对应策略当前参数和实现源码快照。每份证据独立计算 SHA256。当前参数不等于历史运行参数，源码中的外部依赖函数未完整打包；未重新扫描、未运行回测。
- 模型须区分事实、推断和缺失证据。扫描任务非 completed 时须标注异常。引用与 JSON 校验不等于逐条事实正确性保证。
- Codex 不可用或输出无效会记录失败，不回退成 mock 成功。真实返回的 usage 保存到运行，未返回金额则 `cost=null`。
- MCP 可读同一运行，也可经 `quant_submit_analysis` 回存外部分析；只有外部回存模式使用父子运行关系。

## 交付范围

本机已安装桌面连接本项目后使用当前源码与前端构建；旧 0.2.0 安装包内置的离线工作区未重新发行。单独分发给没有 Codex 的机器，需要安装并登录 Codex 才能使用此模式，其余桌面功能仍使用内置 Python。

官方实现依据：[Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)。采用固定的取证、分析、校验、保存流程，参考 [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) 的工作流边界；没有新增 LangGraph 依赖。

## 2026-10-23 本机验收

- 代码在根仓库及嵌套前端仓库的 `codex/desktop-codex-strategy` 分支承接已交付桌面分支，未覆盖 `web` 主线及其他未提交内容。
- 后端相关回归 62 项通过；前端 Agent 12 项通过。`npm run build` 内的 `vue-tsc -b` 与 Vite 生产构建通过；项目没有独立 lint 脚本，构建仍有既有的大包体提示。内置 Python 完成应用、MCP 与真实策略注册表 import smoke。
- 实际已安装的 Windows Electron 桌面中，选择 688613 奥精医疗 → Codex 分析 → 运行，生成 `b23f2ceba1e84e1699ebe6f240440b8d`。真实 provider 为 `codex_cli`，模型 `gpt-6-astra`，21653 输入 tokens、1632 输出 tokens，23285 总 tokens，耗时90314ms；金额未返回。
- 首次实际调用 `4189d15b4c3941298b60d66e07346f90` 使用 PATH 旧启动器失败，已保留失败记录；随后改为优先发现应用当前版本。最终工具隔离参数另做真实连接 smoke：17695 tokens、15474ms，记录的工具调用为空。失败/超时尝试未返回用量，不能当作零消耗。
- 从桌面点击保存复盘，并在复盘编辑页读到报告。`data/review_library/2026/10/2026-10-23.md` 中该运行标记恰好一处，原有每日任务报告仍在。通过实际全局 `ashare_quant` MCP 配置回读同一运行与两份来源，再次保存返回 `already_saved=true`。
- 真实桌面验证了历史选择、重载后恢复报告与 Codex 模式、顶部保存/JSON 控件。证据位于 `output/codex-strategy-20261023/`，包括 `final-desktop.png`、`mcp-verification.json`、`final-provider-smoke.json` 和完整报告。
- 报告明确区分策略记录与重新执行：该候选的所属扫描仍是 `error`，未在本次重跑扫描或回测；未修改观察仓位、成交、每日目标列表或 DeepSeek 配置。启动时原有的全市场数据更新提醒曾出现，本次选择“稍后再说”，不将本次验收说成全市场数据修复。
