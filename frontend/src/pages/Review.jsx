import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Check, X, ClipboardList, UserRound,
  CalendarDays, AlertTriangle, FileText, ShieldCheck,
  Sparkles, MessageSquareText, ListChecks, LockKeyhole
} from 'lucide-react'
import { api, errMsg } from '../api'
import WorkloadHint, { optionLabel, useWorkload } from '../components/Workload'
import { Badge, Btn, Card, Confirm, Empty, ErrorBox, Loading, Modal, Notice, PageHeader, areaCls, inputCls } from '../components/ui'

const lines = (t) => t.split('\n').map((s) => s.trim()).filter(Boolean)
const toDraft = (o) => ({
  summary: o.summary,
  mom: o.mom,
  points: o.discussion_points.join('\n'),
  decisions: o.decisions.join('\n'),
  items: o.action_items.map((a) => ({ ...a })),
})

const L = ({ children }) => <label className="mb-1 block text-sm font-medium text-slate-700">{children}</label>

export default function Review() {
  const { id } = useParams()
  const nav = useNavigate()
  const [m, setM] = useState(null)
  const [out, setOut] = useState(null)
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [dlg, setDlg] = useState(null)
  const [reason, setReason] = useState('')
  const [originalTranscript, setOriginalTranscript] = useState('')

  const load = useCallback(async () => {
    try {
      const [mm, oo, tt] = await Promise.all([
  api.get(`/meetings/${id}/`),
  api.get(`/meetings/${id}/output/`),
  api.get(`/meetings/${id}/transcript/`)
])

setOriginalTranscript(tt.data.original || '')
      setM(mm.data)
      setOut(oo.data || null)
      setD(oo.data ? toDraft(oo.data) : null)
    } catch (e) {
      setErr(errMsg(e))
    }
  }, [id])

  useEffect(() => { load() }, [load])
  const wl = useWorkload((m?.participants || []).map((p) => p.id))

  if (!m) return err ? <ErrorBox msg={err} /> : <Loading />
  if (!out || !d) {
    return (
      <>
        <Link to={`/meetings/${id}`} className="text-sm text-brand hover:underline">← Back to meeting</Link>
        <Empty text="There is no AI output to review yet. Upload a recording first." />
      </>
    )
  }

  const editable = out.status === 'PENDING_REVIEW'
  const setItem = (i, patch) => setD((x) => ({ ...x, items: x.items.map((a, k) => (k === i ? { ...a, ...patch } : a)) }))
  const active = d.items.filter((a) => !a.discard)

  const payload = () => ({
    summary: d.summary,
    mom: d.mom,
    discussion_points: lines(d.points),
    decisions: lines(d.decisions),
    action_items: d.items,
  })

  const run = async (fn) => {
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      await fn()
    } catch (e) {
      setErr(errMsg(e))
      setDlg(null)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    run(async () => {
      const { data } = await api.patch(`/outputs/${out.id}/`, payload())
      setOut(data)
      setD(toDraft(data))
      setMsg('Draft saved.')
    })

  const approve = () =>
    run(async () => {
      await api.patch(`/outputs/${out.id}/`, payload())
      await api.post(`/outputs/${out.id}/approve/`)
      nav('/tasks')
    })

  const reject = () =>
    run(async () => {
      if (!reason.trim()) throw { message: 'Please enter a reason.' }
      await api.post(`/outputs/${out.id}/reject/`, { reason })
      setDlg(null)
      setReason('')
      await load()
      setMsg('Output rejected.')
    })

  const resubmit = () =>
    run(async () => {
      await api.post(`/outputs/${out.id}/resubmit/`)
      await load()
      setMsg('Output is back in review. You can edit it now.')
    })

  const askApprove = () => {
    const i = d.items.findIndex((a) => !a.discard && !a.assignee_id)
    if (i >= 0) return setErr(`Action item ${i + 1} needs an assignee (or discard it).`)
    setErr('')
    setDlg('approve')
  }

  return (
    <>
      <Link to={`/meetings/${id}`} className="text-sm text-brand hover:underline">← Back to meeting</Link>
      <PageHeader title={`Review: ${m.title}`} subtitle="Edit the AI draft, then approve or reject it.">
        <Badge value={out.status} />
      </PageHeader>

      {out.generated_by === 'mock' && (
        <Notice tone="amber" msg="MOCK output from the development adapter. This was NOT produced by Gemini." />
      )}
      <Notice tone="amber" msg="AI output stays a draft. No task becomes active until you approve." />
      {out.status === 'APPROVED' && (
        <Notice msg={<>Approved. Tasks were created. <Link to="/tasks" className="font-medium underline">View tasks</Link></>} />
      )}
      {out.status === 'REJECTED' && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          This output was rejected. Revise and resubmit it to edit again.
          <Btn onClick={resubmit} disabled={busy}>Revise and resubmit</Btn>
        </div>
      )}
      <ErrorBox msg={err} />
      <Notice msg={msg} />
   {/* ORIGINAL TRANSCRIPT */}
<section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm">
  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-6">
    <div className="flex items-center gap-3">
      <span className="rounded-xl bg-blue-100 p-2.5 text-blue-700">
        <MessageSquareText size={19} />
      </span>

      <div>
        <h2 className="text-sm font-semibold text-slate-900">
          Original Meeting Transcript
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Reference the conversation when verifying AI-generated information.
        </p>
      </div>
    </div>

    <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700">
      <LockKeyhole size={13} />
      Manager reference
    </span>
  </div>

  <div className="p-5 sm:p-6">
    <div className="max-h-72 overflow-y-auto rounded-xl border border-slate-200 bg-slate-50 p-5">
      <p className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">
        {originalTranscript || 'No original transcript available.'}
      </p>
    </div>

    <p className="mt-3 flex items-start gap-2 text-xs text-slate-500">
      <ShieldCheck
        size={15}
        className="mt-0.5 shrink-0 text-blue-600"
      />
      Original transcript contains unmasked information.
      Use it only for authorized verification.
    </p>
  </div>
</section>


{/* SUMMARY */}
<section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm">
  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-6">
    <div className="flex items-center gap-3">
      <span className="rounded-xl bg-blue-100 p-2.5 text-blue-700">
        <Sparkles size={19} />
      </span>

      <div>
        <h2 className="text-sm font-semibold text-slate-900">
          Meeting Summary
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          A concise overview of the meeting's key outcomes.
        </p>
      </div>
    </div>

    <span className="rounded-full border border-blue-100 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700">
      AI Generated
    </span>
  </div>

  <div className="p-5 sm:p-6">
    <label
      htmlFor="review-summary"
      className="mb-2 block text-xs font-semibold text-slate-600"
    >
      Executive Summary
    </label>

    <textarea
      id="review-summary"
      className={`${areaCls} !min-h-[110px] !rounded-xl !border-slate-200 !bg-white !p-4 !leading-7 focus:!border-blue-400 focus:!ring-blue-100`}
      rows={3}
      disabled={!editable}
      value={d.summary}
      onChange={(e) =>
        setD({ ...d, summary: e.target.value })
      }
    />

    <p className="mt-2 text-xs text-slate-400">
      Review the summary for accuracy before approving.
    </p>
  </div>
</section>


{/* MINUTES OF MEETING */}
<section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm">
  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-6">
    <div className="flex items-center gap-3">
      <span className="rounded-xl bg-blue-100 p-2.5 text-blue-700">
        <FileText size={19} />
      </span>

      <div>
        <h2 className="text-sm font-semibold text-slate-900">
          Minutes of Meeting
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Detailed meeting documentation for review and approval.
        </p>
      </div>
    </div>

    <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-semibold text-blue-700">
      Draft
    </span>
  </div>

  <div className="p-5 sm:p-6">
    <label
      htmlFor="review-mom"
      className="mb-2 block text-xs font-semibold text-slate-600"
    >
      Meeting Record
    </label>

    <textarea
      id="review-mom"
      className={`${areaCls} !min-h-[180px] !rounded-xl !border-slate-200 !bg-white !p-4 !leading-7 focus:!border-blue-400 focus:!ring-blue-100`}
      rows={7}
      disabled={!editable}
      value={d.mom}
      onChange={(e) =>
        setD({ ...d, mom: e.target.value })
      }
    />

    <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
      <ShieldCheck size={15} className="text-blue-600" />
      Manager verification required before publication.
    </div>
  </div>
</section>


{/* KEY DISCUSSIONS AND DECISIONS */}
<div className="grid gap-5 lg:grid-cols-2">

  {/* KEY DISCUSSION POINTS */}
  <section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm">
    <div className="flex items-center gap-3 border-b border-slate-100 bg-slate-50/70 px-5 py-4">
      <span className="rounded-xl bg-blue-100 p-2.5 text-blue-700">
        <MessageSquareText size={19} />
      </span>

      <div>
        <h2 className="text-sm font-semibold text-slate-900">
          Key Discussion Points
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Important topics discussed during the meeting.
        </p>
      </div>
    </div>

    <div className="p-5">
      <label
        htmlFor="review-points"
        className="mb-2 block text-xs font-semibold text-slate-600"
      >
        Discussion Points
      </label>

      <textarea
        id="review-points"
        className={`${areaCls} !min-h-[180px] !rounded-xl !border-slate-200 !bg-white !p-4 !leading-7 focus:!border-blue-400 focus:!ring-blue-100`}
        rows={5}
        disabled={!editable}
        value={d.points}
        onChange={(e) =>
          setD({ ...d, points: e.target.value })
        }
      />

      <p className="mt-2 text-xs text-slate-400">
        Enter one discussion point per line.
      </p>
    </div>
  </section>


  {/* KEY DECISIONS */}
  <section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-sm">
    <div className="flex items-center gap-3 border-b border-slate-100 bg-slate-50/70 px-5 py-4">
      <span className="rounded-xl bg-blue-100 p-2.5 text-blue-700">
        <ListChecks size={19} />
      </span>

      <div>
        <h2 className="text-sm font-semibold text-slate-900">
          Key Decisions
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Important agreements and decisions reached.
        </p>
      </div>
    </div>

    <div className="p-5">
      <label
        htmlFor="review-decisions"
        className="mb-2 block text-xs font-semibold text-slate-600"
      >
        Decisions Made
      </label>

      <textarea
        id="review-decisions"
        className={`${areaCls} !min-h-[180px] !rounded-xl !border-slate-200 !bg-white !p-4 !leading-7 focus:!border-blue-400 focus:!ring-blue-100`}
        rows={5}
        disabled={!editable}
        value={d.decisions}
        onChange={(e) =>
          setD({ ...d, decisions: e.target.value })
        }
      />

      <p className="mt-2 text-xs text-slate-400">
        Enter one decision per line.
      </p>
    </div>
  </section>
</div>
     <Card title={`Action items (${active.length} active)`}>
  {d.items.length === 0 && (
    <Empty text="No action items were extracted." />
  )}

  <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <ClipboardList size={17} className="text-blue-600" />
      Review and verify the AI-extracted tasks before approval.
    </div>

    <span className="rounded-full bg-blue-100 px-3 py-1.5 text-xs font-semibold text-blue-700">
      {active.length} active tasks
    </span>
  </div>

  <div className="space-y-5">
    {d.items.map((a, i) => {
      const flag =
        !a.discard &&
        (!a.assignee_id || !a.deadline || a.confidence === 'LOW')

      const confidence = String(a.confidence || 'LOW').toUpperCase()

      const confidenceColors = {
        HIGH: 'bg-emerald-50 text-emerald-700 border-emerald-200',
        MEDIUM: 'bg-amber-50 text-amber-700 border-amber-200',
        LOW: 'bg-red-50 text-red-700 border-red-200',
      }

      const priorityColors = {
        HIGH: 'bg-red-100 text-red-700',
        MEDIUM: 'bg-blue-100 text-blue-700',
        LOW: 'bg-emerald-100 text-emerald-700',
      }

      return (
        <div
          key={i}
          className={`overflow-hidden rounded-2xl border bg-white shadow-sm transition-shadow hover:shadow-md ${
            a.discard
              ? 'border-slate-200 opacity-60'
              : flag
                ? 'border-amber-300'
                : 'border-blue-200'
          }`}
        >
          <div className="flex">
            {/* Accent strip */}
            <div
              className={`w-1.5 shrink-0 ${
                a.discard
                  ? 'bg-slate-300'
                  : flag
                    ? 'bg-amber-400'
                    : 'bg-blue-500'
              }`}
            />

            <div className="min-w-0 flex-1">
              {/* HEADER */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/70 px-5 py-4">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-100 text-sm font-bold text-blue-700">
                    {String(i + 1).padStart(2, '0')}
                  </span>

                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      Action Item {i + 1}
                    </p>

                    <p className="text-xs text-slate-500">
                      AI-extracted task
                    </p>
                  </div>

                  <span
                    className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
                      confidenceColors[confidence] ||
                      confidenceColors.LOW
                    }`}
                  >
                    {confidence.toLowerCase()} confidence
                  </span>

                  {flag && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-800">
                      <AlertTriangle size={12} />
                      Needs review
                    </span>
                  )}
                </div>

                <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600">
                  <input
                    type="checkbox"
                    className="accent-blue-600"
                    disabled={!editable}
                    checked={!!a.discard}
                    onChange={(e) =>
                      setItem(i, { discard: e.target.checked })
                    }
                  />
                  Discard item
                </label>
              </div>

              {/* EDITABLE FORM */}
              <div className="space-y-5 p-5">
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <L>Task title</L>

                    <span
                      className={`rounded-md px-2.5 py-1 text-[11px] font-semibold ${
                        priorityColors[a.priority] ||
                        priorityColors.MEDIUM
                      }`}
                    >
                      {String(a.priority || 'MEDIUM').toUpperCase()} PRIORITY
                    </span>
                  </div>

                  <input
                    className={`${inputCls} !rounded-xl !border-slate-200 !bg-white focus:!border-blue-400 focus:!ring-blue-100`}
                    disabled={!editable}
                    value={a.title}
                    onChange={(e) =>
                      setItem(i, { title: e.target.value })
                    }
                  />
                </div>

                <div className="grid gap-4 md:grid-cols-3">
                  {/* ASSIGNEE */}
                  <div>
                    <label className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700">
                      <UserRound size={15} className="text-blue-600" />
                      Assignee
                    </label>

                    <select
                      className={`${inputCls} !rounded-xl`}
                      disabled={!editable}
                      value={a.assignee_id ?? ''}
                      onChange={(e) =>
                        setItem(i, {
                          assignee_id: e.target.value
                            ? Number(e.target.value)
                            : null,
                        })
                      }
                    >
                      <option value="">Unresolved</option>

                      {m.participants.map((p) => (
                        <option key={p.id} value={p.id}>
                          {optionLabel(wl, p)}
                        </option>
                      ))}
                    </select>
                    {editable && !a.discard && (
                      <WorkloadHint
                        data={wl}
                        userId={a.assignee_id}
                        people={m.participants}
                        extra={d.items.filter((x) => !x.discard && x.assignee_id === a.assignee_id).length}
                      />
                    )}
                  </div>

                  {/* DEADLINE */}
                  <div>
                    <label className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700">
                      <CalendarDays size={15} className="text-blue-600" />
                      Deadline
                    </label>

                    <input
                      type="date"
                      className={`${inputCls} !rounded-xl`}
                      disabled={!editable}
                      value={a.deadline || ''}
                      onChange={(e) =>
                        setItem(i, {
                          deadline: e.target.value || null,
                        })
                      }
                    />
                  </div>

                  {/* PRIORITY */}
                  <div>
                    <label className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700">
                      <ShieldCheck size={15} className="text-blue-600" />
                      Priority
                    </label>

                    <select
                      className={`${inputCls} !rounded-xl`}
                      disabled={!editable}
                      value={a.priority}
                      onChange={(e) =>
                        setItem(i, { priority: e.target.value })
                      }
                    >
                      {['HIGH', 'MEDIUM', 'LOW'].map((p) => (
                        <option key={p} value={p}>
                          {p[0] + p.slice(1).toLowerCase()}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* DESCRIPTION */}
                <div>
                  <label className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700">
                    <FileText size={15} className="text-blue-600" />
                    Task description
                  </label>

                  <textarea
                    className={`${areaCls} !rounded-xl`}
                    rows={3}
                    disabled={!editable}
                    value={a.description || ''}
                    onChange={(e) =>
                      setItem(i, {
                        description: e.target.value,
                      })
                    }
                  />
                </div>

                {/* UNCERTAINTY NOTE */}
                {a.uncertainty_note && (
                  <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                    <AlertTriangle
                      size={18}
                      className="mt-0.5 shrink-0 text-amber-600"
                    />

                    <div>
                      <p className="text-xs font-semibold text-amber-900">
                        AI Review Note
                      </p>

                      <p className="mt-1 text-xs leading-5 text-amber-800">
                        {a.uncertainty_note}
                      </p>
                    </div>
                  </div>
                )}

                {/* SOURCE */}
                {a.source_context && (
                  <div className="rounded-xl border border-slate-100 bg-slate-50 px-4 py-3">
                    <div className="mb-2 flex items-center gap-2">
                      <FileText
                        size={14}
                        className="text-slate-500"
                      />

                      <p className="text-xs font-semibold text-slate-600">
                        Transcript Reference
                      </p>
                    </div>

                    <p className="text-xs italic leading-5 text-slate-500">
                      {a.source_context}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )
    })}
  </div>
</Card>

      {editable && (
        <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-end gap-2 rounded-2xl border border-slate-200 bg-white/90 p-3 shadow-lg backdrop-blur">
          <Btn variant="secondary" onClick={save} disabled={busy}>Save draft</Btn>
          <Btn variant="danger" onClick={() => setDlg('reject')} disabled={busy}><X size={16} /> Reject</Btn>
          <Btn onClick={askApprove} disabled={busy}><Check size={16} /> Approve and create tasks</Btn>
        </div>
      )}

      {dlg === 'approve' && (
        <Confirm
          title="Approve and create tasks?"
          text={`This creates ${active.length} active ${active.length === 1 ? 'task' : 'tasks'} and notifies the assignees. Discarded items are skipped. Clicking twice will not create duplicates.`}
          confirmLabel="Approve"
          busy={busy}
          onConfirm={approve}
          onClose={() => setDlg(null)}
        />
      )}
      {dlg === 'reject' && (
        <Modal title="Reject this output" onClose={() => setDlg(null)}>
          <label className="mb-1 block text-sm text-slate-700">Reason (required)</label>
          <textarea className={areaCls} rows={4} value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="mt-4 flex justify-end gap-2">
            <Btn variant="secondary" onClick={() => setDlg(null)} disabled={busy}>Cancel</Btn>
            <Btn variant="danger" onClick={reject} disabled={busy}>{busy ? 'Working...' : 'Reject'}</Btn>
          </div>
        </Modal>
      )}
    </>
  )
}
