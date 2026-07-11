<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Picture, UploadFilled } from '@element-plus/icons-vue'
import { uploadReviewAttachment } from '@/api/reviews'

const props = defineProps<{
  reviewDate: string
  insertMarkdown: (markdown: string) => void
}>()

interface UploadFailure {
  id: number
  filename: string
  message: string
}

const fileInput = ref<HTMLInputElement | null>(null)
const pendingCount = ref(0)
const failures = ref<UploadFailure[]>([])
let failureId = 0

const uploading = computed(() => pendingCount.value > 0)

function getErrorMessage(error: unknown): string {
  const candidate = error as { response?: { data?: { detail?: string; message?: string } }; message?: string }
  return candidate.response?.data?.detail || candidate.response?.data?.message || candidate.message || '上传失败'
}

function imageFiles(files: FileList | File[] | null | undefined): File[] {
  return Array.from(files || []).filter(file => file.type.startsWith('image/'))
}

async function uploadFiles(files: FileList | File[] | null | undefined) {
  const images = imageFiles(files)
  for (const file of images) {
    pendingCount.value += 1
    try {
      const response = await uploadReviewAttachment(props.reviewDate, file)
      const markdown = response.data.data.markdown
      if (!markdown) throw new Error('服务端未返回图片 Markdown')
      props.insertMarkdown(markdown)
    } catch (error) {
      failures.value.push({
        id: ++failureId,
        filename: file.name,
        message: getErrorMessage(error),
      })
    } finally {
      pendingCount.value -= 1
    }
  }
}

function openPicker() {
  fileInput.value?.click()
}

function handleChange(event: Event) {
  const input = event.target as HTMLInputElement
  void uploadFiles(input.files)
  input.value = ''
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  void uploadFiles(event.dataTransfer?.files)
}

function handlePaste(event: ClipboardEvent) {
  const files = imageFiles(event.clipboardData?.files)
  if (!files.length) return
  event.preventDefault()
  void uploadFiles(files)
}

onMounted(() => window.addEventListener('paste', handlePaste))
onBeforeUnmount(() => window.removeEventListener('paste', handlePaste))

defineExpose({ uploadFiles })
</script>

<template>
  <div class="attachment-uploader">
    <button
      class="upload-dropzone"
      type="button"
      title="上传截图；也可拖入或直接粘贴图片"
      :disabled="uploading || !reviewDate"
      @click="openPicker"
      @dragover.prevent
      @drop="handleDrop"
    >
      <el-icon :class="{ spinning: uploading }"><UploadFilled /></el-icon>
      <span>{{ uploading ? `上传中 ${pendingCount}` : '添加截图' }}</span>
      <span class="upload-hint">拖入 / 粘贴</span>
    </button>
    <input
      ref="fileInput"
      class="visually-hidden"
      type="file"
      accept="image/*"
      multiple
      @change="handleChange"
    />

    <div v-if="failures.length" class="upload-failures" role="status">
      <div v-for="failure in failures" :key="failure.id" class="upload-failure">
        <el-icon><Picture /></el-icon>
        <span class="failure-name">{{ failure.filename }}</span>
        <span>{{ failure.message }}</span>
        <button type="button" title="关闭错误" @click="failures = failures.filter(item => item.id !== failure.id)">×</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.attachment-uploader {
  min-width: 0;
}

.upload-dropzone {
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px dashed var(--border-color);
  border-radius: 4px;
  color: var(--text-primary);
  background: var(--bg-tertiary);
  cursor: pointer;
}

.upload-dropzone:hover:not(:disabled) {
  border-color: var(--text-accent);
}

.upload-dropzone:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.upload-hint {
  color: var(--text-secondary);
  font-size: 12px;
}

.upload-failures {
  display: grid;
  gap: 4px;
  margin-top: 6px;
}

.upload-failure {
  display: grid;
  grid-template-columns: auto minmax(80px, auto) minmax(120px, 1fr) auto;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid #8a3b3b;
  border-radius: 4px;
  color: #ffb4b4;
  font-size: 12px;
  background: #351f24;
}

.failure-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-failure button {
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

.spinning {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
