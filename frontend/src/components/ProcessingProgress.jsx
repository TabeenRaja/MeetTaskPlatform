import { useEffect, useRef, useState } from 'react'
import { Check, Clock3, FileText, ListChecks, Mic } from 'lucide-react'
import './processing.css'

// progress comes from the meeting API while it is PROCESSING:
// { stage, label, percent, next_percent, elapsed, steps: [{key,label}] }  or null when the server is not tracking it.
const SHORT = { queued: 'Start', transcribing: 'Transcribe', normalizing: 'Normalize', extracting: 'Find tasks' }
const ICON = { queued: Clock3, transcribing: Mic, normalizing: FileText, extracting: ListChecks }
const TAU = { queued: 3, transcribing: 45, normalizing: 6, extracting: 8 }
const TIPS = {
  queued: ['Getting things ready'],
  transcribing: ['Processing audio locally with Whisper', 'Turning speech into text'],
  normalizing: ['Cleaning whitespace', 'Identifying sentence boundaries', 'Preserving names, dates and negation'],
  extracting: ['Reading each sentence', 'Finding who must do what', 'Reading deadlines like "by Friday"'],
}

function Visual({ stage }) {
  if (stage === 'transcribing') {
    return (
      <div className="flex items-center gap-5">
        <div className="mtp-bars" aria-hidden="true">
          {Array.from({ length: 9 }, (_, i) => <span key={i} />)}
        </div>
        <span className="text-sky-200">→</span>
        <div className="w-40 space-y-2.5" aria-hidden="true">
          <div className="mtp-line mtp-type" style={{ '--w': '100%' }} />
          <div className="mtp-line mtp-type" style={{ '--w': '78%', animationDelay: '0.3s' }} />
          <div className="mtp-line mtp-type" style={{ '--w': '90%', animationDelay: '0.6s' }} />
        </div>
      </div>
    )
  }
  if (stage === 'normalizing') {
    return (
      <div className="w-56 space-y-3" aria-hidden="true">
        {[100, 80, 92].map((w, i) => (
          <div key={i} className="mtp-row flex items-center gap-3" style={{ '--d': `${i * 0.5}s` }}>
            <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-sky-300 text-navy-900"><Check size={13} strokeWidth={3.5} /></span>
            <div className="mtp-line" style={{ width: `${w}%` }} />
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="flex gap-3" aria-hidden="true">
      {[0, 0.2, 0.4].map((d) => <span key={d} className="mtp-dot" style={{ '--d': `${d}s` }} />)}
    </div>
  )
}

export default function ProcessingProgress({ progress }) {
  const stage = progress?.stage
  const [shown, setShown] = useState(progress?.percent ?? 0)
  const [tip, setTip] = useState(0)
  const track = useRef(null)

  // Remember the latest server numbers; the animation loop below reads them.
  useEffect(() => {
    track.current = progress ? { ...progress, at: performance.now() } : null
  }, [progress])

  // Creep the percent smoothly toward (but never past) the next stage's start; jump forward when a stage completes.
  useEffect(() => {
    let raf
    let last = shown
    const tick = () => {
      const t = track.current
      if (t) {
        const secs = t.elapsed + (performance.now() - t.at) / 1000
        const cap = Math.max(t.percent, t.next_percent - 1.5)
        const target = t.percent + (cap - t.percent) * (1 - Math.exp(-secs / (TAU[t.stage] || 10)))
        last = Math.max(last, last + (Math.max(target, t.percent) - last) * 0.08)
        setShown((prev) => (Math.abs(prev - last) > 0.05 ? last : prev))
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    setTip(0)
    const id = setInterval(() => setTip((n) => n + 1), 2600)
    return () => clearInterval(id)
  }, [stage])

  const steps = progress?.steps || Object.keys(SHORT).map((key) => ({ key }))
  const at = steps.findIndex((s) => s.key === stage)
  const tips = TIPS[stage] || ['Working on your meeting']
  const percent = Math.min(99, Math.round(shown))

  return (
    <section
      className="overflow-hidden rounded-2xl bg-gradient-to-br from-navy-900 via-navy-900 to-brand text-white shadow-lg"
      role="status"
      aria-live="polite"
      aria-label={progress ? `${progress.label}, ${percent} percent` : 'Processing the meeting'}
    >
      <div className="grid gap-6 p-6 sm:p-7 md:grid-cols-[1fr_auto] md:items-center">
        <div className="min-w-0">
          <div className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-sky-300">Processing your transcript locally</div>
          <h2 className="mt-2 text-xl font-semibold tracking-tight sm:text-2xl">{progress ? progress.label : 'Processing the meeting'}</h2>
          <p key={`${stage}-${tip}`} className="mtp-fade mt-1 h-5 text-sm text-sky-100/90">
            {tips[tip % tips.length]}…
          </p>
        </div>
        <div className="flex min-h-24 items-center justify-center rounded-xl bg-white/5 px-6 py-4 ring-1 ring-white/10">
          <Visual stage={stage} />
        </div>
      </div>

      <div className="px-6 pb-2 sm:px-7">
        <div className="mb-2 flex items-end justify-between">
          <span className="text-xs text-sky-100/80">{progress ? 'Progress' : 'Starting up'}</span>
          {progress && <span className="font-mono text-2xl font-semibold tabular-nums">{percent}%</span>}
        </div>
        <div
          className={`h-2.5 overflow-hidden rounded-full bg-white/15 ${progress ? '' : 'mtp-indet'}`}
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress ? percent : undefined}
        >
          {progress && <div className="mtp-fill h-full rounded-full" style={{ width: `${shown}%` }} />}
        </div>
      </div>

      <ol className="grid grid-cols-4 gap-1 px-4 pb-6 pt-5 sm:px-6">
        {steps.map((s, i) => {
          const Icon = ICON[s.key] || Clock3
          const done = at > i
          const now = at === i
          return (
            <li key={s.key} className="flex flex-col items-center gap-1.5 text-center">
              <span
                className={`grid h-9 w-9 place-items-center rounded-full transition ${
                  done ? 'bg-sky-300 text-navy-900' : now ? 'mtp-ring bg-white text-brand' : 'bg-white/10 text-sky-100/50'
                }`}
              >
                {done ? <Check size={17} strokeWidth={3} /> : <Icon size={17} />}
              </span>
              <span className={`text-[11px] font-medium ${now ? 'text-white' : done ? 'text-sky-200' : 'text-sky-100/50'}`}>{SHORT[s.key]}</span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
