import axios from 'axios'
import type { AuditEntry, Config, CrewResult, DecisionIn, ExceptionItem, Run, RunRow } from '../types'

const api = axios.create({ withCredentials: true })

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

// Auth
export const login = (password: string) =>
  api.post('/api/auth/login', { password })

export const logout = () =>
  api.post('/api/auth/logout')

export const getMe = () =>
  api.get<{ user: string }>('/api/auth/me')

// Runs
export const createRun = (
  month: string,
  postingBase: File,
  lateSubmission: File,
  postingSheet?: string,
  lateSheet?: string,
) => {
  const form = new FormData()
  form.append('month', month)
  form.append('posting_base', postingBase)
  form.append('late_submission', lateSubmission)
  if (postingSheet) form.append('posting_sheet', postingSheet)
  if (lateSheet) form.append('late_sheet', lateSheet)
  return api.post<{ run_id: string }>('/api/runs', form)
}

// Worksheet names of an uploaded workbook (+ the month-matched default).
export const getWorkbookSheets = (file: File, month?: string) => {
  const form = new FormData()
  form.append('file', file)
  if (month) form.append('month', month)
  return api.post<{ sheets: string[]; suggested: string | null }>('/api/runs/sheets', form)
}

export const listRuns = (limit = 50, offset = 0) =>
  api.get<Run[]>('/api/runs', { params: { limit, offset } })

export const getRun = (id: string) =>
  api.get<Run>(`/api/runs/${id}`)

// Source workbooks submitted to the run (download as <a download href=...>)
export const downloadPostingBaseInput = (runId: string) =>
  `/api/runs/${runId}/inputs/posting-base`

export const downloadLateSubmissionInput = (runId: string) =>
  `/api/runs/${runId}/inputs/late-submission`

// Results
export const getResults = (runId: string) =>
  api.get<CrewResult[]>(`/api/runs/${runId}/results`)

// All rows (every per-day verdict + crew form fields)
export const getRunRows = (runId: string, limit = 2000, offset = 0) =>
  api.get<RunRow[]>(`/api/runs/${runId}/rows`, { params: { limit, offset } })

// Exceptions
export const getExceptions = (runId: string, limit = 100, offset = 0) =>
  api.get<ExceptionItem[]>(`/api/runs/${runId}/exceptions`, { params: { limit, offset } })

export const exportExceptions = (runId: string) =>
  `/api/runs/${runId}/exceptions/export`

// Roster image (auth-gated — use as src via credential fetch)
export const getRosterUrl = (fileId: string) => `/api/rosters/${fileId}`

// Claims / decisions
export const postDecision = (claimId: string, body: DecisionIn) =>
  api.post(`/api/claims/${claimId}/decision`, body)

// Reports
export const downloadReport = (runId: string) =>
  `/api/runs/${runId}/report`

// Config
export const getConfig = () =>
  api.get<Config>('/api/config')

export const updateConfig = (cfg: Config) =>
  api.put<Config>('/api/config', cfg)

// Audit
export const getAudit = (params?: { run_id?: string; claim_id?: string; action?: string; limit?: number; offset?: number }) =>
  api.get<AuditEntry[]>('/api/audit', { params })
