<template>
  <section class="page" data-module="report">
    <header class="page-head">
      <div>
        <h2>报告出具管理</h2>
        <p class="page-desc">维护检测报告，围绕报告编号、报告类型、签发人员做筛选与状态流转，作废报告不会残留在待签发结果里。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记检测报告</button>
        <button class="btn" type="button" @click="exportRows">导出报告出具清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model.trim="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>报告状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ cellValue(row, column) }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条报告出具记录</span>
      <div v-if="totalPages > 1" class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      </div>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/report'
const PAGE_SIZE = 10
const columns = ["报告编号", "关联样品", "报告类型", "编制人员", "审核人员", "签发人员", "出具日期", "报告状态"]
const actions = ["提交编制", "确认签发", "作废报告"]
const statuses = ["待编制", "已编制", "待签发", "已出具", "已作废"]
const stats = [{"label": "待编制报告", "value": 0}, {"label": "本月出具数", "value": 0}, {"label": "作废报告数", "value": 0}]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const emptyMessage = ref('')
const filterFields = ["报告编号", "报告类型", "签发人员"]
const filters = ref<Record<string, string>>(Object.fromEntries(filterFields.map((field) => [field, ''])))
const statusFilter = ref('')
const page = ref(1)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))
const emptyText = computed(() => emptyMessage.value || '暂无报告出具数据，可先登记检测报告')

function cellValue(row: Row, column: string): string {
  // “报告状态”以工作流状态为准，保证作废后立即可见，不使用种子里的展示占位文本。
  if (column === '报告状态') {
    return String(row.status ?? row[column] ?? '—')
  }
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function readQuery() {
  for (const field of filterFields) {
    filters.value[field] = typeof route.query[field] === 'string' ? String(route.query[field]) : ''
  }
  const queryStatus = route.query.status
  statusFilter.value = typeof queryStatus === 'string' && statuses.includes(queryStatus) ? queryStatus : ''
  const queryPage = Number.parseInt(String(route.query.page ?? ''), 10)
  page.value = Number.isFinite(queryPage) && queryPage >= 1 ? queryPage : 1
}

function syncQuery() {
  const query: Record<string, string> = {}
  for (const field of filterFields) {
    if (filters.value[field]) {
      query[field] = filters.value[field]
    }
  }
  if (statusFilter.value) {
    query.status = statusFilter.value
  }
  if (page.value > 1) {
    query.page = String(page.value)
  }
  const next = new URLSearchParams(query)
  const signature = (params: URLSearchParams) =>
    [...params.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => `${key}=${value}`).join('&')
  const current = new URLSearchParams()
  for (const [key, value] of Object.entries(route.query)) {
    if (typeof value === 'string') {
      current.set(key, value)
    }
  }
  // query 完全一致时 router.replace 不会触发 watcher，交给调用方决定是否直接刷新。
  if (signature(current) === signature(next)) {
    return false
  }
  void router.replace({ query })
  return true
}

let requestSeq = 0

async function reload() {
  errorMessage.value = ''
  emptyMessage.value = ''
  // 只构造服务端真正认识的参数，避免空白与历史残留条件被带到接口。
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const keyword = filters.value[field]?.trim()
    if (keyword) {
      params.set(field, keyword)
    }
  }
  if (statusFilter.value) {
    params.set('status', statusFilter.value)
  }
  params.set('page', String(page.value))
  params.set('size', String(PAGE_SIZE))

  const seq = ++requestSeq
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('检测报告列表读取失败')
    }
    const payload = await response.json()
    if (seq !== requestSeq) {
      return // 旧请求晚到，丢弃，防止翻页/查询结果互相覆盖。
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
    emptyMessage.value = payload.total === 0 ? (payload.message ?? '') : ''
    // 后端按过滤后的总数回收越界页码（例如作废后当前页空了）；URL 更新后由 watcher 重新加载。
    if (page.value > totalPages.value && totalPages.value > 0) {
      page.value = totalPages.value
      syncQuery()
    }
  } catch (error) {
    if (seq === requestSeq) {
      errorMessage.value = error instanceof Error ? error.message : '报告出具列表读取失败'
    }
  }
}

function applyFilters() {
  page.value = 1 // 新条件一律从第一页开始，避免拿着旧页码切新结果集。
  if (!syncQuery()) {
    void reload()
  }
}

function goPage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) {
    return
  }
  page.value = target
  if (!syncQuery()) {
    void reload()
  }
}

function resetFilters() {
  for (const field of filterFields) {
    filters.value[field] = ''
  }
  statusFilter.value = ''
  page.value = 1
  if (!syncQuery()) {
    void reload()
  }
}

function exportRows() {
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const keyword = filters.value[field]?.trim()
    if (keyword) {
      params.set(field, keyword)
    }
  }
  if (statusFilter.value) {
    params.set('status', statusFilter.value)
  }
  const suffix = params.toString()
  window.open(suffix ? `${ENDPOINT}/export?${suffix}` : `${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '检测报告登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('报告出具动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '报告出具操作被驳回')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报告出具操作失败'
  }
}

watch(
  () => route.query,
  () => {
    readQuery()
    void reload()
  },
)

onMounted(() => {
  readQuery()
  void reload()
})
</script>
