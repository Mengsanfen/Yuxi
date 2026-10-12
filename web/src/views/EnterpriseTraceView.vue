<template>
  <main class="trace-page">
    <header class="page-header">
      <div class="page-title">
        <span class="title-icon"><Activity :size="22" /></span>
        <div>
          <h1>运行追踪</h1>
          <p>查看企业智能体的节点、工具、审批与质量链路</p>
        </div>
      </div>
      <a-tooltip title="刷新">
        <a-button class="icon-button" :loading="loading" aria-label="刷新" @click="loadTraces">
          <RefreshCw :size="17" />
        </a-button>
      </a-tooltip>
    </header>

    <section class="metric-strip" aria-label="运行指标">
      <div>
        <span>运行数</span>
        <strong>{{ total }}</strong>
      </div>
      <div>
        <span>完成率</span>
        <strong>{{ completionRate }}</strong>
      </div>
      <div>
        <span>平均耗时</span>
        <strong>{{ formatLatency(averageLatency) }}</strong>
      </div>
      <div>
        <span>高风险</span>
        <strong class="risk-value">{{ highRiskCount }}</strong>
      </div>
    </section>

    <section class="toolbar" aria-label="运行追踪筛选">
      <a-select
        v-model:value="filters.status"
        :options="statusOptions"
        aria-label="运行状态"
        class="filter-select"
      />
      <a-select
        v-model:value="filters.risk_level"
        :options="riskOptions"
        aria-label="风险等级"
        class="filter-select"
      />
      <a-input
        v-model:value="filters.thread_id"
        allow-clear
        class="thread-filter"
        placeholder="按会话 ID 筛选"
        @press-enter="applyFilters"
      >
        <template #prefix><Search :size="15" /></template>
      </a-input>
      <a-button type="primary" @click="applyFilters">查询</a-button>
    </section>

    <section class="trace-workbench">
      <div class="trace-list-panel">
        <div class="panel-heading">
          <strong>最近运行</strong>
          <span>{{ traces.length }} / {{ total }}</span>
        </div>
        <div v-if="loading" class="panel-state"><a-spin size="small" /> 正在加载</div>
        <div v-else-if="!traces.length" class="panel-state empty-state">
          <Activity :size="26" />
          <span>暂无符合条件的运行记录</span>
        </div>
        <button
          v-for="trace in traces"
          v-else
          :key="trace.trace_id"
          type="button"
          class="trace-row"
          :class="{ active: selectedTraceId === trace.trace_id }"
          @click="selectTrace(trace.trace_id)"
        >
          <div class="trace-row-main">
            <strong>{{ businessLabel(trace) }}</strong>
            <a-badge
              :status="statusMeta(trace.status).badge"
              :text="statusMeta(trace.status).label"
            />
          </div>
          <div class="trace-row-meta">
            <span>{{ nodeLabel(trace.current_node) }}</span>
            <span>{{ formatLatency(trace.metrics?.latency_ms) }}</span>
          </div>
          <div class="trace-row-footer">
            <span class="trace-id">{{ trace.trace_id }}</span>
            <time>{{ formatDate(trace.finished_at) }}</time>
          </div>
        </button>
      </div>

      <div class="trace-detail-panel">
        <div v-if="detailLoading" class="panel-state"><a-spin size="small" /> 正在加载详情</div>
        <div v-else-if="!selectedTrace" class="panel-state empty-state">
          <GitBranch :size="28" />
          <span>选择一条运行记录查看执行链路</span>
        </div>
        <template v-else>
          <header class="detail-header">
            <div>
              <span class="detail-eyebrow">TRACE</span>
              <h2>{{ businessLabel(selectedTrace) }}</h2>
              <p>{{ selectedTrace.trace_id }}</p>
            </div>
            <div class="detail-tags">
              <a-tag :color="riskMeta(selectedTrace.risk_level).color">
                {{ riskMeta(selectedTrace.risk_level).label }}
              </a-tag>
              <a-badge
                :status="statusMeta(selectedTrace.status).badge"
                :text="statusMeta(selectedTrace.status).label"
              />
            </div>
          </header>

          <dl class="detail-metrics">
            <div>
              <dt>总耗时</dt>
              <dd>{{ formatLatency(selectedTrace.metrics?.latency_ms) }}</dd>
            </div>
            <div>
              <dt>工具耗时</dt>
              <dd>{{ formatLatency(selectedTrace.metrics?.tool_latency_ms) }}</dd>
            </div>
            <div>
              <dt>检索耗时</dt>
              <dd>{{ formatLatency(selectedTrace.metrics?.retrieval_latency_ms) }}</dd>
            </div>
            <div>
              <dt>Token</dt>
              <dd>{{ formatNumber(selectedTrace.metrics?.total_tokens) }}</dd>
            </div>
            <div>
              <dt>模型</dt>
              <dd :title="selectedTrace.metrics?.model || '-'">
                {{ selectedTrace.metrics?.model || '-' }}
              </dd>
            </div>
          </dl>

          <div class="timeline-heading-bar">
            <strong>执行时间线</strong>
            <span>{{ selectedTrace.event_count }} 个事件</span>
          </div>
          <div class="timeline-scroll">
            <EnterpriseTraceTimeline :events="selectedTrace.events" />
          </div>
        </template>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Activity, GitBranch, RefreshCw, Search } from 'lucide-vue-next'
import { message } from 'ant-design-vue'

import { enterpriseApi } from '@/apis/enterprise_api'
import EnterpriseTraceTimeline from '@/components/enterprise/EnterpriseTraceTimeline.vue'

const loading = ref(false)
const detailLoading = ref(false)
const traces = ref([])
const total = ref(0)
const selectedTraceId = ref('')
const selectedTrace = ref(null)
const filters = reactive({ status: '', risk_level: '', thread_id: '' })

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '已中断', value: 'interrupted' },
  { label: '失败', value: 'failed' }
]

const riskOptions = [
  { label: '全部风险', value: '' },
  { label: '低风险', value: 'low' },
  { label: '中风险', value: 'medium' },
  { label: '高风险', value: 'high' }
]

const completionRate = computed(() => {
  if (!traces.value.length) return '-'
  const completed = traces.value.filter((trace) => trace.status === 'completed').length
  return `${Math.round((completed / traces.value.length) * 100)}%`
})

const averageLatency = computed(() => {
  const values = traces.value
    .map((trace) => Number(trace.metrics?.latency_ms))
    .filter((value) => Number.isFinite(value) && value > 0)
  if (!values.length) return 0
  return Math.round(values.reduce((totalValue, value) => totalValue + value, 0) / values.length)
})

const highRiskCount = computed(
  () => traces.value.filter((trace) => trace.risk_level === 'high').length
)

const loadTraces = async () => {
  loading.value = true
  try {
    const response = await enterpriseApi.listTraces({ ...filters, limit: 100 })
    traces.value = response.items || []
    total.value = response.total || 0
    if (
      selectedTraceId.value &&
      !traces.value.some((item) => item.trace_id === selectedTraceId.value)
    ) {
      selectedTraceId.value = ''
      selectedTrace.value = null
    }
    if (!selectedTraceId.value && traces.value.length) {
      await selectTrace(traces.value[0].trace_id)
    }
  } catch (error) {
    console.error('加载运行追踪失败:', error)
    message.error(error.message || '加载运行追踪失败')
  } finally {
    loading.value = false
  }
}

const selectTrace = async (traceId) => {
  if (!traceId || detailLoading.value) return
  selectedTraceId.value = traceId
  detailLoading.value = true
  try {
    selectedTrace.value = await enterpriseApi.getTrace(traceId)
  } catch (error) {
    console.error('加载运行详情失败:', error)
    message.error(error.message || '加载运行详情失败')
  } finally {
    detailLoading.value = false
  }
}

const applyFilters = async () => {
  selectedTraceId.value = ''
  selectedTrace.value = null
  await loadTraces()
}

const businessLabel = (trace) => {
  const labels = { order: '订单处理', refund: '退款处理', ticket: '工单处理', approval: '审批处理' }
  const base = labels[trace.business_type] || '企业服务运行'
  return trace.business_id ? `${base} #${trace.business_id}` : base
}

const nodeLabel = (node) => {
  const labels = {
    classify: '意图识别',
    extract_entities: '实体提取',
    knowledge: '知识检索',
    order: '订单查询',
    refund_order: '订单校验',
    refund: '退款处理',
    ticket: '工单处理',
    quality: '质量检查',
    repair: '结果修复',
    finalize: '生成结果'
  }
  return labels[node] || node || '等待节点'
}

const statusMeta = (status) => {
  const meta = {
    running: { label: '运行中', badge: 'processing' },
    completed: { label: '已完成', badge: 'success' },
    interrupted: { label: '待处理', badge: 'warning' },
    failed: { label: '失败', badge: 'error' }
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

const formatLatency = (value) => {
  const latency = Number(value)
  if (!Number.isFinite(latency) || latency <= 0) return '-'
  if (latency >= 1000) return `${(latency / 1000).toFixed(2)}s`
  return `${latency}ms`
}

const formatNumber = (value) => {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number.toLocaleString('zh-CN') : '-'
}

const formatDate = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(loadTraces)
</script>

<style scoped lang="less">
.trace-page {
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
    font-weight: 650;
    line-height: 30px;
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
  border: 1px solid var(--main-100);
  border-radius: 8px;
  background: var(--main-50);
  color: var(--main-700);
}

.icon-button {
  display: inline-flex;
  width: 36px;
  align-items: center;
  justify-content: center;
  padding: 0;
}

.metric-strip {
  display: grid;
  margin-bottom: 14px;
  overflow: hidden;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-0);

  > div {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 4px;
    padding: 14px 16px;
    border-right: 1px solid var(--gray-150);

    &:last-child {
      border-right: 0;
    }
  }

  span {
    color: var(--gray-600);
    font-size: 12px;
  }

  strong {
    overflow: hidden;
    font-size: 20px;
    font-variant-numeric: tabular-nums;
    line-height: 26px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .risk-value {
    color: var(--color-error-700);
  }
}

.toolbar {
  display: flex;
  min-height: 52px;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--gray-200);
  border-bottom: 0;
  border-radius: 8px 8px 0 0;
  background: var(--gray-0);
}

.filter-select {
  width: 132px;
}

.thread-filter {
  width: min(360px, 100%);
}

.trace-workbench {
  display: grid;
  min-height: 610px;
  grid-template-columns: minmax(300px, 0.7fr) minmax(480px, 1.3fr);
  overflow: hidden;
  border: 1px solid var(--gray-200);
  border-radius: 0 0 8px 8px;
  background: var(--gray-0);
}

.trace-list-panel {
  min-width: 0;
  overflow-y: auto;
  border-right: 1px solid var(--gray-200);
}

.panel-heading,
.timeline-heading-bar {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 16px;
  border-bottom: 1px solid var(--gray-150);

  strong {
    font-size: 13px;
  }

  span {
    color: var(--gray-500);
    font-size: 12px;
  }
}

.trace-row {
  display: block;
  width: 100%;
  padding: 13px 16px;
  border: 0;
  border-bottom: 1px solid var(--gray-100);
  background: var(--gray-0);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s ease;

  &:hover {
    background: var(--gray-25);
  }

  &.active {
    background: var(--main-30);
    box-shadow: inset 3px 0 var(--main-600);
  }
}

.trace-row-main,
.trace-row-meta,
.trace-row-footer {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.trace-row-main strong {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-row-meta {
  margin-top: 7px;
  color: var(--gray-700);
  font-size: 12px;
}

.trace-row-footer {
  margin-top: 5px;
  color: var(--gray-500);
  font-size: 11px;
}

.trace-id {
  min-width: 0;
  overflow: hidden;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-row-footer time {
  flex: 0 0 auto;
}

.trace-detail-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--gray-150);

  h2 {
    margin: 2px 0 3px;
    font-size: 18px;
    line-height: 26px;
  }

  p {
    max-width: 460px;
    margin: 0;
    overflow: hidden;
    color: var(--gray-500);
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.detail-eyebrow {
  color: var(--main-700);
  font-size: 10px;
  font-weight: 700;
}

.detail-tags {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.detail-metrics {
  display: grid;
  margin: 0;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  border-bottom: 1px solid var(--gray-150);

  div {
    min-width: 0;
    padding: 12px 14px;
    border-right: 1px solid var(--gray-100);

    &:last-child {
      border-right: 0;
    }
  }

  dt {
    margin-bottom: 4px;
    color: var(--gray-500);
    font-size: 11px;
  }

  dd {
    margin: 0;
    overflow: hidden;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.timeline-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 20px 24px;
}

.panel-state {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--gray-600);
  font-size: 13px;
}

.empty-state {
  flex-direction: column;
  color: var(--gray-500);
}

@media (max-width: 1100px) {
  .trace-workbench {
    grid-template-columns: minmax(270px, 0.8fr) minmax(420px, 1.2fr);
  }

  .detail-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));

    div:nth-child(3) {
      border-right: 0;
    }

    div:nth-child(n + 4) {
      border-top: 1px solid var(--gray-100);
    }
  }
}

@media (max-width: 767px) {
  .page-title p {
    display: none;
  }

  .metric-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));

    > div:nth-child(2) {
      border-right: 0;
    }

    > div:nth-child(n + 3) {
      border-top: 1px solid var(--gray-150);
    }
  }

  .toolbar {
    flex-wrap: wrap;
  }

  .filter-select,
  .thread-filter {
    flex: 1 1 140px;
    width: auto;
  }

  .trace-workbench {
    min-height: auto;
    grid-template-columns: 1fr;
  }

  .trace-list-panel {
    max-height: 340px;
    border-right: 0;
    border-bottom: 1px solid var(--gray-200);
  }

  .trace-detail-panel {
    min-height: 560px;
  }

  .detail-header {
    flex-direction: column;
  }
}
</style>
