<script setup lang="ts">
import MiniKline from './MiniKline.vue'

const props = defineProps<{
  data: any[]
  loading: boolean
  total: number
  page: number
  pageSize: number
}>()

const emit = defineEmits<{
  (e: 'page-change', page: number): void
  (e: 'sort-change', prop: string, order: string): void
  (e: 'row-click', code: string): void
}>()

function getPriceClass(val: number) {
  if (val > 0) return 'price-up'
  if (val < 0) return 'price-down'
  return 'price-flat'
}

function handleSortChange({ prop, order }: any) {
  emit('sort-change', prop, order)
}
</script>

<template>
  <div class="stock-table">
    <el-table
      :data="data"
      v-loading="loading"
      stripe
      @row-click="(row: any) => emit('row-click', row.code)"
      @sort-change="handleSortChange"
      style="cursor: pointer"
    >
      <el-table-column prop="code" label="代码" width="90" />
      <el-table-column prop="name" label="名称" width="100" />
      <el-table-column prop="latest_price" label="最新价" width="90" sortable="custom" align="right">
        <template #default="{ row }">
          <span :class="getPriceClass(row.change_pct)">{{ row.latest_price }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="change_pct" label="涨跌幅" width="100" sortable="custom" align="right">
        <template #default="{ row }">
          <span :class="getPriceClass(row.change_pct)">
            {{ row.change_pct > 0 ? '+' : '' }}{{ row.change_pct }}%
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="market_cap" label="市值(亿)" width="100" sortable="custom" align="right" />
      <el-table-column prop="latest_date" label="日期" width="110" />
      <el-table-column label="走势" width="140" align="center">
        <template #default="{ row }">
          <MiniKline :code="row.code" :days="30" />
        </template>
      </el-table-column>
    </el-table>
    <div class="pagination-wrapper">
      <el-pagination
        :current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next, total"
        @current-change="(p: number) => emit('page-change', p)"
      />
    </div>
  </div>
</template>

<style scoped>
.stock-table {
  width: 100%;
}
.pagination-wrapper {
  display: flex;
  justify-content: center;
  padding: 16px 0;
}
</style>
