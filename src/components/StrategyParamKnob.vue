<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  label: string
  modelValue: number
  min: number
  max: number
  step: number
  desc?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: number): void
}>()

const localValue = ref(props.modelValue)

watch(() => props.modelValue, (v) => { localValue.value = v })

function onChange(val: number) {
  localValue.value = val
  emit('update:modelValue', val)
}
</script>

<template>
  <div class="param-knob">
    <div class="knob-header">
      <span class="knob-label">{{ label }}</span>
      <span class="knob-value">{{ localValue }}</span>
    </div>
    <el-slider
      v-model="localValue"
      :min="min"
      :max="max"
      :step="step"
      :show-tooltip="true"
      @change="onChange"
    />
    <div v-if="desc" class="knob-desc">{{ desc }}</div>
  </div>
</template>

<style scoped>
.param-knob {
  margin-bottom: 16px;
}
.knob-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 13px;
}
.knob-label {
  color: var(--text-secondary);
}
.knob-value {
  color: var(--text-primary);
  font-weight: bold;
}
.knob-desc {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}
</style>
