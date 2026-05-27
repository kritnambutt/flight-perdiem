import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getAudit } from '../lib/apiClient'
import { Badge } from '../components/ui/badge'
import { Heading } from '../components/ui/heading'
import { Text } from '../components/ui/text'

export const AuditPage = () => {
  const [runId, setRunId] = useState('')
  const [action, setAction] = useState('')

  const { data: entries, isLoading } = useQuery({
    queryKey: ['audit', runId, action],
    queryFn: () =>
      getAudit({
        run_id: runId || undefined,
        action: action || undefined,
        limit: 200,
      }).then((r) => r.data),
  })

  const inputClasses =
    'rounded-lg border border-zinc-950/10 dark:border-white/10 bg-white dark:bg-white/5 text-zinc-950 dark:text-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <Heading>Audit trail</Heading>

      <div className="flex gap-3">
        <input
          type="text"
          placeholder="Filter by run ID"
          value={runId}
          onChange={(e) => setRunId(e.target.value)}
          className={`${inputClasses} w-64 font-mono`}
        />
        <select value={action} onChange={(e) => setAction(e.target.value)} className={inputClasses}>
          <option value="">All actions</option>
          <option value="run_started">run_started</option>
          <option value="run_finished">run_finished</option>
          <option value="run_failed">run_failed</option>
          <option value="override_applied">override_applied</option>
          <option value="config_updated">config_updated</option>
          <option value="worker_restarted">worker_restarted</option>
        </select>
      </div>

      {isLoading ? (
        <Text>Loading audit entries…</Text>
      ) : (
        <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-sm ring-1 ring-zinc-950/5 dark:ring-white/10 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-zinc-50 dark:bg-white/5 border-b border-zinc-950/5 dark:border-white/10 text-left text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Run ID</th>
                <th className="px-4 py-3">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-950/5 dark:divide-white/10">
              {entries?.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-400 text-sm">
                    No audit entries found.
                  </td>
                </tr>
              )}
              {entries?.map((e) => (
                <tr key={e.id} className="hover:bg-zinc-50 dark:hover:bg-white/5 transition">
                  <td className="px-4 py-2 text-xs text-zinc-500 dark:text-zinc-400 whitespace-nowrap">
                    {new Date(e.at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2">
                    <Badge color="zinc">
                      <span className="font-mono">{e.action}</span>
                    </Badge>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-zinc-400 truncate max-w-xs">
                    {e.run_id ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-xs text-zinc-600 dark:text-zinc-300 max-w-sm">
                    <pre className="whitespace-pre-wrap break-all">
                      {JSON.stringify(e.detail, null, 1)}
                    </pre>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
