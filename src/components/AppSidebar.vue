<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { House, Refresh, Setting, DataAnalysis, List, Star, Aim } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const isCollapsed = ref(false)
const activeIndex = computed(() => route.path)

function navigate(path: string) {
  router.push(path)
}
</script>

<template>
  <div class="sidebar" :class="{ collapsed: isCollapsed }">
    <div class="sidebar-header">
      <span v-if="!isCollapsed" class="sidebar-title">A-share Quant</span>
      <span v-else class="sidebar-title-short">AQ</span>
    </div>
    <el-menu
      :default-active="activeIndex"
      :collapse="isCollapsed"
      @select="navigate"
      class="sidebar-menu"
    >
      <el-menu-item index="/">
        <el-icon><House /></el-icon>
        <template #title>首页总览</template>
      </el-menu-item>
      <el-menu-item index="/strategy-results">
        <el-icon><List /></el-icon>
        <template #title>策略结果</template>
      </el-menu-item>
      <el-menu-item index="/manual-pool">
        <el-icon><Star /></el-icon>
        <template #title>人工选股池</template>
      </el-menu-item>
      <el-menu-item index="/update">
        <el-icon><Refresh /></el-icon>
        <template #title>数据更新</template>
      </el-menu-item>
      <el-menu-item index="/settings">
        <el-icon><Setting /></el-icon>
        <template #title>参数设置</template>
      </el-menu-item>
      <el-menu-item index="/backtest">
        <el-icon><DataAnalysis /></el-icon>
        <template #title>回测</template>
      </el-menu-item>
      <el-menu-item index="/tracking">
        <el-icon><Aim /></el-icon>
        <template #title>跟踪运营</template>
      </el-menu-item>
    </el-menu>
    <div class="sidebar-toggle" @click="isCollapsed = !isCollapsed">
      <span>{{ isCollapsed ? '>>' : '<<' }}</span>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 200px;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background-color: var(--bg-secondary);
  border-right: 1px solid var(--border-color);
  transition: width 0.3s;
}
.sidebar.collapsed {
  width: 64px;
}
.sidebar-header {
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid var(--border-color);
  color: var(--text-primary);
  font-size: 16px;
  font-weight: bold;
}
.sidebar-title-short {
  font-size: 18px;
}
.sidebar-menu {
  flex: 1;
  border-right: none !important;
}
.sidebar-toggle {
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-secondary);
  border-top: 1px solid var(--border-color);
}
.sidebar-toggle:hover {
  color: var(--text-primary);
  background-color: var(--bg-tertiary);
}
</style>
