<template>
  <main class="workbench-page">
    <header class="page-header">
      <div class="page-title">
        <span class="title-icon"><ShieldCheck :size="22" /></span>
        <div>
          <h1>审批中心</h1>
          <p>退款风险审核与智能体流程恢复</p>
        </div>
      </div>
      <div class="header-actions">
        <span class="pending-count">待处理 {{ pendingCount }}</span>
        <a-tooltip title="刷新">
          <a-button class="icon-button" :loading="loading" aria-label="刷新" @click="loadApprovals">
            <RefreshCw :size="17" />
          </a-button>
        </a-tooltip>
      </div>
    </header>

    <section class="toolbar" aria-label="审批筛选">
      <a-segmented v-model:value="activeFilter" :options="filterOptions" />
    </section>

    <section class="table-panel">
      <a-table
        :columns="columns"
        :data-source="filteredApprovals"
        :loading="loading"
        :pagination="pagination"
        :scroll="{ x: 1080 }"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'task'">
            <div class="primary-cell">
              <strong>退款审批 #{{ record.id }}</strong>
              <span>申请人 {{ record.requested_by }}</span>
            </div>
          </template>

          <template v-else-if="column.key === 'business'">
            <div class="primary-cell business-cell">
              <strong>订单 #{{ record.business?.order_id || '-' }}</strong>
              <a-tooltip :title="record.business?.reason || '暂无退款原因'">
                <span>{{ record.business?.reason || '暂无退款原因' }}</span>
              </a-tooltip>
            </div>
          </template>

          <template v-else-if="column.key === 'amount'">
            <span class="money">{{ formatMoney(record.business?.amount) }}</span>
          </template>

          <template v-else-if="column.key === 'risk'">
            <a-tag :color="riskMeta(record.business?.risk_level).color">
              {{ riskMeta(record.business?.risk_level).label }}
            </a-tag>
          </template>

          <template v-else-if="column.key === 'status'">
            <a-badge
              :status="statusMeta(record.status).badge"
              :text="statusMeta(record.status).label"
            />
          </template>

          <template v-else-if="column.key === 'created_at'">
            <span class="secondary-text">{{ formatDate(record.created_at) }}</span>
          </template>

          <template v-else-if="column.key === 'actions'">
            <a-button
              v-if="record.status === 'pending'"
              type="link"
              class="review-button"
              @click="openReview(record)"
            >
              <ClipboardCheck :size="16" />
              审核
            </a-button>
            <span v-else class="secondary-text">{{ record.reviewer || '已处理' }}</span>
          </template>
        </template>

        <template #emptyText>
          <div class="empty-state">
            <CircleCheckBig :size="28" />
            <span>当前筛选条件下没有审批任务</span>
          </div>
        </template>
      </a-table>
    </section>

    <a-modal
      v-model:open="reviewVisible"
      title="退款审批"
      :confirm-loading="submitting"
      :footer="null"
      width="560px"
      destroy-on-close
      @cancel="resetReview"
    >
      <div v-if="selectedTask" class="review-content">
        <dl class="review-details">
          <div>
            <dt>任务编号</dt>
            <dd>#{{ selectedTask.id }}</dd>
          </div>
          <div>
            <dt>退款金额</dt>
            <dd class="money">{{ formatMoney(selectedTask.business?.amount) }}</dd>
          </div>
          <div>
            <dt>关联订单</dt>
            <dd>#{{ selectedTask.business?.order_id || '-' }}</dd>
          </div>
          <div>
            <dt>风险等级</dt>
            <dd>{{ riskMeta(selectedTask.business?.risk_level).label }}</dd>
          </div>
        </dl>

        <div class="reason-block">
          <span>退款原因</span>
          <p>{{ selectedTask.business?.reason || '暂无退款原因' }}</p>
        </div>

        <a-form layout="vertical">
          <a-form-item label="审批意见">
            <a-textarea
              v-model:value="reviewComment"
              :rows="3"
              :maxlength="1000"
              placeholder="填写审批依据或驳回原因"
              show-count
            />
          </a-form-item>
        </a-form>

        <div class="review-actions">
          <a-button @click="resetReview">取消</a-button>
          <a-button danger :loading="submitting" @click="submitReview('rejected')">
            <X :size="16" />
            驳回
          </a-button>
          <a-button type="primary" :loading="submitting" @click="submitReview('approved')">
            <Check :size="16" />
            通过
          </a-button>
        </div>
      </div>
    </a-modal>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { Check, CircleCheckBig, ClipboardCheck, RefreshCw, ShieldCheck, X } from 'lucide-vue-next'

import { enterpriseApi } from '@/apis/enterprise_api'

const loading = ref(false)
const submitting = ref(false)
const approvals = ref([])
const activeFilter = ref('pending')
const reviewVisible = ref(false)
const selectedTask = ref(null)
const reviewComment = ref('')

const filterOptions = [
  { label: '待审批', value: 'pending' },
  { label: '已通过', value: 'approved' },
  { label: '已驳回', value: 'rejected' },
  { label: '全部', value: 'all' }
]

const columns = [
  { title: '审批任务', key: 'task', width: 170 },
  { title: '业务信息', key: 'business', width: 270 },
  { title: '退款金额', key: 'amount', width: 120 },
  { title: '风险', key: 'risk', width: 90 },
  { title: '状态', key: 'status', width: 110 },
  { title: '申请时间', key: 'created_at', width: 170 },
  { title: '操作', key: 'actions', width: 100, fixed: 'right' }
]

const pagination = {
  pageSize: 12,
  showSizeChanger: false,
  showTotal: (total) => `共 ${total} 项`
}

const pendingCount = computed(
  () => approvals.value.filter((item) => item.status === 'pending').length
)

const filteredApprovals = computed(() => {
  if (activeFilter.value === 'all') return approvals.value
  return approvals.value.filter((item) => item.status === activeFilter.value)
})

const statusMeta = (status) => {
  const meta = {
    pending: { label: '待审批', badge: 'processing' },
    approved: { label: '已通过', badge: 'success' },
    rejected: { label: '已驳回', badge: 'error' }
  }
  return meta[status] || { label: status || '未知', badge: 'default' }
}

const riskMeta = (risk) => {
  const meta = {
    low: { label: '低风险', color: 'green' },
    medium: { label: '中风险', color: 'orange' },
    high: { label: '高风险', color: 'red' }
  }
  return meta[risk] || { label: '未评估', color: 'default' }
}

const formatMoney = (value) => {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '-'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY'
  }).format(amount)
}

const formatDate = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

const loadApprovals = async () => {
  loading.value = true
  try {
    const response = await enterpriseApi.listApprovals({ limit: 200 })
    approvals.value = response.items || []
  } catch (error) {
    console.error('加载审批任务失败:', error)
    message.error(error.message || '加载审批任务失败')
  } finally {
    loading.value = false
  }
}

const openReview = (task) => {
  selectedTask.value = task
  reviewComment.value = ''
  reviewVisible.value = true
}

const resetReview = () => {
  reviewVisible.value = false
  selectedTask.value = null
  reviewComment.value = ''
}

const submitReview = async (decision) => {
  if (!selectedTask.value || submitting.value) return
  submitting.value = true
  try {
    const response = await enterpriseApi.reviewApproval(selectedTask.value.id, {
      decision,
      review_comment: reviewComment.value.trim() || null
    })
    message.success(decision === 'approved' ? '审批已通过' : '审批已驳回')
    if (response.resume?.attempted && response.resume.status === 'error') {
      message.warning('审批已生效，但原智能体会话恢复失败，请查看服务日志')
    }
    resetReview()
    await loadApprovals()
  } catch (error) {
    console.error('提交审批失败:', error)
    message.error(error.message || '提交审批失败')
  } finally {
    submitting.value = false
  }
}

onMounted(loadApprovals)
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

.header-actions,
.review-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pending-count {
  color: var(--color-warning-700);
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
    overflow: hidden;
    color: var(--gray-600);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.business-cell {
  max-width: 250px;
}

.money {
  color: var(--gray-1000);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.secondary-text {
  color: var(--gray-600);
  font-size: 13px;
}

.review-button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
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

.review-content {
  padding-top: 6px;
}

.review-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 24px;
  margin: 0 0 20px;

  div {
    min-width: 0;
  }

  dt {
    margin-bottom: 4px;
    color: var(--gray-600);
    font-size: 12px;
  }

  dd {
    margin: 0;
    font-size: 14px;
  }
}

.reason-block {
  margin-bottom: 18px;
  padding: 12px;
  background: var(--gray-50);
  border-left: 3px solid var(--color-warning-500);
  border-radius: 4px;

  span {
    color: var(--gray-600);
    font-size: 12px;
  }

  p {
    margin: 6px 0 0;
    line-height: 1.6;
  }
}

.review-actions {
  justify-content: flex-end;

  :deep(.ant-btn) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
  }
}

@media (max-width: 767px) {
  .page-header {
    align-items: flex-start;
  }

  .page-title p,
  .pending-count {
    display: none;
  }

  .review-details {
    grid-template-columns: 1fr;
    gap: 12px;
  }
}
</style>
