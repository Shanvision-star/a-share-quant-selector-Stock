import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

interface StrategyConfigDraft {
  strategy_name: string
  params: Record<string, unknown>
  param_meta: Record<string, unknown>
}

interface SettingsDraftPayload {
  revision: string
  updated_at: string
  configs: StrategyConfigDraft[]
}

function cloneConfigs(configs: StrategyConfigDraft[]) {
  return configs.map((config) => ({
    strategy_name: config.strategy_name,
    params: { ...config.params },
    param_meta: { ...config.param_meta },
  }))
}

export const useSettingsDraftStore = defineStore('settingsDraft', () => {
  const revision = ref('')
  const updatedAt = ref('')
  const serverConfigs = ref<StrategyConfigDraft[]>([])
  const draftConfigs = ref<StrategyConfigDraft[]>([])

  const isDirty = computed(() => JSON.stringify(draftConfigs.value) !== JSON.stringify(serverConfigs.value))

  function loadFromServer(payload: SettingsDraftPayload) {
    revision.value = payload.revision
    updatedAt.value = payload.updated_at
    serverConfigs.value = cloneConfigs(payload.configs)
    draftConfigs.value = cloneConfigs(payload.configs)
  }

  function updateParam(strategyName: string, paramName: string, value: unknown) {
    const targetConfig = draftConfigs.value.find((config) => config.strategy_name === strategyName)
    if (!targetConfig) return
    targetConfig.params[paramName] = value
  }

  return {
    revision,
    updatedAt,
    draftConfigs,
    isDirty,
    loadFromServer,
    updateParam,
  }
})
