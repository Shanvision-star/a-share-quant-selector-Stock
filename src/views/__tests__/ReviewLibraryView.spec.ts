import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReviewListItem, ReviewListWarning } from '@/api/reviews'
import ReviewLibraryView from '@/views/ReviewLibraryView.vue'

const listReviews = vi.hoisted(() => vi.fn())
const routerReplace = vi.hoisted(() => vi.fn())

vi.mock('@/api/reviews', () => ({
  createReview: vi.fn(),
  generateReviewTitle: vi.fn(),
  getReview: vi.fn(),
  listReviews,
  updateReview: vi.fn(),
}))
vi.mock('vue-router', () => ({
  onBeforeRouteLeave: vi.fn(),
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: routerReplace }),
}))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn() },
}))

enableAutoUnmount(afterEach)

function item(reviewDate: string, title: string): ReviewListItem {
  return {
    review_date: reviewDate,
    title,
    status: 'draft',
    tags: [],
    stocks: [],
    updated_at: `${reviewDate}T09:30:00+08:00`,
    body_summary: `${title}摘要`,
    first_attachment_url: null,
    version: 'v1',
  }
}

function response(
  items: ReviewListItem[],
  total = items.length,
  offset = 0,
  warnings: ReviewListWarning[] = [],
) {
  return Promise.resolve({ data: { data: { items, total, limit: 100, offset, warnings } } })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function mountView() {
  return mount(ReviewLibraryView, {
    global: {
      directives: { loading: () => undefined },
      stubs: {
        ReviewAttachmentUploader: true,
        'el-alert': { props: ['title'], template: '<div role="alert">{{ title }}</div>' },
        'el-button': {
          props: ['loading'],
          emits: ['click'],
          template: '<button :data-loading="String(Boolean(loading))" @click="$emit(\'click\')"><slot /></button>',
        },
        'el-date-picker': true,
        'el-empty': { props: ['description'], template: '<div>{{ description }}<slot /></div>' },
        'el-icon': { template: '<span><slot /></span>' },
        'el-input': {
          props: ['modelValue'],
          emits: ['update:modelValue', 'keyup'],
          template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup="$emit(\'keyup\', $event)">',
        },
        'el-option': true,
        'el-select': true,
        'el-tab-pane': { template: '<div><slot /></div>' },
        'el-tabs': { template: '<div><slot /></div>' },
        'el-tag': { template: '<span><slot /></span>' },
      },
    },
  })
}

async function search(wrapper: ReturnType<typeof mountView>, query: string) {
  const input = wrapper.get('.filters input')
  await input.setValue(query)
  await input.trigger('keyup', { key: 'Enter' })
}

describe('ReviewLibraryView list lifecycle', () => {
  afterEach(() => {
    listReviews.mockReset()
    routerReplace.mockReset()
  })

  it('lets only the latest filter request update list data, loading, and errors', async () => {
    const older = deferred<Awaited<ReturnType<typeof response>>>()
    const latest = deferred<Awaited<ReturnType<typeof response>>>()
    listReviews
      .mockReturnValueOnce(response([]))
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(latest.promise)
    const wrapper = mountView()
    await flushPromises()

    await search(wrapper, '旧筛选')
    await search(wrapper, '新筛选')
    older.reject(new Error('旧请求失败'))
    await flushPromises()

    expect(wrapper.find('.review-list-pane [role="alert"]').exists()).toBe(false)
    expect(wrapper.get('.list-header button').attributes('data-loading')).toBe('true')

    latest.resolve(await response([item('2026-07-12', '最新结果')], 1))
    await flushPromises()

    expect(wrapper.text()).toContain('最新结果')
    expect(wrapper.text()).not.toContain('旧请求失败')
    expect(wrapper.get('.list-header button').attributes('data-loading')).toBe('false')
  })

  it('shows server total and updated time, then appends the next page', async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => (
      item(`2026-03-${String(index + 1).padStart(2, '0')}`, `复盘 ${index + 1}`)
    ))
    firstPage[0].first_attachment_url = '/api/reviews/2026-03-01/attachments/cover.png'
    listReviews
      .mockReturnValueOnce(response(firstPage, 101))
      .mockReturnValueOnce(response([item('2026-02-28', '第 101 篇')], 101, 100))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('101 篇')
    expect(wrapper.text()).toContain('更新 2026-03-01 09:30')
    expect(wrapper.get('.item-thumbnail').attributes('src'))
      .toBe('/api/reviews/2026-03-01/attachments/cover.png')
    const loadMore = wrapper.get('[data-test="load-more"]')
    await loadMore.trigger('click')
    await flushPromises()

    expect(listReviews).toHaveBeenLastCalledWith(expect.objectContaining({ limit: 100, offset: 100 }))
    expect(wrapper.text()).toContain('第 101 篇')
  })

  it('resets pagination and replaces items when filters change', async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => (
      item(`2026-04-${String(index + 1).padStart(2, '0')}`, `旧复盘 ${index + 1}`)
    ))
    listReviews
      .mockReturnValueOnce(response(firstPage, 101))
      .mockReturnValueOnce(response([item('2026-03-31', '旧复盘 101')], 101, 100))
      .mockReturnValueOnce(response([item('2026-07-12', '筛选结果')], 1))
    const wrapper = mountView()
    await flushPromises()
    await wrapper.get('[data-test="load-more"]').trigger('click')
    await flushPromises()

    await search(wrapper, '筛选结果')
    await flushPromises()

    expect(listReviews).toHaveBeenLastCalledWith(expect.objectContaining({ query: '筛选结果', offset: 0 }))
    expect(wrapper.text()).toContain('筛选结果')
    expect(wrapper.text()).not.toContain('旧复盘 101')
  })

  it('shows recoverable corrupt-file warnings with relative paths', async () => {
    listReviews.mockReturnValueOnce(response([], 0, 0, [{
      review_date: '2026-07-11',
      relative_path: '2026/07/2026-07-11.md',
      message: '复盘文件无法解析，请先备份原文件后修复 frontmatter 或 UTF-8 编码',
    }]))

    const wrapper = mountView()
    await flushPromises()

    const alert = wrapper.get('.review-list-pane [role="alert"]')
    expect(alert.text()).toContain('发现 1 篇损坏复盘')
    expect(alert.text()).toContain('2026/07/2026-07-11.md')
    expect(alert.text()).toContain('备份')
    expect(alert.text()).not.toContain('D:\\')
  })
})
