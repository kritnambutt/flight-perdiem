import { useState } from 'react'
import { postDecision } from '../lib/apiClient'
import { Button } from './ui/button'

interface DecisionControlsProps {
  claimId: string
  onDone: () => void
}

export const DecisionControls = ({ claimId, onDone }: DecisionControlsProps) => {
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (decision: 'APPROVE' | 'REJECT') => {
    setLoading(true)
    setError(null)
    try {
      await postDecision(claimId, { decision, note: note || undefined })
      onDone()
    } catch {
      setError('Failed to record decision. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <textarea
        className="w-full rounded-lg border border-zinc-950/10 dark:border-white/10 bg-white dark:bg-white/5 text-zinc-950 dark:text-white px-2 py-1.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        rows={2}
        placeholder="Optional note…"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        disabled={loading}
      />
      {error && <p className="text-red-500 text-xs">{error}</p>}
      <div className="flex gap-2">
        <Button color="green" onClick={() => submit('APPROVE')} disabled={loading} className="flex-1">
          Approve
        </Button>
        <Button color="red" onClick={() => submit('REJECT')} disabled={loading} className="flex-1">
          Reject
        </Button>
      </div>
    </div>
  )
}
