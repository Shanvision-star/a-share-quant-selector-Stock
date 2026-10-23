import { flushPromises, shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import HomeView from '../HomeView.vue'
import { useStockStore } from '@/stores/stock'
import { useUpdateJobStore } from '@/stores/updateJob'

const api = vi.hoisted(() => ({
  getStrategyCacheStatus: vi.fn(), getStrategyResults: vi.fn(), getStockList: vi.fn(), getInitStatus: vi.fn(),
  getKline: vi.fn(), getStockPrice: vi.fn(),
}))
vi.mock('@/api', () => api)
vi.mock('vue-router', () => ({useRouter: () => ({push:vi.fn()})}))
vi.mock('@/components/KlineChart.vue', () => ({default:{name:'KlineChart',props:['code','showShortTermTrend','showBullBearLine'],template:'<div />'}}))
vi.mock('@/components/StockTable.vue', () => ({default:{template:'<div />'}}))

describe('Home stock selection ownership', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
    api.getInitStatus.mockResolvedValue({data:{data:{state:'ready'}}})
    api.getStrategyCacheStatus.mockResolvedValue({data:{data:{status:'ready'}}})
    api.getStockList.mockResolvedValue({data:{data:[],total:0}})
  })

  it('keeps a selected non-candidate stock when candidate results refresh', async () => {
    useStockStore().currentCode = '600519'
    api.getStrategyResults.mockResolvedValueOnce({data:{data:{results:[{code:'000001',name:'平安银行'}],total:1}}})
    const wrapper = shallowMount(HomeView, {global:{plugins:[ElementPlus],stubs:{ElButtonGroup:false}}})
    await flushPromises()
    expect(wrapper.getComponent({name:'KlineChart'}).props('code')).toBe('600519')
    expect(wrapper.getComponent({name:'KlineChart'}).props('showShortTermTrend')).toBe(true)
    expect(wrapper.getComponent({name:'KlineChart'}).props('showBullBearLine')).toBe(true)
    api.getStrategyResults.mockResolvedValueOnce({data:{data:{results:[{code:'000002',name:'万科A'}],total:1}}})
    useUpdateJobStore().jobCompleted = true
    await flushPromises()
    expect(wrapper.getComponent({name:'KlineChart'}).props('code')).toBe('600519')
    expect(useStockStore().currentCode).toBe('600519')
    wrapper.unmount()
  })

  it('searches the market, switches outside candidates, and keeps chart toggles', async () => {
    api.getStrategyResults.mockResolvedValue({data:{data:{results:[{code:'000001',name:'平安银行'}],total:1}}})
    const wrapper = shallowMount(HomeView, {global:{plugins:[ElementPlus],stubs:{ElButtonGroup:false}}})
    await flushPromises()
    const select = wrapper.getComponent({name:'ElSelect'})
    expect(select.attributes('aria-label')).toBe('搜索并切换图表股票')
    expect(select.props('filterable')).toBe(true)
    wrapper.findAllComponents({name:'ElCheckbox'})[0]!.vm.$emit('update:modelValue', false)
    api.getStockList.mockResolvedValueOnce({data:{data:[{code:'000717',name:'中南股份'},{code:'000718',name:'苏宁环球'}],total:2}})
    await select.props('remoteMethod')('00071')
    await flushPromises()
    expect(api.getStockList).toHaveBeenLastCalledWith(expect.objectContaining({search:'00071'}), expect.anything())
    select.vm.$emit('update:modelValue', '000717')
    await flushPromises()
    expect(wrapper.getComponent({name:'KlineChart'}).props('code')).toBe('000717')
    expect(wrapper.getComponent({name:'KlineChart'}).props('showShortTermTrend')).toBe(false)
    expect(useStockStore().currentCode).toBe('000717')
    await wrapper.get('[aria-label="下一只股票"]').trigger('click')
    expect(wrapper.getComponent({name:'KlineChart'}).props('code')).toBe('000718')
    await wrapper.get('[aria-label="上一只股票"]').trigger('click')
    expect(wrapper.getComponent({name:'KlineChart'}).props('code')).toBe('000717')
    wrapper.unmount()
  })

  it('keeps search available even without strategy candidates', async () => {
    api.getStrategyResults.mockResolvedValue({data:{data:{results:[],total:0}}})
    const wrapper = shallowMount(HomeView, {global:{plugins:[ElementPlus],stubs:{ElButtonGroup:false}}})
    await flushPromises()
    expect(wrapper.findComponent({name:'ElSelect'}).exists()).toBe(true)
    expect(wrapper.findComponent({name:'KlineChart'}).exists()).toBe(false)
    wrapper.unmount()
  })
})
