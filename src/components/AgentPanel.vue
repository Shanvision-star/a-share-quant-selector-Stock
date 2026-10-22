<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Close,
  Promotion,
  RefreshRight,
  Download,
  Clock,
  DocumentAdd,
} from '@element-plus/icons-vue'
import {
  cancelAgentRun,
  getAgentCapabilities,
  getAgentRun,
  listAgentRuns,
  saveAgentReview,
  startAgentRun,
  type AgentCapabilities,
  type AgentRun,
  type AgentTask,
} from '@/api/agent'
defineEmits<{ close: [] }>()
const route = useRoute()
const router = useRouter()
const question = ref('')
const task = ref<AgentTask>('candidates')
const mode = ref<'local' | 'model'>('local')
const capabilities = ref<AgentCapabilities | null>(null)
const runs = ref<AgentRun[]>([])
const current = ref<AgentRun | null>(null)
const error = ref('')
const sending = ref(false)
const saving = ref(false)
const history = ref(false)
const saveOpen = ref(false)
const today = new Date()
const saveDate = ref(
  `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`,
)
const code = computed(() =>
  /^\d{6}$/.test(String(route.params.code || ''))
    ? String(route.params.code)
    : undefined,
)
const active = computed(
  () => !!current.value && ['queued', 'running'].includes(current.value.status),
)
const labels: Record<AgentRun['status'], string> = {
  queued: '排队中',
  running: '研究中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
}
const tasks = [
  { value: 'candidates', label: '策略研究' },
  { value: 'tracking', label: '跟踪检查' },
  { value: 'reviews', label: '复盘整理' },
]
const prompts = computed(() =>
  task.value === 'candidates'
    ? ['整理最近的策略命中', '检查信号日期与数据缺口']
    : task.value === 'tracking'
      ? ['检查跟踪记录的评估日期', '整理需要复查的跟踪项']
      : ['整理最近复盘的待办', '归纳反复出现的问题'],
)
let timer: ReturnType<typeof setTimeout> | undefined
let generation = 0
let disposed = false
function failure(exc: unknown) {
  const response = exc as { response?: { data?: { detail?: unknown } } }
  return typeof response.response?.data?.detail === 'string'
    ? response.response.data.detail
    : '请求失败，请检查后端连接后重试'
}
async function refreshHistory() {
  runs.value = (await listAgentRuns()).data.items
}
async function selectRun(id: string) {
  const ticket = ++generation
  clearTimeout(timer)
  try {
    const run = (await getAgentRun(id)).data
    if (disposed || ticket !== generation) return
    current.value = run
    error.value = ''
    history.value = false
    localStorage.setItem('quant-agent-run', id)
    if (['queued', 'running'].includes(run.status))
      timer = setTimeout(() => {
        void selectRun(id)
      }, 1200)
    else await refreshHistory()
  } catch (exc) {
    if (!disposed && ticket === generation) error.value = failure(exc)
  }
}
async function submit(preset?: string) {
  const text = (preset || question.value).trim()
  if (!text || sending.value || active.value) return
  generation++
  clearTimeout(timer)
  sending.value = true
  error.value = ''
  try {
    const run = (
      await startAgentRun({
        question: text,
        task: task.value,
        mode: mode.value,
        code: code.value,
      })
    ).data
    current.value = run
    question.value = ''
    await selectRun(run.run_id)
    await refreshHistory()
  } catch (exc) {
    error.value = failure(exc)
  } finally {
    sending.value = false
  }
}
async function cancel() {
  if (!current.value) return
  try {
    await cancelAgentRun(current.value.run_id)
    await selectRun(current.value.run_id)
  } catch (exc) {
    error.value = failure(exc)
  }
}
async function save() {
  if (!current.value || !saveDate.value) return
  saving.value = true
  try {
    await saveAgentReview(current.value.run_id, saveDate.value)
    await selectRun(current.value.run_id)
    saveOpen.value = false
    ElMessage.success('已追加到复盘')
  } catch (exc) {
    error.value = failure(exc)
  } finally {
    saving.value = false
  }
}
function download() {
  if (!current.value) return
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(current.value, null, 2)], {
      type: 'application/json',
    }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = `agent-${current.value.run_id}.json`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
watch(
  () => route.path,
  () => {
    task.value = route.path.startsWith('/tracking')
      ? 'tracking'
      : route.path.startsWith('/review')
        ? 'reviews'
        : 'candidates'
  },
  { immediate: true },
)
onMounted(async () => {
  try {
    capabilities.value = (await getAgentCapabilities()).data
    await refreshHistory()
    // 用户已开始新任务或选择历史时，初始化恢复不得覆盖当前运行。
    if (disposed || generation > 0 || sending.value) return
    const id = localStorage.getItem('quant-agent-run')
    if (id && runs.value.some((run) => run.run_id === id)) await selectRun(id)
    else if (runs.value[0]) await selectRun(runs.value[0].run_id)
  } catch (exc) {
    error.value = failure(exc)
  }
})
onBeforeUnmount(() => {
  disposed = true
  generation++
  clearTimeout(timer)
})
</script>
<template>
  <aside class="agent-panel" aria-label="研究 Agent" :data-run-id="current?.run_id" @keydown.esc="$emit('close')">
    <header class="agent-header">
      <span class="agent-symbol" aria-hidden="true">✦</span>
      <h2>Agent</h2>
      <el-button
        :icon="Clock"
        circle
        text
        aria-label="运行历史"
        :aria-expanded="history"
        @click="history = !history"
      /><el-button
        :icon="Close"
        circle
        text
        aria-label="关闭 Agent"
        @click="$emit('close')"
      />
    </header>
    <div class="agent-controls">
      <el-select
        v-model="task"
        aria-label="研究任务"
        :disabled="active || sending"
        ><el-option
          v-for="item in tasks"
          :key="item.value"
          :value="item.value"
          :label="item.label" /></el-select
      ><el-select
        v-model="mode"
        aria-label="运行模式"
        :disabled="active || sending"
        ><el-option value="local" label="本地整理" /><el-option
          value="model"
          label="模型研究"
          :disabled="!capabilities?.model_ready" /></el-select
      ><span v-if="code" class="context-stock">{{ code }}</span>
    </div>
    <div class="agent-content">
      <div v-if="history" class="run-history">
        <button
          v-for="run in runs"
          :key="run.run_id"
          @click="selectRun(run.run_id)"
        >
          <strong>{{ run.input.question }}</strong
          ><span
            >{{ new Date(run.created_at).toLocaleString('zh-CN') }} ·
            {{ labels[run.status] }}</span
          >
        </button>
        <p v-if="!runs.length" class="muted">暂无运行记录</p>
      </div>
      <div v-if="error" class="agent-error" role="alert">
        {{ error
        }}<el-button
          v-if="current"
          text
          :icon="RefreshRight"
          @click="selectRun(current.run_id)"
          >重试连接</el-button
        >
      </div>
      <template v-if="current && !history">
        <div class="user-question">{{ current.input.question }}</div>
        <div class="run-status" role="status">
          <span :class="{ 'status-pulse': active }" />{{ labels[current.status]
          }}<span class="run-mode">{{
            current.input.mode === 'local'
              ? '本地整理'
              : current.model || '模型研究'
          }}</span>
        </div>
        <p v-if="current.error" class="agent-error" role="alert">
          {{ current.error }}
        </p>
        <article v-if="current.output" class="agent-report">
          <p class="report-summary">{{ current.output.summary }}</p>
          <ul class="findings">
            <li v-for="(item, index) in current.output.findings" :key="index">
              {{ item.text
              }}<span class="source-ref">{{
                item.source_ids.join(' · ')
              }}</span>
            </li>
          </ul>
          <ul v-if="current.output.next_steps.length" class="next-steps">
            <li v-for="item in current.output.next_steps" :key="item">
              {{ item }}
            </li>
          </ul>
          <details class="evidence">
            <summary>来源与限制 · {{ current.sources.length }}</summary>
            <div v-for="source in current.sources" :key="source.source_id">
              <strong>{{ source.source_id }} · {{ source.tool }}</strong>
              <p>{{ source.retrieved_at }}</p>
              <p>{{ source.data.items.length }} / {{ source.data.total }} 条</p>
              <code>{{ source.sha256.slice(0, 16) }}</code>
            </div>
            <p v-for="item in current.output.limitations" :key="item">
              {{ item }}
            </p>
            <p>{{ current.run_id }}</p>
            <p v-if="current.latency_ms">
              {{ (current.latency_ms / 1000).toFixed(1) }}s<span
                v-if="current.usage?.total_tokens"
              >
                · {{ current.usage.total_tokens }} tokens</span
              >
            </p>
          </details>
          <div class="report-actions">
            <el-button
              :icon="DocumentAdd"
              size="small"
              @click="saveOpen = true"
              >{{ current.saved_review ? '追加到复盘' : '保存复盘' }}</el-button
            ><el-button
              :icon="Download"
              size="small"
              aria-label="导出运行 JSON"
              @click="download"
              >JSON</el-button
            >
          </div>
          <el-button
            v-if="current.saved_review"
            text
            size="small"
            @click="router.push('/review-library')"
            >查看复盘 · {{ current.saved_review }}</el-button
          >
        </article>
      </template>
      <div v-if="!current && !history" class="agent-empty">
        <div class="empty-orbit" aria-hidden="true">✦</div>
        <button
          v-for="prompt in prompts"
          :key="prompt"
          :disabled="sending"
          @click="submit(prompt)"
        >
          {{ prompt }}<span aria-hidden="true">↗</span>
        </button>
      </div>
    </div>
    <form class="agent-composer" @submit.prevent="submit()">
      <textarea
        v-model="question"
        aria-label="Agent 任务"
        placeholder="输入研究任务…"
        rows="3"
        maxlength="2000"
        :disabled="sending || active"
        @keydown.ctrl.enter.prevent="submit()"
      />
      <div class="composer-bottom">
        <span v-if="mode === 'model'">{{ capabilities?.model || '模型未配置' }}</span>
        <el-button v-if="active" size="small" @click="cancel">停止</el-button
        ><el-button
          v-else
          type="primary"
          :icon="Promotion"
          circle
          aria-label="运行 Agent"
          :disabled="!question.trim()"
          :loading="sending"
          native-type="submit"
        />
      </div>
    </form>
    <el-dialog
      v-model="saveOpen"
      title="追加到复盘"
      width="360px"
      append-to-body
      ><label class="save-label" for="agent-review-date">复盘日期</label
      ><input
        id="agent-review-date"
        v-model="saveDate"
        type="date"
        class="date-input"
      /><template #footer
        ><el-button @click="saveOpen = false">取消</el-button
        ><el-button
          type="primary"
          :disabled="!saveDate"
          :loading="saving"
          @click="save"
          >确认追加</el-button
        ></template
      ></el-dialog
    >
  </aside>
</template>
<style scoped>
.agent-panel {
  width: 336px;
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: rgba(250, 251, 254, 0.76);
  backdrop-filter: blur(28px);
  border-left: 1px solid var(--border-color);
}
.agent-header {
  height: 68px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 22px;
  border-bottom: 1px solid var(--border-color);
}
.agent-header h2 {
  font-size: 17px;
  flex: 1;
  letter-spacing: -0.4px;
}
.agent-header .el-button + .el-button {
  margin-left: 0;
}
.agent-symbol {
  color: var(--text-accent);
  font-size: 25px;
}
.agent-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 18px 20px 8px;
}
.agent-controls .el-select {
  flex: 1;
  min-width: 125px;
}
.context-stock {
  font-size: 12px;
  color: var(--text-accent);
  background: #eaf1ff;
  border-radius: 6px;
  padding: 3px 8px;
}
.agent-content {
  flex: 1;
  overflow: auto;
  padding: 14px 22px;
}
.user-question {
  padding: 12px 14px;
  border: 1px solid #e5e9f1;
  border-radius: 14px 14px 4px 14px;
  background: white;
  line-height: 1.65;
  font-size: 13px;
  margin-bottom: 20px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.run-status {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: 11px;
  margin-bottom: 14px;
}
.run-status > span:first-child {
  height: 6px;
  width: 6px;
  border-radius: 50%;
  background: var(--text-accent);
}
.run-mode {
  margin-left: auto;
  max-width: 150px;
  overflow-wrap: anywhere;
}
.status-pulse {
  animation: pulse 1.4s ease-in-out infinite;
}
.agent-report {
  font-size: 13px;
  line-height: 1.85;
  overflow-wrap: anywhere;
}
.report-summary {
  font-weight: 600;
  white-space: pre-wrap;
}
.findings,
.next-steps {
  padding-left: 17px;
  margin: 16px 0;
}
.findings li {
  margin: 10px 0;
}
.source-ref {
  font-size: 10px;
  color: #3978cb;
  background: #e9f0fb;
  border-radius: 4px;
  margin-left: 6px;
  padding: 1px 4px;
}
.next-steps {
  color: #43536a;
}
.evidence {
  font-size: 11px;
  color: var(--text-secondary);
  margin: 18px 0;
}
.evidence summary {
  cursor: pointer;
}
.evidence div {
  margin: 8px 0;
  padding: 10px;
  background: white;
  border-radius: 10px;
}
.report-actions {
  display: flex;
  gap: 6px;
}
.report-actions .el-button {
  margin: 0;
}
.agent-composer {
  margin: 12px 16px 18px;
  border: 1px solid #dde3eb;
  border-radius: 16px;
  background: white;
  box-shadow: 0 4px 18px #24355006;
  padding: 12px;
}
.agent-composer:focus-within {
  border-color: #80b0f7;
}
.agent-composer textarea {
  width: 100%;
  resize: none;
  border: 0;
  background: transparent;
  font: inherit;
  font-size: 13px;
  color: var(--text-primary);
  outline: none;
  line-height: 1.7;
}
.composer-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.composer-bottom > span {
  font-size: 11px;
  color: var(--text-secondary);
}
.composer-bottom > .el-button { margin-left: auto }
.agent-empty {
  padding-top: 45px;
}
.empty-orbit {
  width: 60px;
  height: 60px;
  border-radius: 20px;
  background: linear-gradient(135deg, #edf4ff, #fff);
  border: 1px solid #e4ecf8;
  box-shadow: 0 6px 20px #3576d70a;
  display: grid;
  place-items: center;
  font-size: 32px;
  color: #4b86dd;
}
.agent-empty h3 {
  font-size: 22px;
  letter-spacing: -1px;
  margin: 24px 0;
}
.agent-empty button {
  display: flex;
  justify-content: space-between;
  width: 100%;
  text-align: left;
  background: rgba(255, 255, 255, 0.65);
  border: 1px solid #e5e9f0;
  border-radius: 10px;
  padding: 12px;
  margin: 8px 0;
  font: inherit;
  font-size: 12px;
  color: #49556a;
  cursor: pointer;
}
.agent-empty button:hover {
  border-color: #95b7ec;
}
.agent-empty button span {
  margin-left: 6px;
  color: #5486d3;
}
.agent-error {
  font-size: 12px;
  color: #ae3843;
  background: #fff0f1;
  padding: 10px;
  border-radius: 10px;
  margin-bottom: 12px;
}
.run-history button {
  display: block;
  width: 100%;
  text-align: left;
  padding: 12px;
  background: white;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  margin-bottom: 8px;
  cursor: pointer;
  color: inherit;
}
.run-history strong {
  display: block;
  font-size: 12px;
  font-weight: 500;
}
.run-history span,
.muted {
  font-size: 11px;
  color: var(--text-secondary);
}
.save-label {
  display: block;
  margin-bottom: 8px;
}
.date-input {
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  width: 100%;
  font: inherit;
}
@keyframes pulse {
  50% {
    opacity: 0.3;
  }
}
@media (prefers-reduced-motion: reduce) {
  .status-pulse {
    animation: none;
  }
}
@media (max-width: 1250px) {
  .agent-panel {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 100;
    width: min(380px, 100vw);
    box-shadow: -12px 0 70px #263d6b16;
    background: rgba(250, 251, 254, 0.95);
  }
}
</style>
