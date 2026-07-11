import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AddToTodayReviewButton from '@/components/AddToTodayReviewButton.vue'

const addStockToReview = vi.hoisted(() => vi.fn())
const routerPush = vi.hoisted(() => vi.fn())
const messageSuccess = vi.hoisted(() => vi.fn())
const messageInfo = vi.hoisted(() => vi.fn())
const messageError = vi.hoisted(() => vi.fn())

vi.mock('@/api/reviews', () => ({ addStockToReview }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: routerPush }) }))
vi.mock('element-plus', () => ({
  ElMessage: {
    success: messageSuccess,
    info: messageInfo,
    error: messageError,
  },
}))

enableAutoUnmount(afterEach)

function mountButton() {
  return mount(AddToTodayReviewButton, {
    props: { code: '600519', name: '贵州茅台' },
    global: {
      stubs: {
        'el-button': {
          template: '<button :disabled="$attrs.disabled" @click="$emit(\'click\')"><slot /></button>',
        },
        'el-icon': true,
      },
    },
  })
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

describe('AddToTodayReviewButton', () => {
  afterEach(() => {
    vi.useRealTimers()
    addStockToReview.mockReset()
    routerPush.mockReset()
    messageSuccess.mockReset()
    messageInfo.mockReset()
    messageError.mockReset()
  })

  it('uses the Asia/Shanghai date and confirms a newly added stock', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T16:30:00Z'))
    addStockToReview.mockResolvedValue({ data: { data: { already_exists: false } } })
    const wrapper = mountButton()

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(addStockToReview).toHaveBeenCalledWith('2026-01-02', {
      code: '600519',
      name: '贵州茅台',
    })
    expect(messageSuccess).toHaveBeenCalledWith('已加入今日复盘')
    expect(wrapper.find('.review-feedback').exists()).toBe(false)
  })

  it('reports when the stock already exists in today\'s review', async () => {
    addStockToReview.mockResolvedValue({ data: { data: { already_exists: true } } })
    const wrapper = mountButton()

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(messageInfo).toHaveBeenCalledWith('今日复盘中已存在')
    expect(wrapper.find('.review-feedback').exists()).toBe(false)
  })

  it('keeps the failure visible', async () => {
    addStockToReview.mockRejectedValue(new Error('网络不可用'))
    const wrapper = mountButton()

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(messageError).toHaveBeenCalledWith('加入今日复盘失败：网络不可用')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="open-review"]').exists()).toBe(true)
  })

  it('opens today\'s review directly', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-11T01:00:00+08:00'))
    addStockToReview.mockResolvedValue({ data: { data: { already_exists: false } } })
    const wrapper = mountButton()

    await wrapper.get('button').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="open-review"]').trigger('click')

    expect(routerPush).toHaveBeenCalledWith({
      name: 'ReviewLibrary',
      query: { date: '2026-07-11' },
    })
  })

  it('drops a deferred response after the stock props switch', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-11T01:00:00+08:00'))
    const first = deferred<any>()
    addStockToReview
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ data: { data: { already_exists: false } } })
    const wrapper = mountButton()

    await wrapper.get('button').trigger('click')
    await wrapper.setProps({ code: '000001', name: '平安银行' })
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(addStockToReview).toHaveBeenNthCalledWith(2, '2026-07-11', {
      code: '000001',
      name: '平安银行',
    })
    expect(messageSuccess).toHaveBeenCalledTimes(1)

    first.resolve({ data: { data: { already_exists: false } } })
    await flushPromises()

    expect(messageSuccess).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.review-feedback').exists()).toBe(false)
  })

  it.each([
    ['success', { already_exists: false }, messageSuccess, '已加入今日复盘'],
    ['already exists', { already_exists: true }, messageInfo, '今日复盘中已存在'],
  ] as const)('keeps deferred %s feedback after the stock name updates', async (_, result, message, text) => {
    const request = deferred<any>()
    addStockToReview.mockReturnValue(request.promise)
    const wrapper = mountButton()

    await wrapper.get('button').trigger('click')
    await wrapper.setProps({ name: '贵州茅台（更新）' })

    request.resolve({ data: { data: result } })
    await flushPromises()

    expect(message).toHaveBeenCalledWith(text)
  })

  it('keeps deferred failure feedback after the stock name updates', async () => {
    const request = deferred<any>()
    addStockToReview.mockReturnValue(request.promise)
    const wrapper = mountButton()

    await wrapper.get('button').trigger('click')
    await wrapper.setProps({ name: '贵州茅台（更新）' })

    request.reject(new Error('网络不可用'))
    await flushPromises()

    expect(messageError).toHaveBeenCalledWith('加入今日复盘失败：网络不可用')
  })
})
