<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, MagicStick, Menu, Refresh, Search } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import ReviewAttachmentUploader from '@/components/ReviewAttachmentUploader.vue'
import { bindBeforeUnloadGuard } from '@/composables/beforeUnloadGuard'
import {
  createReview,
  generateReviewTitle,
  getReview,
  listReviews,
  updateReview,
  type ReviewDocument,
  type ReviewListItem,
  type ReviewStatus,
} from '@/api/reviews'
import {
  buildReviewListParams,
  createSavedReviewSnapshot,
  insertMarkdownAtSelection,
  markReviewTitleManual,
  reviewIsDirty,
  rewriteReviewImageUrls,
} from '@/views/reviewLibraryState'
import {
  applyReviewCreateResponse,
  applyReviewSaveResponse,
  applyReviewTitleResponse,
  createReviewCreateOperation,
  createReviewLoadController,
  createReviewSaveOperation,
  createReviewTitleOperation,
  reviewCreateOperationIsCurrent,
  reviewSelectionIsActive,
  reviewTitleOperationIsCurrent,
} from '@/views/reviewLibraryLifecycle'

const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true })
const route = useRoute()
const router = useRouter()

const filters = reactive<{
  query: string
  status: ReviewStatus | ''
  dateRange: [string, string] | null
}>({ query: '', status: '', dateRange: null })
const items = ref<ReviewListItem[]>([])
const current = ref<ReviewDocument | null>(null)
const saved = ref<ReviewDocument | null>(null)
const activeDate = ref(todayString())
const activeTab = ref<'edit' | 'preview'>('edit')
const listLoading = ref(false)
const documentLoading = ref(false)
const saving = ref(false)
const generating = ref(false)
const creating = ref(false)
const uploadPending = ref(false)
const listError = ref('')
const documentError = ref('')
const drawerOpen = ref(false)
const isMobile = ref(false)
const editorRef = ref<{ textarea?: HTMLTextAreaElement } | null>(null)
const documentIdentity = ref('')
const selection = reactive({ start: 0, end: 0 })
let removeBeforeUnloadGuard: (() => void) | null = null
let documentIdentitySequence = 0
let pendingDocumentLoads = 0
let titleRequestToken = 0
let createRequestToken = 0
const loadController = createReviewLoadController(async (reviewDate) => {
  const response = await getReview(reviewDate)
  return response.data.data
})

const dirty = computed(() => reviewIsDirty(current.value, saved.value))
const previewHtml = computed(() => {
  if (!current.value?.body.trim()) return ''
  const withApiImages = rewriteReviewImageUrls(current.value.body, current.value.review_date)
  return DOMPurify.sanitize(markdown.render(withApiImages), { USE_PROFILES: { html: true } })
})

function todayString(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function errorMessage(error: unknown, fallback: string): string {
  const candidate = error as {
    response?: { status?: number; data?: { detail?: string; message?: string } }
    message?: string
  }
  return candidate.response?.data?.detail || candidate.response?.data?.message || candidate.message || fallback
}

function statusLabel(status: ReviewStatus): string {
  return { draft: '草稿', completed: '已完成', follow_up: '待跟进' }[status]
}

function statusTagType(status: ReviewStatus): 'info' | 'success' | 'warning' {
  return { draft: 'info', completed: 'success', follow_up: 'warning' }[status] as 'info' | 'success' | 'warning'
}

function checkViewport() {
  isMobile.value = window.innerWidth < 900
  if (!isMobile.value) drawerOpen.value = false
}

async function confirmDiscard(): Promise<boolean> {
  if (uploadPending.value) {
    ElMessage.warning('图片上传中，请等待上传完成后再切换复盘')
    return false
  }
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前复盘尚未保存，确认放弃修改吗？', '未保存修改', {
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
      type: 'warning',
    })
    return true
  } catch {
    return false
  }
}

async function fetchList(selectInitial = false) {
  listLoading.value = true
  listError.value = ''
  try {
    const response = await listReviews(buildReviewListParams(filters))
    items.value = response.data.data.items
    if (selectInitial && !route.query.date && items.value.length) {
      await openReview(items.value[0].review_date, false)
    }
  } catch (error) {
    listError.value = errorMessage(error, '复盘列表加载失败')
  } finally {
    listLoading.value = false
  }
}

function setActiveDocument(document: ReviewDocument) {
  current.value = createSavedReviewSnapshot(document)
  saved.value = createSavedReviewSnapshot(document)
  documentIdentity.value = `${document.review_date}:${++documentIdentitySequence}`
}

async function loadDocument(reviewDate: string): Promise<boolean> {
  titleRequestToken += 1
  createRequestToken += 1
  pendingDocumentLoads += 1
  documentLoading.value = true
  documentError.value = ''
  activeDate.value = reviewDate
  try {
    const result = await loadController.load(reviewDate)
    if (result.stale) return false
    setActiveDocument(result.document)
    activeTab.value = 'edit'
    selection.start = result.document.body.length
    selection.end = result.document.body.length
    return true
  } catch (error) {
    const status = (error as { response?: { status?: number } }).response?.status
    current.value = null
    saved.value = null
    documentIdentity.value = `${reviewDate}:empty:${++documentIdentitySequence}`
    if (status !== 404) documentError.value = errorMessage(error, '复盘加载失败')
    return true
  } finally {
    pendingDocumentLoads -= 1
    documentLoading.value = pendingDocumentLoads > 0
  }
}

async function openReview(reviewDate: string, askToDiscard = true) {
  if (reviewSelectionIsActive(current.value, reviewDate)) {
    drawerOpen.value = false
    return
  }
  if (
    askToDiscard
    && (uploadPending.value || reviewDate !== activeDate.value)
    && !(await confirmDiscard())
  ) return
  const committed = await loadDocument(reviewDate)
  if (!committed) return
  drawerOpen.value = false
  void router.replace({ name: 'ReviewLibrary', query: { ...route.query, date: reviewDate } })
}

async function handleDateChange(reviewDate: string | null) {
  if (!reviewDate) return
  if (reviewDate === activeDate.value) return
  if (!(await confirmDiscard())) return
  await openReview(reviewDate, false)
}

async function createActiveReview() {
  const operation = createReviewCreateOperation(activeDate.value, ++createRequestToken)
  creating.value = true
  documentError.value = ''
  try {
    const response = await createReview(operation.reviewDate)
    const result = applyReviewCreateResponse(
      activeDate.value,
      createRequestToken,
      operation,
      response.data.data,
    )
    if (!result.applied || !result.document) return
    setActiveDocument(result.document)
    await fetchList()
    ElMessage.success('复盘已创建')
  } catch (error) {
    if (reviewCreateOperationIsCurrent(activeDate.value, createRequestToken, operation)) {
      documentError.value = errorMessage(error, '创建复盘失败')
    }
  } finally {
    creating.value = false
  }
}

function updateTitle(value: string) {
  if (!current.value) return
  titleRequestToken += 1
  current.value = markReviewTitleManual(current.value, value)
}

async function saveReview() {
  if (!current.value) return
  const operation = createReviewSaveOperation(current.value, documentIdentity.value)
  saving.value = true
  documentError.value = ''
  try {
    const response = await updateReview(operation.reviewDate, operation.payload)
    const result = applyReviewSaveResponse(
      current.value,
      saved.value,
      documentIdentity.value,
      operation,
      response.data.data,
    )
    if (!result.applied) return
    current.value = result.current
    saved.value = result.saved
    void fetchList()
    ElMessage.success(dirty.value ? '提交时内容已保存，后续修改仍未保存' : '复盘已保存')
  } catch (error) {
    if (
      current.value?.review_date === operation.reviewDate
      && documentIdentity.value === operation.documentIdentity
    ) {
      documentError.value = errorMessage(error, '保存失败，请检查版本或网络状态')
    }
  } finally {
    saving.value = false
  }
}

async function generateTitle() {
  if (!current.value) return
  const operation = createReviewTitleOperation(
    current.value,
    documentIdentity.value,
    ++titleRequestToken,
  )
  generating.value = true
  documentError.value = ''
  try {
    const response = await generateReviewTitle(operation.reviewDate, operation.payload)
    const result = applyReviewTitleResponse(
      current.value,
      documentIdentity.value,
      titleRequestToken,
      operation,
      response.data.data,
    )
    if (!result.applied) return
    current.value = result.current
    if (response.data.data.provider_fallback) {
      ElMessage.warning(response.data.data.provider_error || '标题服务已使用本地回退')
    }
  } catch (error) {
    if (reviewTitleOperationIsCurrent(
      current.value,
      documentIdentity.value,
      titleRequestToken,
      operation,
    )) {
      documentError.value = errorMessage(error, '标题生成失败')
    }
  } finally {
    generating.value = false
  }
}

function setQuickStatus(status: ReviewStatus) {
  filters.status = filters.status === status ? '' : status
  void fetchList()
}

function syncSelection() {
  const textarea = editorRef.value?.textarea
  if (!textarea) return
  selection.start = textarea.selectionStart
  selection.end = textarea.selectionEnd
}

function insertMarkdown(
  markdownText: string,
  context: { reviewDate: string; documentIdentity: string },
) {
  if (
    !current.value
    || current.value.review_date !== context.reviewDate
    || documentIdentity.value !== context.documentIdentity
  ) return
  const insertion = insertMarkdownAtSelection(
    current.value.body,
    markdownText,
    selection.start,
    selection.end,
  )
  current.value.body = insertion.value
  selection.start = insertion.cursor
  selection.end = insertion.cursor
  void nextTick(() => {
    const textarea = editorRef.value?.textarea
    textarea?.focus()
    textarea?.setSelectionRange(insertion.cursor, insertion.cursor)
  })
}

onBeforeRouteLeave(() => {
  if (uploadPending.value) {
    ElMessage.warning('图片上传中，请等待上传完成后再离开')
    return false
  }
  if (!dirty.value) return true
  return window.confirm('当前复盘尚未保存，确认离开吗？')
})

onMounted(async () => {
  checkViewport()
  window.addEventListener('resize', checkViewport)
  removeBeforeUnloadGuard = bindBeforeUnloadGuard(() => dirty.value || uploadPending.value)
  const routeDate = typeof route.query.date === 'string' ? route.query.date : ''
  if (routeDate) await loadDocument(routeDate)
  await fetchList(!routeDate)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', checkViewport)
  removeBeforeUnloadGuard?.()
})
</script>

<template>
  <section class="review-library">
    <button
      v-if="isMobile"
      class="drawer-backdrop"
      :class="{ visible: drawerOpen }"
      type="button"
      aria-label="关闭复盘列表"
      @click="drawerOpen = false"
    />

    <aside class="review-list-pane" :class="{ open: drawerOpen }">
      <header class="list-header">
        <div>
          <h1>复盘库</h1>
          <span>{{ items.length }} 篇</span>
        </div>
        <el-button :icon="Refresh" circle size="small" title="刷新列表" :loading="listLoading" @click="fetchList()" />
      </header>

      <div class="filters">
        <el-input v-model="filters.query" clearable placeholder="搜索标题、正文、股票" @keyup.enter="fetchList()">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-date-picker
          v-model="filters.dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          range-separator="至"
          @change="fetchList()"
        />
        <el-select v-model="filters.status" placeholder="全部状态" clearable @change="fetchList()">
          <el-option label="草稿" value="draft" />
          <el-option label="待跟进" value="follow_up" />
          <el-option label="已完成" value="completed" />
        </el-select>
        <div class="quick-filters">
          <el-button :type="filters.status === 'draft' ? 'primary' : 'default'" size="small" @click="setQuickStatus('draft')">草稿</el-button>
          <el-button :type="filters.status === 'follow_up' ? 'warning' : 'default'" size="small" @click="setQuickStatus('follow_up')">待跟进</el-button>
        </div>
      </div>

      <el-alert v-if="listError" :title="listError" type="error" show-icon :closable="false" />
      <div v-loading="listLoading" class="review-list">
        <button
          v-for="item in items"
          :key="item.review_date"
          class="review-list-item"
          :class="{ active: current?.review_date === item.review_date }"
          type="button"
          @click="openReview(item.review_date)"
        >
          <span class="item-topline">
            <strong>{{ item.title || '未命名复盘' }}</strong>
            <el-tag size="small" :type="statusTagType(item.status)">{{ statusLabel(item.status) }}</el-tag>
          </span>
          <span class="item-meta">{{ item.review_date }} · {{ item.stocks.length }} 只股票</span>
          <span class="item-summary">{{ item.body_summary || '暂无正文' }}</span>
        </button>
        <el-empty v-if="!listLoading && !items.length" description="没有符合条件的复盘" :image-size="72" />
      </div>
    </aside>

    <main class="review-workspace">
      <header class="workspace-toolbar">
        <div class="toolbar-left">
          <el-button v-if="isMobile" :icon="Menu" circle title="打开复盘列表" @click="drawerOpen = true" />
          <el-date-picker
            :model-value="activeDate"
            type="date"
            value-format="YYYY-MM-DD"
            :clearable="false"
            :disabled="uploadPending"
            title="选择复盘日期"
            @update:model-value="handleDateChange"
          />
          <span v-if="dirty" class="dirty-indicator">未保存</span>
        </div>
        <div v-if="current" class="toolbar-actions">
          <el-button :icon="MagicStick" title="根据当前草稿生成标题" :loading="generating" @click="generateTitle">生成标题</el-button>
          <el-button type="primary" :disabled="!dirty" :loading="saving" @click="saveReview">保存</el-button>
        </div>
      </header>

      <el-alert v-if="documentError" class="document-alert" :title="documentError" type="error" show-icon :closable="false" />

      <div v-loading="documentLoading" class="document-area">
        <div v-if="current" class="document-form">
          <div class="field-grid">
            <label class="field title-field">
              <span>标题</span>
              <el-input :model-value="current.title" maxlength="80" show-word-limit @update:model-value="updateTitle" />
            </label>
            <label class="field status-field">
              <span>状态</span>
              <el-select v-model="current.status">
                <el-option label="草稿" value="draft" />
                <el-option label="待跟进" value="follow_up" />
                <el-option label="已完成" value="completed" />
              </el-select>
            </label>
          </div>

          <label class="field">
            <span>标签</span>
            <el-select v-model="current.tags" multiple filterable allow-create default-first-option placeholder="输入后回车添加标签" />
          </label>

          <div class="field stocks-field">
            <span>股票</span>
            <div class="stock-tags">
              <el-tag v-for="stock in current.stocks" :key="stock.code" effect="plain">
                {{ stock.name || stock.code }} {{ stock.code }}
              </el-tag>
              <span v-if="!current.stocks.length" class="muted">暂未关联股票</span>
            </div>
          </div>

          <el-tabs v-model="activeTab" class="editor-tabs">
            <el-tab-pane label="编辑" name="edit">
              <div class="editor-toolbar">
                <ReviewAttachmentUploader
                  :review-date="current.review_date"
                  :document-identity="documentIdentity"
                  :insert-markdown="insertMarkdown"
                  @pending-change="uploadPending = $event"
                />
                <span class="source-label">标题来源：{{ current.title_source }}</span>
              </div>
              <el-input
                ref="editorRef"
                v-model="current.body"
                class="body-editor"
                type="textarea"
                resize="none"
                placeholder="记录市场判断、交易依据与后续计划…"
                @click="syncSelection"
                @keyup="syncSelection"
                @select="syncSelection"
                @input="syncSelection"
              />
            </el-tab-pane>
            <el-tab-pane label="预览" name="preview">
              <article v-if="previewHtml" class="markdown-preview" v-html="previewHtml" />
              <el-empty v-else description="暂无可预览内容" :image-size="72" />
            </el-tab-pane>
          </el-tabs>
        </div>

        <el-empty v-else-if="!documentLoading" description="该日期还没有复盘" :image-size="96">
          <el-button type="primary" :icon="Collection" :loading="creating" @click="createActiveReview">创建 {{ activeDate }} 复盘</el-button>
        </el-empty>
      </div>
    </main>
  </section>
</template>

<style scoped>
.review-library {
  position: relative;
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  height: 100%;
  min-width: 0;
  color: var(--text-primary);
  background: var(--bg-primary);
  overflow: hidden;
}

.review-list-pane {
  min-width: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-color);
  background: var(--bg-secondary);
  z-index: 4;
}

.list-header,
.workspace-toolbar {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
}

.list-header > div {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.list-header h1 {
  font-size: 17px;
  line-height: 1.2;
}

.list-header span,
.muted,
.source-label {
  color: var(--text-secondary);
  font-size: 12px;
}

.filters {
  display: grid;
  gap: 8px;
  padding: 10px;
  border-bottom: 1px solid var(--border-color);
}

.filters :deep(.el-date-editor),
.filters :deep(.el-select) {
  width: 100%;
}

.quick-filters {
  display: flex;
  gap: 6px;
}

.quick-filters .el-button + .el-button {
  margin-left: 0;
}

.review-list {
  flex: 1;
  min-height: 120px;
  overflow: auto;
}

.review-list-item {
  width: 100%;
  display: grid;
  gap: 5px;
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px solid var(--border-color);
  color: inherit;
  text-align: left;
  background: transparent;
  cursor: pointer;
}

.review-list-item:hover,
.review-list-item.active {
  background: var(--bg-tertiary);
}

.review-list-item.active {
  box-shadow: 3px 0 0 var(--text-accent) inset;
}

.item-topline {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.item-topline strong,
.item-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-topline strong {
  font-size: 14px;
}

.item-meta,
.item-summary {
  color: var(--text-secondary);
  font-size: 12px;
}

.review-workspace {
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.workspace-toolbar {
  background: var(--bg-secondary);
}

.toolbar-left,
.toolbar-actions {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.dirty-indicator {
  color: #e6a23c;
  font-size: 12px;
  white-space: nowrap;
}

.document-alert {
  margin: 10px 12px 0;
  width: auto;
}

.document-area {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.document-form {
  width: min(1040px, 100%);
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0 auto;
  padding: 16px 20px 20px;
}

.field-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px;
  gap: 12px;
}

.field {
  min-width: 0;
  display: grid;
  gap: 5px;
  color: var(--text-secondary);
  font-size: 12px;
}

.field :deep(.el-select),
.field :deep(.el-input) {
  width: 100%;
}

.stock-tags {
  min-height: 32px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.editor-tabs {
  flex: 1;
  min-height: 420px;
  display: flex;
  flex-direction: column;
}

.editor-tabs :deep(.el-tabs__content),
.editor-tabs :deep(.el-tab-pane) {
  flex: 1;
  min-height: 0;
}

.editor-tabs :deep(.el-tab-pane) {
  height: 100%;
}

.editor-toolbar {
  min-height: 38px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.body-editor {
  height: calc(100% - 46px);
  min-height: 330px;
}

.body-editor :deep(.el-textarea__inner) {
  height: 100%;
  min-height: 330px !important;
  padding: 12px 14px;
  border-radius: 4px;
  color: var(--text-primary);
  background: var(--bg-secondary);
  box-shadow: 0 0 0 1px var(--border-color) inset;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  line-height: 1.65;
}

.markdown-preview {
  min-height: 330px;
  padding: 16px 18px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  background: var(--bg-secondary);
  line-height: 1.75;
  overflow-wrap: anywhere;
}

.markdown-preview :deep(h1),
.markdown-preview :deep(h2),
.markdown-preview :deep(h3) {
  margin: 18px 0 8px;
  letter-spacing: 0;
}

.markdown-preview :deep(p),
.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  margin: 8px 0;
}

.markdown-preview :deep(img) {
  max-width: 100%;
  height: auto;
  border: 1px solid var(--border-color);
  border-radius: 4px;
}

.drawer-backdrop {
  display: none;
}

@media (max-width: 899px) {
  .review-library {
    display: block;
  }

  .review-list-pane {
    position: absolute;
    inset: 0 auto 0 0;
    width: min(320px, 88vw);
    transform: translateX(-102%);
    transition: transform 0.2s ease;
    box-shadow: 8px 0 20px rgb(0 0 0 / 35%);
  }

  .review-list-pane.open {
    transform: translateX(0);
  }

  .drawer-backdrop {
    position: absolute;
    inset: 0;
    z-index: 3;
    display: block;
    border: 0;
    background: rgb(0 0 0 / 45%);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease;
  }

  .drawer-backdrop.visible {
    opacity: 1;
    pointer-events: auto;
  }

  .review-workspace {
    height: 100%;
  }

  .workspace-toolbar,
  .document-form {
    padding-left: 10px;
    padding-right: 10px;
  }

  .workspace-toolbar {
    align-items: stretch;
    flex-wrap: wrap;
  }

  .toolbar-left,
  .toolbar-actions {
    max-width: 100%;
  }

  .toolbar-actions {
    margin-left: auto;
  }

  .field-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .editor-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
}

@media (max-width: 540px) {
  .toolbar-left {
    width: 100%;
  }

  .toolbar-left :deep(.el-date-editor) {
    flex: 1;
    min-width: 0;
  }

  .toolbar-actions {
    width: 100%;
  }

  .toolbar-actions .el-button {
    flex: 1;
    min-width: 0;
    margin-left: 0;
  }
}
</style>
