import { useEffect, useState } from 'react'
import { CheckCircle2, Flame, UserCheck } from 'lucide-react'
import { api } from '../api'

// Loads open / overdue task counts for the given employee ids. Fails quietly: the warning is a help, never a blocker.
export function useWorkload(ids) {
  const key = [...new Set((ids || []).filter(Boolean).map(Number))].sort((a, b) => a - b).join(',')
  const [data, setData] = useState(null)
  useEffect(() => {
    if (!key) return
    let live = true
    api.get('/workload/', { params: { ids: key } })
      .then((r) => { if (live) setData(r.data) })
      .catch(() => { if (live) setData(null) })
    return () => { live = false }
  }, [key])
  return data
}

const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`

// extra: tasks about to be added that the server does not know about yet (for example the rest of an unapproved draft).
export function isBusy(data, userId, extra = 0) {
  const w = data?.people?.[String(userId)]
  if (!w) return false
  return w.open + extra > data.limits.max_open || w.overdue > data.limits.max_overdue
}

// Text for a dropdown option, e.g. "Ali (4 open, 1 overdue)".
export function optionLabel(data, p) {
  const w = data?.people?.[String(p.id)]
  if (!w) return p.name
  return `${p.name} (${w.open} open${w.overdue ? `, ${w.overdue} overdue` : ''})`
}

function Bar({ value, max, tone }) {
  const pct = Math.min(100, Math.round((value / Math.max(max, 1)) * 100))
  const fill = tone === 'bad' ? 'bg-amber-500' : pct >= 80 ? 'bg-amber-400' : 'bg-emerald-500'
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200/80" role="progressbar" aria-valuenow={value} aria-valuemax={max}>
      <div className={`h-full rounded-full transition-all duration-500 ${fill}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function Chip({ tone = 'slate', children }) {
  const c = {
    slate: 'bg-slate-100 text-slate-700 ring-slate-200',
    amber: 'bg-amber-100 text-amber-800 ring-amber-200',
    red: 'bg-red-100 text-red-700 ring-red-200',
    blue: 'bg-sky-100 text-sky-800 ring-sky-200',
  }[tone]
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${c}`}>{children}</span>
}

// extra: tasks about to be added that the server does not know about yet (for example the rest of an unapproved draft).
export default function WorkloadHint({ data, userId, people, extra = 0 }) {
  const w = data?.people?.[String(userId)]
  if (!userId || !w) return null
  const lim = data.limits
  const name = people.find((p) => Number(p.id) === Number(userId))?.name || 'This person'
  const total = w.open + extra
  const busy = isBusy(data, userId, extra)

  if (!busy) {
    return (
      <div className="mt-2 flex items-center gap-2.5 rounded-lg bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
        <CheckCircle2 size={15} className="shrink-0 text-emerald-600" />
        <span className="shrink-0 text-xs text-slate-600">
          <strong className="font-semibold text-slate-800">{total}</strong> open
          {w.overdue ? <> · <strong className="font-semibold text-slate-800">{w.overdue}</strong> overdue</> : null}
        </span>
        <div className="min-w-[48px] flex-1"><Bar value={total} max={lim.max_open} /></div>
        <span className="shrink-0 text-[11px] text-slate-400">limit {lim.max_open}</span>
      </div>
    )
  }

  const best = people
    .filter((p) => Number(p.id) !== Number(userId) && data.people[String(p.id)] && !isBusy(data, p.id))
    .sort((a, b) => {
      const x = data.people[String(a.id)], y = data.people[String(b.id)]
      return x.overdue - y.overdue || x.open - y.open
    })[0]
  const b = best && data.people[String(best.id)]

  return (
    <div role="alert" className="mt-2 overflow-hidden rounded-xl border border-amber-200 bg-amber-50/60 shadow-sm">
      <div className="flex gap-3 p-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-amber-100 text-amber-600 ring-4 ring-amber-50">
          <Flame size={17} />
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <p className="text-sm font-semibold leading-tight text-slate-900">{name} has a heavy workload</p>
            <p className="mt-0.5 text-xs text-slate-500">Think about who else could take this one.</p>
          </div>

          <div className="flex flex-wrap gap-1.5">
            <Chip tone="amber">{w.open} open</Chip>
            {w.overdue > 0 && <Chip tone="red">{w.overdue} overdue</Chip>}
            {w.due_soon > 0 && <Chip tone="blue">{w.due_soon} due soon</Chip>}
            {extra > 0 && <Chip>+{extra} from this draft</Chip>}
          </div>

          <div>
            <div className="mb-1 flex justify-between text-[11px] text-slate-500">
              <span>{total} open · limit {lim.max_open}</span>
              <span>{w.overdue} overdue · limit {lim.max_overdue}</span>
            </div>
            <Bar value={total} max={lim.max_open} tone="bad" />
          </div>

          {best && (
            <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-2.5 py-1.5 text-xs text-emerald-900 ring-1 ring-inset ring-emerald-200">
              <UserCheck size={14} className="shrink-0 text-emerald-600" />
              <span className="min-w-0">
                Lighter option: <strong className="font-semibold">{best.name}</strong>
                <span className="text-emerald-700"> · {b.open} open{b.overdue ? `, ${b.overdue} overdue` : ''}</span>
              </span>
            </div>
          )}
          <p className="text-[11px] text-slate-400">This is only a warning. You can still assign the task.</p>
        </div>
      </div>
    </div>
  )
}
