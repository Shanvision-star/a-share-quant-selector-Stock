<script setup lang="ts">
// 单股跟踪运营面板：列表 + 规则批量评估 + 告警 + LLM 建议 + OrderIntent 确认/否决
// + 批量导入（TXT/粘贴） + 勾选批量删除（满足前端运营批量化诉求）
// 后端入口：tracking.py / tracking_alert.py / tracking_evaluation.py / tracking_llm.py / tracking_intent.py
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { RefreshRight, VideoPlay } from '@element-plus/icons-vue'
import AddToTodayReviewButton from '@/components/AddToTodayReviewButton.vue'
import { trackingLoopStatusMeta, trackingLoopSummary } from '@/views/trackingLoopState'
import {
  acknowledgeTrackingAlert,
  listTrackingItems,
  listTrackingAlerts,
  evaluateTrackingRules,
  evaluateTrackingItem,
  getTrackingLLMAdvice,
  ignoreTrackingAlert,
  confirmTrackingIntent,
  rejectTrackingIntent,
  batchCreateTrackingItems,
  batchDeleteTrackingItems,
  deleteTrackingItem,
  syncCloseTracking,
  clearKlineCache,
  createTrackingItem,
  getLatestTrackingLoopRun,
  getStockNameByCode,
  getSignalClose,
  patchTrackingEntryPrice,
  runTrackingPostClose,
  type TrackingItem,
  type TrackingAlertItem,
  type TrackingAdvice,
  type TrackingLoopRun,
} from '@/api'

// —— 列表状态 ——
const items = ref<TrackingItem[]>([])
const loading = ref(false)
const statusFilter = ref<string>('all')
const route = useRoute()
const codeFilter = ref<string>(/^\d{6}$/.test(String(route.query.code || '')) ? String(route.query.code) : '')
watch(() => route.query.code, value => {
  codeFilter.value = /^\d{6}$/.test(String(value || '')) ? String(value) : ''
  void refreshItems()
})
const batchLoading = ref(false)

// 路由实例：用于代码/名称点击跳转 K 线详情页（路由名 StockDetail，参数 code）
const router = useRouter()
function goStockDetail(code: string) {
  if (!code) return
  router.push({ name: 'StockDetail', params: { code } })
}

// —— 勾选状态（用于批量删除） ——
// 之所以单独维护一个 Set 而不是依赖 el-table selection 事件，
// 是因为列表刷新会导致 selection 丢失；用 tracking_id 集合可在刷新后保留有效项。
const selectedIds = ref<Set<string>>(new Set())
const selectedItems = computed(() =>
  items.value.filter((it) => selectedIds.value.has(it.tracking_id)),
)
const selectedCount = computed(() => selectedItems.value.length)
function handleSelectionChange(rows: TrackingItem[]) {
  // 同步 el-table 内部状态到 selectedIds，保证 UI 与逻辑一致
  selectedIds.value = new Set(rows.map((r) => r.tracking_id))
}

// —— 批量导入对话框状态 ——
const importDialogVisible = ref(false)
const importText = ref('')          // 粘贴框文本：支持空格/换行/逗号/分号分隔
const importSignalDate = ref('')    // 可选信号日；为空则后端默认今天
const importEvaluateNow = ref(true) // 默认建仓后立即评估，才能在列表里看到 entry_price
const importRefreshData = ref(true) // 默认勾选：导入前先刷行情，确保 evaluate_now 能落 entry_price
const importLoading = ref(false)

// —— 收盘同步状态 ——
const syncCloseLoading = ref(false)

// —— 收盘循环状态 ——
const latestLoopRun = ref<TrackingLoopRun | null>(null)
const loopLoading = ref(false)
const loopStatusLoading = ref(false)
const loopLoadError = ref('')
const loopStatusMeta = computed(() => trackingLoopStatusMeta(latestLoopRun.value?.status))
const loopRunTime = computed(() => {
  const value = latestLoopRun.value?.completed_at || latestLoopRun.value?.started_at
  return value ? value.replace('T', ' ').slice(0, 19) : '-'
})

async function loadLatestLoopRun() {
  loopStatusLoading.value = true
  loopLoadError.value = ''
  try {
    const response = await getLatestTrackingLoopRun()
    latestLoopRun.value = response.data?.data ?? null
  } catch (error: any) {
    loopLoadError.value = error?.response?.data?.detail || error?.message || '运行状态加载失败'
  } finally {
    loopStatusLoading.value = false
  }
}

async function runPostCloseLoop() {
  try {
    await ElMessageBox.confirm(
      '将同步活跃跟踪股票行情、执行规则评估并分发待处理告警。确认现在运行吗？',
      '运行收盘循环',
      { type: 'warning', confirmButtonText: '运行', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  loopLoading.value = true
  try {
    const response = await runTrackingPostClose({
      trigger: 'manual',
      sync_first: true,
      slot: 'post_close',
      per_slot_limit: 8,
    })
    const result = response.data?.data
    if (!result) throw new Error('后端未返回收盘循环结果')
    latestLoopRun.value = result

    if (result?.status === 'busy') {
      ElMessage.warning('已有收盘循环正在运行，请稍后刷新状态')
    } else if (result?.status === 'partial') {
      ElMessage.warning(`收盘循环部分完成：${trackingLoopSummary(result)}`)
    } else if (result?.status === 'error') {
      ElMessage.error(`收盘循环失败：${trackingLoopSummary(result)}`)
    } else {
      ElMessage.success(`收盘循环完成：${trackingLoopSummary(result)}`)
    }

    if (result?.status !== 'busy') clearKlineCache()
    await Promise.all([refreshItems(), loadLatestLoopRun()])
  } catch (error: any) {
    ElMessage.error(`收盘循环请求失败：${error?.response?.data?.detail || error?.message || error}`)
  } finally {
    loopLoading.value = false
  }
}

// —— 单股添加状态 ——
// 设计原因：批量导入对运营是高频路径；但调试/补单/试加单股票时弹窗+粘贴框过重，
// 因此提供 toolbar 上的极简单股入口，并自动按代码查询名称。
const singleAddForm = ref({
  code: '',
  name: '',
  entry_price: undefined as number | undefined,
  quantity: undefined as number | undefined,
  signal_date: '',
})
const singleAddLoading = ref(false)
const singleNameLoading = ref(false)
let stockNameTimer: ReturnType<typeof setTimeout> | null = null
// 是否手动修过买入价：一旦用户改动过 entry_priceー不再自动覆盖。
// 重置表单、或者 code/signal_date 变化时清零。
const entryPriceManuallyEdited = ref(false)
let signalCloseTimer: ReturnType<typeof setTimeout> | null = null

// 根据 code+signal_date 拉信号日收盘价，填为买入价默认值。
// 设计反应：只在未被手动修过且 code 合法、signal_date 非空时执行，
// 并且后端返回的 close 为有效数字才赋值，避免抹掊用户的输入。
function tryFillEntryPriceFromSignal() {
  if (entryPriceManuallyEdited.value) return
  const code = (singleAddForm.value.code || '').trim()
  const date = singleAddForm.value.signal_date
  if (!/^\d{6}$/.test(code) || !date) return
  if (signalCloseTimer) {
    clearTimeout(signalCloseTimer)
    signalCloseTimer = null
  }
  signalCloseTimer = setTimeout(async () => {
    try {
      const resp = await getSignalClose(code, date)
      const close = resp.data?.data?.close
      if (typeof close === 'number' && close > 0 && !entryPriceManuallyEdited.value) {
        singleAddForm.value.entry_price = close
      }
    } catch (e) {
      // 静默失败：用户可手填买入价
    }
  }, 300)
}

function onSingleSignalDateChange(value: string | null) {
  singleAddForm.value.signal_date = value || ''
  entryPriceManuallyEdited.value = false
  tryFillEntryPriceFromSignal()
}

function onSingleEntryPriceChange(_value: number | undefined) {
  // 任何手动改动（含清空）都视为“用户接接控”，不再自动覆盖
  entryPriceManuallyEdited.value = true
}

// 防抖：用户输入 6 位代码后 300ms 自动查询名称；避免每次按键都打后端
function onSingleCodeChange(value: string) {
  // el-input-number / el-input 可能传入非字符串；统一字符串化
  const code = String(value ?? '').trim()
  singleAddForm.value.code = code
  // code 变动时重置“手动改过买入价”标记，以便新 code 能重新拉默认价
  entryPriceManuallyEdited.value = false
  if (stockNameTimer) {
    clearTimeout(stockNameTimer)
    stockNameTimer = null
  }
  // 不足 6 位 / 含非数字时清空名称
  if (!/^\d{6}$/.test(code)) {
    singleAddForm.value.name = ''
    return
  }
  singleNameLoading.value = true
  stockNameTimer = setTimeout(async () => {
    try {
      const resp = await getStockNameByCode(code)
      const name = resp.data?.data?.name || '未知'
      singleAddForm.value.name = name
      // 名称拉到后，顺带拉信号日收盘价默认买入价
      tryFillEntryPriceFromSignal()
    } catch (e: any) {
      // 后端 400/500 都吞掉：用户可手填名称
      singleAddForm.value.name = '未知'
    } finally {
      singleNameLoading.value = false
    }
  }, 300)
}

async function submitSingleAdd() {
  const code = singleAddForm.value.code.trim()
  if (!/^\d{6}$/.test(code)) {
    ElMessage.warning('请输入 6 位股票代码')
    return
  }
  // signal_date 缺省时用今天，确保后端能立刻找到 buy_row
  const today = new Date()
  const yyyy = today.getFullYear()
  const mm = String(today.getMonth() + 1).padStart(2, '0')
  const dd = String(today.getDate()).padStart(2, '0')
  const signalDate = singleAddForm.value.signal_date || `${yyyy}-${mm}-${dd}`

  const params: Record<string, any> = {}
  if (singleAddForm.value.entry_price && singleAddForm.value.entry_price > 0) {
    params.intent_entry_price = singleAddForm.value.entry_price
  }
  if (singleAddForm.value.quantity && singleAddForm.value.quantity > 0) {
    params.intent_quantity = singleAddForm.value.quantity
  }

  singleAddLoading.value = true
  try {
    await createTrackingItem({
      code,
      name: singleAddForm.value.name || undefined,
      strategy_name: 'manual_single',
      signal_date: signalDate,
      params: Object.keys(params).length ? params : undefined,
    })
    ElMessage.success(`已添加跟踪：${code} ${singleAddForm.value.name || ''}`)
    // 添加成功后若用户填了买入价，则立刻 PATCH 触发 force 评估；
    // 因为 createTrackingItem 仅落 params.intent_*，不会写 entry_price 列。
    if (singleAddForm.value.entry_price && singleAddForm.value.entry_price > 0) {
      try {
        // 先刷新列表拿到 tracking_id
        const resp = await listTrackingItems({ code, limit: 5 })
        const newItem = (resp.data?.data?.items ?? [])
          .find((it: TrackingItem) => it.code === code)
        if (newItem) {
          await patchTrackingEntryPrice(newItem.tracking_id, {
            entry_price: singleAddForm.value.entry_price,
            entry_date: signalDate,
            quantity: singleAddForm.value.quantity,
          })
        }
      } catch (e) {
        // 仅在控制台提示；主流程不阻断
        console.warn('单股添加后自动写入买入价失败：', e)
      }
    }
    // 重置表单
    singleAddForm.value = {
      code: '',
      name: '',
      entry_price: undefined,
      quantity: undefined,
      signal_date: '',
    }
    entryPriceManuallyEdited.value = false
    await refreshItems()
  } catch (e: any) {
    if (e?.response?.status === 400) {
      ElMessage.error(e.response?.data?.detail || '添加失败：参数错误')
    } else {
      ElMessage.error(`添加失败：${e?.message || e}`)
    }
  } finally {
    singleAddLoading.value = false
  }
}

// —— 行内编辑买入价状态 ——
// 设计原因：买入价是运营场景下最常需要回填/修正的字段（手工成交价 vs 理论开盘价不一致），
// 因此提供 popover 单字段快编，避免开二级页面。
const entryPriceEditing = ref<Record<string, { value: number | undefined; loading: boolean }>>({})
function openEntryPriceEditor(row: TrackingItem) {
  entryPriceEditing.value[row.tracking_id] = {
    value: row.entry_price ?? undefined,
    loading: false,
  }
}
async function saveEntryPrice(row: TrackingItem) {
  const state = entryPriceEditing.value[row.tracking_id]
  if (!state) return
  const newPrice = Number(state.value)
  if (!newPrice || newPrice <= 0) {
    ElMessage.warning('买入价必须大于 0')
    return
  }
  state.loading = true
  try {
    await patchTrackingEntryPrice(row.tracking_id, { entry_price: newPrice })
    ElMessage.success(`已更新 ${row.code} 买入价为 ${newPrice.toFixed(3)}，已自动重算收益`)
    delete entryPriceEditing.value[row.tracking_id]
    await refreshItems()
  } catch (e: any) {
    if (e?.response?.status === 400) {
      ElMessage.error(e.response?.data?.detail || '修改失败：当前状态不支持')
    } else if (e?.response?.status === 404) {
      ElMessage.error('记录不存在')
    } else {
      ElMessage.error(`修改失败：${e?.message || e}`)
    }
  } finally {
    if (entryPriceEditing.value[row.tracking_id]) {
      entryPriceEditing.value[row.tracking_id].loading = false
    }
  }
}

// —— 删除中状态（用于 loading 反馈） ——
const deletingBatch = ref(false)

// —— 展开行（每个跟踪项独立缓存告警 / 建议） ——
interface RowState {
  alerts: TrackingAlertItem[]
  advice: TrackingAdvice | null
  alertsLoading: boolean
  adviceLoading: boolean
  actionLoading: boolean
  // 任务 D：每行独立记录 LLM 提示词风格，不干扰其他行
  profile: 'default' | 'zettaranc_style'
}
const rowStateMap = ref<Record<string, RowState>>({})

function ensureRowState(id: string): RowState {
  if (!rowStateMap.value[id]) {
    rowStateMap.value[id] = {
      alerts: [],
      advice: null,
      alertsLoading: false,
      adviceLoading: false,
      actionLoading: false,
      profile: 'default',
    }
  }
  return rowStateMap.value[id]
}

// —— 拉取列表 ——
async function refreshItems() {
  loading.value = true
  try {
    const params: { status?: string; code?: string; limit?: number } = { limit: 200 }
    if (statusFilter.value && statusFilter.value !== 'all') params.status = statusFilter.value
    const trimmed = codeFilter.value.trim()
    if (trimmed) params.code = trimmed
    const resp = await listTrackingItems(params)
    items.value = resp.data?.data?.items ?? []
  } catch (e: any) {
    ElMessage.error(`加载跟踪列表失败：${e?.message || e}`)
  } finally {
    loading.value = false
  }
}

// —— 批量规则评估（P5） ——
async function runBatchEvaluate() {
  batchLoading.value = true
  try {
    const resp = await evaluateTrackingRules({})
    const summary = resp.data?.data ?? {}
    ElMessage.success(
      `评估完成：已评估 ${summary.evaluated ?? 0} 条；新增告警 ${summary.alerts_created ?? 0}（去重 ${summary.alerts_skipped_dup ?? 0}）`,
    )
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`批量评估失败：${e?.message || e}`)
  } finally {
    batchLoading.value = false
  }
}

// —— 单条评估 ——
async function evaluateOne(item: TrackingItem) {
  try {
    await evaluateTrackingItem(item.tracking_id)
    ElMessage.success(`已评估 ${item.code}`)
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`评估失败：${e?.message || e}`)
  }
}

// —— 批量导入：打开对话框 ——
function openImportDialog() {
  importText.value = ''
  importSignalDate.value = ''
  importEvaluateNow.value = true
  importRefreshData.value = true
  importDialogVisible.value = true
}

// —— 收盘同步：更新活跃跟踪股票行情并推进评估状态 ——
async function runSyncClose() {
  syncCloseLoading.value = true
  try {
    const resp = await syncCloseTracking()
    const d = resp.data?.data ?? {}
    const updatedCnt = (d.updated ?? []).length
    const skippedCnt = (d.skipped ?? []).length
    const errorCnt = (d.errors ?? []).length
    const evalTotal = d.evaluation?.total ?? 0
    const statusChangeCnt = (d.evaluation?.status_changes ?? []).length
    // 收盘同步会改写本地 CSV；清掉浏览器内存中的旧 K 线，避免跳转详情页仍显示同步前日期。
    clearKlineCache()
    ElMessage.success(
      `收盘同步完成：行情更新 ${updatedCnt} 只 / 跳过 ${skippedCnt} / 失败 ${errorCnt}；` +
      `已评估 ${evalTotal} 条，状态推进 ${statusChangeCnt} 条`,
    )
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`收盘同步失败：${e?.message || e}`)
  } finally {
    syncCloseLoading.value = false
  }
}

// —— 批量导入：从 TXT 文件读取并填充粘贴框 ——
function handleImportFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  // 仅接受文本类（.txt / .csv），> 1MB 直接拒绝避免误传整个数据集
  if (file.size > 1024 * 1024) {
    ElMessage.error('文件超过 1MB，请精简后再上传')
    input.value = ''
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    // 追加而不是覆盖，运营可以多文件合并
    const text = String(reader.result ?? '')
    importText.value = importText.value ? `${importText.value}\n${text}` : text
  }
  reader.onerror = () => ElMessage.error('读取文件失败')
  reader.readAsText(file)
  input.value = ''
}

// —— 批量导入：提交 ——
async function submitImport() {
  const text = importText.value.trim()
  if (!text) {
    ElMessage.warning('请粘贴代码或上传 TXT')
    return
  }
  importLoading.value = true
  try {
    const payload: any = { text, evaluate_now: importEvaluateNow.value, refresh_data: importRefreshData.value }
    if (importSignalDate.value) payload.signal_date = importSignalDate.value
    const resp = await batchCreateTrackingItems(payload)
    const data = resp.data?.data ?? {}
    const createdCnt = (data.created ?? []).length
    const skippedCnt = (data.skipped ?? []).length
    const failedCnt = (data.failed ?? []).length
    ElMessage.success(
      `批量导入完成：新增 ${createdCnt} 条 / 跳过 ${skippedCnt} 条 / 失败 ${failedCnt} 条`,
    )
    importDialogVisible.value = false
    await refreshItems()
  } catch (e: any) {
    if (e?.response?.status === 400) {
      ElMessage.error(e.response?.data?.detail || '导入失败：未识别到任何 6 位代码')
    } else {
      ElMessage.error(`导入失败：${e?.message || e}`)
    }
  } finally {
    importLoading.value = false
  }
}

// —— 批量删除 ——
async function batchDeleteSelected() {
  const ids = selectedItems.value.map((it) => it.tracking_id)
  if (ids.length === 0) {
    ElMessage.warning('请先勾选要删除的跟踪记录')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${ids.length} 条跟踪记录？删除后将同时清理其历史评估事件，且不可恢复。`,
      '确认批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  deletingBatch.value = true
  try {
    const resp = await batchDeleteTrackingItems(ids)
    const data = resp.data?.data ?? {}
    const deletedCnt = (data.deleted ?? []).length
    const notFoundCnt = (data.not_found ?? []).length
    ElMessage.success(`已删除 ${deletedCnt} 条；未找到 ${notFoundCnt} 条`)
    selectedIds.value = new Set()
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`批量删除失败：${e?.message || e}`)
  } finally {
    deletingBatch.value = false
  }
}

// —— 单条删除（行内入口，幂等：not_found 直接提示） ——
async function deleteOne(item: TrackingItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${item.code} ${item.name || ''} 的跟踪记录？`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteTrackingItem(item.tracking_id)
    ElMessage.success(`已删除 ${item.code}`)
    selectedIds.value.delete(item.tracking_id)
    await refreshItems()
  } catch (e: any) {
    if (e?.response?.status === 404) {
      ElMessage.warning('记录已不存在，刷新中…')
      await refreshItems()
    } else {
      ElMessage.error(`删除失败：${e?.message || e}`)
    }
  }
}

// —— 展开时拉取告警 ——
async function handleExpand(row: TrackingItem, expandedRows: TrackingItem[]) {
  const isOpen = expandedRows.some((r) => r.tracking_id === row.tracking_id)
  if (!isOpen) return
  const state = ensureRowState(row.tracking_id)
  if (state.alerts.length > 0 || state.alertsLoading) return
  state.alertsLoading = true
  try {
    const resp = await listTrackingAlerts({ tracking_id: row.tracking_id, limit: 50 })
    state.alerts = resp.data?.data?.items ?? []
  } catch (e: any) {
    ElMessage.error(`加载告警失败：${e?.message || e}`)
  } finally {
    state.alertsLoading = false
  }
}

async function markAlert(row: TrackingItem, alert: TrackingAlertItem, action: 'ack' | 'ignore') {
  if (!alert.alert_id) return
  const state = ensureRowState(row.tracking_id)
  state.actionLoading = true
  try {
    if (action === 'ack') {
      await acknowledgeTrackingAlert(alert.alert_id)
      ElMessage.success('已确认告警')
    } else {
      await ignoreTrackingAlert(alert.alert_id)
      ElMessage.success('已忽略告警')
    }
    const resp = await listTrackingAlerts({ tracking_id: row.tracking_id, limit: 50 })
    state.alerts = resp.data?.data?.items ?? []
  } catch (e: any) {
    ElMessage.error(`更新告警状态失败：${e?.message || e}`)
  } finally {
    state.actionLoading = false
  }
}

// —— LLM 建议 ——
async function fetchAdvice(row: TrackingItem) {
  const state = ensureRowState(row.tracking_id)
  state.adviceLoading = true
  try {
    const resp = await getTrackingLLMAdvice(row.tracking_id, state.profile)
    state.advice = resp.data?.data ?? null
    ElMessage.success('已获取操盘建议')
  } catch (e: any) {
    if (e?.response?.status === 404) {
      ElMessage.error('跟踪记录不存在')
    } else {
      ElMessage.error(`获取建议失败：${e?.message || e}`)
    }
  } finally {
    state.adviceLoading = false
  }
}

// —— 确认 OrderIntent ——
async function confirmIntent(row: TrackingItem) {
  const state = ensureRowState(row.tracking_id)
  // OrderIntent 必须走人工确认；建议服务返回的是 suggested_intent，不是自动下单指令。
  const intent = state.advice?.suggested_intent ?? row.latest_intent ?? null
  state.actionLoading = true
  try {
    await confirmTrackingIntent(row.tracking_id, intent)
    ElMessage.success(`已确认操盘指令：${row.code}`)
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`确认失败：${e?.message || e}`)
  } finally {
    state.actionLoading = false
  }
}

// —— 否决 OrderIntent ——
async function rejectIntent(row: TrackingItem) {
  const state = ensureRowState(row.tracking_id)
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('请输入否决原因（操盘手判断）', '否决建议', {
      confirmButtonText: '提交',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：假信号 / 大盘风险 / 已手动平仓',
    })
    reason = result.value || ''
  } catch {
    return
  }
  state.actionLoading = true
  try {
    await rejectTrackingIntent(row.tracking_id, reason)
    ElMessage.success(`已否决，next_action 已重置为 HOLD`)
    await refreshItems()
  } catch (e: any) {
    ElMessage.error(`否决失败：${e?.message || e}`)
  } finally {
    state.actionLoading = false
  }
}

// —— 状态展示辅助 ——
const STATUS_TAG: Record<string, string> = {
  watch_buy: 'warning',
  holding: 'success',
  partial_sold: 'info',
  closed: '',
}

function statusType(s?: string) {
  if (!s) return ''
  return STATUS_TAG[s] ?? ''
}

function returnPctText(v?: number | null) {
  if (v === null || v === undefined) return '-'
  return `${v >= 0 ? '+' : ''}${(v as number).toFixed(2)}%`
}

function priorityTagType(p?: number) {
  if (p === undefined || p === null) return 'info'
  if (p < 30) return 'danger'
  if (p < 60) return 'warning'
  return 'info'
}

const hasItems = computed(() => items.value.length > 0)

onMounted(() => {
  void Promise.all([refreshItems(), loadLatestLoopRun()])
})
</script>

<template>
  <div class="tracking-view">
    <div class="toolbar">
      <el-select v-model="statusFilter" style="width: 160px" placeholder="状态">
        <el-option label="全部" value="all" />
        <el-option label="待买入 watch_buy" value="watch_buy" />
        <el-option label="持仓 holding" value="holding" />
        <el-option label="部分卖出 partial_sold" value="partial_sold" />
        <el-option label="已平仓 closed" value="closed" />
      </el-select>
      <el-input
        v-model="codeFilter"
        placeholder="按代码过滤（6 位）"
        style="width: 180px"
        clearable
      />
      <el-button type="primary" :loading="loading" @click="refreshItems">刷新</el-button>
      <el-button type="success" :loading="batchLoading" @click="runBatchEvaluate">
        批量规则评估
      </el-button>
      <el-button type="info" :loading="syncCloseLoading" @click="runSyncClose">
        收盘同步
      </el-button>
      <el-button type="warning" @click="openImportDialog">批量导入</el-button>
      <el-button
        type="danger"
        :disabled="selectedCount === 0"
        :loading="deletingBatch"
        @click="batchDeleteSelected"
      >
        批量删除（{{ selectedCount }}）
      </el-button>
      <span class="hint">共 {{ items.length }} 条</span>
    </div>

    <section
      class="loop-status-bar"
      data-test="tracking-loop-status"
      v-loading="loopStatusLoading"
    >
      <div class="loop-status-main">
        <div class="loop-status-heading">
          <strong>收盘循环</strong>
          <el-tag :type="loopStatusMeta.tagType as any" size="small">
            {{ loopStatusMeta.label }}
          </el-tag>
          <span class="loop-status-time">{{ loopRunTime }}</span>
        </div>
        <div class="loop-status-summary" :class="{ 'is-error': loopLoadError }">
          {{ loopLoadError || trackingLoopSummary(latestLoopRun) }}
        </div>
      </div>
      <div class="loop-status-actions">
        <el-button
          :icon="RefreshRight"
          circle
          title="刷新收盘循环状态"
          aria-label="刷新收盘循环状态"
          :loading="loopStatusLoading"
          @click="loadLatestLoopRun"
        />
        <el-button
          type="primary"
          :icon="VideoPlay"
          data-test="run-tracking-loop"
          :loading="loopLoading"
          @click="runPostCloseLoop"
        >
          运行收盘循环
        </el-button>
      </div>
    </section>

    <!-- 单股添加表单：代码 → 自动补全名称 → 可选买入价/数量 → 添加 -->
    <div class="toolbar single-add-bar">
      <span class="single-add-label">单股添加：</span>
      <el-input
        :model-value="singleAddForm.code"
        @update:model-value="onSingleCodeChange"
        placeholder="6 位代码"
        style="width: 130px"
        maxlength="6"
        clearable
      />
      <el-input
        v-model="singleAddForm.name"
        placeholder="名称（自动）"
        style="width: 140px"
        :loading="singleNameLoading"
      />
      <el-input-number
        v-model="singleAddForm.entry_price"
        :precision="3"
        :min="0"
        :step="0.01"
        placeholder="买入价(默认信号日收盘)"
        controls-position="right"
        style="width: 180px"
        @change="onSingleEntryPriceChange"
      />
      <el-input-number
        v-model="singleAddForm.quantity"
        :min="0"
        :step="100"
        placeholder="数量(可选)"
        controls-position="right"
        style="width: 140px"
      />
      <el-date-picker
        v-model="singleAddForm.signal_date"
        type="date"
        value-format="YYYY-MM-DD"
        placeholder="信号日(默认今天)"
        style="width: 180px"
        @change="onSingleSignalDateChange"
      />
      <el-button type="primary" :loading="singleAddLoading" @click="submitSingleAdd">
        添加跟踪
      </el-button>
    </div>

    <el-empty v-if="!loading && !hasItems" description="暂无跟踪记录" />

    <el-table
      v-else
      :data="items"
      v-loading="loading"
      style="width: 100%"
      row-key="tracking_id"
      @expand-change="handleExpand"
      @selection-change="handleSelectionChange"
    >
      <!-- 勾选列：表头自带"全选"，满足批量删除需求 -->
      <el-table-column type="selection" width="48" reserve-selection />
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand-panel">
            <!-- 告警列表 -->
            <div class="panel-block">
              <h4>近期告警</h4>
              <el-table
                :data="rowStateMap[row.tracking_id]?.alerts ?? []"
                v-loading="rowStateMap[row.tracking_id]?.alertsLoading"
                size="small"
                empty-text="暂无告警"
              >
                <el-table-column prop="eval_date" label="评估日" width="110" />
                <el-table-column label="优先级" width="90">
                  <template #default="{ row: a }">
                    <el-tag :type="priorityTagType(a.priority)" size="small">
                      {{ a.priority ?? '-' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="rule_id" label="规则" width="160" show-overflow-tooltip />
                <el-table-column prop="ui_status" label="状态" width="100" />
                <el-table-column prop="message" label="说明" show-overflow-tooltip />
                <el-table-column label="处理" width="150">
                  <template #default="{ row: a }">
                    <el-button
                      size="small"
                      link
                      type="primary"
                      :loading="rowStateMap[row.tracking_id]?.actionLoading"
                      @click="markAlert(row, a, 'ack')"
                    >
                      已确认
                    </el-button>
                    <el-button
                      size="small"
                      link
                      type="info"
                      :loading="rowStateMap[row.tracking_id]?.actionLoading"
                      @click="markAlert(row, a, 'ignore')"
                    >
                      忽略
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <!-- LLM 建议 -->
            <div class="panel-block">
              <h4>LLM 操盘建议（mock/DeepSeek，仅供参考）</h4>
              <el-select
                v-model="rowStateMap[row.tracking_id]!.profile"
                size="small"
                style="width: 160px; margin-right: 8px"
              >
                <el-option label="默认助理口吻" value="default" />
                <el-option label="zettaranc 手游风" value="zettaranc_style" />
              </el-select>
              <el-button
                size="small"
                type="primary"
                :loading="rowStateMap[row.tracking_id]?.adviceLoading"
                @click="fetchAdvice(row)"
              >
                获取 / 刷新建议
              </el-button>
              <div v-if="rowStateMap[row.tracking_id]?.advice" class="advice">
                <div class="advice-meta">
                  <el-tag size="small">
                    {{ rowStateMap[row.tracking_id]!.advice?.profile || 'default' }}
                  </el-tag>
                  <el-tag
                    :type="rowStateMap[row.tracking_id]!.advice?.provider_fallback ? 'warning' : 'success'"
                    size="small"
                  >
                    provider fallback: {{ rowStateMap[row.tracking_id]!.advice?.provider_fallback ? 'yes' : 'no' }}
                  </el-tag>
                  <el-tag
                    v-if="rowStateMap[row.tracking_id]!.advice?.zettaranc_data_source"
                    type="info"
                    size="small"
                  >
                    Zettaranc: {{ rowStateMap[row.tracking_id]!.advice?.zettaranc_data_source }}
                  </el-tag>
                  <el-tag
                    v-if="rowStateMap[row.tracking_id]!.advice?.llm_mismatch"
                    type="warning"
                    size="small"
                  >
                    规则覆盖: {{ rowStateMap[row.tracking_id]!.advice?.rule_action_label || 'priority' }}
                  </el-tag>
                </div>
                <pre>{{ JSON.stringify(rowStateMap[row.tracking_id]!.advice, null, 2) }}</pre>
              </div>
            </div>

            <!-- 操盘确认 / 否决 -->
            <div class="panel-block">
              <h4>操盘手动作</h4>
              <el-button
                type="success"
                size="small"
                :loading="rowStateMap[row.tracking_id]?.actionLoading"
                @click="confirmIntent(row)"
              >
                确认 OrderIntent
              </el-button>
              <el-button
                type="danger"
                size="small"
                :loading="rowStateMap[row.tracking_id]?.actionLoading"
                @click="rejectIntent(row)"
              >
                否决并重置 HOLD
              </el-button>
              <el-button size="small" @click="evaluateOne(row)">单条评估</el-button>
              <div v-if="row.latest_intent" class="advice">
                <span class="muted">latest_intent：</span>
                <pre>{{ JSON.stringify(row.latest_intent, null, 2) }}</pre>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>

      <!-- 代码/名称可点击跳转 K 线详情，提升运营查看效率 -->
      <el-table-column label="代码" width="100">
        <template #default="{ row }">
          <el-link type="primary" :underline="false" @click="goStockDetail(row.code)">{{ row.code }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="名称" width="120">
        <template #default="{ row }">
          <el-link
            class="tracking-stock-name"
            type="primary"
            :underline="false"
            :title="row.name || row.code"
            @click="goStockDetail(row.code)"
          >{{ row.name || '-' }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="strategy_name" label="策略" width="140" show-overflow-tooltip />
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status) as any" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="signal_date" label="信号日" width="110" />
      <el-table-column label="买入点" width="170">
        <template #default="{ row }">
          <!-- 行内编辑买入价：点击"修改"打开 popover -->
          <el-popover
            placement="top"
            :width="260"
            trigger="click"
            @show="openEntryPriceEditor(row)"
          >
            <template #reference>
              <div v-if="row.entry_price != null" class="entry-price-cell">
                <div>
                  <span>{{ Number(row.entry_price).toFixed(3) }}</span>
                  <el-button link size="small" type="primary">改</el-button>
                </div>
                <div class="muted" v-if="row.entry_date">{{ row.entry_date }}</div>
              </div>
              <span v-else class="muted">
                未触发
                <el-button link size="small" type="primary">手填</el-button>
              </span>
            </template>
            <div class="entry-price-editor">
              <div class="muted" style="margin-bottom: 6px">
                修改买入价后会自动按 CSV 重新计算 latest_return_pct
              </div>
              <el-input-number
                v-if="entryPriceEditing[row.tracking_id]"
                v-model="entryPriceEditing[row.tracking_id].value"
                :precision="3"
                :min="0.01"
                :step="0.01"
                style="width: 100%"
              />
              <div style="margin-top: 8px; text-align: right">
                <el-button
                  size="small"
                  type="primary"
                  :loading="entryPriceEditing[row.tracking_id]?.loading"
                  @click="saveEntryPrice(row)"
                >
                  保存
                </el-button>
              </div>
            </div>
          </el-popover>
        </template>
      </el-table-column>
      <el-table-column prop="last_eval_date" label="最近评估" width="110" />
      <el-table-column label="跟踪交易日" width="100" align="right">
        <!-- 后端基于 CSV 计算从 signal_date/entry_date 到 last_eval_date/今天的真实交易日计数，
             跳过周末与停牌；为 0 时表示还未评估过或 CSV 中查不到区间行。 -->
        <template #default="{ row }">
          <span>{{ row.tracked_trading_days ?? '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="跟踪收益" width="110">
        <template #default="{ row }">
          <span :class="(row.latest_return_pct ?? 0) >= 0 ? 'pos' : 'neg'">
            {{ returnPctText(row.latest_return_pct) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="next_action" label="下一步" width="120" />
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <div class="tracking-row-actions">
            <AddToTodayReviewButton :code="row.code" :name="row.name" />
            <el-button size="small" type="danger" link @click="deleteOne(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 批量导入对话框：TXT 上传 + 多行粘贴 + 可选信号日 -->
    <el-dialog v-model="importDialogVisible" title="批量导入跟踪代码" width="560px">
      <div class="import-body">
        <div class="import-row">
          <label class="import-label">从 TXT 读取：</label>
          <input
            type="file"
            accept=".txt,.csv,text/plain"
            @change="handleImportFileChange"
          />
          <span class="muted">支持 .txt/.csv，≤1MB，可多次追加</span>
        </div>
        <div class="import-row">
          <label class="import-label">代码列表（粘贴）：</label>
          <el-input
            v-model="importText"
            type="textarea"
            :rows="8"
            placeholder="一行一个代码，或用空格 / 逗号 / 分号分隔。例如：&#10;600000&#10;000001, 600519&#10;sh600036（前缀会被自动去掉）"
          />
        </div>
        <div class="import-row">
          <label class="import-label">信号日（可选）：</label>
          <el-date-picker
            v-model="importSignalDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="留空则使用今天"
            style="width: 200px"
          />
        </div>
        <div class="import-row">
          <label class="import-label">导入后立即评估：</label>
          <el-switch v-model="importEvaluateNow" />
          <span class="muted">开启可立刻看到买入点 / 跟踪收益</span>
        </div>
        <div class="import-row">
          <label class="import-label">导入前刷新行情：</label>
          <el-switch v-model="importRefreshData" />
          <span class="muted">推荐开启；若 CSV 陈旧则评估无法落 entry_price</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importLoading" @click="submitImport">
          确认导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.tracking-view {
  padding: 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.toolbar .hint {
  color: var(--text-secondary);
  font-size: 12px;
}
.loop-status-bar {
  min-height: 64px;
  margin-bottom: 16px;
  padding: 10px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--border-color);
  border-left: 3px solid var(--el-color-primary);
  background: var(--bg-secondary);
}
.loop-status-main {
  min-width: 0;
}
.loop-status-heading,
.loop-status-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.loop-status-heading strong {
  font-size: 14px;
  color: var(--text-primary);
}
.loop-status-time,
.loop-status-summary {
  color: var(--text-secondary);
  font-size: 12px;
}
.loop-status-summary {
  margin-top: 5px;
  overflow-wrap: anywhere;
}
.loop-status-summary.is-error {
  color: var(--el-color-danger);
}
.loop-status-actions {
  flex: 0 0 auto;
}
.single-add-bar {
  background: var(--bg-secondary);
  padding: 8px 12px;
  border-radius: 4px;
  border: 1px dashed var(--border-color);
}
.single-add-label {
  color: var(--text-secondary);
  font-size: 13px;
}
.entry-price-cell {
  cursor: pointer;
}
.tracking-stock-name {
  display: inline-flex;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tracking-row-actions {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  white-space: nowrap;
}
.entry-price-editor {
  font-size: 12px;
}
.expand-panel {
  padding: 12px 24px;
  background: var(--bg-tertiary);
}
.panel-block {
  margin-bottom: 14px;
}
.panel-block h4 {
  margin: 0 0 8px 0;
  font-size: 13px;
  color: var(--text-primary);
}
.advice {
  margin-top: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 8px;
  max-height: 260px;
  overflow: auto;
}
.advice-meta {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.advice pre {
  margin: 0;
  font-size: 12px;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-all;
}
.muted {
  color: var(--text-secondary);
  font-size: 12px;
}
.pos {
  color: #f56c6c;
}
.neg {
  color: #67c23a;
}
.import-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.import-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.import-label {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 500;
}
@media (max-width: 760px) {
  .loop-status-bar {
    align-items: stretch;
    flex-direction: column;
  }
  .loop-status-actions {
    justify-content: flex-end;
  }
}
</style>
