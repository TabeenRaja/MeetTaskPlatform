import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { CalendarClock, FolderKanban, LockKeyhole, MapPin, Mic2, Search, ShieldCheck, Users } from 'lucide-react'
import { api, errMsg } from '../api'
import { ErrorBox, Loading, inputCls } from '../components/ui'

const localDateTime = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`

const COLORS = ['#1f5c99', '#0f766e', '#7c3aed', '#b45309', '#be123c']

function Section({ title, subtitle, icon: Icon, children }) {
  return (
    <section className="space-y-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex items-start gap-3 border-b border-slate-100 pb-4">
        <span className="rounded-xl bg-blue-50 p-2.5 text-blue-700"><Icon size={19} /></span>
        <div><h2 className="font-semibold text-slate-900">{title}</h2><p className="mt-0.5 text-xs leading-relaxed text-slate-500">{subtitle}</p></div>
      </div>
      {children}
    </section>
  )
}

export default function MeetingNew() {
  const nav = useNavigate()
  const [employees, setEmployees] = useState(null)
  const [projects, setProjects] = useState([])
  const [f, setF] = useState({ title: '', description: '', is_confidential: false })
  const [scheduledAt, setScheduledAt] = useState(() => localDateTime(new Date()))
  const [dateEdited, setDateEdited] = useState(false)
  const [clockNow, setClockNow] = useState(() => Date.now())
  const [location, setLocation] = useState('')
  const [sel, setSel] = useState([])
  const [participantSearch, setParticipantSearch] = useState('')
  const [projectMode, setProjectMode] = useState('none')
  const [projectId, setProjectId] = useState('')
  const [newProject, setNewProject] = useState({ name: '', color: COLORS[0] })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([api.get('/employees/'), api.get('/projects/', { params: { status: 'ACTIVE' } })])
      .then(([e, p]) => {
        setEmployees(Array.isArray(e.data) ? e.data : (e.data?.results || []))
        setProjects(Array.isArray(p.data) ? p.data : (p.data?.results || []))
      })
      .catch((ex) => setErr(errMsg(ex)))
  }, [])

  useEffect(() => {
    const timer = setInterval(() => setClockNow(Date.now()), 15000)
    return () => clearInterval(timer)
  }, [])

  // Unedited default means 'now', even if the form has been open for a while.
  const selectedMs = new Date(scheduledAt).getTime()
  const mode = !dateEdited ? 'now' : selectedMs > clockNow ? 'later' : selectedMs < clockNow - 60000 ? 'past' : 'now'

  const toggle = (id) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const matches = (employees || []).filter((u) => u.name.toLowerCase().includes(participantSearch.toLowerCase()))

  const submit = async (e) => {
    e.preventDefault()
    setErr('')
    if (!f.title.trim()) return setErr('Meeting title is required.')
    if (sel.length === 0) return setErr('Select at least one participant.')
    if (!scheduledAt || Number.isNaN(new Date(scheduledAt).getTime())) return setErr('Select a valid meeting date and time.')
    const submittedMode = !dateEdited ? 'now' : new Date(scheduledAt).getTime() > Date.now() ? 'later' : new Date(scheduledAt).getTime() < Date.now() - 60000 ? 'past' : 'now'
    if (submittedMode === 'later' && new Date(scheduledAt).getTime() < Date.now() + 60 * 60 * 1000) return setErr('Scheduled meetings must be at least one hour from now.')
    if (submittedMode === 'later' && !location.trim()) return setErr('Enter the meeting location.')
    if (projectMode === 'existing' && !projectId) return setErr('Select a project or choose No Project.')
    if (projectMode === 'create' && !newProject.name.trim()) return setErr('Enter a name for the new project.')

    setBusy(true)
    try {
      let pid = null
      if (projectMode === 'existing') {
        pid = projectId
      } else if (projectMode === 'create') {
        const created = await api.post('/projects/', { name: newProject.name.trim(), color: newProject.color })
        pid = created.data.id
      }

      // The backend must support meeting_mode, location, and scheduled creation (see integration guide).
      // Capture the timestamp when the manager actually submits Start Now, not when the form opens.
      const { data } = await api.post('/meetings/', {
        ...f,
        title: f.title.trim(),
        meeting_mode: submittedMode,
        scheduled_at: submittedMode === 'now' ? new Date().toISOString() : new Date(scheduledAt).toISOString(),
        location: submittedMode === 'later' ? location.trim() : '',
        participant_ids: sel,
        project: pid,
      })
      if (submittedMode === 'later') {
        nav('/meetings', { state: { notice: data.notification_status === 'sent' ? 'Meeting scheduled. Invitation emails were submitted successfully.' : 'Meeting scheduled. Invitations could not be confirmed; please check email settings and participant addresses.' } })
      } else {
        nav(`/meetings/${data.id}`)
      }
    } catch (ex) {
      setErr(errMsg(ex))
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 pb-16">
      <div>
        <Link to="/meetings" className="text-sm font-medium text-blue-700 hover:underline">← Back to meetings</Link>
        <h1 className="mt-3 text-2xl font-bold tracking-tight text-slate-900">Create a meeting</h1>
        <p className="mt-1 text-sm text-slate-500">Create a meeting for now, schedule a future session, or upload audio from a past meeting.</p>
      </div>

      <form onSubmit={submit} className="space-y-5">
        <ErrorBox msg={err} />

        <Section title="Meeting date & time" subtitle="Defaults to now. Choose a future time to schedule or a past time to process an earlier meeting." icon={CalendarClock}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="meeting-date" className="mb-1.5 block text-sm font-medium text-slate-700">Date & time <span className="text-red-500">*</span></label>
              <input id="meeting-date" required type="datetime-local" className={inputCls} value={scheduledAt} onChange={(e) => { setScheduledAt(e.target.value); setDateEdited(true) }} />
              <p className="mt-1 text-xs text-slate-500">Pre-filled with your local date and time.</p>
            </div>
            {mode === 'later' && <div>
              <label htmlFor="meeting-location" className="mb-1.5 block text-sm font-medium text-slate-700">Meeting room / location <span className="text-red-500">*</span></label>
              <div className="relative"><MapPin size={16} className="pointer-events-none absolute left-3 top-3 text-slate-400" />
                <input id="meeting-location" required className={`${inputCls} pl-9`} value={location} maxLength={200} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Conference Room 2" /></div>
            </div>}
          </div>
          {mode === 'later' && <p className="rounded-xl bg-blue-50 p-3 text-sm text-blue-800">Schedule at least one hour ahead. Invitations will be emailed to participants when email delivery is configured.</p>}
          {mode === 'past' && <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Past meeting: after creation you can upload an existing recording to generate minutes. Live recording will be unavailable.</p>}
          {mode === 'now' && <p className="text-xs text-slate-500">Creating this meeting will use the current timestamp and let you record live or upload audio.</p>}
        </Section>

        <Section title="Meeting details" subtitle="Make the purpose of the conversation clear." icon={FolderKanban}>
          <div><label htmlFor="meeting-title" className="mb-1.5 block text-sm font-medium text-slate-700">Meeting title <span className="text-red-500">*</span></label>
            <input id="meeting-title" required className={inputCls} placeholder="e.g. Sprint Architecture & Milestone Review" maxLength={200} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></div>
          <div><label htmlFor="meeting-agenda" className="mb-1.5 block text-sm font-medium text-slate-700">Agenda & objectives</label>
            <textarea id="meeting-agenda" className={`${inputCls} h-28 resize-y py-2.5`} placeholder="Outline key talking points and goals..." value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
        </Section>

        <Section title="Project context" subtitle="Optional: connect this meeting to a project for organized follow-up." icon={FolderKanban}>
          <div className="grid grid-cols-3 gap-2">
            {[['none', 'No project'], ['existing', 'Existing'], ['create', 'Create new']].map(([value, label]) => (
              <button key={value} type="button" onClick={() => setProjectMode(value)} aria-pressed={projectMode === value}
                className={`rounded-xl border px-2 py-2.5 text-xs font-semibold transition sm:text-sm ${projectMode === value ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600 hover:border-blue-200'}`}>{label}</button>
            ))}
          </div>
          {projectMode === 'existing' && <select className={inputCls} value={projectId} onChange={(e) => setProjectId(e.target.value)}><option value="">Select an active project…</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
          {projectMode === 'create' && <div className="space-y-3">
            <input className={inputCls} placeholder="Project name" value={newProject.name} onChange={(e) => setNewProject({ ...newProject, name: e.target.value })} />
            <div className="flex flex-wrap items-center gap-2"><span className="mr-2 text-xs text-slate-500">Project color</span>{COLORS.map((c) => <button key={c} type="button" aria-label={`Choose project color ${c}`} aria-pressed={newProject.color === c} onClick={() => setNewProject({ ...newProject, color: c })} className={`h-7 w-7 rounded-full ${newProject.color === c ? 'ring-2 ring-blue-600 ring-offset-2' : ''}`} style={{ backgroundColor: c }} />)}</div>
          </div>}
        </Section>

        <Section title="Access & participants" subtitle={mode === 'later' ? 'Selected participants are the recipients of meeting invitations.' : 'Choose the registered employees who attended or will attend.'} icon={Users}>
          <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
            <input type="checkbox" checked={f.is_confidential} onChange={(e) => setF({ ...f, is_confidential: e.target.checked })} className="mt-0.5 h-4 w-4 accent-blue-700" />
            <span><span className="flex items-center gap-1.5 text-sm font-semibold text-slate-800"><LockKeyhole size={15} /> Confidential meeting</span><span className="mt-1 block text-xs text-slate-500">Protect the transcript with the platform's existing access controls.</span></span>
          </label>
          <div className="flex items-center justify-between"><label htmlFor="participants-search" className="font-medium text-sm text-slate-700">Participants <span className="text-red-500">*</span></label><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">{sel.length} selected</span></div>
          <div className="relative"><Search size={16} className="pointer-events-none absolute left-3 top-3 text-slate-400" /><input id="participants-search" className={`${inputCls} pl-9`} placeholder="Search employees" value={participantSearch} onChange={(e) => setParticipantSearch(e.target.value)} /></div>
          {!employees && !err && <Loading />}
          {employees?.length === 0 && <p className="text-sm text-slate-500">No active employees available.</p>}
          <div className="grid max-h-60 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {matches.map((u) => <label key={u.id} className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 transition ${sel.includes(u.id) ? 'border-blue-400 bg-blue-50' : 'border-slate-200 hover:border-blue-200'}`}>
              <input type="checkbox" checked={sel.includes(u.id)} onChange={() => toggle(u.id)} className="h-4 w-4 accent-blue-700" /><span className="min-w-0"><span className="block truncate text-sm font-medium text-slate-800">{u.name}</span><span className="text-xs capitalize text-slate-400">{u.role || 'Employee'}</span></span>
            </label>)}
            {employees && matches.length === 0 && <p className="text-sm text-slate-500">No matching employees.</p>}
          </div>
          {mode === 'later' && <div className="flex items-start gap-2 rounded-xl bg-slate-50 p-3 text-xs leading-relaxed text-slate-600"><ShieldCheck size={16} className="shrink-0 text-blue-700" /> Invites are sent by the backend after scheduling; delivery requires notification/email setup.</div>}
        </Section>

        <div className="flex flex-wrap items-center justify-end gap-3 pt-2">
          <Link to="/meetings" className="rounded-xl px-5 py-3 text-sm font-medium text-slate-600 hover:bg-slate-100">Cancel</Link>
          <button type="submit" disabled={busy} className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-6 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-800 disabled:opacity-50">
            {busy ? 'Saving meeting…' : mode === 'later' ? <><CalendarClock size={17} /> Schedule Meeting</> : 'Create Meeting'}
          </button>
        </div>
      </form>
    </div>
  )
}
