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

interface StrategyConfig {
  strategy_name: string
  params: Record<string, number>
  param_meta: Record<string, ParamMeta>
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
</script>

<template>
  <div class="settings-view" v-loading="loading">
    <h2>策略参数配置</h2>

    <div v-for="cfg in configs" :key="cfg.strategy_name" class="strategy-section">
      <el-card shadow="never">
        <template #header>
          <span class="strategy-title">{{ cfg.strategy_name }}</span>
        </template>

        <div class="params-grid">
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
.action-buttons {
  margin-top: 20px;
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
</style>
