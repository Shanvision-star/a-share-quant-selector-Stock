<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
import GlobalJobBanner from './GlobalJobBanner.vue'
import { computed } from 'vue'
import { useUpdateJobStore } from '@/stores/updateJob'

const store = useUpdateJobStore()
// 当横幅展开时，主区域上移 36px 避免内容被覆盖
const bannerVisible = computed(
  () => (store.isRunning || store.jobCompleted || !!store.jobError) && !store.bannerCollapsed
)
</script>

<template>
  <div class="app-layout">
    <GlobalJobBanner />
    <AppSidebar />
    <main class="app-main" :style="bannerVisible ? 'padding-top: 36px' : ''">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  width: 100%;
  height: 100vh;
}
.app-main {
  flex: 1;
  overflow: auto;
  background-color: #ffffff;
}
</style>
