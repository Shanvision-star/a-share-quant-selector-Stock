import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

interface StrategyConfigDraft {
  strategy_name: string
  params: Record<string, unknown>
  param_meta: Record<string, unknown>
  case_examples?: unknown[]
}

interface SettingsDraftPayload {
  revision: string
  updated_at: string
  configs: StrategyConfigDraft[]
}

function cloneConfigs(configs: StrategyConfigDraft[]) {
  return JSON.parse(JSON.stringify(configs)) as StrategyConfigDraft[]
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

  function markSaved(newRevision: string, strategyName?: string, newUpdatedAt?: string) {
    revision.value = newRevision
    if (newUpdatedAt) {
      updatedAt.value = newUpdatedAt
    }
    if (!strategyName) {
      serverConfigs.value = cloneConfigs(draftConfigs.value)
      return
    }

    const savedConfig = draftConfigs.value.find((config) => config.strategy_name === strategyName)
    if (!savedConfig) return

    const nextServerConfigs = cloneConfigs(serverConfigs.value)
    const savedIndex = nextServerConfigs.findIndex((config) => config.strategy_name === strategyName)
    if (savedIndex === -1) return
    nextServerConfigs[savedIndex] = cloneConfigs([savedConfig])[0]
    serverConfigs.value = nextServerConfigs
  }

  function refreshFromServerWithConflict(payload: SettingsDraftPayload, conflictedStrategyName: string) {
    revision.value = payload.revision
    updatedAt.value = payload.updated_at
    serverConfigs.value = cloneConfigs(payload.configs)

    const localDraftByStrategy = new Map(
      draftConfigs.value.map((config) => [config.strategy_name, cloneConfigs([config])[0]]),
    )
    draftConfigs.value = payload.configs.map((serverConfig) => {
      if (serverConfig.strategy_name === conflictedStrategyName) {
        return cloneConfigs([serverConfig])[0]
      }
      return localDraftByStrategy.get(serverConfig.strategy_name) ?? cloneConfigs([serverConfig])[0]
    })
  }

  return {
    revision,
    updatedAt,
    serverConfigs,
    draftConfigs,
    isDirty,
    loadFromServer,
    updateParam,
    markSaved,
    refreshFromServerWithConflict,
  }
})
