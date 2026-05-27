import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { createRun, getRun, getWorkbookSheets, listRuns } from '../lib/apiClient'
import { ProgressBar } from '../components/ProgressBar'
import { usePolling } from '../hooks/usePolling'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Divider } from '../components/ui/divider'
import { Field, FieldGroup, Label, Description, ErrorMessage } from '../components/ui/fieldset'
import { Input } from '../components/ui/input'
import { Heading, Subheading } from '../components/ui/heading'
import type { Run } from '../types'

const STAGE_LABELS: Record<string, string> = {
  parsing: 'Parsing form responses',
  downloading: 'Downloading rosters',
  ocr: 'Running OCR',
  validating: 'Validating claims',
  aggregating: 'Aggregating results',
  done: 'Complete',
  error: 'Error',
  crashed: 'Crashed',
}

const STATUS_COLORS: Record<string, React.ComponentProps<typeof Badge>['color']> = {
  DONE: 'green',
  FAILED: 'red',
  RUNNING: 'blue',
  PENDING: 'zinc',
}

const RunStatusBadge = ({ run }: { run: Run }) => (
  <Badge color={STATUS_COLORS[run.status] ?? 'zinc'}>
    {run.stage ? (STAGE_LABELS[run.stage] ?? run.stage) : run.status}
  </Badge>
)

// The month picker yields a `YYYY-MM` string; the API expects `MONTH YYYY` (e.g. FEBRUARY 2026).
const formatCycleMonth = (pickerValue: string): string => {
  const [year, m] = pickerValue.split('-')
  const monthName = new Date(Number(year), Number(m) - 1, 1)
    .toLocaleString('en-US', { month: 'long' })
    .toUpperCase()
  return `${monthName} ${year}`
}

const currentMonth = (() => {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
})()

// Worksheet picker shown once a workbook is uploaded — lets the admin override
// the month-matched default sheet (workbooks have look-alike tabs, e.g. "MAY 26"
// vs "MAY 2026"). A native <select> styled to match the zinc design language.
const SheetSelect = ({ sheets, value, loading, onChange }: {
  sheets: string[]; value: string; loading: boolean; onChange: (v: string) => void
}) => {
  if (loading) return <p className="mt-2 text-xs text-zinc-400">Reading worksheets…</p>
  if (sheets.length === 0) return null
  return (
    <div className="mt-3">
      <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
        Worksheet to read
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="block w-full rounded-md py-1.5 px-3 text-sm bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white ring-1 ring-inset ring-zinc-950/10 dark:ring-white/10 focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        {sheets.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
    </div>
  )
}

export const RunPage = () => {
  const navigate = useNavigate()
  const [month, setMonth] = useState('')
  const [postingFile, setPostingFile] = useState<File | null>(null)
  const [lateFile, setLateFile] = useState<File | null>(null)
  const [postingSheets, setPostingSheets] = useState<string[]>([])
  const [lateSheets, setLateSheets] = useState<string[]>([])
  const [postingSheet, setPostingSheet] = useState('')
  const [lateSheet, setLateSheet] = useState('')
  const [loadingSheets, setLoadingSheets] = useState<{ posting: boolean; late: boolean }>({
    posting: false,
    late: false,
  })
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const postingRef = useRef<HTMLInputElement>(null)
  const lateRef = useRef<HTMLInputElement>(null)

  // Fetch a workbook's sheet names and preselect the month-matched default.
  const loadSheets = async (file: File, kind: 'posting' | 'late') => {
    setLoadingSheets((s) => ({ ...s, [kind]: true }))
    try {
      const { data } = await getWorkbookSheets(file, month ? formatCycleMonth(month) : undefined)
      const fallback = data.suggested ?? data.sheets[0] ?? ''
      if (kind === 'posting') {
        setPostingSheets(data.sheets)
        setPostingSheet(fallback)
      } else {
        setLateSheets(data.sheets)
        setLateSheet(fallback)
      }
    } catch {
      setFormError('Could not read worksheets from the uploaded file.')
    } finally {
      setLoadingSheets((s) => ({ ...s, [kind]: false }))
    }
  }

  const onPickFile = (file: File | null, kind: 'posting' | 'late') => {
    if (kind === 'posting') {
      setPostingFile(file)
      setPostingSheets([])
      setPostingSheet('')
    } else {
      setLateFile(file)
      setLateSheets([])
      setLateSheet('')
    }
    if (file) loadSheets(file, kind)
  }

  // When the cycle month changes, refresh the suggested sheet for any loaded file.
  useEffect(() => {
    if (postingFile) loadSheets(postingFile, 'posting')
    if (lateFile) loadSheets(lateFile, 'late')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month])

  const { data: history, refetch: refetchHistory } = useQuery({
    queryKey: ['runs'],
    queryFn: () => listRuns(20).then((r) => r.data),
  })

  const { data: activeRun, refetch: refetchActive } = useQuery({
    queryKey: ['run', activeRunId],
    queryFn: () => getRun(activeRunId!).then((r) => r.data),
    enabled: !!activeRunId,
  })

  const isRunning = activeRun && activeRun.status === 'RUNNING'

  usePolling(
    () => {
      refetchActive()
      if (!isRunning) refetchHistory()
    },
    3000,
    !!isRunning,
  )

  const handleStart = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!month || !postingFile || !lateFile) return
    setFormError(null)
    setSubmitting(true)
    try {
      const res = await createRun(
        formatCycleMonth(month),
        postingFile,
        lateFile,
        postingSheet || undefined,
        lateSheet || undefined,
      )
      setActiveRunId(res.data.run_id)
      refetchHistory()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      const fallback = 'Failed to start run. Check the uploaded files.'
      let msg: string
      if (typeof detail === 'string') {
        msg = detail
      } else if (Array.isArray(detail)) {
        // FastAPI validation errors: [{ loc, msg, ... }]
        msg = detail.map((d) => (d as { msg?: string })?.msg ?? JSON.stringify(d)).join('; ')
      } else {
        msg = fallback
      }
      setFormError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-10">
      <Heading>Start a cycle run</Heading>

      <form onSubmit={handleStart} className="space-y-8">
        <FieldGroup>
          <Field>
            <Label>Cycle month</Label>
            <Description>The work month being reconciled.</Description>
            <Input
              type="month"
              value={month}
              max={currentMonth}
              onChange={(e) => setMonth(e.target.value)}
              required
            />
            {month && (
              <p className="mt-2 text-xs text-zinc-400 font-medium tracking-wide">
                → {formatCycleMonth(month)}
              </p>
            )}
          </Field>

          <Field>
            <Label>Posting Base responses</Label>
            <Description>.xlsx export from the on-time Google Form.</Description>
            <div data-slot="control" className="mt-3">
              <input
                ref={postingRef}
                type="file"
                accept=".xlsx"
                onChange={(e) => onPickFile(e.target.files?.[0] ?? null, 'posting')}
                className="block w-full text-sm text-zinc-500 dark:text-zinc-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-zinc-100 file:text-zinc-700 hover:file:bg-zinc-200 dark:file:bg-white/10 dark:file:text-zinc-200 dark:hover:file:bg-white/20 transition"
              />
            </div>
            <SheetSelect
              sheets={postingSheets}
              value={postingSheet}
              loading={loadingSheets.posting}
              onChange={setPostingSheet}
            />
          </Field>

          <Field>
            <Label>Late Submission responses</Label>
            <Description>.xlsx export from the back-claim Google Form.</Description>
            <div data-slot="control" className="mt-3">
              <input
                ref={lateRef}
                type="file"
                accept=".xlsx"
                onChange={(e) => onPickFile(e.target.files?.[0] ?? null, 'late')}
                className="block w-full text-sm text-zinc-500 dark:text-zinc-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-zinc-100 file:text-zinc-700 hover:file:bg-zinc-200 dark:file:bg-white/10 dark:file:text-zinc-200 dark:hover:file:bg-white/20 transition"
              />
            </div>
            <SheetSelect
              sheets={lateSheets}
              value={lateSheet}
              loading={loadingSheets.late}
              onChange={setLateSheet}
            />
          </Field>
        </FieldGroup>

        {formError && <ErrorMessage>{formError}</ErrorMessage>}

        <Button
          type="submit"
          color="blue"
          disabled={submitting || !month || !postingFile || !lateFile}
          className="w-full"
        >
          {submitting ? 'Starting…' : 'Run pipeline'}
        </Button>
      </form>

      {activeRun && (
        <>
          <Divider />
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <Subheading level={2}>{activeRun.cycle_month}</Subheading>
              <RunStatusBadge run={activeRun} />
            </div>

            <ProgressBar value={activeRun.progress} />

            {Object.keys(activeRun.counts).length > 0 && (
              <div className="grid grid-cols-4 gap-3 text-center text-sm">
                {(['total', 'valid', 'review', 'invalid'] as const).map((k) => (
                  <div key={k} className="bg-zinc-50 dark:bg-white/5 rounded-lg py-3 ring-1 ring-zinc-950/5 dark:ring-white/10">
                    <p className="text-lg font-bold text-zinc-800 dark:text-white">{activeRun.counts[k] ?? 0}</p>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 capitalize mt-0.5">{k}</p>
                  </div>
                ))}
              </div>
            )}

            {activeRun.status === 'DONE' && (
              <Button
                color="green"
                onClick={() => navigate(`/runs/${activeRun.id}/results`)}
                className="w-full"
              >
                View results
              </Button>
            )}
          </div>
        </>
      )}

      {history && history.length > 0 && (
        <>
          <Divider />
          <div className="space-y-3">
            <Subheading level={2}>Recent runs</Subheading>
            <div className="divide-y divide-zinc-950/5 dark:divide-white/10 rounded-xl ring-1 ring-zinc-950/5 dark:ring-white/10 overflow-hidden">
              {history.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center justify-between px-4 py-3 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-white/5 cursor-pointer transition"
                  onClick={() => navigate(`/runs/${run.id}/results`)}
                >
                  <div>
                    <p className="text-sm font-medium text-zinc-800 dark:text-white">{run.cycle_month}</p>
                    <p className="text-xs text-zinc-400 mt-0.5">
                      {run.started_at ? new Date(run.started_at).toLocaleString() : 'Not started'}
                    </p>
                  </div>
                  <RunStatusBadge run={run} />
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
