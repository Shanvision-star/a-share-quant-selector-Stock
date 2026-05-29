<script setup lang="ts">
// 任务 B：战法文档浏览页
// - 左侧按 category 分组列出白名单文档，支持模糊搜索
// - 右侧通过 markdown-it 渲染 + DOMPurify 净化输出，禁用 HTML 透传，防 XSS
// - localStorage 记录最近 5 个浏览过的 slug，便于快速回到上次查看的文档
import { computed, onMounted, ref, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { getStrategyDocs, getStrategyDoc, type StrategyDocItem, type StrategyDocDetail } from '@/api'

const RECENT_KEY = 'strategy_docs_recent_v1'
const RECENT_MAX = 5

// markdown-it 配置：禁用 raw HTML，启用 linkify/typographer，避免任何用户内容意外渲染脚本
const md = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: true })

const allDocs = ref<StrategyDocItem[]>([])
const categories = ref<string[]>([])
const search = ref('')
const loadingList = ref(false)
const loadingDoc = ref(false)
const currentSlug = ref('')
const currentDoc = ref<StrategyDocDetail | null>(null)
const recentSlugs = ref<string[]>([])
const contentRef = ref<HTMLDivElement | null>(null)

const filteredDocs = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return allDocs.value
  return allDocs.value.filter(item =>
    item.title.toLowerCase().includes(q) || item.slug.toLowerCase().includes(q),
  )
})

const docsByCategory = computed(() => {
  const map = new Map<string, StrategyDocItem[]>()
  for (const doc of filteredDocs.value) {
    if (!map.has(doc.category)) map.set(doc.category, [])
    map.get(doc.category)!.push(doc)
  }
  return Array.from(map.entries()).map(([cat, items]) => ({ category: cat, items }))
})

const recentDocs = computed(() => {
  const byId = new Map(allDocs.value.map(d => [d.slug, d]))
  return recentSlugs.value
    .map(slug => byId.get(slug))
    .filter((item): item is StrategyDocItem => Boolean(item))
})

const renderedHtml = computed(() => {
  if (!currentDoc.value) return ''
  const rawHtml = md.render(currentDoc.value.content || '')
  // 任务 B：DOMPurify 二次净化，移除任何潜在脚本/事件属性
  return DOMPurify.sanitize(rawHtml, { USE_PROFILES: { html: true } })
})

function loadRecentFromStorage() {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return
    const arr = JSON.parse(raw)
    if (Array.isArray(arr)) recentSlugs.value = arr.filter(x => typeof x === 'string').slice(0, RECENT_MAX)
  } catch {
    recentSlugs.value = []
  }
}

function rememberRecent(slug: string) {
  const next = [slug, ...recentSlugs.value.filter(s => s !== slug)].slice(0, RECENT_MAX)
  recentSlugs.value = next
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    // 存储失败不影响主功能，忽略
  }
}

async function loadList() {
  loadingList.value = true
  try {
    const { data } = await getStrategyDocs()
    allDocs.value = data?.items ?? []
    categories.value = data?.categories ?? []
    if (!currentSlug.value && allDocs.value.length > 0) {
      const first = recentSlugs.value.find(s => allDocs.value.some(d => d.slug === s)) || allDocs.value[0].slug
      void selectDoc(first)
    }
  } catch (err: any) {
    ElMessage.error(`战法文档列表加载失败：${err?.message || err}`)
  } finally {
    loadingList.value = false
  }
}

async function selectDoc(slug: string) {
  if (!slug || slug === currentSlug.value) return
  currentSlug.value = slug
  loadingDoc.value = true
  try {
    const { data } = await getStrategyDoc(slug)
    currentDoc.value = data
    rememberRecent(slug)
    await nextTick()
    contentRef.value?.scrollTo({ top: 0, behavior: 'auto' })
  } catch (err: any) {
    currentDoc.value = null
    ElMessage.error(`文档加载失败：${err?.message || err}`)
  } finally {
    loadingDoc.value = false
  }
}

function scrollToTop() {
  contentRef.value?.scrollTo({ top: 0, behavior: 'smooth' })
}

onMounted(() => {
  loadRecentFromStorage()
  void loadList()
})

watch(search, () => {
  // 搜索为空时不动当前选中文档；有结果时保持当前；无匹配时不自动跳转，避免抖动
})
</script>

<template>
  <div class="strategy-docs-view">
    <aside class="docs-sidebar">
      <div class="sidebar-search">
        <el-input v-model="search" placeholder="搜索文档标题或 slug" clearable size="small" />
      </div>
      <div v-if="recentDocs.length" class="sidebar-section">
        <div class="sidebar-section-title">最近浏览</div>
        <div
          v-for="doc in recentDocs"
          :key="`recent-${doc.slug}`"
          :class="['doc-item', { active: doc.slug === currentSlug }]"
          @click="selectDoc(doc.slug)"
        >
          {{ doc.title }}
        </div>
      </div>
      <div v-loading="loadingList" class="sidebar-section sidebar-list">
        <template v-for="group in docsByCategory" :key="group.category">
          <div class="sidebar-section-title">{{ group.category }}</div>
          <div
            v-for="doc in group.items"
            :key="doc.slug"
            :class="['doc-item', { active: doc.slug === currentSlug }]"
            @click="selectDoc(doc.slug)"
            :title="doc.slug"
          >
            {{ doc.title }}
          </div>
        </template>
        <div v-if="!loadingList && filteredDocs.length === 0" class="empty-hint">无匹配文档</div>
      </div>
    </aside>
    <main class="docs-main" v-loading="loadingDoc">
      <div v-if="currentDoc" class="docs-header">
        <h1>{{ currentDoc.title }}</h1>
        <div class="meta">
          <span class="meta-item">分类：{{ currentDoc.category }}</span>
          <span v-if="currentDoc.updated_at" class="meta-item">更新：{{ currentDoc.updated_at }}</span>
          <span class="meta-item">slug：{{ currentDoc.slug }}</span>
        </div>
      </div>
      <div ref="contentRef" class="docs-content markdown-body" v-html="renderedHtml"></div>
      <el-button v-if="currentDoc" class="back-to-top" type="primary" circle size="small" @click="scrollToTop">↑</el-button>
      <div v-if="!currentDoc && !loadingDoc" class="empty-hint">请选择左侧文档</div>
    </main>
  </div>
</template>

<style scoped>
.strategy-docs-view {
  display: flex;
  height: 100%;
  min-height: 0;
  background: #fff;
}
.docs-sidebar {
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  background: #fafbfc;
}
.sidebar-search {
  padding: 10px;
  border-bottom: 1px solid #ebeef5;
}
.sidebar-section {
  padding: 6px 0;
}
.sidebar-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.sidebar-section-title {
  padding: 6px 12px 4px;
  font-size: 12px;
  color: #909399;
  letter-spacing: 0.5px;
}
.doc-item {
  padding: 6px 14px;
  font-size: 13px;
  color: #303133;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}
.doc-item:hover {
  background: #f0f2f5;
}
.doc-item.active {
  background: #ecf5ff;
  border-left-color: #409eff;
  color: #1d6fde;
  font-weight: 600;
}
.docs-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}
.docs-header {
  padding: 16px 24px 8px;
  border-bottom: 1px solid #ebeef5;
}
.docs-header h1 {
  margin: 0 0 6px;
  font-size: 20px;
  color: #303133;
}
.docs-header .meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: #909399;
}
.docs-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 16px 28px 48px;
  line-height: 1.7;
  color: #303133;
}
.docs-content :deep(h1),
.docs-content :deep(h2),
.docs-content :deep(h3) {
  margin-top: 1.4em;
  margin-bottom: 0.6em;
  color: #1f2d3d;
}
.docs-content :deep(pre) {
  background: #f6f8fa;
  padding: 10px 12px;
  border-radius: 4px;
  overflow: auto;
}
.docs-content :deep(code) {
  background: rgba(27,31,35,0.05);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.92em;
}
.docs-content :deep(table) {
  border-collapse: collapse;
  margin: 1em 0;
}
.docs-content :deep(th),
.docs-content :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
}
.docs-content :deep(blockquote) {
  border-left: 4px solid #d0d7de;
  margin: 1em 0;
  padding: 0.4em 1em;
  color: #57606a;
  background: #f6f8fa;
}
.back-to-top {
  position: absolute;
  right: 24px;
  bottom: 24px;
  opacity: 0.85;
}
.empty-hint {
  padding: 16px;
  color: #909399;
  font-size: 13px;
  text-align: center;
}
</style>
