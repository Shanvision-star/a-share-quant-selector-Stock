<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import GlobalJobBanner from './GlobalJobBanner.vue'
import AgentPanel from './AgentPanel.vue'
import { computed, nextTick, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useUpdateJobStore } from '@/stores/updateJob'
const store = useUpdateJobStore()
const route = useRoute()
const agentOpen = ref(window.innerWidth >= 1400)
const bannerVisible = computed(
  () =>
    (store.isRunning || store.jobCompleted || !!store.jobError) &&
    !store.bannerCollapsed,
)
const titles: Record<string, string> = {
  '/': '工作台',
  '/strategy-results': '策略结果',
  '/manual-pool': '选股池',
  '/update': '数据更新',
  '/settings': '设置',
  '/status': '系统状态',
  '/backtest': '回测',
  '/tracking': '跟踪',
  '/review-library': '复盘',
  '/strategy-docs': '战法文档',
  '/zettaranc': 'Zettaranc',
}
const title = computed(
  () =>
    titles[route.path] ||
    (route.path.startsWith('/stocks/') ? String(route.params.code) : '工作台'),
)
async function toggleAgent() {
  agentOpen.value = !agentOpen.value
  await nextTick()
  if (agentOpen.value) document.querySelector<HTMLTextAreaElement>('.agent-composer textarea')?.focus()
}
async function closeAgent() {
  agentOpen.value = false
  await nextTick()
  document.querySelector<HTMLButtonElement>('.agent-toggle')?.focus()
}
</script>
<template>
  <div class="app-layout" :class="{ 'has-job-banner': bannerVisible, 'agent-expanded': agentOpen }">
    <GlobalJobBanner /><AppSidebar />
    <div class="workspace">
      <header class="workspace-header">
        <h1>{{ title }}</h1>
        <div class="header-actions">
          <RouterLink
            v-if="route.path !== '/review-library'"
            to="/review-library"
            class="review-link"
            >写复盘</RouterLink
          ><button
            class="agent-toggle"
            :class="{ active: agentOpen }"
            :aria-expanded="agentOpen"
            aria-controls="workspace-agent"
            @click="toggleAgent"
          >
            <span aria-hidden="true">✦</span> Agent
          </button>
        </div>
      </header>
      <main id="main-content" class="app-main"><router-view /></main>
    </div>
    <button
      v-if="agentOpen"
      class="agent-backdrop"
      aria-label="关闭 Agent 面板"
      @click="closeAgent"
    /><AgentPanel
      v-if="agentOpen"
      id="workspace-agent"
      @close="closeAgent"
    />
  </div>
</template>
<style scoped>
.app-layout {
  display: flex;
  width: 100%;
  height: 100dvh;
  background:
    radial-gradient(ellipse at 95% 0, #e9f1ff66, transparent 45%), #f8f9fc;
  overflow: hidden;
}
.has-job-banner {
  padding-top: 36px;
}
.workspace {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}
.workspace-header {
  height: 68px;
  min-height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(24px);
  border-bottom: 1px solid var(--border-color);
  gap: 12px;
}
.workspace-header h1 {
  font-size: 18px;
  font-weight: 650;
  letter-spacing: -0.6px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 22px;
}
.review-link {
  color: #6f7d91;
  font-size: 12px;
  text-decoration: none;
  white-space: nowrap;
}
.agent-toggle {
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  border: 1px solid #dbe4f1;
  background: white;
  padding: 8px 13px;
  border-radius: 9px;
  color: #596e8f;
  cursor: pointer;
  white-space: nowrap;
}
.agent-toggle span {
  margin-right: 5px;
  font-size: 16px;
  color: #5386d6;
}
.agent-toggle.active {
  background: #edf4ff;
  border-color: #d4e3fa;
  color: #286ad4;
}
.app-main {
  flex: 1;
  min-height: 0;
  overflow: auto;
  scrollbar-gutter: stable;
}
.app-main:deep(> div) {
  animation: view-enter 0.32s ease-out;
}
.agent-backdrop {
  display: none;
}
@keyframes view-enter {
  from {
    opacity: 0;
    transform: translateY(5px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@media (max-width: 1250px) {
  .agent-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 99;
    background: #22304722;
    border: 0;
    backdrop-filter: blur(2px);
  }
}
@media (max-width: 800px) {
  .workspace-header {
    padding: 0 16px;
  }
  .header-actions {
    gap: 12px;
  }
  .review-link {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .app-main:deep(> div) {
    animation: none;
  }
}
</style>

<style scoped>
@media (min-width:1251px) and (max-width:1700px) {
  .agent-expanded .app-main :deep(.stock-detail .panel-right),
  .agent-expanded .app-main :deep(.stock-detail .panel-edge-right) { display:none }
}
</style>
