import { useMemo, useState } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search } from 'lucide-react'

import { Trend } from '@/components/trend'
import { Verdict } from '@/components/verdict'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { kina, pct, RATING_ORDER, sectionLabel, type Valuation } from '@/lib/data'
import { ratingFilters, type RatingFilter } from '@/lib/ratings'
import { cn } from '@/lib/utils'

const rank = (v: Valuation) => RATING_ORDER.indexOf(v.label)

/** Every item on the home server: its fair value, the price to buy below, and the rating now. */
export function ItemsTable({
  items,
  homeName,
  filter,
  onFilter,
  counts,
  onSelect,
}: {
  items: Valuation[]
  homeName: string
  filter: RatingFilter
  onFilter: (f: RatingFilter) => void
  counts: Record<RatingFilter, number>
  onSelect: (item: Valuation) => void
}) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'rating', desc: false }])
  const [query, setQuery] = useState('')
  const [section, setSection] = useState('all')

  const sections = useMemo(() => [...new Set(items.map((i) => i.section ?? 'other'))].sort(), [items])
  const data = useMemo(
    () => items.filter((i) => ratingFilters[filter](i) && (section === 'all' || (i.section ?? 'other') === section)),
    [items, filter, section],
  )

  const columns = useMemo<ColumnDef<Valuation>[]>(
    () => [
      {
        accessorKey: 'name',
        header: 'Item',
        cell: ({ row }) => (
          <div className="min-w-40">
            <div className="font-medium">{row.original.name}</div>
            <div className="text-xs text-muted-foreground">{row.original.category ?? sectionLabel(row.original.section)}</div>
          </div>
        ),
      },
      {
        id: 'rating',
        header: 'Rating',
        accessorFn: (v) => v.label,
        // best rating first; within one, the most upside first
        sortingFn: (a, b) => rank(a.original) - rank(b.original) || (b.original.upside ?? -9) - (a.original.upside ?? -9),
        cell: ({ row }) => <Verdict label={row.original.label} />,
      },
      {
        accessorKey: 'now',
        header: 'Price now',
        sortUndefined: 'last',
        cell: ({ getValue }) => <span className="tabular font-medium">{kina(getValue<number | null>())}</span>,
        meta: { numeric: true },
      },
      {
        accessorKey: 'fair',
        header: 'Fair value',
        sortUndefined: 'last',
        cell: ({ row }) => {
          const v = row.original
          if (v.fair == null) return <span className="text-muted-foreground">–</span>
          return (
            <div className="grid justify-items-end">
              <span className="tabular">{kina(v.fair)}</span>
              <span className="tabular text-[11px] text-muted-foreground">
                {kina(v.low)}–{kina(v.high)}
              </span>
            </div>
          )
        },
        meta: { numeric: true },
      },
      {
        accessorKey: 'upside',
        header: 'Upside',
        sortUndefined: 'last',
        cell: ({ getValue }) => {
          const u = getValue<number | null | undefined>()
          if (u == null) return <span className="text-muted-foreground">–</span>
          return <span className={cn('tabular font-medium', u > 0.1 ? 'text-good' : u < -0.1 && 'text-critical')}>{pct(1 + u)}</span>
        },
        meta: { numeric: true },
      },
      {
        accessorKey: 'buy_below',
        header: 'Buy below',
        sortUndefined: 'last',
        cell: ({ getValue }) => <span className="tabular">{kina(getValue<number | undefined>())}</span>,
        meta: { numeric: true },
      },
      {
        accessorKey: 'growth',
        header: 'Trend',
        sortUndefined: 'last',
        cell: ({ getValue }) => <Trend growth={getValue<number | null>()} />,
        meta: { numeric: true },
      },
      {
        accessorKey: 'per_day',
        header: 'Sells/day',
        sortUndefined: 'last',
        cell: ({ getValue }) => {
          const v = getValue<number | null>()
          return <span className="tabular text-muted-foreground">{v == null ? '?' : v < 10 ? v.toFixed(1) : Math.round(v)}</span>
        },
        meta: { numeric: true },
      },
    ],
    [],
  )

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: query },
    onSortingChange: setSorting,
    onGlobalFilterChange: setQuery,
    globalFilterFn: (row, _id, value: string) => row.original.name.toLowerCase().includes(value.toLowerCase()),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    autoResetPageIndex: true,
    initialState: { pagination: { pageSize: 15 } },
  })

  const { pageIndex } = table.getState().pagination
  const shown = table.getFilteredRowModel().rows.length

  return (
    <div className="grid gap-3">
      <ToggleGroup
        type="single"
        variant="outline"
        value={filter}
        onValueChange={(v) => v && onFilter(v as RatingFilter)}
        className="flex-wrap justify-start"
      >
        <ToggleGroupItem value="buy">
          <Verdict label="Buy" /> <Count n={counts.buy} />
        </ToggleGroupItem>
        <ToggleGroupItem value="sell">
          <Verdict label="Sell" /> <Count n={counts.sell} />
        </ToggleGroupItem>
        <ToggleGroupItem value="fair">
          <Verdict label="Fair" /> <Count n={counts.fair} />
        </ToggleGroupItem>
        <ToggleGroupItem value="wait">
          <Verdict label="Wait" /> <Count n={counts.wait} />
        </ToggleGroupItem>
        <ToggleGroupItem value="overpriced">
          <Verdict label="Overpriced" /> <Count n={counts.overpriced} />
        </ToggleGroupItem>
        <ToggleGroupItem value="unlisted">
          <Verdict label="Not listed" /> <Count n={counts.unlisted} />
        </ToggleGroupItem>
        <ToggleGroupItem value="all">
          All on {homeName} <Count n={counts.all} />
        </ToggleGroupItem>
      </ToggleGroup>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search items…" className="pl-8" />
        </div>
        <Select value={section} onValueChange={setSection}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All sections</SelectItem>
            {sections.map((s) => (
              <SelectItem key={s} value={s}>
                {sectionLabel(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader className="bg-muted/50">
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id}>
                {group.headers.map((h) => {
                  const numeric = (h.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric
                  const sorted = h.column.getIsSorted()
                  return (
                    <TableHead key={h.id} className={cn(numeric && 'text-right')}>
                      <button
                        className={cn('inline-flex items-center gap-1 hover:text-foreground', numeric && 'flex-row-reverse')}
                        onClick={h.column.getToggleSortingHandler()}
                      >
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {sorted === 'asc' ? <ArrowUp className="size-3" /> : sorted === 'desc' ? <ArrowDown className="size-3" /> : null}
                      </button>
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow key={row.id} className="cursor-pointer" onClick={() => onSelect(row.original)}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cn((cell.column.columnDef.meta as { numeric?: boolean } | undefined)?.numeric && 'text-right')}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {shown === 0 && (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                  No items match.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span className="tabular">
          {shown} items · page {pageIndex + 1} of {Math.max(1, table.getPageCount())}
        </span>
        <div className="flex gap-1">
          <Button variant="outline" size="icon" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()} aria-label="Previous page">
            <ChevronLeft />
          </Button>
          <Button variant="outline" size="icon" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()} aria-label="Next page">
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  )
}

function Count({ n }: { n: number }) {
  return <span className="tabular text-xs text-muted-foreground">{n}</span>
}
