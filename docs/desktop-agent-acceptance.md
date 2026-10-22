# 桌面 Agent 验收记录 · 2026-10-23

## 可复现检查

```powershell
.venv/Scripts/python.exe -m pytest tests/test_workspace_agent.py tests/test_frontend_spa_fallback.py tests/test_review_repository.py tests/test_review_service.py tests/test_review_api.py tests/test_tracking_llm_service.py tests/test_tracking_loop_contract.py tests/test_tracking_route_order.py -q
npm --prefix web/frontend run build
npm --prefix web/frontend run test -- --run
npm --prefix desktop run check
npm --prefix desktop run dist
npm --prefix desktop start -- --smoke-test
```

后端87项通过。前端原有105项与新增Agent的2项通过。构建含 vue-tsc；没有现成 lint 脚本。构建保留 ECharts/Element Plus 大包提示。浏览器记录中的 Element Plus underline 旧接口弃用警告未纳入本轮功能变更。

## 实际运行证据

- `output/desktop/agent-smoke.json`：MCP协议握手、工具发现、任务往返；独立真实 DeepSeek 研究完成，2335 tokens、4158ms，费用字段为null。
- `output/desktop/smoke.json`：最终便携包运行结果；title=A-share Quant，12导航链接，Node未暴露，401/200认证隔离。退出后验证端口关闭、发现文件移除。
- `output/playwright/workspace-desktop.png`：真实工作台与行情缓存；缓存日期保留为2026-08-28，不将它宣称为今日行情。
- `output/playwright/workspace-kline.png`：实际个股K线和Agent布局。
- `output/playwright/workspace-reviews.png`、`workspace-mobile.png`：复盘与窄屏。
- `output/playwright/workspace-live-qa.js`：业务路由、Agent、下载、确认、移动尺寸检查。
- `output/playwright/workspace-final-focus.js`：参数5区块、K线加载完成和图表边界。
- `output/playwright/workspace-polish-qa.js`：面板空间、股票上下文过滤、新任务身份与Esc焦点恢复。

浏览器保存复盘验证只打开并取消确认；实际追加及重复追加使用临时复盘库自动测试。未改写用户原有复盘。真实模型smoke与UI检查新增的Agent运行保留在审计表中。

便携程序是当前项目的桌面入口，运行时依赖项目Python环境与前端dist；未做完整Python捆绑、代码签名、跨平台发行、生产发布或真实交易测试。根仓库和嵌套前端均在隔离分支，未合并到web、未推送远端。
