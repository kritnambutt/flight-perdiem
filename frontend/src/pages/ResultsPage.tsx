import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  downloadLateSubmissionInput,
  downloadPostingBaseInput,
  downloadReport,
  exportExceptions,
  getConfig,
  getRun,
  getRunRows,
} from '../lib/apiClient'
import { Badge } from '../components/ui/badge'
import { Heading } from '../components/ui/heading'
import { Text } from '../components/ui/text'
import { DecisionControls } from '../components/DecisionControls'
import { RosterPreview } from '../components/RosterPreview'
import type { RunRow } from '../types'

type BadgeColor = React.ComponentProps<typeof Badge>['color']

const VERDICT_META: Record<string, { label: string; color: BadgeColor; accent: string }> = {
  VALID: { label: 'Valid', color: 'green', accent: 'border-l-green-500' },
  VALID_BACKCLAIM: { label: 'Valid (back-claim)', color: 'teal', accent: 'border-l-teal-500' },
  NEEDS_REVIEW: { label: 'Needs review', color: 'yellow', accent: 'border-l-yellow-500' },
  INVALID: { label: 'Invalid', color: 'red', accent: 'border-l-red-500' },
}
const VERDICT_ORDER = ['NEEDS_REVIEW', 'INVALID', 'VALID_BACKCLAIM', 'VALID']
const PAYABLE = new Set(['VALID', 'VALID_BACKCLAIM'])

const STATUS_COLORS: Record<string, BadgeColor> = {
  DONE: 'green', FAILED: 'red', RUNNING: 'blue', PENDING: 'zinc',
}
const SOURCE_LABEL: Record<string, string> = {
  POSTING_BASE: 'Posting Base',
  LATE: 'Late Submission',
  LATE_SUBMISSION: 'Late Submission',
}
const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s

const fmtDate = (d: string) =>
  new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

// Form submission timestamp: date + time, e.g. "6 Aug 2025, 14:30".
const fmtDateTime = (d?: string | null): string | null => {
  if (!d) return null
  const t = new Date(d)
  if (Number.isNaN(t.getTime())) return null
  return t.toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// Wall-clock processing time between a run's start and finish, e.g. "17m 32s".
const fmtDuration = (start?: string | null, end?: string | null): string | null => {
  if (!start || !end) return null
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (Number.isNaN(ms) || ms < 0) return null
  const total = Math.round(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

// A submission row = one claim (one Google Form response). It carries many
// per-day verdicts, but approve/reject and the summary all work at this row level.
interface ClaimGroup {
  claimId: string
  staffId: string | null
  name: string
  email: string
  source: string
  submittedAt: string | null
  position: string | null
  base: string | null
  claimMonth: string
  rowRef: string
  rosterFileId: string | null
  claimedDays: number[]
  decision: 'APPROVE' | 'REJECT' | null
  rows: RunRow[] // per-day verdicts, sorted by date
}

// Row-level verdict: an admin decision wins; otherwise roll the day verdicts up
// (any review, or a mix of payable + invalid, surfaces as NEEDS_REVIEW so the
// whole row is reviewed rather than silently part-paid / part-rejected).
const claimStatus = (c: ClaimGroup): string => {
  if (c.decision === 'APPROVE') return 'VALID'
  if (c.decision === 'REJECT') return 'INVALID'
  const vs = c.rows.map((r) => r.verdict)
  const hasReview = vs.some((v) => v === 'NEEDS_REVIEW')
  const hasInvalid = vs.some((v) => v === 'INVALID')
  const hasPayable = vs.some((v) => PAYABLE.has(v))
  if (hasReview || (hasInvalid && hasPayable)) return 'NEEDS_REVIEW'
  if (hasInvalid) return 'INVALID'
  return 'VALID'
}

// source_row_ref is "<path>!<sheet>!<row>"; show the workbook sheet + 1-based row.
const parseRowRef = (ref: string): { sheet: string | null; row: string | null } => {
  const parts = ref.split('!')
  return {
    row: parts.length ? parts[parts.length - 1] : null,
    sheet: parts.length >= 2 ? parts[parts.length - 2] : null,
  }
}

// Numeric row number (NaN-safe) for ordering submission rows.
const rowNum = (ref: string): number => {
  const n = parseInt(parseRowRef(ref).row ?? '', 10)
  return Number.isNaN(n) ? Number.MAX_SAFE_INTEGER : n
}

// Posting Base before Late Submission; everything else after.
const sourceRank = (s: string): number =>
  s === 'POSTING_BASE' ? 0 : s === 'LATE' || s === 'LATE_SUBMISSION' ? 1 : 2

const SummaryCard = ({ value, label, sub }: { value: string | number; label: string; sub?: string }) => (
  <div className="bg-white dark:bg-zinc-900 rounded-xl ring-1 ring-zinc-950/5 dark:ring-white/10 shadow-sm p-4 text-center">
    <p className="text-2xl font-bold text-zinc-900 dark:text-white">{value}</p>
    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">{label}</p>
    {sub && <p className="text-xs text-zinc-400 mt-0.5">{sub}</p>}
  </div>
)

// A single downloadable workbook in the session-files panel. Disabled rows render
// greyed-out (e.g. result reports before the run has finished).
const FileRow = ({ label, sub, href, disabled }: {
  label: string; sub: string; href: string; disabled?: boolean
}) => {
  const body = (
    <>
      <svg viewBox="0 0 20 20" fill="currentColor" className="size-4 shrink-0 text-zinc-400" aria-hidden="true">
        <path d="M4 3a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.414A2 2 0 0 0 17.414 6L14 2.586A2 2 0 0 0 12.586 2H4Zm6 5a.75.75 0 0 1 .75.75v3.19l1.22-1.22a.75.75 0 1 1 1.06 1.06l-2.5 2.5a.75.75 0 0 1-1.06 0l-2.5-2.5a.75.75 0 1 1 1.06-1.06l1.22 1.22V8.75A.75.75 0 0 1 10 8Z" />
      </svg>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-zinc-800 dark:text-zinc-100 truncate">{label}</span>
        <span className="block text-xs text-zinc-500 dark:text-zinc-400">{sub}</span>
      </span>
      <span className="ml-auto text-xs font-medium text-blue-600 dark:text-blue-400 shrink-0">
        {disabled ? 'Not ready' : 'Download'}
      </span>
    </>
  )
  const base = 'flex items-center gap-3 rounded-lg ring-1 px-3 py-2.5 transition'
  if (disabled) {
    return (
      <div className={`${base} ring-zinc-950/5 dark:ring-white/10 opacity-50 cursor-not-allowed`} aria-disabled="true">
        {body}
      </div>
    )
  }
  return (
    <a
      href={href}
      download
      className={`${base} ring-zinc-950/10 dark:ring-white/10 hover:bg-zinc-50 dark:hover:bg-white/5 hover:ring-blue-500/40 focus:outline-none focus:ring-2 focus:ring-blue-500`}
    >
      {body}
    </a>
  )
}

const InfoField = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div>
    <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">{label}</p>
    <p className="text-sm text-zinc-800 dark:text-zinc-200 mt-0.5 break-words">{value || '—'}</p>
  </div>
)

// One submission row (claim) card; expandable to the file row number, the per-day
// verdict breakdown, the roster, and a single approve/reject decision for the row.
const ClaimCard = ({ claim, expanded, onToggle, onDecision }: {
  claim: ClaimGroup; expanded: boolean; onToggle: () => void; onDecision: () => void
}) => {
  const status = claimStatus(claim)
  const meta = VERDICT_META[status] ?? { label: status, color: 'zinc' as BadgeColor, accent: 'border-l-zinc-400' }
  const { sheet, row } = parseRowRef(claim.rowRef)
  const days = claim.rows.length

  return (
    <div className={`bg-white dark:bg-zinc-900 rounded-xl ring-1 ring-zinc-950/5 dark:ring-white/10 border-l-4 ${meta.accent} overflow-hidden`}>
      <div className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-zinc-50 dark:hover:bg-white/5 transition" onClick={onToggle}>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-zinc-900 dark:text-white truncate">{claim.name}</p>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {claim.staffId ?? '—'} · {sourceLabel(claim.source)} · {days} claimed {days === 1 ? 'day' : 'days'}
            {row && <> · <span className="font-medium">Row {row}</span></>}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {claim.decision && (
            <span className="text-xs text-zinc-400 italic">
              {claim.decision === 'APPROVE' ? 'approved' : 'rejected'} by admin
            </span>
          )}
          <Badge color={meta.color}>{meta.label}</Badge>
          <span className="text-zinc-400 text-sm">{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-zinc-950/5 dark:border-white/10 px-4 py-4 space-y-6">
          {/* Top: crew details (left) + roster preview (right) */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-6">
            <div className="md:col-span-3">
              <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">Submitted by crew</p>
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                <InfoField label="Source form" value={sourceLabel(claim.source)} />
                <InfoField label="Submitted at" value={fmtDateTime(claim.submittedAt)} />
                <InfoField label="File row" value={row ? `${sheet ? sheet + ' · ' : ''}row ${row}` : '—'} />
                <InfoField label="Staff ID" value={claim.staffId} />
                <InfoField label="Name" value={claim.name} />
                <InfoField label="Position" value={claim.position} />
                <InfoField label="Operating base" value={claim.base} />
                <InfoField label="Email" value={claim.email} />
                <InfoField label="Claim month" value={claim.claimMonth} />
                <InfoField label="Claimed days" value={claim.claimedDays.join(', ')} />
                <InfoField label="Total days" value={days} />
              </div>
            </div>
            <div className="md:col-span-2">
              <RosterPreview fileId={claim.rosterFileId} />
            </div>
          </div>

          {/* Per-day verdicts — full width, aligned columns, full reason text */}
          <div>
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-2">
              Per-day verdicts ({days})
            </p>
            <div className="overflow-x-auto rounded-lg ring-1 ring-zinc-950/5 dark:ring-white/10">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-zinc-50 dark:bg-white/5 text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    <th className="px-3 py-2 w-40">Verdict</th>
                    <th className="px-3 py-2 w-32 whitespace-nowrap">Date</th>
                    <th className="px-3 py-2 w-16">Rule</th>
                    <th className="px-3 py-2">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-950/5 dark:divide-white/10">
                  {claim.rows.map((d) => {
                    const dm = VERDICT_META[d.verdict] ?? { label: d.verdict, color: 'zinc' as BadgeColor }
                    return (
                      <tr key={d.verdict_id} className="align-top">
                        <td className="px-3 py-2">
                          <Badge color={dm.color}>{d.verdict.replace(/_/g, ' ')}</Badge>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-zinc-700 dark:text-zinc-200">
                          {fmtDate(d.claimed_date)}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap text-zinc-500 dark:text-zinc-400">{d.rule}</td>
                        <td className="px-3 py-2 text-zinc-600 dark:text-zinc-300 wrap-break-word">
                          {d.reason ?? '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Decision — full width below the breakdown */}
          <div>
            <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide mb-1">
              Decision (applies to the whole row)
            </p>
            <DecisionControls claimId={claim.claimId} onDone={onDecision} />
          </div>
        </div>
      )}
    </div>
  )
}

export const ResultsPage = () => {
  const { runId } = useParams<{ runId: string }>()
  const queryClient = useQueryClient()
  const [openClaim, setOpenClaim] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set(VERDICT_ORDER))
  const [sourceFilter, setSourceFilter] = useState<string>('') // '' = all forms

  const { data: run } = useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId!).then((r) => r.data),
    enabled: !!runId,
  })
  const { data: rows, isLoading } = useQuery({
    queryKey: ['rows', runId],
    queryFn: () => getRunRows(runId!).then((r) => r.data),
    enabled: !!runId,
  })
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => getConfig().then((r) => r.data),
  })

  // Group per-day verdicts into submission rows (one claim = one form response).
  const claims = useMemo<ClaimGroup[]>(() => {
    const map = new Map<string, ClaimGroup>()
    for (const r of rows ?? []) {
      let c = map.get(r.claim_id)
      if (!c) {
        c = {
          claimId: r.claim_id,
          staffId: r.staff_id,
          name: r.name,
          email: r.email,
          source: r.source,
          submittedAt: r.submitted_at,
          position: r.position,
          base: r.base,
          claimMonth: r.claim_month,
          rowRef: r.source_row_ref,
          rosterFileId: r.roster_file_id,
          claimedDays: r.claimed_days,
          decision: r.decision,
          rows: [],
        }
        map.set(r.claim_id, c)
      }
      c.rows.push(r)
    }
    for (const c of map.values()) {
      c.rows.sort((a, b) => a.claimed_date.localeCompare(b.claimed_date))
    }
    // Order: Posting Base first, then Late Submission; within a form, by file row ASC.
    return [...map.values()].sort(
      (a, b) =>
        sourceRank(a.source) - sourceRank(b.source) ||
        rowNum(a.rowRef) - rowNum(b.rowRef),
    )
  }, [rows])

  const sourceMatches = (c: ClaimGroup) => sourceFilter === '' || c.source === sourceFilter
  const sourceClaims = claims.filter(sourceMatches)

  // Verdict tallies are per submission row, reflecting the selected form.
  const verdictCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const cl of sourceClaims) {
      const s = claimStatus(cl)
      c[s] = (c[s] ?? 0) + 1
    }
    return c
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claims, sourceFilter])

  const presentVerdicts = VERDICT_ORDER.filter((v) => verdictCounts[v] > 0)

  const presentSources = useMemo(() => {
    const set = new Set<string>()
    for (const c of claims) set.add(c.source)
    // Posting Base first, then the rest alphabetically.
    return [...set].sort((a, b) =>
      a === 'POSTING_BASE' ? -1 : b === 'POSTING_BASE' ? 1 : a.localeCompare(b)
    )
  }, [claims])

  const distinctCrew = useMemo(
    () => new Set((rows ?? []).map((r) => r.staff_id || r.name)).size,
    [rows],
  )

  // Summary is row-based: a row counts once regardless of how many days it claims.
  // Per diem sums the days of every payable (valid) row × the daily rate.
  const rate = config?.rate_thb_per_day ?? 0
  const validForms = sourceClaims.filter((c) => claimStatus(c) === 'VALID')
  const needsReviewForms = sourceClaims.filter((c) => claimStatus(c) === 'NEEDS_REVIEW').length
  const invalidForms = sourceClaims.filter((c) => claimStatus(c) === 'INVALID').length
  const payableDays = validForms.reduce((sum, c) => sum + c.rows.length, 0)
  const perDiemThb = payableDays * rate

  const toggle = (v: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(v)) next.delete(v)
      else next.add(v)
      return next
    })

  const onDecision = () => {
    queryClient.invalidateQueries({ queryKey: ['rows', runId] })
    queryClient.invalidateQueries({ queryKey: ['run', runId] })
  }

  // A claim is visible if its row-level verdict matches the verdict + source filters.
  const visibleClaims = sourceClaims.filter((c) => selected.has(claimStatus(c)))

  const duration = fmtDuration(run?.started_at, run?.finished_at)

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <Heading>{run?.cycle_month ?? 'Run'}</Heading>
            {run && <Badge color={STATUS_COLORS[run.status] ?? 'zinc'}>{run.status}</Badge>}
          </div>
          <Text className="mt-1">{distinctCrew} crew · {claims.length} submission rows · {rows?.length ?? 0} claimed days</Text>
          {run && (
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
              <span>
                <span className="font-semibold text-zinc-700 dark:text-zinc-200">{duration ?? '—'}</span> processing time
              </span>
              <span>
                <span className="font-semibold text-zinc-700 dark:text-zinc-200">{run.counts.pdf ?? 0}</span> PDF
              </span>
              <span>
                <span className="font-semibold text-zinc-700 dark:text-zinc-200">{run.counts.image ?? 0}</span> images
              </span>
              {(run.counts.no_roster ?? 0) > 0 && (
                <span>
                  <span className="font-semibold text-zinc-700 dark:text-zinc-200">{run.counts.no_roster}</span> no roster
                </span>
              )}
            </div>
          )}
        </div>

        {/* Run timing — started / finished datetimes */}
        {run && (run.started_at || run.finished_at) && (
          <dl className="shrink-0 rounded-lg ring-1 ring-zinc-950/5 dark:ring-white/10 bg-white dark:bg-zinc-900 px-4 py-3 text-xs sm:min-w-56">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Started</dt>
              <dd className="font-medium text-zinc-800 dark:text-zinc-100">{fmtDateTime(run.started_at) ?? '—'}</dd>
            </div>
            <div className="mt-1.5 flex items-baseline justify-between gap-4">
              <dt className="font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Finished</dt>
              <dd className="font-medium text-zinc-800 dark:text-zinc-100">{fmtDateTime(run.finished_at) ?? '—'}</dd>
            </div>
          </dl>
        )}
      </div>

      {/* Session files — the workbooks submitted to this run and the validation output */}
      <div className="bg-white dark:bg-zinc-900 rounded-xl ring-1 ring-zinc-950/5 dark:ring-white/10 shadow-sm p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400 mb-2">
              Submitted to pipeline
            </p>
            <div className="space-y-2">
              <FileRow
                label="Posting Base response"
                sub="On-time form submissions (.xlsx)"
                href={downloadPostingBaseInput(runId!)}
              />
              <FileRow
                label="Late Submission response"
                sub="Back-claim form submissions (.xlsx)"
                href={downloadLateSubmissionInput(runId!)}
              />
            </div>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400 mb-2">
              Validation results
            </p>
            <div className="space-y-2">
              <FileRow
                label="Master report"
                sub="Payable per diem by crew (.xlsx)"
                href={downloadReport(runId!)}
                disabled={run?.status !== 'DONE'}
              />
              <FileRow
                label="Exceptions report"
                sub="Flagged & rejected claims (.xlsx)"
                href={exportExceptions(runId!)}
                disabled={run?.status !== 'DONE' && run?.status !== 'FAILED'}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Filters (above the cards): source select (left) + verdict toggles (right) */}
      {(presentVerdicts.length > 0 || presentSources.length > 0) && (
        <div className="flex flex-wrap items-center gap-2">
          {presentSources.length > 0 && (
            <>
              <span className="text-sm text-zinc-500 dark:text-zinc-400 mr-1">Form:</span>
              {['', ...presentSources].map((s) => {
                const on = sourceFilter === s
                const color: BadgeColor = s === '' ? 'zinc' : s === 'POSTING_BASE' ? 'blue' : 'indigo'
                return (
                  <button
                    key={s || 'ALL'}
                    type="button"
                    onClick={() => setSourceFilter(s)}
                    className={`rounded-md transition ${on ? '' : 'opacity-40 grayscale'} focus:outline-none focus:ring-2 focus:ring-blue-500`}
                    aria-pressed={on}
                  >
                    <Badge color={color}>{s === '' ? 'All forms' : sourceLabel(s)}</Badge>
                  </button>
                )
              })}
            </>
          )}
          {presentVerdicts.length > 0 && (
            <div className="ml-auto flex flex-wrap items-center gap-2">
              {presentVerdicts.map((v) => {
                const meta = VERDICT_META[v]
                const on = selected.has(v)
                return (
                  <button
                    key={v}
                    type="button"
                    onClick={() => toggle(v)}
                    className={`rounded-md transition ${on ? '' : 'opacity-40 grayscale'} focus:outline-none focus:ring-2 focus:ring-blue-500`}
                    aria-pressed={on}
                    title={on ? `Hide ${meta.label}` : `Show ${meta.label}`}
                  >
                    <Badge color={meta.color}>{meta.label} · {verdictCounts[v]}</Badge>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Summary cards — counted per submission row, reflecting the selected form.
          Valid + Needs review + Invalid partition every row, so they reconcile
          with the submission-row total above. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <SummaryCard value={validForms.length} label="Valid forms" sub="payable rows" />
        <SummaryCard value={needsReviewForms} label="Needs review" sub="flagged rows" />
        <SummaryCard value={invalidForms} label="Invalid forms" sub="rejected rows" />
        <SummaryCard value={perDiemThb.toLocaleString()} label="Per diem (THB)" sub={`${payableDays} days`} />
      </div>

      {isLoading ? (
        <Text>Loading rows…</Text>
      ) : (rows?.length ?? 0) === 0 ? (
        <div className="bg-white dark:bg-zinc-900 rounded-xl ring-1 ring-zinc-950/5 dark:ring-white/10 p-10 text-center">
          <p className="text-lg font-medium text-zinc-700 dark:text-zinc-200">No rows</p>
          <Text className="mt-1">
            {run?.status === 'FAILED' ? 'This run failed before producing verdicts.'
              : run?.status === 'DONE' ? 'This run produced no claimed days.'
              : 'This run has not finished yet.'}
          </Text>
        </div>
      ) : visibleClaims.length === 0 ? (
        <Text>No submission rows match the selected filters.</Text>
      ) : (
        <div className="space-y-2">
          {visibleClaims.map((claim) => (
            <ClaimCard
              key={claim.claimId}
              claim={claim}
              expanded={openClaim === claim.claimId}
              onToggle={() => setOpenClaim(openClaim === claim.claimId ? null : claim.claimId)}
              onDecision={onDecision}
            />
          ))}
        </div>
      )}
    </div>
  )
}
