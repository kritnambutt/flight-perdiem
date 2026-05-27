import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { exportExceptions, getExceptions } from '../lib/apiClient'
import { DecisionControls } from '../components/DecisionControls'
import { RosterPreview } from '../components/RosterPreview'
import { VerdictBadge } from '../components/VerdictBadge'
import { Button } from '../components/ui/button'
import { Heading } from '../components/ui/heading'
import { Text } from '../components/ui/text'
import type { ExceptionItem } from '../types'

const FieldLabel = ({ children }: { children: React.ReactNode }) => (
  <p className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">{children}</p>
)

export const ExceptionsPage = () => {
  const { runId } = useParams<{ runId: string }>()
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: exceptions, isLoading } = useQuery({
    queryKey: ['exceptions', runId],
    queryFn: () => getExceptions(runId!).then((r) => r.data),
    enabled: !!runId,
  })

  const handleDecisionDone = () => {
    queryClient.invalidateQueries({ queryKey: ['exceptions', runId] })
    queryClient.invalidateQueries({ queryKey: ['results', runId] })
    setExpanded(null)
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <Heading>Exception queue</Heading>
        <Button outline href={exportExceptions(runId!)} download>
          Export xlsx
        </Button>
      </div>

      {isLoading ? (
        <Text>Loading…</Text>
      ) : exceptions?.length === 0 ? (
        <div className="text-center py-16 text-zinc-400">
          <p className="text-lg font-medium text-zinc-600 dark:text-zinc-300">No exceptions</p>
          <p className="text-sm mt-1">All claims passed validation.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {exceptions?.map((item: ExceptionItem) => (
            <div
              key={item.verdict_id}
              className="bg-white dark:bg-zinc-900 rounded-xl ring-1 ring-zinc-950/5 dark:ring-white/10 shadow-sm overflow-hidden"
            >
              <div
                className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-zinc-50 dark:hover:bg-white/5 transition"
                onClick={() => setExpanded(expanded === item.verdict_id ? null : item.verdict_id)}
              >
                <div className="flex items-center gap-3">
                  <VerdictBadge verdict={item.verdict} />
                  <div>
                    <p className="text-sm font-medium text-zinc-900 dark:text-white">{item.name}</p>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400">
                      {item.staff_id} · {item.claimed_date} · Rule {item.rule}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {item.confidence != null && (
                    <span className="text-xs text-zinc-400">OCR {(item.confidence * 100).toFixed(0)}%</span>
                  )}
                  <span className="text-zinc-400 text-sm">{expanded === item.verdict_id ? '▲' : '▼'}</span>
                </div>
              </div>

              {expanded === item.verdict_id && (
                <div className="border-t border-zinc-950/5 dark:border-white/10 px-4 py-4 grid grid-cols-2 gap-6">
                  <div className="space-y-3">
                    <div>
                      <FieldLabel>Reason</FieldLabel>
                      <p className="text-sm text-zinc-800 dark:text-zinc-200 mt-0.5">
                        {item.reason ?? 'No reason provided'}
                      </p>
                    </div>
                    <div>
                      <FieldLabel>Source</FieldLabel>
                      <p className="text-xs text-zinc-600 dark:text-zinc-300 font-mono mt-0.5">{item.source_row_ref}</p>
                    </div>
                    {item.extracted && (
                      <div>
                        <FieldLabel>OCR fields</FieldLabel>
                        <pre className="text-xs text-zinc-600 dark:text-zinc-300 mt-0.5 bg-zinc-50 dark:bg-white/5 rounded p-2 overflow-x-auto">
                          {JSON.stringify(item.extracted, null, 2)}
                        </pre>
                      </div>
                    )}
                    <div>
                      <FieldLabel>Decision</FieldLabel>
                      <div className="mt-1">
                        <DecisionControls claimId={item.claim_id} onDone={handleDecisionDone} />
                      </div>
                    </div>
                  </div>
                  <div>
                    <RosterPreview fileId={item.roster_file_id} />
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
