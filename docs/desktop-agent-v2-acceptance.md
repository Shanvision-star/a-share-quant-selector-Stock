# Windows 桌面与 Agent 0.2.0 验收记录

日期：2026-10-23。发行源码：根仓库 `27ed3e4`，前端 `1da6074`；功能分支 `codex/apple-quant-workspace`，未合并或推送。后续验收文档和测试脚本不改变发行代码。五项整改完成，最终安装版、便携版及下列范围的重新验收通过。

## 五项审核整改

| 原问题 | 交付行为 | 验证 |
| --- | --- | --- |
| 当前股票未传给 Agent，历史报告对象混淆 | 主页选择进入真实请求；报告独立显示运行股票、日期，切股显示历史对象 | Electron 页面实际 POST、切股与跟踪确认检查 |
| 复盘只追加正文，无法按股检索 | 合并股票索引、标签及原正文，重复追加幂等，精确打开保存日期 | MCP 保存、同股检索、正文保留及界面跳转 |
| 本地模式承诺超出能力 | 明确为记录检查，实际检查日期、缺失字段和截断；模型不可用时禁止提交并提供配置帮助 | 后端定向测试、Agent 组件测试和页面检查 |
| Codex 只取证，无法回写与调用业务 | 12 个 MCP 工具；来源 SHA256 校验，独立分析子运行；确认后更新、回测、跟踪并查询真实终态 | 内置 Python 真实 stdio MCP，21 项业务闭环 |
| 退出绕过未保存及运行任务保护 | 先确认活动任务，再执行页面未保存保护；窗口关闭后收尾后端；死 owner 受控回测恢复并审计 | 原生退出/重启、临时库恢复及活实例保护 |

界面使用白色背景、半透明面板、克制的阴影和进入动效；保留控件可访问名称、减少动态效果适配及原有页面。状态栏收紧，K 线和候选记录为主；900px 窗口可显式收起股票信息面板。390/768px 只检查文档横向溢出，不宣称手机端完整验收。

## 集成期间关闭的额外问题

- B1/B2 策略名称含 `ST` 导致普通股票被误判：ST 排除仅依据股票名称；回测样本实际产生模拟交易。
- 设置首次导入阻塞 API：放入线程池；Windows 父管道监视改为 PeekNamedPipe，避免阻塞 stdin 影响 SciPy 原生库加载。最终设置冷读取 **1.359 秒**。
- 打包遗漏原 Zettaranc 回测和历史扩展的子脚本：补齐白名单。内置解释器通过真实路由执行人工 180 行 CSV 回测，产生模拟交易、写入并读取 latest；extend → backfill dry-run 通过。
- 死 owner 回测遗留 running：关联业务和操作恢复为 failed，追加 `owner_interrupted`，旧 request_id 不重放，新请求可继续；已有结果和活 owner 保持不变。

整分支独立源码审核发现最后两项 P2 后，一次修复波完成；一次 scoped re-review 的 Spec/Quality 均 PASS，无剩余阻断项。

## 新鲜验证

| 范围 | 结果与证据 |
| --- | --- |
| 最终 Agent、异步回测、打包脚本 | **55 passed**；包含内置 CPython `_pth` isolated=1 的离线子进程入口测试，app/services import 通过 |
| Windows 父管道 | **2 passed**；真实 pipe 保持打开不退出，写入后仍运行，EOF 退出 |
| pytest collection 隔离 | **20 passed** 相关检查；独立复核 **2 passed**，在连接层拒绝真实根数据库路径 |
| 桌面代码/工作区升级 | **3 passed**；代码更新、配置/复盘/数据库保留，路径与损坏资源校验，MCP 配置 |
| 前端 | **114 passed** 基线；随后 Home **1**、Agent **8** 定向测试；最终 vue-tsc/Vite build 通过。没有 lint 脚本，不声称执行 lint |
| 打包业务闭环 | **21 passed**：[result.json](../output/desktop-v2/business-20261023-191127/result.json) |
| Electron 界面 | **23 passed**：[result.json](../output/desktop-v2/ui-1792754042965/result.json)，原有10路由可达、无未捕获页面错误；截图人工检查 |
| Windows 安装与原生恢复 | NSIS 退出码0，安装至 `C:\Users\Rome\AppData\Local\Programs\A-share Quant`；安装后实际运行 **16 passed**：[result.json](../output/desktop-v2/native-1792754811234/result.json) |
| 发行一致性 | 安装版320个文件与清单一致，app.asar、内置 Python 和运行时清单与发行资源一致：[resources.json](../output/desktop-v2/install-final/resources.json) |
| 便携版 | 实际单文件启动，打包 Python、认证200/401、Node隔离、退出发现文件/端口/进程清理 **8项通过**：[result.json](../output/desktop-v2/portable-final/result.json) |

较早后端整合基线为135项通过，后续修复按实际影响定向验证；上述数字不相加冒充一轮完整测试。业务验收运行真实本地服务和打包 Python，使用复制的历史 CSV 与明确标记的种子候选记录。Codex 分析提交是协议验收夹具，不是本轮真实模型推理；没有伪造 tokens、费用或投资结论。

## 发行文件

两个文件均内置 CPython **3.14.9 x64** 与85项锁定生产依赖，应用白名单320文件；不携带用户 CSV、数据库、复盘及凭证。默认创建独立可写工作区，可通过菜单连接已有项目。

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `A-share-Quant-Setup-0.2.0.exe` | 224344983 | `6A5D69B9B148D7F396156332CDADC7D997DBDB5C4202713629DED6C8FD081037` |
| `A-share-Quant-0.2.0.exe` | 224117612 | `5BB55FABE0C6B231DBD9619D0311B7BE3D005BF41D012783E0BAFBC4DB120CD9` |

文件位于 `desktop/release/`，校验文件为 `SHA256SUMS-0.2.0.txt`。两者 Authenticode 状态均为 **NotSigned**。桌面菜单“复制 Codex MCP 配置”提供内置解释器路径；需要将配置加入 Codex，本轮没有改写用户全局配置。

安装程序与桌面验收均把 PATH 限制为 Windows/System32，移除 Python/虚拟环境相关变量。安装回执见 [install-final/result.json](../output/desktop-v2/install-final/result.json)。原生16项使用真实 Electron 生命周期，自动选择原生对话框按钮；包括未保存取消/放弃、活动任务取消退出、当前 owner 运行状态夹具、退出后端口与发现文件清理、重启首次活动查询排除中断回测、审计事件及复盘持久化。不是人工逐项点击的验收。

日常使用建议安装版：从开始菜单打开 A-share Quant，再通过“工作台 → 连接已有项目”选择本仓库，重启后使用原数据；或保留默认独立工作区。便携版每次启动要解压运行时。本机安装验收耗时约9分钟，期间同时执行便携解压，这不是一般机器上的性能基准；安装后的启动不需重新解压。发行展开后约745 MiB、10603文件。

实机截图（隔离历史样本）：[工作台与 Agent](../output/desktop-v2/ui-1792754042965/02-home-agent-report.png)、[主页](../output/desktop-v2/ui-1792754042965/01-home-1512.png)、[900px桌面](../output/desktop-v2/ui-1792754042965/05-stock-900.png)。

## 数据保护纠错

本轮早期执行的旧测试曾触及项目数据：使派生策略缓存失效，并写入8条明确的测试回测任务和24条事件。已按准确ID归档后移除这些测试记录；从最后成功历史运行 `20260829_180913_226da45d` 恢复85条策略结果（B1 13、B2 27、brick 45），保留恢复来源标记。该恢复不是原缓存逐字节还原；没有证据的零结果组未伪造，界面可能提示这些策略需要重建。历史 CSV 与复盘正文未删除。

归档证据：`output/desktop-v2/removed-test-backtest-records.json`、`recovered-strategy-cache.json`。之后修正了配置/任务测试夹具和 pytest 导入前 SQLite 隔离；最终业务、UI 与桌面验收均使用单独工作区。这一事件不能表述为“整个过程中从未触及用户数据”。

## 验收边界与处理决定

- 已验证本机 Windows 安装/启动链路的结果单独记录；清除 PATH 中系统 Python 入口不能冒充在全新 Windows 虚拟机卸载 Python 后测试。
- 更新检查覆盖已有历史日期的无下载路径；未进行全市场重新下载、真实供应商完整链路、新一轮付费模型、钉钉发送、实盘交易、卸载、多版本升级或签名发布。
- 回测中断恢复包含状态夹具与真实进程退出/重启；不把它描述为真实耗时回测强杀的完整实验。
- Ruling：复用现有隔离功能分支和环境，避免复制工作区；交叉编辑可能混入其他修改，因此以文件分工、独立审核和最终差异核对控制。保留无关脏文件和子模块状态，未修改主线、Week历史文档或全局记忆。

完整使用方式与接口见 [桌面与 Agent 使用说明](desktop-agent-workspace.md)；0.1记录仅作为历史证据。
