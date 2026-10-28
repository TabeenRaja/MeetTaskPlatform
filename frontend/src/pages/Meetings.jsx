import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api, errMsg } from '../api'
import { useAuth } from '../auth'
import { Badge, Empty, ErrorBox, Loading } from '../components/ui'
import { CalendarClock, CalendarDays, ChevronLeft, ChevronRight, FolderKanban, LockKeyhole, Plus, Search, Users, XCircle, PlayCircle } from 'lucide-react'

const STATUSES = ['SCHEDULED', 'IN_PROGRESS', 'DRAFT', 'PROCESSING', 'NORMALIZED', 'PENDING_REVIEW', 'APPROVED', 'REJECTED', 'FAILED', 'CANCELLED']

function MeetingStatus({ status }) {
  if (status === 'NORMALIZED') return <span className="rounded-full bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-800">Normalized</span>
  if (status === 'SCHEDULED') return <span className="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-3 py-1.5 text-xs font-semibold text-violet-700 ring-1 ring-inset ring-violet-200"><CalendarClock size={14} /> Scheduled</span>
  if (status === 'IN_PROGRESS') return <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200"><PlayCircle size={14} /> In progress</span>
  if (status === 'CANCELLED') return <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-700 ring-1 ring-inset ring-red-200"><XCircle size={14} /> Cancelled</span>
  return <Badge value={status} />
}

export default function Meetings() {
  const { user } = useAuth()
  const location = useLocation()
  const [data, setData] = useState(null)
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [err, setErr] = useState('')

  useEffect(() => {
    setData(null)
    setErr('')
    const t = setTimeout(() => {
      api.get('/meetings/', { params: { q: q || undefined, status: status || undefined, page } })
        .then((r) => setData(r.data))
        .catch((e) => setErr(errMsg(e)))
    }, 250)
    return () => clearTimeout(t)
  }, [q, status, page])

  return (
    <div className="mx-auto max-w-6xl space-y-6 pb-12">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">Meetings</h1>
          <p className="mt-1 text-sm text-slate-500">Browse upcoming sessions, meeting records and AI processing progress.</p>
        </div>
        {user.role === 'MANAGER' && (
          <Link to="/meetings/new" className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-800">
            <Plus size={17} /> New meeting
          </Link>
        )}
      </div>

      {location.state?.notice && <div role="status" className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">{location.state.notice}</div>}

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <label className="relative block w-full sm:max-w-sm">
            <Search size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input className="w-full rounded-xl border border-slate-200 bg-slate-50 py-3 pl-10 pr-4 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100" placeholder="Search meetings by title..." value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
          </label>
          <select aria-label="Filter by status" className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 sm:w-52" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replaceAll('_', ' ')}</option>)}
          </select>
        </div>
        {data && <p className="mt-3 text-xs text-slate-500">{data.count} {data.count === 1 ? 'meeting' : 'meetings'} found</p>}
      </div>

      <ErrorBox msg={err} />
      {!data && !err && <Loading />}
      {data && data.results.length === 0 && <div className="rounded-2xl border border-slate-200 bg-white p-8"><Empty text="No meetings found." /></div>}
      {data && data.results.length > 0 && (
        <div className="space-y-3">
          {data.results.map((m) => (
            <article key={m.id} className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition duration-150 hover:border-blue-200 hover:shadow-md sm:p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1 space-y-3">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <Link to={`/meetings/${m.id}`} className="break-words text-base font-semibold text-slate-900 transition hover:text-blue-700 hover:underline sm:text-lg">{m.title}</Link>
                    {m.is_confidential && <span className="inline-flex items-center gap-1 rounded-md bg-slate-800 px-2 py-1 text-[11px] font-semibold text-white"><LockKeyhole size={11} /> Confidential</span>}
                  </div>
                  <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-500">
                    <span className="inline-flex items-center gap-2"><CalendarDays size={16} className="shrink-0 text-blue-600" /> {new Date(m.scheduled_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}</span>
                    <span className="inline-flex items-center gap-2"><FolderKanban size={16} className="shrink-0 text-blue-600" /> {m.project_name || 'No project'}</span>
                    <span className="inline-flex items-center gap-2"><Users size={16} className="shrink-0 text-blue-600" /> {m.manager_name}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center justify-between gap-3 sm:flex-col sm:items-end">
                  <MeetingStatus status={m.status} />
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {data && (data.previous || data.next) && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm">
          <button type="button" disabled={!data.previous} onClick={() => setPage((p) => p - 1)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"><ChevronLeft size={16} /> Previous</button>
          <span className="text-center text-xs text-slate-500 sm:text-sm">Page {page}</span>
          <button type="button" disabled={!data.next} onClick={() => setPage((p) => p + 1)} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40">Next <ChevronRight size={16} /></button>
        </div>
      )}
    </div>
  )
}
