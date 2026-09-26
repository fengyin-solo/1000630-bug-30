<template>
  <section class="page" data-module="report">
    <header class="page-head">
      <div>
        <h2>报告出具管理</h2>
        <p class="page-desc">维护检测报告，围绕报告编号、关联样品、报告类型、编制人员做登记、筛选与状态流转。</p>
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

    <form class="filter-bar" @submit.prevent="search">
      <label class="filter-item">
        <span>报告编号</span>
        <input v-model="filters['报告编号']" placeholder="按报告编号检索" />
      </label>
      <label class="filter-item">
        <span>报告类型</span>
        <input v-model="filters['报告类型']" placeholder="按报告类型检索" />
      </label>
      <label class="filter-item">
        <span>签发人员</span>
        <input v-model="filters['签发人员']" placeholder="按签发人员检索" />
      </label>
      <label class="filter-item">
        <span>报告状态</span>
        <select v-model="filters['报告状态']">
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
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'is-void': row.status === '已作废' }">
          <td v-for="column in columns" :key="column">{{ cellValue(row, column) }}</td>
          <td class="row-actions">
            <template v-if="actionsFor(row).length">
              <button
                v-for="action in actionsFor(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyMessage }}</td>
        </tr>
      </tbody>
    </table>

    <div class="pager">
      <button class="btn" type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
      <span>第 {{ page }} / {{ totalPages }} 页</span>
      <button class="btn" type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
      <label class="page-size">
        每页
        <select v-model.number="size" @change="changeSize">
          <option :value="10">10</option>
          <option :value="20">20</option>
          <option :value="50">50</option>
        </select>
        条
      </label>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条报告出具记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/report'
const columns = ["报告编号", "关联样品", "报告类型", "编制人员", "审核人员", "签发人员", "出具日期", "报告状态"]
const statuses = ["待编制", "已编制", "待签发", "已出具", "已作废"]
const stats = [{"label": "待编制报告", "value": 0}, {"label": "本月出具数", "value": 0}, {"label": "作废报告数", "value": 0}]

// 动作入口与后端 ACTION_RULES 保持一致：作废后的报告不再给出任何流转入口，
// 「确认签发」只对待签发报告开放，避免作废报告残留待签发结果里。
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  "待编制": ["提交编制", "作废报告"],
  "已编制": ["作废报告"],
  "待签发": ["确认签发", "作废报告"],
  "已出具": [],
  "已作废": [],
}

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const page = ref(1)
const size = ref(20)
const filters = ref<Record<string, string>>({
  "报告编号": '',
  "报告类型": '',
  "签发人员": '',
  "报告状态": '',
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / size.value)))
const activeFilterCount = computed(() =>
  Object.values(filters.value).filter((value) => value.trim()).length,
)
const emptyMessage = computed(() =>
  activeFilterCount.value
    ? '没有符合当前筛选条件的报告：请检查报告编号、报告类型、签发人员或状态是否正确，或重置条件后再查询'
    : '暂无报告出具数据，可先登记检测报告',
)

function actionsFor(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row.status ?? '')] ?? []
}

function cellValue(row: Row, column: string) {
  // 「报告状态」列以后端流转状态为准，种子里的同名展示字段不可信。
  if (column === '报告状态') return row.status ?? '—'
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

// 连续查询/翻页时只认最后一次请求，避免旧响应晚回来覆盖新条件下的结果。
let requestSeq = 0
let abortController: AbortController | null = null

async function reload() {
  errorMessage.value = ''
  const seq = ++requestSeq
  abortController?.abort()
  const controller = new AbortController()
  abortController = controller

  const params = new URLSearchParams()
  const reportNo = filters.value['报告编号'].trim()
  const reportType = filters.value['报告类型'].trim()
  const issuer = filters.value['签发人员'].trim()
  const status = filters.value['报告状态'].trim()
  if (reportNo) params.set('report_no', reportNo)
  if (reportType) params.set('report_type', reportType)
  if (issuer) params.set('issuer', issuer)
  if (status) params.set('status', status)
  params.set('page', String(page.value))
  params.set('size', String(size.value))

  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`, { signal: controller.signal })
    if (seq !== requestSeq) return
    if (!response.ok) {
      let detail = '检测报告列表读取失败'
      try {
        const body = await response.json()
        if (body?.detail) detail = body.detail
      } catch {
        // 非 JSON 错误体时保留兜底文案
      }
      throw new Error(detail)
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    syncQuery()

    // 筛选后停在超出范围的页码时，回退到最后一页而不是展示空表冒充"无数据"。
    if (rows.value.length === 0 && total.value > 0 && page.value > 1) {
      page.value = Math.max(1, Math.ceil(total.value / size.value))
      await reload()
    }
  } catch (error) {
    if (seq !== requestSeq) return
    if (error instanceof Error && error.message.includes('abort')) return
    errorMessage.value = error instanceof Error ? error.message : '报告出具列表读取失败'
  }
}

// 筛选条件与页码写进 URL，刷新或分享链接后条件不丢。
function syncQuery() {
  const query: Record<string, string> = {}
  if (filters.value['报告编号'].trim()) query.report_no = filters.value['报告编号'].trim()
  if (filters.value['报告类型'].trim()) query.report_type = filters.value['报告类型'].trim()
  if (filters.value['签发人员'].trim()) query.issuer = filters.value['签发人员'].trim()
  if (filters.value['报告状态'].trim()) query.status = filters.value['报告状态'].trim()
  if (page.value > 1) query.page = String(page.value)
  if (size.value !== 20) query.size = String(size.value)
  void router.replace({ query })
}

function readQuery() {
  const query = route.query
  filters.value = {
    "报告编号": typeof query.report_no === 'string' ? query.report_no : '',
    "报告类型": typeof query.report_type === 'string' ? query.report_type : '',
    "签发人员": typeof query.issuer === 'string' ? query.issuer : '',
    "报告状态": typeof query.status === 'string' ? query.status : '',
  }
  const queryPage = Number.parseInt(String(query.page ?? '1'), 10)
  const querySize = Number.parseInt(String(query.size ?? '20'), 10)
  page.value = Number.isFinite(queryPage) && queryPage > 0 ? queryPage : 1
  size.value = Number.isFinite(querySize) && querySize > 0 ? querySize : 20
}

function search() {
  page.value = 1
  void reload()
}

function goPage(target: number) {
  if (target < 1 || target > totalPages.value || target === page.value) return
  page.value = target
  void reload()
}

function changeSize() {
  page.value = 1
  void reload()
}

function resetFilters() {
  for (const key of Object.keys(filters.value)) {
    filters.value[key] = ''
  }
  page.value = 1
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '检测报告登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message || '报告出具动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报告出具操作失败'
  }
}

onMounted(() => {
  readQuery()
  void reload()
})
</script>
