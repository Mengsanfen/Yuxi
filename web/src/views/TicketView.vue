<template>
  <main class="workbench-page">
    <header class="page-header">
      <div class="page-title">
        <span class="title-icon"><Headphones :size="22" /></span>
        <div>
          <h1>售后工单</h1>
          <p>统一跟进咨询、物流、退款与投诉任务</p>
        </div>
      </div>
      <div class="header-actions">
        <span class="active-count">处理中 {{ activeCount }}</span>
        <a-tooltip title="刷新">
          <a-button class="icon-button" :loading="loading" aria-label="刷新" @click="loadTickets">
            <RefreshCw :size="17" />
          </a-button>
        </a-tooltip>
      </div>
    </header>

    <section class="toolbar" aria-label="工单筛选">
      <a-segmented v-model:value="activeFilter" :options="filterOptions" />
    </section>

    <section class="table-panel">
      <a-table
        :columns="columns"
        :data-source="filteredTickets"
        :loading="loading"
        :pagination="pagination"
        :scroll="{ x: 1180 }"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'ticket'">
            <div class="primary-cell">
              <strong>工单 #{{ record.id }}</strong>
              <span>{{ typeLabel(record.type) }} · {{ sourceLabel(record.source) }}</span>
            </div>
          </template>

          <template v-else-if="column.key === 'summary'">
            <a-tooltip :title="record.summary">
              <div class="summary-cell">{{ record.summary }}</div>
            </a-tooltip>
          </template>

          <template v-else-if="column.key === 'relation'">
            <div class="primary-cell relation-cell">
              <strong>客户 #{{ record.customer_id }}</strong>
              <span>{{ record.order_id ? `订单 #${record.order_id}` : '未关联订单' }}</span>
            </div>
          </template>

          <template v-else-if="column.key === 'priority'">
            <a-tag :color="priorityMeta(record.priority).color">
              {{ priorityMeta(record.priority).label }}
            </a-tag>
          </template>

          <template v-else-if="column.key === 'status'">
            <a-badge
              :status="statusMeta(record.status).badge"
              :text="statusMeta(record.status).label"
            />
          </template>

          <template v-else-if="column.key === 'assignee'">
            <span :class="{ 'secondary-text': !record.assignee }">
              {{ record.assignee || '未分配' }}
            </span>
          </template>

          <template v-else-if="column.key === 'updated_at'">
            <span class="secondary-text">{{ formatDate(record.updated_at) }}</span>
          </template>

          <template v-else-if="column.key === 'actions'">
            <div v-if="transitionOptions(record.status).length" class="transition-control">
              <a-select
                v-model:value="selectedTransitions[record.id]"
                :options="transitionOptions(record.status)"
                aria-label="选择下一状态"
                size="small"
              />
              <a-tooltip title="更新状态">
                <a-button
                  class="transition-button"
                  type="primary"
                  size="small"
                  :loading="updatingId === record.id"
                  aria-label="更新状态"
                  @click="updateStatus(record)"
                >
                  <ArrowRight :size="14" />
                </a-button>
              </a-tooltip>
            </div>
            <span v-else class="secondary-text">流程已结束</span>
          </template>
        </template>

        <template #emptyText>
          <div class="empty-state">
            <Inbox :size="28" />
            <span>当前筛选条件下没有工单</span>
          </div>
        </template>
      </a-table>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { ArrowRight, Headphones, Inbox, RefreshCw } from 'lucide-vue-next'

import { enterpriseApi } from '@/apis/enterprise_api'

const loading = ref(false)
const updatingId = ref(null)
const tickets = ref([])
const activeFilter = ref('active')
const selectedTransitions = reactive({})

const filterOptions = [
  { label: '处理中', value: 'active' },
  { label: '待受理', value: 'open' },
  { label: '待客户', value: 'waiting_customer' },
  { label: '已解决', value: 'resolved' },
  { label: '已关闭', value: 'closed' },
  { label: '全部', value: 'all' }
]

const columns = [
  { title: '工单', key: 'ticket', width: 150 },
  { title: '问题摘要', key: 'summary', width: 270 },
  { title: '客户 / 订单', key: 'relation', width: 150 },
  { title: '优先级', key: 'priority', width: 90 },
  { title: '状态', key: 'status', width: 120 },
  { title: '负责人', key: 'assignee', width: 100 },
  { title: '更新时间', key: 'updated_at', width: 170 },
  { title: '状态流转', key: 'actions', width: 220, fixed: 'right' }
]

const pagination = {
  pageSize: 12,
  showSizeChanger: false,
  showTotal: (total) => `共 ${total} 项`
}

const activeStatuses = new Set(['open', 'processing', 'waiting_customer'])

const activeCount = computed(
  () => tickets.value.filter((ticket) => activeStatuses.has(ticket.status)).length
)

const filteredTickets = computed(() => {
  if (activeFilter.value === 'all') return tickets.value
  if (activeFilter.value === 'active') {
    return tickets.value.filter((ticket) => activeStatuses.has(ticket.status))
  }
  return tickets.value.filter((ticket) => ticket.status === activeFilter.value)
})

const typeLabel = (type) => {
  const labels = {
    after_sale: '售后',
    complaint: '投诉',
    inquiry: '咨询',
    logistics: '物流',
    refund: '退款'
  }
  return labels[type] || type || '其他'
}

const sourceLabel = (source) => {
  const labels = { manual: '人工创建', agent: '智能体创建', api: 'API 创建' }
  return labels[source] || source || '未知来源'
}

const priorityMeta = (priority) => {
  const meta = {
    low: { label: '低', color: 'default' },
    medium: { label: '中', color: 'blue' },
    high: { label: '高', color: 'orange' },
    urgent: { label: '紧急', color: 'red' }
  }
  return meta[priority] || { label: priority || '未知', color: 'default' }
}

const statusMeta = (status) => {
  const meta = {
    open: { label: '待受理', badge: 'default' },
    processing: { label: '处理中', badge: 'processing' },
    waiting_customer: { label: '待客户回复', badge: 'warning' },
    resolved: { label: '已解决', badge: 'success' },
    closed: { label: '已关闭', badge: 'default' }
  }
  return meta[status] || { label: status || '未知', badge: 'default' }
}

const transitionMap = {
  open: ['processing', 'resolved'],
  processing: ['waiting_customer', 'resolved'],
  waiting_customer: ['processing', 'resolved'],
  resolved: ['closed', 'processing'],
  closed: []
}

const transitionOptions = (status) => {
  return (transitionMap[status] || []).map((value) => ({
    value,
    label: statusMeta(value).label
  }))
}

const formatDate = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

const initializeTransitions = () => {
  tickets.value.forEach((ticket) => {
    const options = transitionOptions(ticket.status)
    if (options.length) selectedTransitions[ticket.id] = options[0].value
    else delete selectedTransitions[ticket.id]
  })
}

const loadTickets = async () => {
  loading.value = true
  try {
    const response = await enterpriseApi.listTickets({ limit: 200 })
    tickets.value = response.items || []
    initializeTransitions()
  } catch (error) {
    console.error('加载工单失败:', error)
    message.error(error.message || '加载工单失败')
  } finally {
    loading.value = false
  }
}

const updateStatus = async (ticket) => {
  const targetStatus = selectedTransitions[ticket.id]
  if (!targetStatus || updatingId.value) return
  updatingId.value = ticket.id
  try {
    const updated = await enterpriseApi.updateTicketStatus(ticket.id, targetStatus)
    const index = tickets.value.findIndex((item) => item.id === ticket.id)
    if (index !== -1) tickets.value[index] = updated
    initializeTransitions()
    message.success(`工单 #${ticket.id} 已更新为${statusMeta(targetStatus).label}`)
  } catch (error) {
    console.error('更新工单状态失败:', error)
    message.error(error.message || '更新工单状态失败')
  } finally {
    updatingId.value = null
  }
}

onMounted(loadTickets)
</script>

<style scoped lang="less">
.workbench-page {
  min-height: 100%;
  padding: var(--page-padding);
  background: var(--gray-25);
  color: var(--gray-1000);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;

  h1 {
    margin: 0;
    font-size: 22px;
    line-height: 30px;
    font-weight: 650;
  }

  p {
    margin: 2px 0 0;
    color: var(--gray-600);
    font-size: 13px;
  }
}

.title-icon {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  color: var(--main-700);
  background: var(--main-50);
  border: 1px solid var(--main-100);
  border-radius: 8px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.active-count {
  color: var(--main-700);
  font-size: 13px;
  font-weight: 600;
}

.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  padding: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  min-height: 52px;
  padding: 8px 14px;
  overflow-x: auto;
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-bottom: 0;
  border-radius: 8px 8px 0 0;
}

.table-panel {
  overflow: hidden;
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 0 0 8px 8px;
}

.primary-cell {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 3px;

  strong {
    font-size: 14px;
    font-weight: 600;
  }

  span {
    color: var(--gray-600);
    font-size: 12px;
  }
}

.relation-cell {
  font-variant-numeric: tabular-nums;
}

.summary-cell {
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.secondary-text {
  color: var(--gray-600);
  font-size: 13px;
}

.transition-control {
  display: grid;
  width: 190px;
  grid-template-columns: minmax(0, 1fr) 32px;
  gap: 6px;

  :deep(.ant-select) {
    width: 100%;
  }
}

.transition-button {
  display: inline-flex;
  width: 32px;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.empty-state {
  display: flex;
  min-height: 160px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  color: var(--gray-500);
}

@media (max-width: 767px) {
  .page-header {
    align-items: flex-start;
  }

  .page-title p,
  .active-count {
    display: none;
  }
}
</style>
