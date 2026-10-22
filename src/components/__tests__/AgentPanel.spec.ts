import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentPanel from '../AgentPanel.vue'

const api = vi.hoisted(() => ({
  getAgentCapabilities: vi.fn(), listAgentRuns: vi.fn(), getAgentRun: vi.fn(),
  startAgentRun: vi.fn(), cancelAgentRun: vi.fn(), saveAgentReview: vi.fn(),
}))
vi.mock('@/api/agent', () => api)
vi.mock('vue-router', () => ({ useRoute: () => ({ path: '/', params: {} }), useRouter: () => ({ push: vi.fn() }) }))

const run = (id: string, question: string) => ({
  run_id: id, status: 'completed', input: { question, mode: 'local', task: 'candidates' },
  output: { summary: question, findings: [], next_steps: [], limitations: [] },
  sources: [], events: [], created_at: '2026-10-23T00:00:00Z', error: null,
})

describe('Agent panel request ownership', () => {
  beforeEach(() => { vi.resetAllMocks(); localStorage.clear() })

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
})
