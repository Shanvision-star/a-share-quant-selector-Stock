# 日期 Markdown 复盘库设计

> 状态：已由用户确认。本文是复盘库一期实现的权威设计规格。

## 目标

在现有 FastAPI + Vue 3 Web 工作台中增加“复盘库”，让用户按日期维护每天一篇总复盘，在同一篇复盘中记录多只股票、Markdown 正文和截图，并能通过日期、标题、状态、股票、标签和正文关键词快速反查。

复盘内容必须长期保存在本地普通文件中。大模型只负责显式触发的候选标题生成，不能成为创建、编辑、保存、预览或搜索复盘的前置条件。

## 当前现实与边界

- 顶层仓库当前主线是 `web`，生产后端为 FastAPI，前端为嵌套仓库 `web/frontend` 中的 Vue 3 + TypeScript + Element Plus。
- 前端已有 `markdown-it` 和 `dompurify`，复盘预览复用现有 Markdown 渲染与 HTML 清洗技术栈，不引入第二套富文本编辑器。
- 后端已有 `config/llm.yaml`、DeepSeek provider 和 provider fallback 边界。标题生成复用这一配置，但使用独立的复盘标题服务和专用输出契约。
- 复盘库是记录和人工跟进模块，不触发自动交易、数据更新、策略扫描或订单执行。
- Markdown 文件是唯一真相源；一期不增加复盘 SQLite 表、搜索数据库或专有文档格式。

## 开源设计参考

- [Eleven-Trading/TradeNote](https://github.com/Eleven-Trading/TradeNote)：借鉴交易日志按股票、标签和状态组织与回看的产品思路。
- [mingi3314/tradelens](https://github.com/mingi3314/tradelens)：借鉴交易数据生成可移植 Markdown 模板的方式。
- [Erallie/diarian](https://github.com/Erallie/diarian)：借鉴按日期创建、浏览和回看每日记录的方式。
- [trganda/obsidian-attachment-management](https://github.com/trganda/obsidian-attachment-management)：借鉴附件跟随文档目录、时间戳命名和重复文件防冲突方式。

只借鉴公开的产品模式和文件组织思想，不复制上述项目代码，也不引入其 MongoDB、Obsidian 插件或桌面运行时。

## 文件模型

### 目录

复盘根目录固定为项目内的 `data/review_library`：

```text
data/review_library/
└── 2026/
    └── 07/
        ├── 2026-07-11.md
        └── 2026-07-11.assets/
            ├── 20260711-153012-001.png
            └── 20260711-160845-002.jpg
```

- 每个自然日最多一篇总复盘。
- 文件名严格为 `YYYY-MM-DD.md`，目录按 `YYYY/MM` 分层。
- 文档标题变化不重命名文件，保证日期排序、外部引用和图片链接稳定。
- 附件目录与 Markdown 同级，名称为 `YYYY-MM-DD.assets`。
- 日期的“今天”统一按 `Asia/Shanghai` 计算。

### Frontmatter

后端负责序列化 YAML frontmatter，字段契约如下：

```yaml
---
date: 2026-07-11
title: 沐曦放量突破，B1 候选出现分化
status: follow_up
title_source: manual
tags:
  - B1
  - 放量
stocks:
  - code: "688802"
    name: 沐曦股份
created_at: 2026-07-11T15:30:12+08:00
updated_at: 2026-07-11T16:20:00+08:00
---
```

- `status` 只允许 `draft`、`completed`、`follow_up`。
- `title_source` 只允许 `manual`、`deepseek`、`local_fallback`。
- 股票代码按字符串保存，避免丢失前导零；同一代码在 `stocks` 中只能出现一次。
- `created_at` 首次创建后不改变；每次成功写入更新 `updated_at`。
- 未知 frontmatter 字段不进入 API 响应，也不由前端写回，避免形成未定义的隐式契约。

### 标题与正文

- 页面顶部标题输入框是标题的编辑入口。
- 保存时后端同时更新 frontmatter 的 `title` 和正文第一行一级标题 `# <title>`。
- 正文编辑器编辑一级标题之后的 Markdown 内容，避免标题输入框和正文第一行出现两个可冲突的编辑源。
- 生成标题回填后，`title_source` 使用生成结果的来源；用户随后手动修改标题时，前端立即把来源改回 `manual`。
- 标题为空时不能保存；新建文档的默认标题为 `<YYYY-MM-DD> 交易复盘`。

### 标准模板

新建文档默认正文如下，用户可自由增删内容：

```markdown
# 2026-07-11 交易复盘

## 市场环境

## 今日计划与实际执行

## 重点股票

## 错误与交易纪律

## 明日跟踪清单
```

通过结构化动作加入股票时，在“重点股票”下追加：

```markdown
### 688802 沐曦股份

#### 观察逻辑

#### 走势与截图

#### 当前结论

#### 下一步动作
```

若股票代码已存在于 frontmatter，加入动作返回 `already_exists=true`，不追加重复章节。

## 后端设计

### 模块职责

- `review_repository`：日期与路径校验、Markdown/frontmatter 解析、原子文件写入、版本冲突检测、附件读写。
- `review_service`：模板创建、列表与全文检索、股票去重与章节追加、状态和标题规则。
- `review_title_service`：DeepSeek 标题候选和本地回退，不直接保存文档。
- `review` router：稳定的 HTTP 契约和错误映射，不在路由中拼接磁盘路径。

每个模块只承担一层职责，未来可替换索引方式，但不能改变 Markdown 唯一真相源。

### API 契约

```text
GET    /api/reviews
POST   /api/reviews/{review_date}
GET    /api/reviews/{review_date}
PUT    /api/reviews/{review_date}
POST   /api/reviews/{review_date}/stocks
POST   /api/reviews/{review_date}/generate-title
GET    /api/reviews/{review_date}/attachments
POST   /api/reviews/{review_date}/attachments
GET    /api/reviews/{review_date}/attachments/{filename}
DELETE /api/reviews/{review_date}/attachments/{filename}
```

附件删除接口接受可选查询参数 `force=false|true`。默认 `false` 时，仍被正文引用的附件返回 HTTP 409；只有用户在前端确认后才允许以 `force=true` 重试。

`GET /api/reviews` 支持：

```text
query=<全文关键词>
status=draft|completed|follow_up
stock=<代码或名称>
date_from=YYYY-MM-DD
date_to=YYYY-MM-DD
limit=<正整数>
offset=<非负整数>
```

列表项返回日期、标题、状态、标签、股票、更新时间、正文摘要、首张截图 URL 和版本号。默认按日期降序，其次按更新时间降序。

`POST /api/reviews/{review_date}` 是幂等创建：不存在时按模板创建，已存在时返回当前文档并标记 `created=false`。

`PUT /api/reviews/{review_date}` 接收标题、状态、标签、股票、正文和客户端看到的 `version`。版本不匹配返回 HTTP 409，前端保留未保存内容并提示用户重新加载或复制内容，不静默覆盖。

### 原子写入与索引

- 所有路径都从经过严格日期/文件名校验的值构造，并在 `resolve()` 后回校仍位于复盘根目录。
- Markdown 先写入同目录临时文件，刷新后通过 `os.replace` 原子替换。
- `version` 由文件修改时间和内容大小生成，作为轻量乐观锁。
- 列表和搜索直接扫描 Markdown 文件；允许进程内缓存文件路径、mtime 和解析结果，但删除缓存后必须能从 Markdown 完整重建。
- 一期不写持久化索引 JSON，避免出现第二真相源。

## 图片与附件

- 支持 PNG、JPEG、WebP、GIF；不接受 SVG、HTML 或其他可执行/复合格式。
- 单张上限 10 MiB；后端同时校验扩展名、声明 MIME 和文件签名。
- 文件名由服务端生成：`YYYYMMDD-HHMMSS-NNN.<ext>`，不直接采用用户文件名。
- 上传 API 返回可移植的相对 Markdown：`![说明](./2026-07-11.assets/<filename>)`。
- 前端预览时仅把上述安全相对路径映射到附件读取 API，然后交给 DOMPurify 清洗。
- 支持文件选择、拖拽和剪贴板粘贴；上传成功后在当前光标处插入 Markdown 图片语法。
- 删除附件前检查当前 Markdown 是否仍引用它。仍被引用时返回 HTTP 409；前端必须先移除引用，或在明确二次确认后以 `force=true` 重试。
- 保存正文不会自动删除未引用附件，避免误删尚未整理的截图。

## 标题生成

标题生成是显式按钮，不在保存、打开或搜索时自动调用模型。

1. 前端提交当前标题、正文、股票和标签，但不提交图片二进制。
2. provider 配置为 DeepSeek 且调用成功时，返回 8 到 30 个中文字符的候选标题，`source=deepseek`。
3. 未配置、provider 不是 DeepSeek、超时、响应非法或调用失败时，从股票名称、正文首个有效句子和标签生成本地候选，`source=local_fallback`。
4. 返回值只填入标题输入框并显示来源；用户仍可修改，且必须点击保存才写入文件。
5. 标题生成失败不得修改文档正文、状态或原文件。

真实 provider smoke 不进入默认测试，只使用 mock 验证 DeepSeek 成功/失败契约。

## 前端设计

### 路由与导航

- 新增侧边栏入口“复盘库”，路由 `/review-library`。
- 页面保持现有工作台的紧凑风格，不使用营销式大标题或嵌套卡片。

### 双栏布局

左栏固定宽度、右栏自适应：

- 左栏：新建按钮、关键词搜索、日期区间、状态筛选、复盘列表。
- 列表项：日期、标题、状态、股票数量、更新时间和首张截图缩略图。
- 顶部提供“草稿”和“待跟进”快捷筛选，便于继续未完成工作。
- 右栏：日期、标题、状态、标签、股票标签、生成标题、保存、编辑/预览页签。
- 小屏幕将左栏折叠为抽屉，编辑区保持全宽，所有按钮文字和日期不得溢出。

页面打开时不自动创建当天文件。用户点击“新建”或从其他页面加入股票时才创建，避免产生大量空复盘。

### 编辑行为

- Markdown 编辑使用普通多行文本编辑器和现有 Markdown 预览栈，不引入 WYSIWYG 编辑器。
- 切换复盘、离开页面或关闭窗口时，如有未保存修改，复用现有离开保护模式提示用户。
- 保存成功后更新版本号和列表摘要。
- 409 冲突、图片失败、标题 provider 回退和保存失败必须在页面可见，不能只写控制台。
- 快捷搜索同时匹配日期、标题、股票代码/名称、标签和正文。

## 跨页面加入股票

- `StockDetail.vue` 增加“加入今日复盘”。
- `TrackingView.vue` 每只股票的操作区增加“加入今日复盘”。
- 点击后调用当天的股票加入 API；若文档不存在，后端先按标准模板创建。
- 成功反馈区分“已加入”和“今日复盘中已存在”，并提供“打开今日复盘”的直接入口。
- 加入动作只写股票元数据和标准章节，不复制 K 线数据、不自动截图、不调用大模型。

## 错误与安全边界

- 非法日期、路径分隔符、`.`、`..` 和未知附件名一律拒绝，错误信息不暴露真实磁盘路径。
- Markdown 预览必须经过 DOMPurify；不执行 Markdown 中的脚本、iframe 或事件属性。
- 图片读取只允许返回白名单附件目录中的普通文件。
- 单个损坏 Markdown 不得阻断整个列表；列表返回可识别的损坏项告警，打开该日期时提供原始文件路径的相对定位信息和恢复提示。
- DeepSeek 密钥只从现有服务端配置读取，不写入 Markdown、前端响应或日志。

## 一期不做

- 不做自动交易、券商导入、成交单自动解析或收益统计仪表盘。
- 不自动导入全部跟踪股票。
- 不自动调用模型总结整篇复盘。
- 不做云同步、多人协作、账号权限、加密仓库或移动端原生应用。
- 不引入 SQLite、MongoDB、Elasticsearch、Obsidian 或第二套富文本编辑器。
- 不提供自动清理未引用附件或文档历史版本 UI。

## 验收标准

- 可为任意合法日期创建且最多创建一篇复盘，磁盘文件路径和 frontmatter 符合本规格。
- 标题输入同时决定 frontmatter 标题和 Markdown 一级标题，修改标题不改变文件名。
- 标准模板可自由编辑，并能在一篇文档中加入多只不重复股票。
- 股票详情页和跟踪运营页都能加入当天复盘，并提供打开入口。
- PNG/JPEG/WebP/GIF 可选择、拖拽或粘贴上传，保存到当天附件目录并在预览中显示。
- 草稿、已完成、待跟进可切换和筛选。
- 可按日期、标题、股票代码/名称、标签和正文关键词反查。
- DeepSeek 成功时返回模型标题；未配置或失败时返回本地候选，且不会阻断保存。
- 两个页面同时编辑时，旧版本保存收到 409，原内容不会被静默覆盖。
- 重启后不依赖缓存或数据库即可从 Markdown 重建全部列表与搜索结果。

## 验证计划

后端最低验证：

```powershell
python -m pytest tests/test_review_repository.py tests/test_review_service.py tests/test_review_api.py -q
python -c "from web.backend.main import app; print(any(r.path.startswith('/api/reviews') for r in app.routes))"
```

前端最低验证：

```powershell
cd web/frontend
npm run test -- src/api/__tests__/reviewApi.spec.ts src/views/__tests__/reviewLibraryState.spec.ts
npm run build
```

浏览器验证必须覆盖桌面和移动宽度：新建过去日期、保存草稿、添加两只股票、防重复、粘贴截图、预览图片、生成标题的 DeepSeek 回退提示、全文搜索、状态筛选、从股票详情和跟踪运营加入、未保存离开提示及 409 冲突反馈。

收口检查：

```powershell
git diff --check
```

真实 DeepSeek 调用、全市场数据更新和交易 provider smoke 与默认自动化测试分开记录。
