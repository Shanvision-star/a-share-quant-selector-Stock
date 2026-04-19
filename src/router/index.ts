import { createRouter, createWebHistory } from 'vue-router'

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

export default createRouter({
  history: createWebHistory(),
  routes,
})
