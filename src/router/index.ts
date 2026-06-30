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
    path: '/manual-pool',
    name: 'ManualSelectionPool',
    component: () => import('@/views/ManualSelectionPoolView.vue'),
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
    path: '/status',
    name: 'SystemStatus',
    component: () => import('@/views/SystemStatusView.vue'),
  },
  {
    path: '/backtest',
    name: 'Backtest',
    component: () => import('@/views/BacktestView.vue'),
  },
  {
    // P1.5 跟踪运营面板：列表 / 告警 / LLM 建议 / OrderIntent 确认否决
    path: '/tracking',
    name: 'Tracking',
    component: () => import('@/views/TrackingView.vue'),
  },
  {
    // 任务 B：战法文档页面，集中展示策略与系统说明文档
    path: '/strategy-docs',
    name: 'StrategyDocs',
    component: () => import('@/views/StrategyDocsView.vue'),
  },
  {
    // Zettaranc 综合看板：回测结果 / 持仓纪律 / 攻击日候选
    path: '/zettaranc',
    name: 'Zettaranc',
    component: () => import('@/views/ZettarancView.vue'),
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
