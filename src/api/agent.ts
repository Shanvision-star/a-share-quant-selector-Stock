import api from './index'
export type AgentTask = 'candidates' | 'tracking' | 'reviews'
export interface AgentInput {
  question: string
  task: AgentTask
  mode: 'local' | 'model'
  code?: string
  trade_date?: string
  limit?: number
}
export interface AgentRun {
  run_id: string
  status:
    'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  created_at: string
  input: AgentInput
  provider: string | null
  model: string | null
  latency_ms: number | null
  usage: { total_tokens?: number } | null
  error: string | null
  saved_review?: string
  sources: {
    source_id: string
    tool: string
    retrieved_at: string
    sha256: string
    data: { total: number; items: unknown[] }
  }[]
  events: { at: string; type: string }[]
  output: {
    summary: string
    findings: { text: string; source_ids: string[] }[]
    next_steps: string[]
    limitations: string[]
  } | null
}
export interface AgentCapabilities {
  model_ready: boolean
  provider: string | null
  model: string | null
}
export const getAgentCapabilities = () =>
  api.get<AgentCapabilities>('/agent/capabilities')
export const listAgentRuns = () => api.get<{ items: AgentRun[] }>('/agent/runs')
export const getAgentRun = (id: string) =>
  api.get<AgentRun>(`/agent/runs/${encodeURIComponent(id)}`)
export const startAgentRun = (payload: AgentInput) =>
  api.post<AgentRun>('/agent/runs', payload)
export const cancelAgentRun = (id: string) =>
  api.post<AgentRun>(`/agent/runs/${encodeURIComponent(id)}/cancel`)
export const saveAgentReview = (id: string, reviewDate: string) =>
  api.post(`/agent/runs/${encodeURIComponent(id)}/review`, {
    review_date: reviewDate,
    confirmed: true,
  })
