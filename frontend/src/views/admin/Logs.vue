<template>
  <div class="page">
    <div class="page-head">
      <span class="page-title">调用记录</span>
      <el-select v-model="filterAgentId" placeholder="按专家筛选" clearable filterable
                 class="filter-select" size="small" @change="onFilterChange">
        <el-option v-for="a in agents" :key="a.id" :label="a.name" :value="a.id" />
      </el-select>
    </div>

    <el-table :data="calls.items" v-loading="loading" size="small">
      <el-table-column label="时间" width="160">
        <template #default="{ row }"><span class="mono">{{ fmtTime(row.created_at) }}</span></template>
      </el-table-column>
      <el-table-column label="专家" width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.agent_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="模型" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.model_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="输入" width="90"><template #default="{ row }"><span class="mono">{{ row.tokens_in }}</span></template></el-table-column>
      <el-table-column label="输出" width="90"><template #default="{ row }"><span class="mono">{{ row.tokens_out }}</span></template></el-table-column>
      <el-table-column label="耗时" width="90"><template #default="{ row }"><span class="mono">{{ row.latency_ms }}ms</span></template></el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <span :class="['status-chip', row.status === 'ok' ? 'status-success' : 'status-danger']">
            <span class="status-dot"></span>{{ row.status === 'ok' ? '成功' : '失败' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="error" label="错误" min-width="160" show-overflow-tooltip />
    </el-table>

    <div class="pager">
      <el-pagination
        background layout="total, prev, pager, next"
        :total="calls.total" :page-size="pageSize" :current-page="page"
        @current-change="onPageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api'

const page = ref(1)
const pageSize = ref(15)
const loading = ref(false)
const calls = ref<{ items: any[]; total: number }>({ items: [], total: 0 })
const filterAgentId = ref<number | null>(null)
const agents = ref<any[]>([])

async function load() {
  loading.value = true
  try {
    calls.value = await api.callLogs({
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
      agent_id: filterAgentId.value ?? undefined,
    })
  } finally { loading.value = false }
}
function onPageChange(p: number) { page.value = p; load() }
function onFilterChange() { page.value = 1; load() }

function fmtTime(s: string) {
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

onMounted(async () => {
  agents.value = await api.agents().catch(() => [])
  await load()
})
</script>

<style scoped>
.filter-select { width: 200px; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
