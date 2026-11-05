import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { pct, ratioColor, ratioInk, sectionLabel, type Server } from '@/lib/data'

/** Servers × item sections, each cell the section's price index on that server (blue cheaper, red dearer). */
export function SectionHeatmap({ servers, homeId }: { servers: Server[]; homeId: number }) {
  const order = ['weapons', 'armor', 'accessories', 'consumables', 'materials', 'skins']
  const present = new Set(servers.flatMap((s) => Object.keys(s.sections)))
  const sections = [...order.filter((s) => present.has(s)), ...[...present].filter((s) => !order.includes(s))]
  const rows = [...servers].sort((a, b) => (a.index ?? 1) - (b.index ?? 1))

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-separate border-spacing-[2px] text-xs">
        <thead>
          <tr>
            <th className="w-28" />
            {sections.map((s) => (
              <th key={s} className="pb-1 text-center font-medium text-muted-foreground">
                {sectionLabel(s)}
              </th>
            ))}
            <th className="pb-1 text-center font-medium text-foreground">All</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.id}>
              <th
                scope="row"
                className={cn(
                  'pr-2 text-right font-normal whitespace-nowrap',
                  s.id === homeId ? 'font-semibold text-foreground' : 'text-muted-foreground',
                )}
              >
                {s.name}
                {s.id === homeId && ' ★'}
              </th>
              {[...sections.map((sec) => [sec, s.sections[sec]] as const), ['all', s.index] as const].map(([sec, v]) => (
                <Tooltip key={sec}>
                  <TooltipTrigger asChild>
                    <td
                      className={cn(
                        'tabular h-7 rounded-[4px] text-center transition-[filter] hover:brightness-110',
                        ratioInk(v),
                        sec === 'all' && 'font-semibold',
                        v == null && 'text-muted-foreground',
                      )}
                      style={{ background: v == null ? undefined : ratioColor(v) }}
                    >
                      {v == null ? '·' : pct(v)}
                    </td>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    {s.name} · {sec === 'all' ? 'all items' : sectionLabel(sec)}:{' '}
                    {v == null ? 'too few items to compare' : `${pct(v, 1)} vs a typical server`}
                  </TooltipContent>
                </Tooltip>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <Legend />
    </div>
  )
}

function Legend() {
  const steps = [0.77, 0.85, 0.93, 1, 1.08, 1.17, 1.3]
  return (
    <div className="mt-3 flex items-center justify-end gap-2 text-xs text-muted-foreground">
      <span>Cheaper</span>
      <div className="flex gap-[2px]">
        {steps.map((r) => (
          <span key={r} className="h-3 w-6 rounded-[3px]" style={{ background: ratioColor(r) }} />
        ))}
      </div>
      <span>Dearer</span>
    </div>
  )
}
