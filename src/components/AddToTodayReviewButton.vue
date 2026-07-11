<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { DocumentAdd, FolderOpened } from '@element-plus/icons-vue'
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
const failureMessage = ref('')

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
  adding.value = true
  feedback.value = null
  failureMessage.value = ''
  try {
    const response = await addStockToReview(todayInShanghai(), {
      code: props.code,
      name: props.name || props.code,
    })
    feedback.value = response.data.data.already_exists ? 'exists' : 'added'
  } catch (error) {
    feedback.value = 'failed'
    failureMessage.value = errorMessage(error)
  } finally {
    adding.value = false
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
  <span class="today-review-action">
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
    <span v-if="feedback === 'added'" class="review-feedback success" role="status">已加入今日复盘</span>
    <span v-else-if="feedback === 'exists'" class="review-feedback muted" role="status">今日复盘中已存在</span>
    <span v-else-if="feedback === 'failed'" class="review-feedback failure" role="alert">加入今日复盘失败：{{ failureMessage }}</span>
    <el-button
      v-if="feedback"
      data-test="open-review"
      link
      :icon="FolderOpened"
      :size="size"
      title="打开今日复盘"
      @click="openTodayReview"
    >
      打开复盘
    </el-button>
  </span>
</template>

<style scoped>
.today-review-action {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  gap: 4px;
  flex-wrap: wrap;
  min-width: 0;
  white-space: nowrap;
}

.review-feedback {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
}

.success {
  color: #67c23a;
}

.muted {
  color: var(--text-secondary);
}

.failure {
  color: #f56c6c;
}
</style>
