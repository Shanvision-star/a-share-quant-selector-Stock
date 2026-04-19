<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import StrategyParamKnob from '@/components/StrategyParamKnob.vue'
import { getConfig, updateConfig } from '@/api'

interface ParamMeta {
  label: string
  min: number
  max: number
  step: number
  desc: string
  default: number
}

interface CaseExample {
  id: string
  name: string
  code: string
  date: string
  description: string
  tags: string[]
  source: string
}

interface StrategyConfig {
  strategy_name: string
  params: Record<string, number>
  param_meta: Record<string, ParamMeta>
  case_examples?: CaseExample[]
}

const configs = ref<StrategyConfig[]>([])
const loading = ref(true)
const saving = ref<Record<string, boolean>>({})

onMounted(async () => {
  await loadConfig()
})

async function loadConfig() {
  loading.value = true
  try {
    const res = await getConfig()
    configs.value = res.data.data || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function resetDefaults(cfg: StrategyConfig) {
  for (const [key, meta] of Object.entries(cfg.param_meta)) {
    if (meta.default !== undefined) {
      cfg.params[key] = meta.default
    }
  }
}

async function saveConfig(cfg: StrategyConfig) {
  saving.value[cfg.strategy_name] = true
  try {
    await updateConfig({
      strategy_name: cfg.strategy_name,
      params: cfg.params,
    })
    ElMessage.success(`${cfg.strategy_name} 参数已保存`)
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value[cfg.strategy_name] = false
  }
}

function getCaseSourceLabel(source?: string) {
  if (source === 'b1-stage') return 'B1阶段型'
  if (source === 'b1-perfect') return 'B1完美图形'
  if (source === 'b2-perfect') return 'B2经典'
  return '案例'
}
</script>

<template>
  <div class="settings-view" v-loading="loading">
    <h2>策略参数配置</h2>

    <div v-for="cfg in configs" :key="cfg.strategy_name" class="strategy-section">
      <el-card shadow="never">
        <template #header>
          <span class="strategy-title">{{ cfg.strategy_name }}</span>
        </template>

        <div class="params-grid" v-if="Object.keys(cfg.param_meta || {}).length">
          <StrategyParamKnob
            v-for="(meta, key) in cfg.param_meta"
            :key="key"
            :label="meta.label"
            v-model="cfg.params[key as string]"
            :min="meta.min"
            :max="meta.max"
            :step="meta.step"
            :desc="meta.desc"
          />
        </div>
        <el-empty
          v-else
          :image-size="56"
          description="当前策略暂无可调参数"
          class="no-param-placeholder"
        />

        <div v-if="cfg.case_examples && cfg.case_examples.length" class="case-library">
          <div class="case-library-title">案例库（{{ cfg.case_examples.length }}）</div>
          <el-table :data="cfg.case_examples" size="small" stripe>
            <el-table-column prop="name" label="案例" width="120" />
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small">{{ getCaseSourceLabel(row.source) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="标签" width="220">
              <template #default="{ row }">
                <el-tag
                  v-for="tag in (row.tags || [])"
                  :key="`${row.id}-${tag}`"
                  size="small"
                  type="info"
                  class="case-tag"
                >
                  {{ tag }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="说明" show-overflow-tooltip />
          </el-table>
        </div>

        <div class="action-buttons">
          <el-button @click="resetDefaults(cfg)">恢复默认</el-button>
          <el-button
            type="primary"
            :loading="saving[cfg.strategy_name]"
            @click="saveConfig(cfg)"
          >
            保存
          </el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.settings-view {
  padding: 20px;
  max-width: 800px;
}
h2 {
  margin-bottom: 20px;
}
.strategy-section {
  margin-bottom: 24px;
}
.strategy-title {
  font-size: 16px;
  font-weight: bold;
}
.params-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 32px;
}
.no-param-placeholder {
  padding: 0;
}
.case-library {
  margin-top: 14px;
}
.case-library-title {
  margin-bottom: 8px;
  font-weight: 600;
  color: #303133;
}
.case-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}
.action-buttons {
  margin-top: 20px;
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
