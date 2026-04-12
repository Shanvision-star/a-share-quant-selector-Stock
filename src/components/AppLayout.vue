<script setup lang="ts">
import AppSidebar from './AppSidebar.vue'
</script>

<template>
  <div class="app-layout">
    <AppSidebar />
    <main class="app-main">
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
  background-color: var(--bg-primary);
}
</style>
