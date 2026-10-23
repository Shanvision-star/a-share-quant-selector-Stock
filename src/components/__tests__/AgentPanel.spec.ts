import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useStockStore } from '@/stores/stock'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentPanel from '../AgentPanel.vue'

const api = vi.hoisted(() => ({
  getAgentCapabilities: vi.fn(), listAgentRuns: vi.fn(), getAgentRun: vi.fn(),
  startAgentRun: vi.fn(), cancelAgentRun: vi.fn(), saveAgentReview: vi.fn(),
  getDailyAgentStatus: vi.fn(),
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
  beforeEach(() => { vi.resetAllMocks(); api.getDailyAgentStatus.mockResolvedValue({data:{status:'not_run',targets:{}}}); localStorage.clear(); setActivePinia(createPinia()); useStockStore().currentCode = '000001' })

  it('submits Codex explicitly for the selected stock and shows the real provider mode', async () => {
    const report = {...run('codex', '解释策略'), model:'configured-codex', input:{...run('x','').input,mode:'codex'}}
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false,codex_available:true,codex_model:'configured-codex'}})
    api.listAgentRuns.mockResolvedValue({data:{items:[]}})
    api.startAgentRun.mockResolvedValue({data:report})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true}})
    await flushPromises()
    wrapper.findAllComponents({name:'ElSelect'})[1]!.vm.$emit('update:modelValue', 'codex')
    await wrapper.get('textarea').setValue('解释策略')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.startAgentRun).toHaveBeenCalledWith(expect.objectContaining({code:'000001',mode:'codex'}))
    expect(wrapper.get('.run-mode').text()).toContain('Codex · configured-codex')
    expect(wrapper.get('[aria-label="运行历史"]').text()).toBe('历史')
    expect(localStorage.getItem('quant-agent-mode')).toBe('codex')
    wrapper.unmount()
  })

  it('restores an explicit Codex mode without starting a paid call', async () => {
    localStorage.setItem('quant-agent-mode','codex')
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false,codex_available:true}})
    api.listAgentRuns.mockResolvedValue({data:{items:[]}})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true}})
    await flushPromises()
    expect(wrapper.findAllComponents({name:'ElSelect'})[1]!.props('modelValue')).toBe('codex')
    expect(api.startAgentRun).not.toHaveBeenCalled()
    expect(wrapper.get('[aria-label="Codex 分析"]').text()).toBe('Codex 分析')
    wrapper.unmount()
  })

  it('blocks unavailable Codex with visible feedback', async () => {
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:true,codex_available:false}})
    api.listAgentRuns.mockResolvedValue({data:{items:[]}})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true}})
    await flushPromises()
    wrapper.findAllComponents({name:'ElSelect'})[1]!.vm.$emit('update:modelValue', 'codex')
    await wrapper.get('textarea').setValue('解释策略')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.startAgentRun).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('安装并登录')
    wrapper.unmount()
  })

  it('opens the daily report for its own stock and exposes failure details', async () => {
    const dailyRun = {...run('daily', '日线研究'), input:{...run('daily','').input, task:'market', code:'000717', trade_date:'2026-10-23'}}
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:true}})
    api.listAgentRuns.mockResolvedValue({data:{items:[]}})
    api.getAgentRun.mockResolvedValue({data:dailyRun})
    api.getDailyAgentStatus.mockResolvedValue({data:{status:'failed',target_date:'2026-10-23',error:'观察刷新暂不可达',targets:{'000717':{name:'中南股份',run_id:'daily'}}}})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true}})
    await flushPromises()
    expect(wrapper.get('[aria-label="每日任务"]').text()).toContain('未完成')
    expect(wrapper.get('.daily-status [role="alert"]').text()).toContain('观察刷新暂不可达')
    await wrapper.get('[aria-label="查看 000717 每日分析"]').trigger('click')
    await flushPromises()
    expect(wrapper.attributes('data-run-id')).toBe('daily')
    expect(wrapper.get('.report-context').text()).toContain('000717')
    expect(api.startAgentRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })

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

  it('opens safe configuration guidance instead of strategy settings and blocks unconfigured model runs', async () => {
    api.getAgentCapabilities.mockResolvedValue({data:{model_ready:false}})
    api.listAgentRuns.mockResolvedValue({data:{items:[]}})
    const wrapper = shallowMount(AgentPanel, {global:{plugins:[ElementPlus],renderStubDefaultSlot:true,stubs:{ElDialog:{props:['modelValue'],template:'<div v-if="modelValue"><slot/><slot name="footer"/></div>'}}}})
    await flushPromises()
    wrapper.findAllComponents({name:'ElSelect'})[1]!.vm.$emit('update:modelValue', 'model')
    await flushPromises()
    expect(wrapper.text()).not.toContain('打开设置')
    expect(wrapper.find('.model-help').exists()).toBe(false)
    await wrapper.findAll('el-button-stub').find(button => button.text() === '配置方式')!.trigger('click')
    expect(navigation.push).not.toHaveBeenCalled()
    const help = wrapper.get('.model-help').text()
    expect(help).toContain('工作台 → 打开数据目录')
    expect(help).toContain('config/llm.yaml')
    expect(help).toContain('保存后重启应用')
    expect(help).toContain('复制 Codex MCP 配置')
    expect(help).toContain('无需此 DeepSeek 密钥')
    expect(wrapper.get('pre').text()).toContain('api_key: "<填写你的 DeepSeek API Key>"')
    await wrapper.get('textarea').setValue('研究当前股票')
    const submit = wrapper.findAllComponents({name:'ElButton'}).find(button => button.attributes('aria-label') === '运行 Agent')!
    expect(submit.props('disabled')).toBe(true)
    await wrapper.get('form').trigger('submit')
    expect(api.startAgentRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })

})
