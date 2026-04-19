<script setup lang="ts">
const props = withDefaults(defineProps<{
  priceInfo: any
  stockInfo?: any
  side?: 'left' | 'right'
}>(), {
  side: 'right',
})

function getPriceClass(val: number) {
  if (val > 0) return 'price-up'
  if (val < 0) return 'price-down'
  return 'price-flat'
}

function getBoardClass(board: string) {
  if (board === '创业板') return 'board-cy'
  if (board === '科创板') return 'board-kc'
  if (board === '北交所') return 'board-bj'
  return 'board-zb'
}
</script>

<template>
  <div class="stock-info-panel" :class="{ 'is-left': props.side === 'left' }" v-if="priceInfo">
    <!-- 标题 -->
    <div class="panel-header">
      <span class="stock-code">{{ priceInfo.code }}</span>
      <span class="stock-name">{{ priceInfo.name }}</span>
      <span v-if="priceInfo.board" class="board-tag" :class="getBoardClass(priceInfo.board)">{{ priceInfo.board }}</span>
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

    <!-- 公司信息（来自 stockInfo 懒加载，有缓存）-->
    <div class="info-section" v-if="stockInfo && (stockInfo.industry || stockInfo.region || stockInfo.main_business)">
      <div class="section-title">公司信息</div>
      <div class="info-row" v-if="stockInfo.industry"><span class="label">行业</span><span>{{ stockInfo.industry }}</span></div>
      <div class="info-row" v-if="stockInfo.region"><span class="label">地区</span><span>{{ stockInfo.region }}</span></div>
      <div class="info-row-full" v-if="stockInfo.main_business">
        <span class="label">主要产品研发方向</span>
        <div class="info-value-wrap">{{ stockInfo.main_business }}</div>
      </div>
    </div>
    <div class="info-section" v-else-if="!stockInfo">
      <div class="section-title">公司信息</div>
      <div class="concept-loading">加载中...</div>
    </div>

    <!-- 概念标签 -->
    <div class="info-section">
      <div class="section-title">概念板块</div>
      <div v-if="!stockInfo" class="concept-loading">加载中...</div>
      <div v-else-if="stockInfo.concept_tags && stockInfo.concept_tags.length" class="concept-tags">
        <span v-for="tag in stockInfo.concept_tags" :key="tag" class="concept-tag">{{ tag }}</span>
      </div>
      <div v-else class="concept-loading">暂无概念数据</div>
    </div>

    <!-- 近期表现 -->
    <div class="info-section" v-if="priceInfo.max_gain_30d != null || priceInfo.max_daily_gain_30d != null">
      <div class="section-title">近30日表现</div>
      <div class="info-row" v-if="priceInfo.max_gain_30d != null">
        <span class="label">最大涨幅</span>
        <span class="price-up">{{ priceInfo.max_gain_30d > 0 ? '+' : '' }}{{ priceInfo.max_gain_30d }}%</span>
      </div>
      <div class="info-row" v-if="priceInfo.max_daily_gain_30d != null">
        <span class="label">单日最大涨幅</span>
        <span class="price-up">{{ priceInfo.max_daily_gain_30d > 0 ? '+' : '' }}{{ priceInfo.max_daily_gain_30d }}%</span>
      </div>
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
.stock-info-panel.is-left {
  border-left: none;
  border-right: 1px solid var(--border-color);
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
/* ── 板块标签 ─────────────────────────────────────────────────── */
.board-tag {
  display: inline-block;
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  color: #fff;
  margin-left: 4px;
  vertical-align: middle;
  line-height: 1.5;
}
.board-zb { background: #409eff; }
.board-cy { background: #67c23a; }
.board-kc { background: #f56c6c; }
.board-bj { background: #e6a23c; }
/* ── 区块标题 ─────────────────────────────────────────────────── */
.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #303133);
  margin-bottom: 6px;
}
/* ── 主营业务换行 ─────────────────────────────────────────────── */
.info-row-full {
  padding: 3px 0;
  font-size: 13px;
}
.info-row-full .label {
  color: var(--text-secondary);
  display: block;
  margin-bottom: 2px;
}
.info-value-wrap {
  font-size: 12px;
  color: var(--text-primary, #606266);
  line-height: 1.5;
  word-break: break-all;
  max-height: 80px;
  overflow-y: auto;
}
/* ── 概念标签 ─────────────────────────────────────────────────── */
.concept-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.concept-tag {
  display: inline-block;
  font-size: 10px;
  padding: 1px 5px;
  background: rgba(64, 158, 255, 0.1);
  color: #409eff;
  border: 1px solid rgba(64, 158, 255, 0.3);
  border-radius: 3px;
  line-height: 1.5;
}
.concept-loading {
  font-size: 11px;
  color: var(--text-secondary, #909399);
}
</style>
