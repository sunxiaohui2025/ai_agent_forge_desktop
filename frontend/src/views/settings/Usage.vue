<template>
  <div class="page">
    <div class="page-head">
      <span class="page-title">用量统计</span>
      <el-radio-group v-model="days" size="small" @change="load">
        <el-radio-button :value="7">7 天</el-radio-button>
        <el-radio-button :value="30">30 天</el-radio-button>
        <el-radio-button :value="90">90 天</el-radio-button>
      </el-radio-group>
    </div>

    <!-- Summary cards -->
    <div class="cards">
      <div class="card">
        <div class="card-label">总 Token</div>
        <div class="card-value mono">{{ fmt(stats.summary.total_tokens) }}</div>
        <div class="card-sub">输入 {{ fmt(stats.summary.total_tokens_in) }} · 输出 {{ fmt(stats.summary.total_tokens_out) }}</div>
      </div>
      <div class="card">
        <div class="card-label">调用次数</div>
        <div class="card-value mono">{{ fmt(stats.summary.total_calls) }}</div>
        <div class="card-sub">
          <span class="status-success"><span class="status-dot"></span> {{ stats.summary.ok_calls }} 成功</span>
          <span v-if="stats.summary.error_calls" class="status-danger" style="margin-left:10px">
            <span class="status-dot"></span> {{ stats.summary.error_calls }} 失败</span>
        </div>
      </div>
      <div class="card">
        <div class="card-label">活跃模型</div>
        <div class="card-value mono">{{ stats.by_model.length }}</div>
        <div class="card-sub">近 {{ days }} 天</div>
      </div>
      <div class="card">
        <div class="card-label">缓存命中 Token</div>
        <div class="card-value mono">{{ fmt(stats.summary.total_cache_hit_tokens) }}</div>
        <div class="card-sub">
          <span v-if="stats.summary.total_tokens_in" style="color: var(--m-text-secondary)">
            命中率 {{ ((stats.summary.total_cache_hit_tokens || 0) / stats.summary.total_tokens_in * 100).toFixed(1) }}%
          </span>
          <span v-else>—</span>
        </div>
      </div>
    </div>

    <!-- Daily trend chart -->
    <div class="section">
      <div class="section-title">每日 Token 趋势</div>
      <div v-if="!stats.daily.length" class="empty">暂无数据</div>
      <div v-else class="chart-wrapper">
        <div class="chart">
          <!-- Y-axis scale -->
          <div class="y-axis">
            <span v-for="label in yLabels" :key="label.val" class="y-label" :style="{ bottom: label.pos + '%' }">
              {{ label.text }}
            </span>
          </div>
          <!-- Bars -->
          <div class="bars">
            <div v-for="d in stats.daily" :key="d.date" class="bar-col" :title="`${d.date}\nToken: ${fmt(d.tokens_in + d.tokens_out)}\n缓存命中: ${fmt(d.cache_hit_tokens || 0)}\n调用: ${d.calls} 次`">
              <div class="bar-wrap">
                <div class="bar bar-main" :style="{ height: barH(d.tokens_in + d.tokens_out) + '%' }">
                  <div class="bar bar-cache" :style="{ height: d.cache_hit_tokens ? cacheBarH(d.cache_hit_tokens, d.tokens_in + d.tokens_out) + '%' : '0%' }"></div>
                </div>
              </div>
              <div class="bar-x">{{ d.date.slice(5) }}</div>
            </div>
          </div>
        </div>
        <!-- Legend -->
        <div class="legend">
          <span class="legend-item"><span class="legend-dot token"></span> Token</span>
          <span class="legend-item"><span class="legend-dot cache"></span> 缓存命中</span>
        </div>
      </div>
    </div>

    <!-- Per-model breakdown -->
    <div class="section">
      <div class="section-title">按模型</div>
      <el-table :data="stats.by_model" size="small">
        <el-table-column prop="model" label="模型" />
        <el-table-column prop="provider" label="协议" width="140" />
        <el-table-column label="输入" width="120"><template #default="{ row }"><span class="mono">{{ fmt(row.tokens_in) }}</span></template></el-table-column>
        <el-table-column label="输出" width="120"><template #default="{ row }"><span class="mono">{{ fmt(row.tokens_out) }}</span></template></el-table-column>
        <el-table-column label="缓存命中" width="120"><template #default="{ row }"><span class="mono">{{ fmt(row.cache_hit_tokens || 0) }}</span></template></el-table-column>
        <el-table-column label="调用" width="100"><template #default="{ row }"><span class="mono">{{ row.calls }}</span></template></el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { api } from '@/api'

const days = ref(30)
const stats = reactive<any>({
  summary: { total_tokens: 0, total_tokens_in: 0, total_tokens_out: 0, total_cache_hit_tokens: 0, total_calls: 0, ok_calls: 0, error_calls: 0 },
  by_model: [], daily: []
})

function fmt(n: number) {
  if (n == null) return '0'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k'
  return String(n)
}

const maxToken = computed(() => {
  return Math.max(1, ...stats.daily.map((d: any) => Math.max(d.tokens_in + d.tokens_out, d.cache_hit_tokens || 0)))
})

function barH(v: number) {
  return Math.max(2, Math.round((v / maxToken.value) * 100))
}

// Cache hit shows as percentage of the bar's total tokens (not chart max)
function cacheBarH(cache: number, total: number) {
  if (!total) return 0
  return Math.min(100, Math.round((cache / total) * 100))
}

// Y-axis labels (4 ticks)
const yLabels = computed(() => {
  const max = maxToken.value
  const steps = [0, 0.25, 0.5, 0.75, 1]
  return steps.map(s => ({
    val: max * s,
    pos: s * 100,
    text: fmt(Math.round(max * s)),
  }))
})

async function load() {
  const r = await api.usageStats(days.value)
  Object.assign(stats, r)
}
onMounted(load)
</script>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 18px; }
.card { border: 1px solid var(--m-border); border-radius: var(--m-radius-lg); padding: 14px 16px; background: var(--m-surface); }
.card-label { font-size: 12px; color: var(--m-text-tertiary); }
.card-value { font-size: 26px; font-weight: 650; margin: 4px 0 2px; letter-spacing: -0.02em; }
.card-sub { font-size: 12px; color: var(--m-text-secondary); }

.section { margin-bottom: 20px; }
.section-title { font-size: 12px; font-weight: 650; color: var(--m-text-secondary); margin-bottom: 8px; }
.empty { font-size: 13px; color: var(--m-text-tertiary); padding: 20px; text-align: center; border: 1px dashed var(--m-border); border-radius: var(--m-radius-lg); }

/* Chart container */
.chart-wrapper { border: 1px solid var(--m-border); border-radius: var(--m-radius-lg); padding: 12px 8px 4px; background: var(--m-surface); overflow: hidden; }

/* The chart area with y-axis + bars */
.chart { display: flex; position: relative; height: 240px; overflow-x: auto; overflow-y: hidden; }

/* Y-axis */
.y-axis { position: relative; width: 52px; flex-shrink: 0; border-right: 1px dashed var(--m-border); margin-right: 4px; padding: 12px 0; }
.y-label { position: absolute; right: 6px; transform: translateY(50%); font-size: 10px; color: var(--m-text-tertiary); white-space: nowrap; line-height: 1; }

/* Bars area */
.bars { display: flex; align-items: flex-end; gap: 6px; flex: 1; padding: 0 0 20px 0; }
.bar-col { display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; flex: 1; max-width: 40px; min-width: 28px; }
.bar-wrap { width: 60%; height: 100%; display: flex; align-items: flex-end; }
.bar-main { width: 100%; background: var(--m-primary); border-radius: 5px 5px 0 0; min-height: 2px; transition: height .2s; display: flex; flex-direction: column; justify-content: flex-end; overflow: hidden; }
.bar-cache { width: 100%; background: #67c23a; border-radius: 5px 5px 0 0; opacity: 0.85; min-height: 0; transition: height .2s; }

/* Legend */
.legend { display: flex; justify-content: center; gap: 16px; margin-top: 8px; padding-top: 4px; }
.legend-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--m-text-secondary); }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; }
.legend-dot.token { background: var(--m-primary); }
.legend-dot.cache { background: #67c23a; }

.status-success .status-dot, .status-danger .status-dot { margin-right: 3px; }
</style>
