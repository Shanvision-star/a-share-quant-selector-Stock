<script setup lang="ts">
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  House,
  Refresh,
  Setting,
  DataAnalysis,
  List,
  Star,
  Aim,
  Document,
  Notebook,
  Monitor,
  Fold,
  Expand,
} from '@element-plus/icons-vue'
const route = useRoute()
const collapsed = ref(false)
const items = [
  { path: '/', label: '工作台', icon: House },
  { path: '/strategy-results', label: '策略结果', icon: List },
  { path: '/manual-pool', label: '选股池', icon: Star },
  { path: '/tracking', label: '跟踪', icon: Aim },
  { path: '/backtest', label: '回测', icon: DataAnalysis },
  { path: '/review-library', label: '复盘', icon: Notebook },
  { path: '/zettaranc', label: 'Zettaranc', icon: DataAnalysis },
  { path: '/strategy-docs', label: '战法文档', icon: Document },
]
const utilities = [
  { path: '/update', label: '数据更新', icon: Refresh },
  { path: '/status', label: '系统状态', icon: Monitor },
  { path: '/settings', label: '设置', icon: Setting },
]
</script>
<template>
  <nav class="sidebar" :class="{ collapsed }" aria-label="主导航">
    <RouterLink to="/" class="brand" aria-label="A-share Quant 工作台"
      ><span class="brand-mark" aria-hidden="true">a<span>•</span></span
      ><span class="brand-name">A-share<span>Quant</span></span></RouterLink
    >
    <div class="nav-primary">
      <RouterLink
        v-for="item in items"
        :key="item.path"
        :to="item.path"
        :class="{ selected: route.path === item.path }"
        :aria-label="item.label"
        :title="collapsed ? item.label : undefined"
        ><el-icon><component :is="item.icon" /></el-icon
        ><span>{{ item.label }}</span
        ><i class="nav-dot" v-if="route.path === item.path" aria-hidden="true"
      /></RouterLink>
    </div>
    <div class="nav-utilities">
      <RouterLink
        v-for="item in utilities"
        :key="item.path"
        :to="item.path"
        :class="{ selected: route.path === item.path }"
        :aria-label="item.label"
        :title="collapsed ? item.label : undefined"
        ><el-icon><component :is="item.icon" /></el-icon
        ><span>{{ item.label }}</span></RouterLink
      >
    </div>
    <button
      class="sidebar-toggle"
      :aria-label="collapsed ? '展开导航' : '收起导航'"
      :aria-expanded="!collapsed"
      @click="collapsed = !collapsed"
    >
      <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon
      ><span v-if="!collapsed">收起</span>
    </button>
  </nav>
</template>
<style scoped>
.sidebar {
  width: 204px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 26px 14px 14px;
  background: rgba(244, 246, 250, 0.76);
  backdrop-filter: blur(32px);
  border-right: 1px solid #e5e9ef;
  transition: width 0.22s ease;
  overflow-y: auto;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: #1d2636;
  padding: 0 13px 36px;
  white-space: nowrap;
}
.brand-mark {
  font-size: 36px;
  letter-spacing: -4px;
  font-weight: 750;
  line-height: 1;
}
.brand-mark > span {
  color: #4c88f1;
}
.brand-name {
  font-size: 14px;
  font-weight: 650;
  line-height: 1.35;
  letter-spacing: -0.2px;
}
.brand-name > span {
  display: block;
  font-size: 11px;
  color: #8390a3;
  font-weight: 500;
  letter-spacing: 1.4px;
}
.nav-primary,
.nav-utilities {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.sidebar a:not(.brand) {
  display: flex;
  gap: 11px;
  align-items: center;
  border-radius: 10px;
  padding: 12px;
  color: #687487;
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  position: relative;
  white-space: nowrap;
  transition:
    background 0.18s,
    color 0.18s;
}
.sidebar a:not(.brand):hover {
  background: #e9edf4;
  color: #243550;
}
.sidebar a.selected {
  background: white;
  color: #286ad4;
  box-shadow: 0 3px 12px #304c7010;
  border: 1px solid #e5eaf3;
  padding: 11px;
}
.sidebar .el-icon {
  font-size: 18px;
  flex-shrink: 0;
}
.selected .nav-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #4c88f1;
  margin-left: auto;
}
.nav-utilities {
  margin-top: auto;
  padding-top: 30px;
}
.sidebar-toggle {
  border: 0;
  background: transparent;
  color: #8490a0;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 20px 12px 4px;
  cursor: pointer;
  font: inherit;
  font-size: 11px;
}
.collapsed {
  width: 70px;
  padding-inline: 10px;
}
.collapsed .brand {
  padding-inline: 4px;
}
.collapsed .brand-name,
.collapsed a:not(.brand) > span,
.collapsed .selected .nav-dot {
  display: none;
}
.collapsed a:not(.brand) {
  justify-content: center;
}
.collapsed .sidebar-toggle {
  justify-content: center;
}
.collapsed .brand-mark {
  font-size: 30px;
}
@media (max-width: 800px) {
  .sidebar {
    width: 66px;
    padding-inline: 8px;
  }
  .brand {
    padding-inline: 5px;
  }
  .brand-name,
  .sidebar a:not(.brand) > span,
  .selected .nav-dot,
  .sidebar-toggle {
    display: none;
  }
  .sidebar a:not(.brand) {
    justify-content: center;
  }
  .brand-mark {
    font-size: 30px;
  }
  .nav-utilities {
    padding-top: 16px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .sidebar,
  .sidebar a {
    transition: none;
  }
}
</style>
