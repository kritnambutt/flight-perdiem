import { Badge } from './ui/badge'
import type React from 'react'

const COLORS: Record<string, React.ComponentProps<typeof Badge>['color']> = {
  VALID: 'green',
  VALID_BACKCLAIM: 'teal',
  NEEDS_REVIEW: 'yellow',
  INVALID: 'red',
}

export const VerdictBadge = ({ verdict }: { verdict: string }) => (
  <Badge color={COLORS[verdict] ?? 'zinc'}>
    {verdict.replace(/_/g, ' ')}
  </Badge>
)
