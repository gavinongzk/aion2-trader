import { ArrowDownRight, ArrowUpRight } from 'lucide-react'

import { pct } from '@/lib/data'
import { cn } from '@/lib/utils'

/** A week's price change per day, with an arrow; "flat" under 1%/day. */
export function Trend({ growth }: { growth: number | null }) {
  if (growth == null) return <span className="text-muted-foreground">?</span>
  if (Math.abs(growth) < 0.01) return <span className="text-muted-foreground">flat</span>
  const Icon = growth > 0 ? ArrowUpRight : ArrowDownRight
  return (
    <span className="tabular inline-flex items-center gap-0.5">
      <Icon className={cn('size-3.5', growth > 0 ? 'text-dear' : 'text-cheap')} aria-hidden />
      {pct(1 + growth)}/day
    </span>
  )
}
