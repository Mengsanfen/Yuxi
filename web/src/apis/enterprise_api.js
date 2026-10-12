import { apiAdminGet, apiAdminPost, apiRequest } from './base'

const buildQuery = (params = {}) => {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, value)
    }
  })
  const suffix = query.toString()
  return suffix ? `?${suffix}` : ''
}

export const enterpriseApi = {
  listApprovals(params = {}) {
    return apiAdminGet(`/api/enterprise/approvals${buildQuery(params)}`)
  },

  getApproval(taskId) {
    return apiAdminGet(`/api/enterprise/approvals/${taskId}`)
  },

  reviewApproval(taskId, data) {
    return apiAdminPost(`/api/enterprise/approvals/${taskId}/review`, data)
  },

  listTickets(params = {}) {
    return apiAdminGet(`/api/enterprise/tickets${buildQuery(params)}`)
  },

  updateTicketStatus(ticketId, status) {
    return apiRequest(`/api/enterprise/tickets/${ticketId}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status })
    })
  },

  listTraces(params = {}) {
    return apiAdminGet(`/api/enterprise/traces${buildQuery(params)}`)
  },

  getTrace(traceId) {
    return apiAdminGet(`/api/enterprise/traces/${traceId}`)
  },

  getThreadTrace(threadId) {
    return apiRequest(`/api/enterprise/threads/${threadId}/trace`, { method: 'GET' })
  }
}
