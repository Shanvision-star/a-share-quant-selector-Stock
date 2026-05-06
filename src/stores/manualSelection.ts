import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  deleteManualSelection,
  getManualSelectionDates,
  getManualSelections,
  saveManualSelection,
  type ManualSelectionPayload,
} from '@/api'

export interface ManualSelectionItem extends ManualSelectionPayload {
  selection_id?: number
  created_at?: string
  updated_at?: string
}

export const useManualSelectionStore = defineStore('manualSelection', () => {
  const currentDate = ref('')
  const items = ref<ManualSelectionItem[]>([])
  const dates = ref<string[]>([])
  const loading = ref(false)
  const savingCodes = ref(new Set<string>())

  const selectedCodes = computed(() => new Set(items.value.map(item => item.code)))

  function isSelected(code: string): boolean {
    return selectedCodes.value.has(code)
  }

  async function fetchByDate(date: string) {
    if (!date) return
    currentDate.value = date
    loading.value = true
    try {
      const res = await getManualSelections({ date })
      const payload = res?.data?.data ?? []
      items.value = Array.isArray(payload) ? payload : []
    } finally {
      loading.value = false
    }
  }

  async function fetchByRange(startDate: string, endDate: string) {
    if (!startDate || !endDate) return
    loading.value = true
    try {
      const res = await getManualSelections({ start_date: startDate, end_date: endDate })
      const payload = res?.data?.data ?? []
      items.value = Array.isArray(payload) ? payload : []
    } finally {
      loading.value = false
    }
  }

  async function fetchDates(limit = 60) {
    const res = await getManualSelectionDates(limit)
    const payload = res?.data?.data ?? []
    dates.value = Array.isArray(payload) ? payload : []
    return dates.value
  }

  async function add(payload: ManualSelectionPayload) {
    savingCodes.value = new Set([...savingCodes.value, payload.code])
    try {
      const res = await saveManualSelection(payload)
      const item = res?.data?.data ?? payload
      const nextItems = items.value.filter(existing => existing.code !== payload.code)
      items.value = [item, ...nextItems]
      currentDate.value = payload.selection_date
    } finally {
      const nextSaving = new Set(savingCodes.value)
      nextSaving.delete(payload.code)
      savingCodes.value = nextSaving
    }
  }

  async function remove(date: string, code: string) {
    savingCodes.value = new Set([...savingCodes.value, code])
    try {
      await deleteManualSelection(date, code)
      items.value = items.value.filter(item => !(item.selection_date === date && item.code === code))
    } finally {
      const nextSaving = new Set(savingCodes.value)
      nextSaving.delete(code)
      savingCodes.value = nextSaving
    }
  }

  return {
    currentDate,
    items,
    dates,
    loading,
    savingCodes,
    selectedCodes,
    isSelected,
    fetchByDate,
    fetchByRange,
    fetchDates,
    add,
    remove,
  }
})
