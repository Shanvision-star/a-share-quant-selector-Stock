<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { DocumentAdd, FolderOpened } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { addStockToReview } from '@/api/reviews'

const props = withDefaults(defineProps<{
  code: string
  name?: string
  size?: 'large' | 'default' | 'small'
}>(), {
  name: '',
  size: 'small',
})

const router = useRouter()
const adding = ref(false)
const feedback = ref<'added' | 'exists' | 'failed' | null>(null)
let requestToken = 0

watch(
  () => props.code,
  () => {
    requestToken += 1
    adding.value = false
    feedback.value = null
  },
)

function todayInShanghai(date = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function errorMessage(error: unknown): string {
  const candidate = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
  return candidate.response?.data?.detail || candidate.response?.data?.message || candidate.message || '请稍后重试'
}

async function addToTodayReview() {
  if (!props.code || adding.value) return
  const token = ++requestToken
  const code = props.code
  const name = props.name || code
  adding.value = true
  feedback.value = null
  try {
    const response = await addStockToReview(todayInShanghai(), {
      code,
      name,
    })
    if (token !== requestToken) return
    if (response.data.data.already_exists) {
      feedback.value = 'exists'
      ElMessage.info('今日复盘中已存在')
    } else {
      feedback.value = 'added'
      ElMessage.success('已加入今日复盘')
    }
  } catch (error) {
    if (token !== requestToken) return
    feedback.value = 'failed'
    ElMessage.error(`加入今日复盘失败：${errorMessage(error)}`)
  } finally {
    if (token === requestToken) adding.value = false
  }
}

function openTodayReview() {
  router.push({
    name: 'ReviewLibrary',
    query: { date: todayInShanghai() },
  })
}
</script>

<template>
  <span class="today-review-action" :data-feedback="feedback || undefined">
    <el-button
      link
      type="primary"
      :icon="DocumentAdd"
      :size="size"
      :loading="adding"
      :disabled="!code"
      title="加入今日复盘"
      @click="addToTodayReview"
    >
      加入复盘
    </el-button>
    <el-button
      data-test="open-review"
      link
      circle
      :icon="FolderOpened"
      :size="size"
      title="打开今日复盘"
      aria-label="打开今日复盘"
      @click="openTodayReview"
    />
  </span>
</template>

<style scoped>
.today-review-action {
  display: inline-flex;
  align-items: center;
  flex: 0 0 88px;
  width: 88px;
  height: 28px;
  gap: 0;
  white-space: nowrap;
}

.today-review-action :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
