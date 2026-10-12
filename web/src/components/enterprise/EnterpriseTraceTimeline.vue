<template>
  <div class="trace-timeline" :class="{ compact }">
    <div v-if="!events.length" class="timeline-empty">
      <Activity :size="22" />
      <span>暂无运行事件</span>
    </div>

    <ol v-else class="timeline-list">
      <li v-for="event in events" :key="event.id" class="timeline-item">
        <span class="timeline-marker" :class="statusClass(event.status)">
          <component :is="eventIcon(event.event_type)" :size="14" />
        </span>
        <div class="timeline-body">
          <div class="timeline-heading">
            <div class="event-name">
              <strong>{{ eventLabel(event) }}</strong>
              <span v-if="event.agent_name">{{ agentLabel(event.agent_name) }}</span>
            </div>
            <span class="event-time">{{ formatLatency(event.latency_ms) }}</span>
          </div>
          <div v-if="summaryItems(event).length" class="event-summary">
            <span v-for="item in summaryItems(event)" :key="item.label">
              {{ item.label }}：{{ item.value }}
            </span>
          </div>
          <time>{{ formatDate(event.created_at) }}</time>
        </div>
      </li>
    </ol>
  </div>
</template>

<script setup>
import {
  Activity,
  BadgeCheck,
  BrainCircuit,
  Flag,
  Gauge,
  GitBranch,
  RefreshCw,
  Search,
  ShieldCheck,
  Wrench
} from 'lucide-vue-next'

defineProps({
  events: {
    type: Array,
    default: () => []
  },
  compact: {
    type: Boolean,
    default: false
  }
})

const eventMeta = {
  input: { label: '接收请求', icon: Activity },
  intent: { label: '意图识别', icon: BrainCircuit },
  entities: { label: '实体提取', icon: Search },
  retrieval: { label: '知识检索', icon: Search },
  business_query: { label: '业务查询', icon: GitBranch },
  business_action: { label: '业务处理', icon: Gauge },
  tool_call: { label: '工具调用', icon: Wrench },
  quality: { label: '质量检查', icon: ShieldCheck },
  repair: { label: '结果修复', icon: RefreshCw },
  resume: { label: '审批恢复', icon: RefreshCw },
  final: { label: '生成结果', icon: Flag },
  result: { label: '运行结束', icon: BadgeCheck },
  node: { label: '节点执行', icon: GitBranch }
}

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

const riskLabels = { low: '低风险', medium: '中风险', high: '高风险' }

const eventIcon = (type) => eventMeta[type]?.icon || Activity

const eventLabel = (event) => {
  if (event.event_type === 'tool_call') {
    return event.payload_summary?.tool_name || '工具调用'
  }
  return eventMeta[event.event_type]?.label || event.node_name || '运行事件'
}

const agentLabel = (name) => {
  const labels = {
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
  return labels[name] || name
}

const statusClass = (status) => {
  if (status === 'failed') return 'is-error'
  if (status === 'warning' || status === 'interrupted') return 'is-warning'
  if (status === 'running') return 'is-running'
  return 'is-success'
}

const summaryItems = (event) => {
  const payload = event.payload_summary || {}
  const result = []
  if (payload.intent)
    result.push({ label: '意图', value: intentLabels[payload.intent] || payload.intent })
  if (payload.intent_confidence !== undefined) {
    result.push({
      label: '置信度',
      value: `${Math.round(Number(payload.intent_confidence) * 100)}%`
    })
  }
  if (payload.risk_level) {
    result.push({ label: '风险', value: riskLabels[payload.risk_level] || payload.risk_level })
  }
  if (payload.order_no) result.push({ label: '订单', value: payload.order_no })
  if (payload.customer_id) result.push({ label: '客户', value: `#${payload.customer_id}` })
  if (payload.ticket_id) result.push({ label: '工单', value: `#${payload.ticket_id}` })
  if (payload.quality_result?.passed !== undefined) {
    result.push({ label: '质检', value: payload.quality_result.passed ? '通过' : '未通过' })
  }
  if (payload.knowledge_result?.security?.blocked) {
    result.push({ label: '安全', value: '已隔离可疑知识指令' })
  }
  if (payload.review_decision) result.push({ label: '审批', value: payload.review_decision })
  if (event.event_type === 'tool_call') {
    result.push({ label: '状态', value: payload.status === 'failed' ? '失败' : '成功' })
  }
  return result.slice(0, 4)
}

const formatLatency = (value) => {
  const latency = Number(value)
  if (!Number.isFinite(latency) || latency <= 0) return '-'
  if (latency >= 1000) return `${(latency / 1000).toFixed(2)}s`
  return `${latency}ms`
}

const formatDate = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped lang="less">
.trace-timeline {
  min-width: 0;
}

.timeline-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.timeline-item {
  position: relative;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
  padding-bottom: 18px;

  &::before {
    position: absolute;
    top: 26px;
    bottom: 0;
    left: 13px;
    width: 1px;
    background: var(--gray-200);
    content: '';
  }

  &:last-child {
    padding-bottom: 0;

    &::before {
      display: none;
    }
  }
}

.timeline-marker {
  z-index: 1;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid var(--gray-200);
  border-radius: 50%;
  background: var(--gray-0);
  color: var(--gray-600);

  &.is-success {
    border-color: var(--color-success-100);
    background: var(--color-success-50);
    color: var(--color-success-700);
  }

  &.is-running {
    border-color: var(--main-200);
    background: var(--main-50);
    color: var(--main-700);
  }

  &.is-warning {
    border-color: var(--color-warning-100);
    background: var(--color-warning-50);
    color: var(--color-warning-700);
  }

  &.is-error {
    border-color: var(--color-error-100);
    background: var(--color-error-50);
    color: var(--color-error-700);
  }
}

.timeline-body {
  min-width: 0;
  padding-top: 2px;

  time {
    display: block;
    margin-top: 5px;
    color: var(--gray-500);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
}

.timeline-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.event-name {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;

  strong {
    overflow: hidden;
    color: var(--gray-900);
    font-size: 13px;
    line-height: 18px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  span {
    color: var(--gray-600);
    font-size: 11px;
  }
}

.event-time {
  flex: 0 0 auto;
  color: var(--gray-600);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.event-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 7px;
  color: var(--gray-700);
  font-size: 12px;
  line-height: 18px;
}

.timeline-empty {
  display: flex;
  min-height: 120px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  color: var(--gray-500);
  font-size: 13px;
}

.compact {
  .timeline-item {
    padding-bottom: 14px;
  }

  .event-summary {
    display: grid;
    gap: 2px;
  }
}
</style>
