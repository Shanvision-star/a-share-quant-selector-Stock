<script setup lang="ts">
// Zettaranc 综合看板：3 个 Tab
//   ① 回测结果（读取 latest，可一键小池子回跑）
//   ② 持仓纪律（CRUD + 自动巡检告警）
//   ③ 攻击日候选（今日入场扫描）
// 为什么集中在一个视图：三件套互相关联 —— 回测验证策略可行，攻击日提供候选，
// 持仓纪律保证执行。一个页面三个 tab 比拆成 3 个路由更贴合 zettaranc 工作流。

import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchBacktestLatest,
  runBacktest,
  listHoldings,
  addHolding,
  updateHolding,
  deleteHolding,
  fetchHoldingAlerts,
  fetchAttackCandidates,
  type BacktestSummary,
  type Holding,
  type HoldingAlert,
  type AttackCandidate,
} from '@/api/zettaranc'

const activeTab = ref<'backtest' | 'holdings' | 'attack'>('backtest')

// ---------- 回测 ----------
const backtest = ref<BacktestSummary | null>(null)
const backtestLoading = ref(false)
const backtestForm = reactive({
  start: '2024-01-01',
  end: '',
  limit: 20,
  take_profit: 15.0,
  hold_days: 20,
  j_buy: 0.0,
  vol_ratio: 1.3,
})

async function loadBacktest() {
  backtestLoading.value = true
  try {
    backtest.value = await fetchBacktestLatest()
  } catch (e: any) {
    ElMessage.warning(`暂无回测结果：${e?.response?.data?.detail || e?.message || e}`)
    backtest.value = null
  } finally {
    backtestLoading.value = false
  }
}

async function triggerBacktest() {
  backtestLoading.value = true
  try {
    backtest.value = await runBacktest({ ...backtestForm })
    ElMessage.success('回测完成')
  } catch (e: any) {
    ElMessage.error(`回测失败：${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    backtestLoading.value = false
  }
}

// ---------- 持仓 ----------
const holdings = ref<Holding[]>([])
const alerts = ref<HoldingAlert[]>([])
const alertSummary = ref({ total: 0, critical: 0, warn: 0 })
const holdingsLoading = ref(false)
const holdingDialog = ref(false)
const editingCode = ref<string | null>(null)
const holdingForm = reactive<Holding>({
  code: '', name: '', entry_date: '', entry_price: 0, qty: 0, stop_loss: 0,
  take_profit_pct: 15, hold_days_limit: 20, max_position_pct: 10, total_capital: 1_000_000,
  notes: '',
})

function resetHoldingForm() {
  editingCode.value = null
  Object.assign(holdingForm, {
    code: '', name: '', entry_date: '', entry_price: 0, qty: 0, stop_loss: 0,
    take_profit_pct: 15, hold_days_limit: 20, max_position_pct: 10, total_capital: 1_000_000,
    notes: '',
  })
}

function openCreateDialog() {
  resetHoldingForm()
  holdingDialog.value = true
}

function openEditDialog(h: Holding) {
  editingCode.value = h.code
  Object.assign(holdingForm, h)
  holdingDialog.value = true
}

async function saveHolding() {
  if (!holdingForm.code || !holdingForm.entry_date) {
    ElMessage.warning('股票代码和入场日期必填')
    return
  }
  try {
    if (editingCode.value) {
      const { code: _c, ...patch } = holdingForm
      await updateHolding(editingCode.value, patch)
    } else {
      await addHolding(holdingForm)
    }
    holdingDialog.value = false
    await loadHoldings()
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(`保存失败：${e?.response?.data?.detail || e?.message || e}`)
  }
}

async function removeHolding(code: string) {
  try {
    await ElMessageBox.confirm(`确认删除持仓 ${code}？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  await deleteHolding(code)
  await loadHoldings()
}

async function loadHoldings() {
  holdingsLoading.value = true
  try {
    holdings.value = await listHoldings()
    const a = await fetchHoldingAlerts()
    alerts.value = a.alerts
    alertSummary.value = a.summary
  } catch (e: any) {
    ElMessage.error(`加载持仓失败：${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    holdingsLoading.value = false
  }
}

function severityTag(s: string) {
  if (s === 'critical') return 'danger'
  if (s === 'warn') return 'warning'
  return 'info'
}

// ---------- 攻击日扫描 ----------
const attackList = ref<AttackCandidate[]>([])
const attackLoading = ref(false)
const attackLimit = ref(50)

async function loadAttack() {
  attackLoading.value = true
  try {
    const res = await fetchAttackCandidates(attackLimit.value)
    attackList.value = res.candidates
    ElMessage.success(`扫描完成，命中 ${res.count} 只`)
  } catch (e: any) {
    ElMessage.error(`扫描失败：${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    attackLoading.value = false
  }
}

// 切 tab 时按需加载（提到 script 里避免 vue-tsc 对模板内联 TS 类型解析失败）
function onTabChange(t: string | number) {
  if (t === 'holdings') loadHoldings()
  if (t === 'attack' && attackList.value.length === 0) loadAttack()
}

onMounted(loadBacktest)
</script>

<template>
  <div class="zettaranc-view">
    <h2 class="title">Zettaranc 综合看板</h2>
    <el-tabs v-model="activeTab" @tab-change="onTabChange">
      <!-- ① 回测 -->
      <el-tab-pane label="回测结果" name="backtest">
        <el-card class="block">
          <div class="form-row">
            <el-form :inline="true" size="small">
              <el-form-item label="起始"><el-input v-model="backtestForm.start" style="width:130px" /></el-form-item>
              <el-form-item label="结束"><el-input v-model="backtestForm.end" placeholder="留空=今日" style="width:130px" /></el-form-item>
              <el-form-item label="股票数"><el-input-number v-model="backtestForm.limit" :min="1" :max="300" /></el-form-item>
              <el-form-item label="止盈%"><el-input-number v-model="backtestForm.take_profit" :step="1" /></el-form-item>
              <el-form-item label="持仓天数"><el-input-number v-model="backtestForm.hold_days" :min="1" :max="60" /></el-form-item>
              <el-form-item label="J 阈值"><el-input-number v-model="backtestForm.j_buy" :step="1" /></el-form-item>
              <el-form-item label="量比阈值"><el-input-number v-model="backtestForm.vol_ratio" :step="0.1" /></el-form-item>
              <el-button type="primary" @click="triggerBacktest" :loading="backtestLoading">运行回测</el-button>
              <el-button @click="loadBacktest" :loading="backtestLoading">刷新最新</el-button>
            </el-form>
          </div>
        </el-card>

        <el-empty v-if="!backtest" description="暂无回测结果，请先运行" />
        <template v-else>
          <el-row :gutter="12" class="block">
            <el-col :span="4"><el-statistic title="信号数" :value="backtest.total_signals" /></el-col>
            <el-col :span="4"><el-statistic title="成交笔数" :value="backtest.total_trades" /></el-col>
            <el-col :span="4"><el-statistic title="胜率%" :value="backtest.win_rate" :precision="2" /></el-col>
            <el-col :span="4"><el-statistic title="平均盈%" :value="backtest.avg_win_pct" :precision="2" /></el-col>
            <el-col :span="4"><el-statistic title="平均亏%" :value="backtest.avg_loss_pct" :precision="2" /></el-col>
            <el-col :span="4"><el-statistic title="最大回撤%" :value="backtest.max_drawdown_pct" :precision="2" /></el-col>
          </el-row>
          <el-row :gutter="12" class="block">
            <el-col :span="12">
              <el-card header="退出原因">
                <div v-for="(v, k) in backtest.exit_reason_counts" :key="k">{{ k }}: {{ v }}</div>
              </el-card>
            </el-col>
            <el-col :span="12">
              <el-card header="信号分类">
                <div v-for="(v, k) in backtest.category_counts" :key="k">{{ k }}: {{ v }}</div>
              </el-card>
            </el-col>
          </el-row>
          <el-card header="月度盈亏（%）" class="block" v-if="backtest.monthly_pnl">
            <div class="month-grid">
              <div v-for="(v, k) in backtest.monthly_pnl" :key="k" :class="['month-cell', v >= 0 ? 'win' : 'loss']">
                <div class="m-key">{{ k }}</div>
                <div class="m-val">{{ Number(v).toFixed(2) }}</div>
              </div>
            </div>
          </el-card>
        </template>
      </el-tab-pane>

      <!-- ② 持仓 -->
      <el-tab-pane label="持仓纪律" name="holdings">
        <el-card class="block">
          <el-row :gutter="12">
            <el-col :span="6"><el-statistic title="持仓数" :value="holdings.length" /></el-col>
            <el-col :span="6"><el-statistic title="告警合计" :value="alertSummary.total" /></el-col>
            <el-col :span="6"><el-statistic title="critical" :value="alertSummary.critical" value-style="color:#f56c6c" /></el-col>
            <el-col :span="6"><el-statistic title="warn" :value="alertSummary.warn" value-style="color:#e6a23c" /></el-col>
          </el-row>
          <div class="action-row">
            <el-button type="primary" @click="openCreateDialog">新增持仓</el-button>
            <el-button @click="loadHoldings" :loading="holdingsLoading">刷新</el-button>
          </div>
        </el-card>

        <el-card header="持仓列表" class="block">
          <el-table :data="holdings" size="small" empty-text="暂无持仓">
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="entry_date" label="入场日" width="110" />
            <el-table-column prop="entry_price" label="入场价" width="90" />
            <el-table-column prop="qty" label="数量" width="90" />
            <el-table-column prop="stop_loss" label="止损" width="90" />
            <el-table-column prop="take_profit_pct" label="止盈%" width="80" />
            <el-table-column prop="hold_days_limit" label="持仓上限" width="90" />
            <el-table-column prop="notes" label="备注" />
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button size="small" @click="openEditDialog(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="removeHolding(row.code)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card header="纪律告警" class="block">
          <el-table :data="alerts" size="small" empty-text="无告警">
            <el-table-column label="severity" width="100">
              <template #default="{ row }">
                <el-tag :type="severityTag(row.severity)">{{ row.severity }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="rule" label="规则" width="160" />
            <el-table-column prop="message" label="说明" />
          </el-table>
        </el-card>

        <el-dialog v-model="holdingDialog" :title="editingCode ? '编辑持仓' : '新增持仓'" width="520px">
          <el-form :model="holdingForm" label-width="100px" size="small">
            <el-form-item label="代码"><el-input v-model="holdingForm.code" :disabled="!!editingCode" /></el-form-item>
            <el-form-item label="名称"><el-input v-model="holdingForm.name" /></el-form-item>
            <el-form-item label="入场日期"><el-input v-model="holdingForm.entry_date" placeholder="YYYY-MM-DD" /></el-form-item>
            <el-form-item label="入场价"><el-input-number v-model="holdingForm.entry_price" :precision="2" :step="0.1" /></el-form-item>
            <el-form-item label="数量"><el-input-number v-model="holdingForm.qty" :step="100" /></el-form-item>
            <el-form-item label="止损价"><el-input-number v-model="holdingForm.stop_loss" :precision="2" :step="0.1" /></el-form-item>
            <el-form-item label="止盈%"><el-input-number v-model="holdingForm.take_profit_pct" :step="1" /></el-form-item>
            <el-form-item label="持仓上限"><el-input-number v-model="holdingForm.hold_days_limit" :min="1" :max="60" /></el-form-item>
            <el-form-item label="仓位上限%"><el-input-number v-model="holdingForm.max_position_pct" :step="1" /></el-form-item>
            <el-form-item label="总资本"><el-input-number v-model="holdingForm.total_capital" :step="10000" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="holdingForm.notes" type="textarea" /></el-form-item>
          </el-form>
          <template #footer>
            <el-button @click="holdingDialog = false">取消</el-button>
            <el-button type="primary" @click="saveHolding">保存</el-button>
          </template>
        </el-dialog>
      </el-tab-pane>

      <!-- ③ 攻击日 -->
      <el-tab-pane label="攻击日候选" name="attack">
        <el-card class="block">
          <el-form :inline="true" size="small">
            <el-form-item label="扫描股票数">
              <el-input-number v-model="attackLimit" :min="10" :max="2000" :step="50" />
            </el-form-item>
            <el-button type="primary" @click="loadAttack" :loading="attackLoading">开始扫描</el-button>
            <span class="hint">提示：limit 越大耗时越长（5000 只 ~ 1 分钟）</span>
          </el-form>
        </el-card>
        <el-card header="今日候选" class="block">
          <el-table :data="attackList" size="small" empty-text="无候选">
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="signal_date" label="信号日" width="110" />
            <el-table-column prop="close" label="收盘" width="90" />
            <el-table-column prop="stop_loss" label="建议止损" width="100" />
            <el-table-column prop="J" label="J" width="80" :formatter="(_r:any, _c:any, v:any) => Number(v).toFixed(2)" />
            <el-table-column prop="vol_ratio" label="量比" width="80" :formatter="(_r:any, _c:any, v:any) => Number(v).toFixed(2)" />
            <el-table-column prop="category" label="分类" width="140" />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.zettaranc-view { padding: 16px; }
.title { margin: 0 0 16px 0; }
.block { margin-bottom: 12px; }
.action-row { margin-top: 12px; }
.form-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.hint { color: var(--text-secondary); margin-left: 12px; font-size: 12px; }
.month-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; }
.month-cell { padding: 6px 8px; border-radius: 4px; text-align: center; }
.month-cell.win { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
.month-cell.loss { background: rgba(245, 108, 108, 0.12); color: #f56c6c; }
.m-key { font-size: 11px; }
.m-val { font-weight: bold; }
</style>
