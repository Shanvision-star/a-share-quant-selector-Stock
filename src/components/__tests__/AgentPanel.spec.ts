import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useStockStore } from '@/stores/stock'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentPanel from '../AgentPanel.vue'

const api = vi.hoisted(() => ({
  getAgentCapabilities: vi.fn(), listAgentRuns: vi.fn(), getAgentRun: vi.fn(),
  startAgentRun: vi.fn(), cancelAgentRun: vi.fn(), saveAgentReview: vi.fn(),
}))
vi.mock('@/api/agent', () => api)
const navigation = vi.hoisted(() => ({push: vi.fn()}))
vi.mock('vue-router', () => ({ useRoute: () => ({ path: '/', params: {} }), useRouter: () => navigation }))
const tracking = vi.hoisted(() => ({createTrackingItem:vi.fn()}))
vi.mock('@/api', () => tracking)

const run = (id: string, question: string) => ({
  run_id: id, status: 'completed', input: { question, mode: 'local', task: 'candidates', code:'000001' },
  output: { summary: question, findings: [], next_steps: [], limitations: [] },
  sources: [], events: [], created_at: '2026-10-23T00:00:00Z', error: null,
})

describe('Agent panel request ownership', () => {
  beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); setActivePinia(createPinia()); useStockStore().currentCode = '000001' })

  it('keeps a newly submitted run when initial history finishes later', async () => {
    const older = run('old', '旧任务')
    const newer = run('new', '新任务')
    let releaseCapabilities!: (value: unknown) => void
    api.getAgentCapabilities.mockReturnValue(new Promise(resolve => { releaseCapabilities = resolve }))
    api.listAgentRuns.mockResolvedValue({ data: { items: [older] } })
    api.startAgentRun.mockResolvedValue({ data: newer })
    api.getAgentRun.mockImplementation((id: string) => Promise.resolve({ data: id === 'new' ? newer : older }))
    const wrapper = shallowMount(AgentPanel, { global: { plugins: [ElementPlus] } })
    await wrapper.get('textarea').setValue('新任务')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    releaseCapabilities({ data: { model_ready: false } })
    await flushPromises()
    expect(wrapper.attributes('data-run-id')).toBe('new')
    expect(wrapper.get('.user-question').text()).toBe('新任务')
    expect(api.getAgentRun).not.toHaveBeenCalledWith('old')
    wrapper.unmount()
  })

  it('shows an API failure without presenting a successful report', async () => {
    api.getAgentCapabilities.mockResolvedValue({ data: { model_ready: false } })
    api.listAgentRuns.mockResolvedValue({ data: { items: [] } })
    api.startAgentRun.mockRejectedValue({ response: { data: { detail: 'Agent 队列已满' } } })
    const wrapper = shallowMount(AgentPanel, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    await wrapper.get('textarea').setValue('检查跟踪')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Agent 队列已满')
    expect(wrapper.find('.agent-report').exists()).toBe(false)
    wrapper.unmount()
  })

  it('sends the latest home selection and keeps the old report object explicit', async () => {
    const older = run('old', '检查记录')
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false}})
    api.listAgentRuns.mockResolvedValue({data:{items:[older]}})
    api.getAgentRun.mockResolvedValue({data:older})
    api.startAgentRun.mockResolvedValue({data:older})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true}})
    await flushPromises()
    useStockStore().currentCode = '600519'
    await flushPromises()
    expect(wrapper.get('.context-stock').text()).toBe('600519')
    expect(wrapper.get('.report-context').text()).toContain('000001')
    expect(wrapper.get('.report-context').text()).toContain('历史对象')
    await wrapper.get('textarea').setValue('检查日期')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.startAgentRun).toHaveBeenCalledWith(expect.objectContaining({code:'600519', mode:'local'}))
    wrapper.unmount()
  })

  it('blocks runs without a selected stock', async () => {
    useStockStore().currentCode = ''
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false}})
    api.listAgentRuns.mockResolvedValue({data:{items:[]}})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true}})
    await flushPromises()
    await wrapper.get('textarea').setValue('检查日期')
    await wrapper.get('form').trigger('submit')
    expect(api.startAgentRun).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('选择股票')
    wrapper.unmount()
  })

  it('identifies Codex and its parent, and navigates to the saved review date', async () => {
    const external = {...run('external', 'Codex报告'), input:{...run('x','').input,mode:'external'}, parent_run_id:'parent',saved_review:'2026-10-20'}
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false}})
    api.listAgentRuns.mockResolvedValue({data:{items:[external]}})
    api.getAgentRun.mockResolvedValue({data:external})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true}})
    await flushPromises()
    expect(wrapper.get('.run-mode').text()).toContain('Codex')
    expect(wrapper.get('.evidence').text()).toContain('parent')
    const reviewLink = wrapper.findAll('el-button-stub').find(button => button.text().includes('查看复盘'))!
    await reviewLink.trigger('click')
    expect(navigation.push).toHaveBeenCalledWith({path:'/review-library',query:{date:'2026-10-20'}})
    const trackButton = wrapper.findAll('el-button-stub').find(button => button.text().includes('加入跟踪'))!
    await trackButton.trigger('click')
    expect(tracking.createTrackingItem).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('writes tracking only after confirmation and keeps the report stock when selection changes', async () => {
    const report = run('report', '检查记录')
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false}})
    api.listAgentRuns.mockResolvedValue({data:{items:[report]}})
    api.getAgentRun.mockResolvedValue({data:report})
    tracking.createTrackingItem.mockResolvedValue({data:{success:true}})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true,stubs:{ElDialog:{template:'<div><slot/><slot name="footer"/></div>'}}}})
    await flushPromises()
    await wrapper.findAll('el-button-stub').find(button => button.text().includes('加入跟踪'))!.trigger('click')
    expect(tracking.createTrackingItem).not.toHaveBeenCalled()
    useStockStore().currentCode = '600519'
    await wrapper.get('#agent-signal-date').setValue('2026-10-20')
    await wrapper.findAll('el-button-stub').find(button => button.text() === '确认加入')!.trigger('click')
    await flushPromises()
    expect(tracking.createTrackingItem).toHaveBeenCalledWith(expect.objectContaining({code:'000001',signal_date:'2026-10-20',note:'Agent report'}))
    expect(navigation.push).toHaveBeenCalledWith({path:'/tracking',query:{code:'000001'}})
    await wrapper.get('aside').trigger('keydown', {key:'Escape'})
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })

  it('shows a failed tracking write inside its confirmation dialog', async () => {
    const report = run('report', '检查记录')
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false}})
    api.listAgentRuns.mockResolvedValue({data:{items:[report]}})
    api.getAgentRun.mockResolvedValue({data:report})
    tracking.createTrackingItem.mockRejectedValue({response:{data:{detail:'信号日期不可用'}}})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true,stubs:{ElDialog:{template:'<div class="confirmation"><slot/><slot name="footer"/></div>'}}}})
    await flushPromises()
    await wrapper.findAll('el-button-stub').find(button => button.text().includes('加入跟踪'))!.trigger('click')
    await wrapper.findAll('el-button-stub').find(button => button.text() === '确认加入')!.trigger('click')
    await flushPromises()
    expect(wrapper.get('.confirmation [role="alert"]').text()).toContain('信号日期不可用')
    expect(navigation.push).not.toHaveBeenCalled()
    wrapper.unmount()
  })

})
