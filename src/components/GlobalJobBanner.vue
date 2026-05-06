<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUpdateJobStore } from '@/stores/updateJob'

const router = useRouter()
const store = useUpdateJobStore()

const show = computed(() => store.isRunning || store.jobCompleted || !!store.jobError)

function goToUpdate() {
  router.push('/update')
}
</script>

<template>
  <transition name="slide-down">
    <div
      v-if="show"
      class="global-job-banner"
      :class="{
        done: store.jobCompleted,
        error: !!store.jobError,
        collapsed: store.bannerCollapsed
      }"
    >
      <!-- 折叠态：悬浮小胶囊 -->
      <div v-if="store.bannerCollapsed" class="banner-pill" @click="store.toggleBannerCollapse()">
        <span class="banner-icon">
          <span v-if="store.jobError">❌</span>
          <span v-else-if="store.jobCompleted">✅</span>
          <span v-else class="spinner">🔄</span>
        </span>
        <span class="pill-label">
          {{ store.isRunning ? `${store.progress}%` : (store.jobCompleted ? '已完成' : '出错') }}
        </span>
        <span class="pill-expand" title="展开">▲</span>
      </div>

      <!-- 展开态：完整横幅 -->
      <div v-else class="banner-inner">
        <!-- 图标 -->
        <span class="banner-icon">
          <span v-if="store.jobError">❌</span>
          <span v-else-if="store.jobCompleted">✅</span>
          <span v-else class="spinner">🔄</span>
        </span>

        <!-- 文字 -->
        <span class="banner-label">{{ store.statusLabel }}</span>

        <!-- 进度条（运行中才显示） -->
        <div v-if="store.isRunning" class="banner-bar-wrap">
          <div class="banner-bar" :style="{ width: store.progress + '%' }" />
        </div>

        <!-- 实时命中数 -->
        <span v-if="store.isRunning && store.liveSignals.length" class="banner-hits">
          实时命中 {{ store.liveSignals.length }} 只
        </span>

        <!-- 跳转链接 -->
        <el-button
          v-if="!store.jobCompleted"
          text
          size="small"
          class="banner-link"
          @click="goToUpdate"
        >
          查看详情 →
        </el-button>

        <!-- 完成后关闭 -->
        <el-button
          v-if="store.jobCompleted || store.jobError"
          text
          size="small"
          class="banner-close"
          @click="store.reset()"
        >
          ✕
        </el-button>

        <!-- 折叠按钮 -->
        <el-button
          text
          size="small"
          class="banner-collapse"
          title="最小化"
          @click="store.toggleBannerCollapse()"
        >
          ▼
        </el-button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.global-job-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  background: linear-gradient(90deg, #409eff, #36b7ff);
  color: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.18);
  transition: all 0.3s ease;
}

/* 折叠态：缩为右上角小胶囊 */
.global-job-banner.collapsed {
  left: auto;
  right: 16px;
  top: 8px;
  border-radius: 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25);
}

.global-job-banner.done {
  background: linear-gradient(90deg, #67c23a, #85d850);
}

.global-job-banner.error {
  background: linear-gradient(90deg, #f56c6c, #ff8585);
}

.banner-inner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 16px;
  font-size: 13px;
  font-weight: 500;
  min-height: 36px;
}

.banner-icon {
  font-size: 15px;
  flex-shrink: 0;
}

.spinner {
  display: inline-block;
  animation: spin 1.2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.banner-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.banner-bar-wrap {
  width: 120px;
  height: 6px;
  background: rgba(255, 255, 255, 0.35);
  border-radius: 3px;
  flex-shrink: 0;
  overflow: hidden;
}

.banner-bar {
  height: 100%;
  background: #fff;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.banner-hits {
  font-size: 12px;
  background: rgba(255, 255, 255, 0.25);
  border-radius: 10px;
  padding: 1px 8px;
  white-space: nowrap;
  flex-shrink: 0;
}

.banner-link,
.banner-close,
.banner-collapse {
  color: #fff !important;
  opacity: 0.9;
  flex-shrink: 0;
  padding: 0 4px;
}

.banner-link:hover,
.banner-close:hover,
.banner-collapse:hover {
  opacity: 1;
}

/* ── 折叠态小胶囊 ── */
.banner-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
}

.banner-pill:hover {
  opacity: 0.85;
}

.pill-label {
  font-size: 12px;
}

.pill-expand {
  font-size: 10px;
  opacity: 0.8;
}

/* 滑入动画 */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: transform 0.25s ease, opacity 0.25s ease;
}
.slide-down-enter-from,
.slide-down-leave-to {
  transform: translateY(-100%);
  opacity: 0;
}
</style>
