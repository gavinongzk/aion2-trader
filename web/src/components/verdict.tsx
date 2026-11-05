import { CircleCheck, CircleCheckBig, CircleDot, CircleMinus, Clock, HandCoins, TriangleAlert } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { Rating } from '@/lib/data'

const STYLE: Record<Rating, { icon: typeof CircleCheck; color: string }> = {
  'Strong buy': { icon: CircleCheckBig, color: 'text-good' },
  Buy: { icon: CircleCheck, color: 'text-good' },
  Sell: { icon: HandCoins, color: 'text-dear' },
  Fair: { icon: CircleDot, color: 'text-muted-foreground' },
  Wait: { icon: Clock, color: 'text-warning' },
  Overpriced: { icon: TriangleAlert, color: 'text-critical' },
  'Not listed': { icon: CircleMinus, color: 'text-muted-foreground' },
  Unknown: { icon: CircleMinus, color: 'text-muted-foreground' },
}

/** A rating as icon + label: the status color never carries the meaning alone. */
export function Verdict({ label, className, large }: { label: Rating; className?: string; large?: boolean }) {
  const { icon: Icon, color } = STYLE[label]
  return (
    <span className={cn('inline-flex items-center gap-1.5 font-medium whitespace-nowrap', large ? 'text-lg' : 'text-sm', className)}>
      <Icon className={cn(large ? 'size-5' : 'size-4', color)} aria-hidden />
      {label}
    </span>
  )
}
