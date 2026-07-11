# 日期 Markdown 复盘库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 FastAPI + Vue 3 工作台中交付按日期保存 Markdown、截图附件、快速检索、AI/本地标题候选和跨页面加入股票的复盘库。

**Architecture:** `data/review_library/YYYY/MM/YYYY-MM-DD.md` 是唯一真相源；后端用 repository 隔离路径与原子 IO，用 service 处理模板、检索和股票章节，用 router 暴露 API。前端新增独立复盘 API、状态助手和双栏编辑页，股票详情与跟踪运营复用一个“加入今日复盘”按钮。

**Tech Stack:** Python 3、FastAPI、PyYAML、Pillow、pytest、Vue 3、TypeScript、Element Plus、markdown-it、DOMPurify、Vitest、Vite。

## Global Constraints

- 每个自然日最多一篇 `YYYY-MM-DD.md`；日期按 `Asia/Shanghai`。
- Markdown 是唯一真相源，不新增 SQLite 表或持久化索引文件。
- 新 Python 文件必须有中文模块 docstring；注释只解释意图、约束或边界。
- 图片只允许 PNG/JPEG/WebP/GIF，单张最大 10 MiB；禁止 SVG 和路径穿越。
- 标题生成必须显式触发；DeepSeek 不可用时本地回退，不能阻断保存。
- 前端复用现有 `markdown-it`、`DOMPurify`、API 客户端和离开保护模式。
- `web/frontend` 是独立 gitlink：从顶层记录的 `ba8eca511810f06d3b4da746d07da7f188930c1c` 初始化并创建 `codex/review-library`；先提交前端，再提交顶层 gitlink。
- 不碰主工作区中用户未提交的 `TrackingView.vue`，只在隔离前端仓库基于 gitlink 提交实现。
- 默认测试不调用真实 DeepSeek，不触发全市场更新或交易 provider。

---

### Task 1: Markdown Repository 与文件安全

**Files:**
- Create: `web/backend/services/review_repository.py`
- Create: `tests/test_review_repository.py`

**Interfaces:**
- Produces: `ReviewRepository(root: Path)`。
- Produces: `ReviewDocument`，字段为 `review_date/title/status/title_source/tags/stocks/body/created_at/updated_at/version`。
- Produces: `load(review_date) -> ReviewDocument | None`、`save(document, expected_version=None) -> ReviewDocument`、`iter_documents() -> list[ReviewDocument]`。
- Produces: `save_attachment(review_date, upload_name, content_type, raw) -> AttachmentInfo`、`list_attachments(review_date)`、`read_attachment(review_date, filename)`、`delete_attachment(review_date, filename, force=False)`。

- [ ] **Step 1: 写 repository 失败测试**

测试必须覆盖：合法路径、非法日期/穿越拒绝、frontmatter 往返、股票代码前导零、原子保存、旧版本 409 对应异常、图片签名和 10 MiB 限制、被正文引用的附件不能直接删除。

```python
def test_save_and_load_round_trip(tmp_path):
    repo = ReviewRepository(tmp_path)
    saved = repo.save(ReviewDocument.new("2026-07-11"))
    loaded = repo.load("2026-07-11")
    assert loaded.review_date == "2026-07-11"
    assert loaded.title == "2026-07-11 交易复盘"
    assert (tmp_path / "2026" / "07" / "2026-07-11.md").is_file()

def test_save_rejects_stale_version(tmp_path):
    repo = ReviewRepository(tmp_path)
    original = repo.save(ReviewDocument.new("2026-07-11"))
    repo.save(replace(original, title="新标题"), expected_version=original.version)
    with pytest.raises(ReviewConflictError):
        repo.save(replace(original, title="旧页面标题"), expected_version=original.version)
```

- [ ] **Step 2: 运行测试确认红灯**

Run: `python -m pytest tests/test_review_repository.py -q`

Expected: collection 失败，提示 `review_repository` 不存在。

- [ ] **Step 3: 实现最小 repository**

关键类型和边界必须按以下签名实现：

```python
@dataclass(frozen=True)
class ReviewDocument:
    review_date: str
    title: str
    status: Literal["draft", "completed", "follow_up"]
    title_source: Literal["manual", "deepseek", "local_fallback"]
    tags: tuple[str, ...]
    stocks: tuple[ReviewStock, ...]
    body: str
    created_at: str
    updated_at: str
    version: str = ""

class ReviewConflictError(RuntimeError):
    pass

class ReviewValidationError(ValueError):
    pass

class ReviewAttachmentReferencedError(RuntimeError):
    pass
```

用 `yaml.safe_load/safe_dump` 解析 frontmatter；用同目录临时文件、`flush/fsync` 和 `os.replace` 原子写入；用 Pillow `Image.verify()` 校验图片实际格式；所有 resolve 后路径必须 `relative_to(self.root.resolve())` 成功。

- [ ] **Step 4: 运行 repository 测试确认绿灯**

Run: `python -m pytest tests/test_review_repository.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交 Task 1**

```powershell
git add web/backend/services/review_repository.py tests/test_review_repository.py
git commit -m "feat: add markdown review repository"
```

### Task 2: 复盘业务服务与标题候选

**Files:**
- Create: `web/backend/services/review_service.py`
- Create: `web/backend/services/review_title_service.py`
- Create: `tests/test_review_service.py`
- Create: `tests/test_review_title_service.py`

**Interfaces:**
- Consumes: Task 1 `ReviewRepository` 与 `ReviewDocument`。
- Produces: `ReviewService.create_or_get()`、`list_reviews()`、`update_review()`、`add_stock()`。
- Produces: `ReviewTitleService.generate(document) -> TitleSuggestion`。

- [ ] **Step 1: 写 service 失败测试**

```python
def test_add_stock_appends_one_section_and_deduplicates(tmp_path):
    service = ReviewService(ReviewRepository(tmp_path))
    service.create_or_get("2026-07-11")
    first = service.add_stock("2026-07-11", "688802", "沐曦股份")
    second = service.add_stock("2026-07-11", "688802", "沐曦股份")
    assert first["already_exists"] is False
    assert second["already_exists"] is True
    assert first["document"].body.count("### 688802 沐曦股份") == 1

def test_list_reviews_searches_title_stock_tag_and_body(tmp_path):
    service = ReviewService(ReviewRepository(tmp_path))
    doc, _ = service.create_or_get("2026-07-11")
    service.add_stock("2026-07-11", "688802", "沐曦股份")
    current = service.get_review("2026-07-11")
    service.update_review(
        "2026-07-11",
        title="沐曦放量突破",
        status="follow_up",
        title_source="manual",
        tags=["B1"],
        stocks=[{"code": "688802", "name": "沐曦股份"}],
        body="半导体观察",
        expected_version=current.version,
    )
    assert len(service.list_reviews(query="688802")["items"]) == 1
    assert len(service.list_reviews(query="半导体")["items"]) == 1
```

标题测试分别 monkeypatch `load_llm_config` 和 `call_deepseek`：成功时断言 `source=deepseek`；未配置、超时、非法 JSON 时断言 `source=local_fallback` 且候选包含股票名称或首个有效句子。

- [ ] **Step 2: 运行 service 测试确认红灯**

Run: `python -m pytest tests/test_review_service.py tests/test_review_title_service.py -q`

Expected: collection 失败，提示两个 service 模块不存在。

- [ ] **Step 3: 实现模板、搜索、股票去重和标题回退**

`TitleSuggestion` 固定字段为 `title: str`、`source: Literal["deepseek", "local_fallback"]`、`provider_fallback: bool`、`provider_error: str | None`。

`ReviewService` 的公开签名固定为：

- `create_or_get(review_date: str) -> tuple[ReviewDocument, bool]`
- `get_review(review_date: str) -> ReviewDocument`
- `list_reviews(*, query: str = "", status: str | None = None, stock: str = "", date_from: str | None = None, date_to: str | None = None, limit: int = 50, offset: int = 0) -> dict`
- `update_review(review_date: str, *, title: str, status: str, title_source: str, tags: list[str], stocks: list[dict], body: str, expected_version: str) -> ReviewDocument`
- `add_stock(review_date: str, code: str, name: str) -> dict`

`create_or_get` 先 `repository.load`，存在即返回 `(document, False)`，不存在则构造标准模板并保存后返回 `(saved, True)`。`add_stock` 先按 code 检查 frontmatter；不存在时把股票写入 metadata，并把标准章节插入“## 重点股票”之后。搜索把标题、标签、股票代码/名称和正文归一化为小写字符串后做包含匹配，再应用日期、状态、分页和降序排序。

本地标题回退顺序固定为：股票名称（最多两个）→ 正文首个非标题句子 → 标签；压缩空白并限制 30 个字符。DeepSeek prompt 只要求 `{"title":"沐曦放量突破"}` 这种单字段 JSON，正文截断到 12,000 字符。

- [ ] **Step 4: 运行 service 测试确认绿灯**

Run: `python -m pytest tests/test_review_service.py tests/test_review_title_service.py -q`

Expected: 全部通过。

- [ ] **Step 5: 提交 Task 2**

```powershell
git add web/backend/services/review_service.py web/backend/services/review_title_service.py tests/test_review_service.py tests/test_review_title_service.py
git commit -m "feat: add review library services"
```

### Task 3: FastAPI 复盘接口

**Files:**
- Create: `web/backend/routers/review.py`
- Modify: `web/backend/main.py`
- Create: `tests/test_review_api.py`

**Interfaces:**
- Consumes: Task 1/2 repository、service、title service。
- Produces: `/api/reviews` 及附件接口，响应统一为 `{"success": true, "data": {"review_date": "2026-07-11"}}` 这一 envelope 结构。

- [ ] **Step 1: 写 API 失败测试**

使用临时目录和 monkeypatch 的 service 构造独立 FastAPI client，覆盖：幂等创建、读取、列表筛选、保存、版本冲突 409、股票去重、标题回退来源、上传/读取/删除附件、非法日期 422、路径穿越 404/422。

```python
def test_create_update_and_conflict(client):
    created = client.post("/api/reviews/2026-07-11").json()["data"]
    payload = {**created, "title": "今日复盘", "version": created["version"]}
    saved = client.put("/api/reviews/2026-07-11", json=payload)
    assert saved.status_code == 200
    stale = client.put("/api/reviews/2026-07-11", json=payload)
    assert stale.status_code == 409
```

- [ ] **Step 2: 运行 API 测试确认红灯**

Run: `python -m pytest tests/test_review_api.py -q`

Expected: collection 失败，提示 router 不存在。

- [ ] **Step 3: 实现 Pydantic 请求模型和错误映射**

创建 `ReviewUpdatePayload`、`ReviewStockPayload`、`ReviewTitlePayload`。路由把 `ReviewValidationError` 映射为 422、`ReviewConflictError` 和仍引用附件映射为 409、文件不存在映射为 404；错误内容不包含绝对路径。

在 `web/backend/main.py` 导入并 `app.include_router(review.router)`，固定路由先于前端 SPA fallback 注册。

- [ ] **Step 4: 运行 API 与 import smoke**

Run: `python -m pytest tests/test_review_api.py tests/test_frontend_spa_fallback.py -q`

Run: `python -c "from web.backend.main import app; print([r.path for r in app.routes if r.path.startswith('/api/reviews')])"`

Expected: 测试通过，输出包含 `/api/reviews` 和附件路由。

- [ ] **Step 5: 提交 Task 3**

```powershell
git add web/backend/routers/review.py web/backend/main.py tests/test_review_api.py
git commit -m "feat: expose review library api"
```

### Task 4: 初始化嵌套前端并增加 API/状态助手

**Files:**
- Create: `web/frontend/src/api/reviews.ts`
- Create: `web/frontend/src/api/__tests__/reviewApi.spec.ts`
- Create: `web/frontend/src/views/reviewLibraryState.ts`
- Create: `web/frontend/src/views/__tests__/reviewLibraryState.spec.ts`

**Interfaces:**
- Consumes: Task 3 HTTP 契约。
- Produces: `listReviews/createReview/getReview/updateReview/addStockToReview/generateReviewTitle/uploadReviewAttachment/deleteReviewAttachment`。
- Produces: `rewriteReviewImageUrls()`、`reviewIsDirty()`、`mergeTitleSuggestion()`。

- [ ] **Step 1: 初始化独立前端分支**

```powershell
git clone --no-checkout "D:\stock\20260329dingtalk\a-share-quant-selector-main-zuozhe\a-share-quant-selector-Stock\web\frontend" web/frontend
git -C web/frontend checkout -b codex/review-library ba8eca511810f06d3b4da746d07da7f188930c1c
npm --prefix web/frontend install
```

Expected: `git -C web/frontend status --short --branch` 显示 `codex/review-library` 且干净。

- [ ] **Step 2: 写前端 API 和状态失败测试**

```ts
it('uploads an attachment as multipart form data', async () => {
  const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: {} } } as any)
  await uploadReviewAttachment('2026-07-11', new File(['png'], 'shot.png'))
  expect(post).toHaveBeenCalledWith('/reviews/2026-07-11/attachments', expect.any(FormData), {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
})

it('rewrites only safe local review image paths', () => {
  expect(rewriteReviewImageUrls('![图](./2026-07-11.assets/a.png)', '2026-07-11'))
    .toContain('/reviews/2026-07-11/attachments/a.png')
  expect(rewriteReviewImageUrls('![图](javascript:alert(1))', '2026-07-11'))
    .toContain('javascript:alert(1)')
})
```

- [ ] **Step 3: 运行前端测试确认红灯**

Run: `npm --prefix web/frontend run test -- src/api/__tests__/reviewApi.spec.ts src/views/__tests__/reviewLibraryState.spec.ts`

Expected: import 失败，提示目标模块不存在。

- [ ] **Step 4: 实现类型化 API 和纯状态函数**

所有日期和附件名使用 `encodeURIComponent`；API 类型必须包括 `ReviewStatus`、`ReviewStock`、`ReviewDocument`、`ReviewListItem`、`ReviewTitleSuggestion`、`ReviewAttachment`。图片 URL 重写只接受 `./<date>.assets/<safe filename>`。

- [ ] **Step 5: 运行前端测试确认绿灯**

Run: `npm --prefix web/frontend run test -- src/api/__tests__/reviewApi.spec.ts src/views/__tests__/reviewLibraryState.spec.ts`

Expected: 全部通过。

### Task 5: 复盘库双栏页面与图片编辑

**Files:**
- Create: `web/frontend/src/views/ReviewLibraryView.vue`
- Create: `web/frontend/src/components/ReviewAttachmentUploader.vue`
- Modify: `web/frontend/src/router/index.ts`
- Modify: `web/frontend/src/components/AppSidebar.vue`
- Test: `web/frontend/src/views/__tests__/reviewLibraryState.spec.ts`

**Interfaces:**
- Consumes: Task 4 API 和状态助手。
- Produces: `/review-library` 可用页面。

- [ ] **Step 1: 扩展状态测试覆盖编辑生命周期**

增加标题手改后 `title_source=manual`、生成候选合并、保存快照 dirty 比较、图片 Markdown 在光标位置插入、状态筛选参数构造测试。

- [ ] **Step 2: 实现双栏工作台**

页面必须包含：左侧搜索/日期/状态/草稿和待跟进快捷筛选；右侧日期、标题、状态、标签、股票、生成标题、保存、编辑/预览页签；无文档时显示创建入口。标题字段与正文分离，保存时 API body 不包含一级标题。

使用 Element Plus 图标按钮；图标不熟悉时提供 `title` tooltip。编辑器使用原生 textarea/`el-input type=textarea`，预览通过 `markdown-it({html:false})` + DOMPurify。

- [ ] **Step 3: 实现截图上传、拖拽和粘贴**

`ReviewAttachmentUploader.vue` 接收 `reviewDate` 和 `insertMarkdown(markdown)`；`paste/drop/change` 都调用同一个 `uploadFiles(files)`。上传失败逐张显示，成功后在当前光标位置插入后端返回的 Markdown。

- [ ] **Step 4: 接入未保存保护和响应式布局**

复用 `bindBeforeUnloadGuard`；Vue router 离开时用 `onBeforeRouteLeave` 提示。桌面左栏宽度 300px，小于 900px 时改为抽屉；按钮、日期、标题不得溢出。

- [ ] **Step 5: 接入路由和侧边栏**

路由名固定 `ReviewLibrary`，路径 `/review-library`；侧边栏使用 Element Plus `Notebook` 或最接近的文档图标，标题“复盘库”。

- [ ] **Step 6: 运行前端测试和构建**

Run: `npm --prefix web/frontend run test -- src/api/__tests__/reviewApi.spec.ts src/views/__tests__/reviewLibraryState.spec.ts`

Run: `npm --prefix web/frontend run build`

Expected: 测试和 `vue-tsc -b && vite build` 全部通过。

### Task 6: 股票详情与跟踪运营加入今日复盘

**Files:**
- Create: `web/frontend/src/components/AddToTodayReviewButton.vue`
- Create: `web/frontend/src/components/__tests__/AddToTodayReviewButton.spec.ts`
- Modify: `web/frontend/src/views/StockDetail.vue`
- Modify: `web/frontend/src/views/TrackingView.vue`

**Interfaces:**
- Consumes: Task 4 `addStockToReview()`，Task 5 `/review-library` 路由。
- Produces: 可复用按钮 props `{ code: string; name?: string; size?: string }`。

- [ ] **Step 1: 写组件失败测试**

mock `addStockToReview` 和 router，分别断言：首次加入显示“已加入今日复盘”；重复返回显示“今日复盘中已存在”；失败时错误可见；点击“打开复盘”导航到 `{name:'ReviewLibrary', query:{date:<today>}}`。

- [ ] **Step 2: 运行组件测试确认红灯**

Run: `npm --prefix web/frontend run test -- src/components/__tests__/AddToTodayReviewButton.spec.ts`

Expected: import 失败，提示组件不存在。

- [ ] **Step 3: 实现共享按钮并接入两个页面**

按钮以 `Asia/Shanghai` 本地日期调用股票加入 API。StockDetail 放在股票操作区；TrackingView 放在每行操作区。两个页面不得复制 API 调用和消息分支。

- [ ] **Step 4: 运行前端相关测试和构建**

Run: `npm --prefix web/frontend run test -- src/components/__tests__/AddToTodayReviewButton.spec.ts src/api/__tests__/reviewApi.spec.ts`

Run: `npm --prefix web/frontend run build`

Expected: 全部通过。

- [ ] **Step 5: 提交嵌套前端**

```powershell
git -C web/frontend add src/api/reviews.ts src/api/__tests__/reviewApi.spec.ts src/views/reviewLibraryState.ts src/views/__tests__/reviewLibraryState.spec.ts src/views/ReviewLibraryView.vue src/components/ReviewAttachmentUploader.vue src/components/AddToTodayReviewButton.vue src/components/__tests__/AddToTodayReviewButton.spec.ts src/router/index.ts src/components/AppSidebar.vue src/views/StockDetail.vue src/views/TrackingView.vue
git -C web/frontend diff --cached --check
git -C web/frontend commit -m "feat: add markdown review library workspace"
```

### Task 7: 使用文档、整体验证与顶层收口

**Files:**
- Modify: `README.md`
- Modify: `web/frontend` gitlink

**Interfaces:**
- Consumes: Tasks 1-6 全部产物。
- Produces: 可从 README 找到的复盘库入口、完整验证证据和顶层提交。

- [ ] **Step 1: 更新 README 当前能力与使用方法**

在 Web 功能和启动后使用章节增加：侧边栏“复盘库”、每天一篇 Markdown、截图上传/粘贴、标题候选、状态与搜索、从股票详情/跟踪运营加入；注明文件位于 `data/review_library`，备份该目录即可迁移。

- [ ] **Step 2: 跑后端完整相关测试**

Run: `python -m pytest tests/test_review_repository.py tests/test_review_service.py tests/test_review_title_service.py tests/test_review_api.py tests/test_frontend_spa_fallback.py -q`

Run: `python -c "from web.backend.main import app; assert any(r.path == '/api/reviews' for r in app.routes); print('review routes ok')"`

Expected: 全部通过，import smoke 输出 `review routes ok`。

- [ ] **Step 3: 跑前端完整测试和构建**

Run: `npm --prefix web/frontend run test -- src/api/__tests__/reviewApi.spec.ts src/views/__tests__/reviewLibraryState.spec.ts src/components/__tests__/AddToTodayReviewButton.spec.ts`

Run: `npm --prefix web/frontend run build`

Expected: 全部通过。

- [ ] **Step 4: 启动隔离服务并做浏览器验收**

后端使用未占用端口（优先 8023），前端使用未占用端口（优先 5180），并确保 Vite proxy 指向当前 worktree 后端。浏览器覆盖桌面 1440x900 和移动 390x844：创建过去日期、保存草稿、两只股票、防重复、粘贴 PNG、预览图片、标题本地回退、全文搜索、状态筛选、股票详情加入、跟踪页加入、未保存离开提示。

同时检查页面无重叠、标题不溢出、移动端左栏为抽屉、图片非空且来自当前附件 API。

- [ ] **Step 5: 检查差异并提交顶层收口**

```powershell
git diff --check
git status --short
git add README.md web/frontend
git diff --cached --check
git commit -m "feat: add markdown review library"
```

- [ ] **Step 6: 最终核验提交和工作区状态**

```powershell
git status --short --branch
git log --oneline --decorate -8
git -C web/frontend status --short --branch
```

Expected: 顶层和嵌套前端工作区都干净；顶层 gitlink 指向 Task 6 的前端提交；所有功能提交都位于 `codex/review-library-design` / `codex/review-library`。
