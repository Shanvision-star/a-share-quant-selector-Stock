<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import KlineChart from '@/components/KlineChart.vue'
import StockInfoPanel from '@/components/StockInfoPanel.vue'
import { getKline, getStockPrice, getStrategyResults } from '@/api'

const props = defineProps<{ code: string }>()

const period = ref('daily')
const klineData = ref<any>(null)
const priceInfo = ref<any>(null)
const signals = ref<any[]>([])
const strategyCard = ref<any>(null)
const loading = ref(false)
const showShortTermTrend = ref(true)
const showBullBearLine = ref(true)

onMounted(() => {
  loadAll(props.code)
})

watch(() => props.code, (newCode) => {
  loadAll(newCode)
})

async function loadAll(code: string) {
  loading.value = true
  try {
    const [kRes, pRes] = await Promise.all([
      getKline(code, { period: period.value, limit: 250 }),
      getStockPrice(code),
    ])

    klineData.value = kRes.data.data
    priceInfo.value = pRes.data.data

    void loadSignals(code)
  } catch (e) {
    console.error('加载失败', e)
  } finally {
    loading.value = false
  }
}

async function loadSignals(code: string) {
  try {
    const response = await getStrategyResults({ strategy: 'all' })
    const allResults = response.data.data?.results || []

    const matched = allResults.filter((row: any) => row.code === code)
    strategyCard.value = matched[0] || null
    signals.value = matched.map((item: any) => ({
      date: item.date,
      close: item.trigger_price || item.close,
      category: item.category || item.strategy_name,
      label: item.strategy_name === 'B1CaseStrategy' ? 'B1' : item.strategy_name === 'BowlReboundStrategy' ? '碗' : 'B2',
    }))
  } catch (e) {
    console.error('加载策略信号失败', e)
    strategyCard.value = null
    signals.value = []
  }
}

function onPeriodChange(nextPeriod: string) {
  period.value = nextPeriod
  getKline(props.code, { period: nextPeriod, limit: 250 }).then((res) => {
    klineData.value = res.data.data
  })
}
</script>

<template>
  <div class="stock-detail" v-loading="loading">
    <div class="detail-main">
      <div class="detail-header">
        <h2>{{ priceInfo?.name }} {{ code }}</h2>
        <div class="detail-actions">
          <el-checkbox v-model="showShortTermTrend">短期趋势线</el-checkbox>
          <el-checkbox v-model="showBullBearLine">知行多空线</el-checkbox>
          <el-radio-group v-model="period" size="small" @change="onPeriodChange">
            <el-radio-button value="daily">日K</el-radio-button>
            <el-radio-button value="weekly">周K</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <div class="chart-area">
        <KlineChart
          :code="code"
          :period="period"
          :limit="250"
          :signals="signals"
          :show-short-term-trend="showShortTermTrend"
          :show-bull-bear-line="showBullBearLine"
        />
      </div>

      <div class="strategy-card" v-if="strategyCard">
        <el-card shadow="never">
          <template #header>策略匹配详情</template>
          <p><strong>策略:</strong> {{ strategyCard.strategy_name }}</p>
          <p><strong>分类:</strong> {{ strategyCard.category }}</p>
          <p><strong>匹配日期:</strong> {{ strategyCard.date }}</p>
          <p v-if="strategyCard.reason"><strong>原因:</strong> {{ strategyCard.reason }}</p>
        </el-card>
      </div>
    </div>

    <StockInfoPanel :price-info="priceInfo" />
  </div>
</template>

<style scoped>
.stock-detail {
  display: flex;
  height: 100%;
}
.detail-main {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.detail-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
}
.detail-header h2 {
  margin: 0;
  font-size: 18px;
}
.chart-area {
  height: 600px;
  margin-bottom: 16px;
}
.strategy-card {
  margin-top: 8px;
}
</style>
