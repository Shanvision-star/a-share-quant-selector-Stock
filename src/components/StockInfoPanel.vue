<script setup lang="ts">
const props = defineProps<{
  priceInfo: any
}>()

function getPriceClass(val: number) {
  if (val > 0) return 'price-up'
  if (val < 0) return 'price-down'
  return 'price-flat'
}
</script>

<template>
  <div class="stock-info-panel" v-if="priceInfo">
    <!-- 标题 -->
    <div class="panel-header">
      <span class="stock-code">{{ priceInfo.code }}</span>
      <span class="stock-name">{{ priceInfo.name }}</span>
    </div>

    <!-- 价格大字 -->
    <div class="price-big" :class="getPriceClass(priceInfo.change_pct)">
      {{ priceInfo.close }}
    </div>
    <div class="price-change" :class="getPriceClass(priceInfo.change_pct)">
      {{ priceInfo.change > 0 ? '+' : '' }}{{ priceInfo.change }}
      ({{ priceInfo.change_pct > 0 ? '+' : '' }}{{ priceInfo.change_pct }}%)
    </div>

    <!-- 基础信息 -->
    <div class="info-section">
      <div class="info-row"><span class="label">开盘</span><span>{{ priceInfo.open }}</span></div>
      <div class="info-row"><span class="label">最高</span><span class="price-up">{{ priceInfo.high }}</span></div>
      <div class="info-row"><span class="label">最低</span><span class="price-down">{{ priceInfo.low }}</span></div>
      <div class="info-row"><span class="label">昨收</span><span>{{ priceInfo.prev_close }}</span></div>
    </div>

    <!-- 成交信息 -->
    <div class="info-section">
      <div class="info-row"><span class="label">成交量</span><span>{{ priceInfo.volume }}</span></div>
      <div class="info-row"><span class="label">成交额(万)</span><span>{{ priceInfo.amount }}</span></div>
      <div class="info-row"><span class="label">换手率</span><span>{{ priceInfo.turnover }}%</span></div>
      <div class="info-row"><span class="label">市值(亿)</span><span>{{ priceInfo.market_cap }}</span></div>
    </div>

    <!-- 均线 -->
    <div class="info-section">
      <div class="info-row"><span class="label" style="color:#f5c878">MA5</span><span>{{ priceInfo.ma5 }}</span></div>
      <div class="info-row"><span class="label" style="color:#ff6d9e">MA10</span><span>{{ priceInfo.ma10 }}</span></div>
      <div class="info-row"><span class="label" style="color:#42a5f5">MA20</span><span>{{ priceInfo.ma20 }}</span></div>
      <div class="info-row"><span class="label" style="color:#ab47bc">MA60</span><span>{{ priceInfo.ma60 }}</span></div>
    </div>

    <!-- KDJ -->
    <div class="info-section">
      <div class="info-row"><span class="label">K</span><span>{{ priceInfo.k }}</span></div>
      <div class="info-row"><span class="label">D</span><span>{{ priceInfo.d }}</span></div>
      <div class="info-row"><span class="label">J</span><span>{{ priceInfo.j }}</span></div>
    </div>

    <div class="info-date">数据日期: {{ priceInfo.latest_date }}</div>
  </div>
</template>

<style scoped>
.stock-info-panel {
  width: 260px;
  padding: 16px;
  background-color: var(--bg-secondary);
  border-left: 1px solid var(--border-color);
  overflow-y: auto;
  height: 100%;
}
.panel-header {
  margin-bottom: 12px;
}
.stock-code {
  font-size: 14px;
  color: var(--text-secondary);
  margin-right: 8px;
}
.stock-name {
  font-size: 16px;
  font-weight: bold;
}
.price-big {
  font-size: 32px;
  font-weight: bold;
  margin-bottom: 4px;
}
.price-change {
  font-size: 14px;
  margin-bottom: 16px;
}
.info-section {
  border-top: 1px solid var(--border-color);
  padding: 10px 0;
}
.info-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 13px;
}
.label {
  color: var(--text-secondary);
}
.info-date {
  margin-top: 12px;
  font-size: 11px;
  color: var(--text-secondary);
  text-align: center;
}
</style>
