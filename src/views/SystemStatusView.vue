<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { RefreshRight } from '@element-plus/icons-vue'
import { getSystemStatus, type SystemStatusBlock, type SystemStatusPayload } from '@/api'

const router = useRouter()
const loading = ref(false)
const errorMessage = ref('')
const statusPayload = ref<SystemStatusPayload | null>(null)

const mainBlocks = computed(() => {
  const payload = statusPayload.value
  if (!payload) return []
  return [
    { key: 'data', title: '行情数据', block: payload.data },
    { key: 'strategy_cache', title: '策略缓存', block: payload.strategy_cache },
    { key: 'update_pipeline', title: '更新链路', block: payload.update_pipeline },
  ]
})

const supportBlocks = computed(() => {
  const payload = statusPayload.value
  if (!payload) return []
  return [
    { key: 'tracking', title: '跟踪运营', block: payload.tracking },
    { key: 'integrations', title: '外部集成', block: payload.integrations },
    { key: 'backend', title: '后端服务', block: payload.backend },
  ]
})

const overallTagType = computed(() => getStatusType(statusPayload.value?.overall_status))

onMounted(() => {
  loadStatus()
})

async function loadStatus() {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await getSystemStatus()
    statusPayload.value = response.data.data
  } catch (error: any) {
    console.error('系统状态读取失败', error)
    statusPayload.value = null
    errorMessage.value = `系统状态读取失败：${error?.message || '未知错误'}。请检查 FastAPI 后端是否正在运行，并确认 /api/system/status 可访问。`
  } finally {
    loading.value = false
  }
}

function goTo(path: string) {
  router.push(path)
}

function getStatusType(status?: string) {
  if (status === 'ready') return 'success'
  if (status === 'running') return 'primary'
  if (status === 'stale' || status === 'partial') return 'warning'
  if (status === 'missing' || status === 'error') return 'danger'
  return 'info'
}

function getStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    ready: '可用',
    stale: '过期',
    missing: '缺失',
    running: '运行中',
    partial: '部分完成',
    error: '错误',
    disabled: '未启用',
  }
  return status ? labels[status] || status : '-'
}

function compactDetails(block: SystemStatusBlock) {
  return Object.entries(block.details || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .slice(0, 8)
}

function formatDetailValue(value: unknown) {
  if (Array.isArray(value)) return value.length ? value.join(', ') : '-'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}
</script>

<template>
  <div class="system-status-view" v-loading="loading">
    <div class="status-header">
      <div>
        <h2>系统状态</h2>
        <p>只读检查数据、策略缓存与后端链路；本页不会触发数据更新或策略重建。</p>
      </div>
      <div class="status-actions">
        <el-button :icon="RefreshRight" :loading="loading" @click="loadStatus">
          刷新状态
        </el-button>
        <el-button @click="goTo('/update')">前往数据更新</el-button>
        <el-button type="primary" @click="goTo('/strategy-results')">查看策略结果</el-button>
      </div>
    </div>

    <el-alert
      v-if="errorMessage"
      class="status-alert"
      type="error"
      show-icon
      :closable="false"
      :title="errorMessage"
    />

    <template v-if="statusPayload">
      <div class="overall-card">
        <div>
          <div class="section-label">总体状态</div>
          <div class="overall-title">
            <el-tag :type="overallTagType" size="large">
              {{ getStatusLabel(statusPayload.overall_status) }}
            </el-tag>
            <span>{{ statusPayload.checked_at || '-' }}</span>
          </div>
        </div>
        <div class="overall-hints">
          <el-tag
            v-for="hint in statusPayload.frontend_hints"
            :key="hint"
            type="info"
            effect="plain"
          >
            {{ hint }}
          </el-tag>
        </div>
      </div>

      <section class="status-section">
        <div class="section-title">主链路</div>
        <div class="block-grid">
          <article v-for="item in mainBlocks" :key="item.key" class="status-block">
            <div class="block-head">
              <h3>{{ item.title }}</h3>
              <el-tag :type="getStatusType(item.block.status)">
                {{ getStatusLabel(item.block.status) }}
              </el-tag>
            </div>
            <p class="block-message">{{ item.block.message }}</p>
            <p class="block-action">{{ item.block.next_action }}</p>
            <dl class="detail-list">
              <template v-for="[key, value] in compactDetails(item.block)" :key="key">
                <dt>{{ key }}</dt>
                <dd>{{ formatDetailValue(value) }}</dd>
              </template>
            </dl>
          </article>
        </div>
      </section>

      <section class="status-section">
        <div class="section-title">辅助链路</div>
        <div class="block-grid support-grid">
          <article v-for="item in supportBlocks" :key="item.key" class="status-block">
            <div class="block-head">
              <h3>{{ item.title }}</h3>
              <el-tag :type="getStatusType(item.block.status)">
                {{ getStatusLabel(item.block.status) }}
              </el-tag>
            </div>
            <p class="block-message">{{ item.block.message }}</p>
            <p class="block-action">{{ item.block.next_action }}</p>
            <dl class="detail-list">
              <template v-for="[key, value] in compactDetails(item.block)" :key="key">
                <dt>{{ key }}</dt>
                <dd>{{ formatDetailValue(value) }}</dd>
              </template>
            </dl>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.system-status-view {
  padding: 20px;
}

.status-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.status-header h2 {
  margin: 0 0 6px;
  font-size: 22px;
  color: #303133;
}

.status-header p {
  margin: 0;
  color: #909399;
  font-size: 13px;
}

.status-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.status-alert {
  margin-bottom: 16px;
}

.overall-card {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
  flex-wrap: wrap;
  padding: 18px;
  margin-bottom: 18px;
  border: 1px solid #e4e7ed;
  border-radius: 12px;
  background: linear-gradient(135deg, #f6f8fc, #ffffff);
}

.section-label {
  margin-bottom: 8px;
  color: #909399;
  font-size: 13px;
}

.overall-title {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #606266;
}

.overall-hints {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  max-width: 680px;
}

.status-section {
  margin-bottom: 20px;
}

.section-title {
  margin-bottom: 10px;
  font-size: 16px;
  font-weight: 700;
  color: #303133;
}

.block-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.support-grid {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.status-block {
  padding: 16px;
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  background: #ffffff;
}

.block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.block-head h3 {
  margin: 0;
  font-size: 15px;
  color: #303133;
}

.block-message {
  min-height: 42px;
  margin: 0 0 8px;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}

.block-action {
  margin: 0 0 12px;
  color: #409eff;
  font-size: 13px;
  line-height: 1.5;
}

.detail-list {
  display: grid;
  grid-template-columns: minmax(100px, 130px) minmax(0, 1fr);
  gap: 8px 10px;
  margin: 0;
  font-size: 12px;
}

.detail-list dt {
  color: #909399;
}

.detail-list dd {
  margin: 0;
  color: #606266;
  word-break: break-all;
}
</style>
