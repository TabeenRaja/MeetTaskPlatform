import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bell, CheckCheck, CircleCheck, FileCheck2, RotateCcw, Undo2, X } from 'lucide-react'
import { api, errMsg } from '../api'
import { Btn, Empty, ErrorBox, Loading, PageHeader, Pager } from '../components/ui'
import { timeAgo } from '../utils'

const EMAIL = {
  SENT: ['Email sent', 'text-emerald-600'],
  FAILED: ['Email failed', 'text-red-600'],
  NOT_CONFIGURED: ['In-app only (email not configured)', 'text-slate-400'],
}

// Proof notifications get their own icon and colour so a manager can spot submissions at a glance.
const KIND = {
  PROOF_SUBMITTED: { icon: FileCheck2, read: 'bg-amber-100 text-amber-700', unread: 'bg-amber-500 text-white', tag: 'Needs your review' },
  PROOF_WITHDRAWN: { icon: Undo2, read: 'bg-slate-100 text-slate-400', unread: 'bg-slate-500 text-white', tag: 'Withdrawn' },
  PROOF_APPROVED: { icon: CircleCheck, read: 'bg-emerald-100 text-emerald-600', unread: 'bg-emerald-600 text-white', tag: 'Approved' },
  PROOF_CHANGES: { icon: RotateCcw, read: 'bg-red-100 text-red-500', unread: 'bg-red-600 text-white', tag: 'Changes requested' },
}

export function NotificationBell() {
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const wrapper = useRef(null)
  const trigger = useRef(null)

  useEffect(() => {
    let active = true
    const load = () => api.get('/notifications/').then(({ data }) => {
      if (active) setUnread(data.results.filter((n) => !n.is_read).length)
    }).catch(() => {})

    load()
    window.addEventListener('mt:notifications', load)
    return () => {
      active = false
      window.removeEventListener('mt:notifications', load)
    }
  }, [location.key])

  useEffect(() => { setOpen(false) }, [location.key])

  const close = useCallback(() => {
    setOpen(false)
    trigger.current?.focus()
  }, [])

  useEffect(() => {
    if (!open) return
    const onOutside = (e) => {
      if (!wrapper.current?.contains(e.target)) setOpen(false)
    }
    const onKey = (e) => {
      if (e.key === 'Escape' && !e.defaultPrevented) close()
    }
    document.addEventListener('pointerdown', onOutside)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])

  return (
    <div ref={wrapper} className="relative flex">
      <button
        ref={trigger}
        type="button"
        title="Notifications"
        aria-label={unread ? `Notifications (${unread} unread)` : 'Notifications'}
        aria-expanded={open}
        aria-controls={open ? 'header-notifications' : undefined}
        onClick={() => setOpen((value) => !value)}
        className={`relative rounded-xl p-2.5 text-slate-600 transition hover:bg-slate-100 ${open ? 'bg-brand-soft text-brand' : ''}`}
      >
        <Bell size={18} aria-hidden="true" />
        {unread > 0 && (
          <span aria-hidden="true" className="absolute right-1.5 top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>

      {open && (
        <section
          id="header-notifications"
          aria-label="Notifications"
          className="fixed inset-x-3 top-[5.25rem] z-50 flex max-h-[min(66vh,34rem)] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-full sm:mt-3 sm:w-[28rem]"
        >
          <Notifications onClose={close} />
        </section>
      )}
    </div>
  )
}

export default function Notifications({ onClose } = {}) {
  const nav = useNavigate()
  const [data, setData] = useState(null)
  const [page, setPage] = useState(1)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('inbox')

  const load = useCallback(
    () => api.get('/notifications/', { params: { page } }).then((r) => setData(r.data)).catch((e) => setErr(errMsg(e))),
    [page]
  )
  useEffect(() => { load() }, [load])

  const ping = () => window.dispatchEvent(new Event('mt:notifications'))

  const open = async (n) => {
    if (!n.is_read) {
      try { await api.post(`/notifications/${n.id}/read/`); ping() } catch { /* ignore */ }
    }
    if (n.link) {
      onClose?.()
      nav(n.link)
    } else load()
  }

  const markAll = async () => {
    try { await api.post('/notifications/mark_all_read/'); ping(); load() } catch (e) { setErr(errMsg(e)) }
  }

  const unread = data ? data.results.filter((n) => !n.is_read).length : 0

  const rows = data?.results.filter((n) => filter === 'inbox' || !n.is_read)
  const markButton = (
    <Btn variant="secondary" onClick={markAll} disabled={!unread && !(onClose && data?.count > data?.results.length)}>
      <CheckCheck size={16} aria-hidden="true" /> Mark all as read
    </Btn>
  )

  return (
    <>
      {onClose ? (
        <div className="shrink-0 border-b border-slate-200">
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-3 sm:px-4">
            <h2 className="font-semibold text-navy-900">Notifications</h2>
            <div className="flex items-center gap-2">
              {markButton}
              <button type="button" aria-label="Close notifications" onClick={onClose} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100">
                <X size={16} aria-hidden="true" />
              </button>
            </div>
          </div>
          <div className="flex gap-5 px-4">
            {['inbox', 'unread'].map((view) => (
              <button
                key={view}
                type="button"
                aria-pressed={filter === view}
                onClick={() => { setFilter(view); setPage(1) }}
                className={`border-b-2 px-1 pb-2 text-sm font-medium capitalize ${filter === view ? 'border-brand text-brand' : 'border-transparent text-slate-600 hover:text-brand'}`}
              >
                {view}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <PageHeader title="Notifications" subtitle="Review requests, task assignments and reminders.">
          {markButton}
        </PageHeader>
      )}
      <div className={onClose ? 'min-h-0 overflow-y-auto overscroll-contain' : ''}>
        <ErrorBox msg={err} />
        {!data && !err && <Loading />}
        {rows?.length === 0 && (
          onClose ? (
            <div className="grid min-h-52 place-content-center justify-items-center gap-3 px-5 text-center">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-brand-soft text-brand"><Bell size={20} aria-hidden="true" /></span>
              <p className="text-sm font-medium text-navy-900">
                {filter === 'unread' && data.count > data.results.length ? 'No unread notifications on this page.' : filter === 'unread' ? 'No unread notifications.' : 'No notifications yet.'}
              </p>
            </div>
          ) : <Empty text="You're all caught up. No notifications yet." />
        )}
        {rows?.length > 0 && (
          <div className={`divide-y divide-slate-100 bg-white ${onClose ? "" : "overflow-hidden rounded-2xl border border-slate-200 shadow-sm"}`}>
            {rows.map((n) => {
              const k = KIND[n.kind]
              const Icon = k?.icon || Bell
              return (
              <button
                key={n.id}
                onClick={() => open(n)}
                className={`flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-slate-50 ${n.is_read ? '' : 'bg-brand-soft/50'}`}
              >
                <span className={`mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg ${
                  n.is_read ? (k?.read || 'bg-slate-100 text-slate-400') : (k?.unread || 'bg-brand text-white')
                }`}>
                  <Icon size={16} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className={`text-sm ${n.is_read ? 'text-slate-700' : 'font-semibold text-navy-900'}`}>{n.title}</span>
                    {!n.is_read && <span aria-label="Unread" className="h-2 w-2 shrink-0 rounded-full bg-brand" />}
                    {k?.tag && (
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">{k.tag}</span>
                    )}
                  </span>
                  {n.message && <span className="mt-0.5 block text-sm text-slate-500">{n.message}</span>}
                  <span className="mt-1 block text-xs text-slate-400">
                    {timeAgo(n.created_at)} · <span className={EMAIL[n.email_status]?.[1]}>{EMAIL[n.email_status]?.[0]}</span>
                  </span>
                </span>
              </button>
              )
            })}
          </div>
        )}
        <div className={onClose ? 'px-4' : ''}>
          <Pager data={data} page={page} setPage={setPage} noun="notifications" />
        </div>
      </div>
    </>
  )
}
