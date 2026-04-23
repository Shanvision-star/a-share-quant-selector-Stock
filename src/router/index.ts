import { createRouter, createWebHistory } from 'vue-router'
import { useSettingsDraftStore } from '@/stores/settingsDraft'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue'),
  },
  {
    path: '/strategy-results',
    name: 'StrategyResults',
    component: () => import('@/views/StrategyResultsView.vue'),
  },
  {
    path: '/stocks/:code',
    name: 'StockDetail',
    component: () => import('@/views/StockDetail.vue'),
    props: true,
  },
  {
    path: '/update',
    name: 'Update',
    component: () => import('@/views/UpdateView.vue'),
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/SettingsView.vue'),
  },
  {
    path: '/backtest',
    name: 'Backtest',
    component: () => import('@/views/BacktestView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  if (from.name === 'Settings' && to.name !== 'Settings') {
    const draft = useSettingsDraftStore()
    if (draft.isDirty && !window.confirm('参数尚未保存，确认离开吗？')) {
      next(false)
      return
    }
  }
  next()
})

export default router
