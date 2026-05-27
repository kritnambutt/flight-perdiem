export interface Run {
  id: string
  cycle_month: string
  status: string
  stage: string | null
  progress: number
  counts: {
    total?: number
    valid?: number
    review?: number
    invalid?: number
    pdf?: number
    image?: number
    no_roster?: number
  }
  posting_sheet?: string | null
  late_sheet?: string | null
  started_at: string | null
  finished_at: string | null
}

export interface Period {
  start: string
  end: string
}

export interface CrewResult {
  staff_id: string
  name: string
  email: string
  periods: Period[]
  days: number
  total_thb: number
  remark: string | null
}

export interface ExceptionItem {
  claim_id: string
  verdict_id: string
  staff_id: string | null
  name: string
  email: string
  source_row_ref: string
  claimed_date: string
  verdict: string
  rule: string
  reason: string | null
  confidence: number | null
  roster_file_id: string | null
  extracted: Record<string, unknown> | null
}

export interface RunRow {
  claim_id: string
  verdict_id: string
  // verdict (per claimed day)
  claimed_date: string
  verdict: string
  decision: 'APPROVE' | 'REJECT' | null
  rule: string
  reason: string | null
  confidence: number | null
  // crew-submitted form fields
  source: string
  source_row_ref: string
  submitted_at: string | null
  staff_id: string | null
  name: string
  email: string
  position: string | null
  base: string | null
  claim_month: string
  claimed_days: number[]
  roster_file_id: string | null
}

export interface DecisionIn {
  decision: 'APPROVE' | 'REJECT'
  note?: string
  corrected_days?: number[]
}

export interface Config {
  outbound_flights: string[]
  return_flights: string[]
  rate_thb_per_day: number
  name_match_threshold: number
  ocr_confidence_threshold: number
}

export interface AuditEntry {
  id: string
  run_id: string | null
  claim_id: string | null
  action: string
  detail: Record<string, unknown>
  at: string
}
