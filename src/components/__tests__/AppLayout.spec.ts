import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import AppLayout from '../AppLayout.vue'

vi.mock('@/stores/updateJob', () => ({useUpdateJobStore: () => ({isRunning:false,jobCompleted:false,jobError:'',bannerCollapsed:false})}))
vi.mock('vue-router', () => ({useRoute: () => ({path:'/',params:{}})}))

describe('Agent keyboard focus', () => {
  it('returns focus to its trigger after closing the panel', async () => {
    const wrapper = mount(AppLayout, {attachTo:document.body,global:{stubs:{AppSidebar:true,GlobalJobBanner:true,RouterLink:true,RouterView:true,AgentPanel:{template:'<aside><button @click="$emit(\'close\')">关闭</button></aside>'}}}})
    const toggle = wrapper.get<HTMLButtonElement>('.agent-toggle')
    if (toggle.attributes('aria-expanded') === 'false') await toggle.trigger('click')
    await wrapper.get('aside button').trigger('click')
    await flushPromises()
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(toggle.element)
    wrapper.unmount()
  })
})
