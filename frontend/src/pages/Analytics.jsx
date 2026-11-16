import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errMsg } from '../api'
import { Card, Empty, ErrorBox, Loading, PageHeader } from '../components/ui'

function weekLabel(start) {
  return new Date(start + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function OnTimeRate({ value }) {
  if (value == null) return <span aria-label="Rate unavailable">—</span>
  const color = value >= 80 ? 'bg-emerald-500' : value >= 50 ? 'bg-brand' : 'bg-red-500'
  return (
    <div className="flex items-center gap-3">
      <div aria-hidden="true" className="h-2 w-20 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="tabular-nums">{value}%</span>
    </div>
  )
}

function WeeklyActivity({ weeks }) {
  const max = Math.max(0, ...weeks.flatMap((week) => [week.total, week.completed_in_week]))
  if (!max) return <Empty text="No tasks were created or completed in this period." />

  const step = Math.ceil(max / 4)
  const scale = step * 4

  return (
    <>
      <ul className="mb-5 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-600">
        <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm bg-brand" /> Created that week</li>
        <li className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm bg-emerald-600" /> Completed that week</li>
      </ul>
      <div className="overflow-x-auto">
        <div className="flex min-w-full gap-3" style={{ minWidth: Math.max(320, weeks.length * 54 + 36) }}>
          <div aria-hidden="true" className="flex h-48 shrink-0 flex-col justify-between text-right text-xs tabular-nums text-slate-500">
            {[4, 3, 2, 1, 0].map((tick) => <span key={tick}>{tick * step}</span>)}
          </div>
          <div className="relative flex flex-1">
            <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 flex h-48 flex-col justify-between">
              {[4, 3, 2, 1, 0].map((tick) => <div key={tick} className="border-t border-slate-200" />)}
            </div>
            {weeks.map((week) => {
              const label = weekLabel(week.week_start)
              const summary = `Week of ${label}: ${week.total} created, ${week.completed_in_week} completed`
              return (
                <div key={week.week_start} className="relative min-w-0 flex-1 text-center" title={summary}>
                  <span className="sr-only">{summary}</span>
                  <div aria-hidden="true" className="flex h-48 items-end justify-center gap-1 px-1">
                    <div className="w-1/3 max-w-8 rounded-t-sm bg-brand" style={{ height: `${(week.total / scale) * 100}%` }} />
                    <div className="w-1/3 max-w-8 rounded-t-sm bg-emerald-600" style={{ height: `${(week.completed_in_week / scale) * 100}%` }} />
                  </div>
                  <div aria-hidden="true" className="mt-2 whitespace-nowrap text-xs text-slate-600">{label}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
      <details className="mt-5 border-t border-slate-100 pt-3">
        <summary className="cursor-pointer text-sm font-medium text-brand">Weekly breakdown</summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full whitespace-nowrap text-left text-sm">
            <thead className="text-xs text-slate-600">
              <tr>
                <th scope="col" className="px-2 py-2">Week of</th>
                <th scope="col" className="px-2 py-2">Created</th>
                <th scope="col" className="px-2 py-2">Completed that week</th>
                <th scope="col" className="px-2 py-2">Of tasks created that week, now complete</th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((week) => (
                <tr key={week.week_start} className="border-t border-slate-100 tabular-nums">
                  <th scope="row" className="px-2 py-2 font-medium">{weekLabel(week.week_start)}</th>
                  <td className="px-2 py-2">{week.total}</td>
                  <td className="px-2 py-2">{week.completed_in_week}</td>
                  <td className="px-2 py-2">{week.total ? `${week.done}/${week.total} (${Math.round((week.done / week.total) * 100)}%)` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  )
}

export default function Analytics() {
  const [d, setD] = useState(null)
  const [weeks, setWeeks] = useState(8)
  const [err, setErr] = useState('')

  useEffect(() => {
    setErr('')
    api.get('/analytics/', { params: { weeks } }).then((r) => setD(r.data)).catch((e) => setErr(errMsg(e)))
  }, [weeks])

  if (err && !d) return <ErrorBox msg={err} />
  if (!d) return <Loading />

  const t = d.totals

  return (
    <div className="space-y-6">
      <PageHeader title="Analytics">
        <select
          aria-label="Analytics date range"
          className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm"
          value={weeks}
          onChange={(e) => setWeeks(Number(e.target.value))}
        >
          {[4, 8, 12, 16].map((n) => <option key={n} value={n}>Last {n} weeks</option>)}
        </select>
      </PageHeader>
      <ErrorBox msg={err} />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          ['All tasks', t.total],
          ['Completed', t.done],
          ['Currently overdue', t.overdue],
          ['On-time rate', t.on_time_rate == null ? '—' : `${t.on_time_rate}%`],
        ].map(([label, v]) => (
          <div key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="text-sm text-slate-500">{label}</div>
            <div className="mt-2 text-3xl font-semibold tabular-nums text-navy-900">{v}</div>
          </div>
        ))}
      </div>

      <Card title="Weekly task activity">
        <WeeklyActivity weeks={d.weeks} />
      </Card>

      <Card title="Employee performance" action={<Link to="/tasks" className="text-xs font-medium text-brand hover:underline">Open tasks →</Link>}>
        {!d.employees.length ? <Empty text="No assigned work to score yet." /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-slate-400">
                  <th className="pb-3">Employee</th>
                  <th className="pb-3">Assigned</th>
                  <th className="pb-3">Done</th>
                  <th className="pb-3">On time</th>
                  <th className="pb-3">Late</th>
                  <th className="pb-3">Overdue now</th>
                  <th className="pb-3">On-time rate</th>
                </tr>
              </thead>
              <tbody>
                {d.employees.map((e) => (
                  <tr key={e.id} className="border-t border-slate-100">
                    <td className="py-3 font-medium text-navy-900">{e.name}</td>
                    <td className="py-3">{e.assigned}</td>
                    <td className="py-3">{e.done}</td>
                    <td className="py-3 text-emerald-700">{e.on_time}</td>
                    <td className="py-3 text-amber-700">{e.late}</td>
                    <td className="py-3 text-red-600">{e.overdue}</td>
                    <td className="py-3">
                      <OnTimeRate value={e.on_time_rate} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
