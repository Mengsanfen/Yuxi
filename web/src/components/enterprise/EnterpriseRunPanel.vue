<template>
  <aside ref="panelRef" class="enterprise-run-panel" :class="{ resizing: isResizing }">
    <div class="resize-handle" @pointerdown="startResize"></div>

    <header class="panel-header">
      <div>
        <span class="panel-eyebrow">ENTERPRISE RUN</span>
        <strong>业务运行</strong>
      </div>
      <div class="panel-actions">
        <a-tooltip title="刷新">
          <button class="icon-button" type="button" aria-label="刷新" @click="refreshPanel">
            <RefreshCw :size="15" :class="{ spinning: loading }" />
          </button>
        </a-tooltip>
        <a-tooltip :title="isExpanded ? '恢复高度' : '向上展开'">
          <button
            class="icon-button"
            type="button"
            aria-label="切换高度"
            @click="emit('toggle-expand')"
          >
            <component :is="isExpanded ? ChevronsDownUp : ChevronsUpDown" :size="15" />
          </button>
        </a-tooltip>
        <button class="icon-button" type="button" aria-label="关闭" @click="emit('close')">
          <X :size="17" />
        </button>
      </div>
    </header>

    <div class="panel-scroll">
      <section class="run-status-band">
        <div class="status-main">
          <span class="status-dot" :class="statusMeta.statusClass"></span>
          <div>
            <strong>{{ statusMeta.label }}</strong>
            <span>{{ currentNodeLabel }}</span>
          </div>
        </div>
        <a-tag :color="riskMeta.color">{{ riskMeta.label }}</a-tag>
      </section>

      <section class="panel-section">
        <div class="section-heading">
          <strong>运行概览</strong>
          <span v-if="trace?.metrics?.latency_ms">{{
            formatLatency(trace.metrics.latency_ms)
          }}</span>
        </div>
        <dl class="overview-grid">
          <div>
            <dt>意图</dt>
            <dd>{{ intentLabel }}</dd>
          </div>
          <div>
            <dt>置信度</dt>
            <dd>{{ confidenceLabel }}</dd>
          </div>
          <div>
            <dt>当前智能体</dt>
            <dd>{{ currentAgentLabel }}</dd>
          </div>
          <div>
            <dt>质量门</dt>
            <dd :class="qualityClass">{{ qualityLabel }}</dd>
          </div>
        </dl>
      </section>

      <section v-if="hasBusinessContext" class="panel-section">
        <div class="section-heading"><strong>业务上下文</strong></div>
        <dl class="business-list">
          <div v-if="agentState.order_no">
            <dt>订单号</dt>
            <dd>{{ agentState.order_no }}</dd>
          </div>
          <div v-if="orderStatus">
            <dt>订单状态</dt>
            <dd>{{ orderStatus }}</dd>
          </div>
          <div v-if="refundStatus">
            <dt>退款状态</dt>
            <dd>{{ refundStatus }}</dd>
          </div>
          <div v-if="approvalStatus">
            <dt>审批状态</dt>
            <dd>{{ approvalStatus }}</dd>
          </div>
          <div v-if="agentState.ticket_id || ticketStatus">
            <dt>工单</dt>
            <dd>{{ agentState.ticket_id ? `#${agentState.ticket_id}` : ticketStatus }}</dd>
          </div>
          <div v-if="agentState.knowledge_result">
            <dt>知识依据</dt>
            <dd>已完成检索</dd>
          </div>
          <div v-if="knowledgeSecurityBlocked">
            <dt>安全防护</dt>
            <dd class="is-negative">已隔离可疑知识指令</dd>
          </div>
        </dl>
      </section>

      <section class="panel-section timeline-section">
        <div class="section-heading">
          <strong>执行时间线</strong>
          <span>{{ recentEvents.length }} 个事件</span>
        </div>
        <EnterpriseTraceTimeline :events="recentEvents" compact />
      </section>
    </div>
  </aside>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ChevronsDownUp, ChevronsUpDown, RefreshCw, X } from 'lucide-vue-next'

import { enterpriseApi } from '@/apis/enterprise_api'
import EnterpriseTraceTimeline from '@/components/enterprise/EnterpriseTraceTimeline.vue'

const props = defineProps({
  agentState: {
    type: Object,
    default: () => ({})
  },
  threadId: {
    type: String,
    default: null
  },
  isExpanded: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['refresh', 'close', 'resize', 'resizing', 'toggle-expand'])
const panelRef = ref(null)
const trace = ref(null)
const loading = ref(false)
const isResizing = ref(false)
let refreshTimer = null
let resizePointerId = null
let pendingClientX = 0
let resizeFrameId = 0

const intentLabels = {
  product_question: '产品咨询',
  policy_question: '政策咨询',
  order_query: '订单查询',
  logistics_query: '物流查询',
  refund_request: '退款申请',
  ticket_query: '工单查询',
  complaint: '投诉处理',
  unknown: '待澄清'
}

const nodeLabels = {
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

const agentLabels = {
  'intent-router': '意图路由',
  'entity-extractor': '实体提取',
  'knowledge-agent': '知识智能体',
  'order-agent': '订单节点',
  'refund-agent': '退款节点',
  'ticket-agent': '工单节点',
  'quality-agent': '质量节点',
  'enterprise-service-agent': '企业服务智能体',
  EnterpriseServiceAgent: '企业服务智能体'
}

const latestNodeEvent = computed(() => {
  const events = trace.value?.events || []
  return [...events].reverse().find((event) => event.node_name) || null
})

const statusMeta = computed(() => {
  const status = trace.value?.status || (props.agentState.intent ? 'running' : 'idle')
  const meta = {
    idle: { label: '等待运行', statusClass: 'is-idle' },
    running: { label: '运行中', statusClass: 'is-running' },
    completed: { label: '已完成', statusClass: 'is-success' },
    interrupted: { label: '等待人工处理', statusClass: 'is-warning' },
    failed: { label: '运行失败', statusClass: 'is-error' }
  }
  return meta[status] || { label: status, statusClass: 'is-idle' }
})

const riskMeta = computed(() => {
  const risk = props.agentState.risk_level || trace.value?.risk_level
  const meta = {
    low: { label: '低风险', color: 'green' },
    medium: { label: '中风险', color: 'orange' },
    high: { label: '高风险', color: 'red' }
  }
  return meta[risk] || { label: '未评估', color: 'default' }
})

const intentLabel = computed(
  () => intentLabels[props.agentState.intent] || props.agentState.intent || '-'
)
const confidenceLabel = computed(() => {
  const confidence = Number(props.agentState.intent_confidence)
  return Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : '-'
})
const currentNodeLabel = computed(() => nodeLabels[latestNodeEvent.value?.node_name] || '等待节点')
const currentAgentLabel = computed(
  () => agentLabels[latestNodeEvent.value?.agent_name] || latestNodeEvent.value?.agent_name || '-'
)
const qualityLabel = computed(() => {
  const quality = props.agentState.quality_result
  if (!quality) return '待检查'
  return quality.passed ? '通过' : '未通过'
})
const qualityClass = computed(() => {
  if (!props.agentState.quality_result) return ''
  return props.agentState.quality_result.passed ? 'is-positive' : 'is-negative'
})

const orderStatus = computed(() => {
  const context = props.agentState.order_context || {}
  return context.status || context.data?.status || ''
})
const refundStatus = computed(() => {
  const result = props.agentState.refund_result || {}
  return result.data?.status || result.status || result.workflow || ''
})
const approvalStatus = computed(() => {
  const result = props.agentState.approval_result || {}
  return result.status || result.data?.status || ''
})
const ticketStatus = computed(() => {
  const result = props.agentState.ticket_result || {}
  return result.status || result.data?.status || ''
})
const knowledgeSecurityBlocked = computed(
  () => Boolean(props.agentState.knowledge_result?.security?.blocked)
)
const hasBusinessContext = computed(
  () =>
    props.agentState.order_no ||
    orderStatus.value ||
    refundStatus.value ||
    approvalStatus.value ||
    props.agentState.ticket_id ||
    ticketStatus.value ||
    props.agentState.knowledge_result
)
const recentEvents = computed(() => (trace.value?.events || []).slice(-12))

const loadTrace = async () => {
  if (!props.threadId) {
    trace.value = null
    return
  }
  loading.value = true
  try {
    trace.value = await enterpriseApi.getThreadTrace(props.threadId)
  } catch (error) {
    if (error?.response?.status !== 404) {
      console.warn('加载企业运行追踪失败:', error)
    }
    trace.value = null
  } finally {
    loading.value = false
  }
}

const refreshPanel = async () => {
  emit('refresh', props.threadId)
  await loadTrace()
}

const scheduleTraceRefresh = () => {
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(loadTrace, 250)
}

const formatLatency = (value) => {
  const latency = Number(value)
  if (!Number.isFinite(latency) || latency <= 0) return '-'
  if (latency >= 1000) return `${(latency / 1000).toFixed(2)}s`
  return `${latency}ms`
}

const flushResize = () => {
  resizeFrameId = 0
  if (isResizing.value) emit('resize', pendingClientX)
}

const startResize = (event) => {
  if (event.button !== 0) return
  isResizing.value = true
  resizePointerId = event.pointerId
  pendingClientX = event.clientX
  emit('resizing', true, event.clientX)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

const onPointerMove = (event) => {
  if (!isResizing.value || event.pointerId !== resizePointerId) return
  pendingClientX = event.clientX
  if (!resizeFrameId) resizeFrameId = window.requestAnimationFrame(flushResize)
}

const stopResize = (event) => {
  if (!isResizing.value || (event && event.pointerId !== resizePointerId)) return
  if (resizeFrameId) window.cancelAnimationFrame(resizeFrameId)
  resizeFrameId = 0
  if (event) emit('resize', event.clientX)
  isResizing.value = false
  resizePointerId = null
  emit('resizing', false)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
}

watch(() => props.threadId, loadTrace)
watch(
  () => [
    props.agentState.intent,
    props.agentState.risk_level,
    props.agentState.refund_result,
    props.agentState.approval_result,
    props.agentState.quality_result
  ],
  scheduleTraceRefresh,
  { deep: true }
)

onMounted(loadTrace)
onUnmounted(() => {
  if (refreshTimer) window.clearTimeout(refreshTimer)
  if (resizeFrameId) window.cancelAnimationFrame(resizeFrameId)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})
</script>

<style scoped lang="less">
.enterprise-run-panel {
  position: relative;
  display: flex;
  width: 100%;
  height: 100%;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  border-left: 1px solid var(--gray-200);
  background: var(--gray-0);
}

.resize-handle {
  position: absolute;
  z-index: 4;
  top: 0;
  bottom: 0;
  left: -3px;
  width: 7px;
  cursor: col-resize;

  &:hover,
  .resizing & {
    background: color-mix(in srgb, var(--main-500) 24%, transparent);
  }
}

.panel-header {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px 9px 16px;
  border-bottom: 1px solid var(--gray-150);

  > div:first-child {
    display: flex;
    min-width: 0;
    flex-direction: column;
  }

  strong {
    color: var(--gray-900);
    font-size: 14px;
  }
}

.panel-eyebrow {
  color: var(--main-700);
  font-size: 9px;
  font-weight: 700;
}

.panel-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 2px;
}

.icon-button {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-600);
  cursor: pointer;

  &:hover {
    background: var(--gray-50);
    color: var(--gray-900);
  }
}

.spinning {
  animation: spin 0.8s linear infinite;
}

.panel-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.run-status-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 16px;
  border-bottom: 1px solid var(--gray-150);
  background: var(--gray-25);
}

.status-main {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;

  > div {
    display: flex;
    min-width: 0;
    flex-direction: column;
  }

  strong {
    font-size: 13px;
  }

  span:last-child {
    overflow: hidden;
    color: var(--gray-600);
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.status-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
  background: var(--gray-400);

  &.is-running {
    background: var(--main-500);
    box-shadow: 0 0 0 3px var(--main-100);
  }

  &.is-success {
    background: var(--color-success-500);
  }

  &.is-warning {
    background: var(--color-warning-500);
  }

  &.is-error {
    background: var(--color-error-500);
  }
}

.panel-section {
  padding: 15px 16px;
  border-bottom: 1px solid var(--gray-150);
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;

  strong {
    font-size: 12px;
  }

  span {
    color: var(--gray-500);
    font-size: 11px;
  }
}

.overview-grid {
  display: grid;
  margin: 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;

  div {
    min-width: 0;
  }

  dt,
  dd {
    margin: 0;
  }

  dt {
    margin-bottom: 3px;
    color: var(--gray-500);
    font-size: 10px;
  }

  dd {
    overflow: hidden;
    font-size: 12px;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.business-list {
  display: grid;
  margin: 0;
  gap: 8px;

  div {
    display: grid;
    min-width: 0;
    grid-template-columns: 74px minmax(0, 1fr);
    gap: 8px;
  }

  dt,
  dd {
    margin: 0;
    font-size: 12px;
  }

  dt {
    color: var(--gray-500);
  }

  dd {
    overflow: hidden;
    color: var(--gray-800);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.is-positive {
  color: var(--color-success-700);
}

.is-negative {
  color: var(--color-error-700);
}

.timeline-section {
  border-bottom: 0;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
