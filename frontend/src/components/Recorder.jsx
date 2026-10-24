import { useCallback, useEffect, useRef, useState } from 'react'
import { Mic2, Pause, Play, RotateCcw, Square, UploadCloud, Volume2 } from 'lucide-react'

const fmt = (seconds) => {
  const whole = Math.max(0, Math.floor(seconds || 0))
  return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
}

const BARS = 54

export default function Recorder({ disabled = false, onRecorded }) {
  const [phase, setPhase] = useState('idle') // idle | recording | paused | ready
  const [seconds, setSeconds] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const audioContextRef = useRef(null)
  const frameRef = useRef(null)
  const analyserRef = useRef(null)
  const samplesRef = useRef(Array(BARS).fill(0.06))
  const chunksRef = useRef([])
  const blobRef = useRef(null)
  const urlRef = useRef(null)
  const playbackRef = useRef(null)
  const durationRef = useRef(0)
  const tickRef = useRef(null)
  const elapsedRef = useRef(0)
  const clockRef = useRef(0)
  const phaseRef = useRef('idle')
  const liveRef = useRef(true)

  useEffect(() => { phaseRef.current = phase }, [phase])

  const releaseMic = useCallback(() => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current)
    frameRef.current = null
    analyserRef.current = null
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (audioContextRef.current) audioContextRef.current.close().catch(() => {})
    audioContextRef.current = null
  }, [])

  const stopClock = () => {
    if (tickRef.current) clearInterval(tickRef.current)
    tickRef.current = null
  }

  const clearPreview = () => {
    playbackRef.current?.pause()
    if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    urlRef.current = null
    blobRef.current = null
    setPlaying(false)
    setPosition(0)
  }

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const ratio = window.devicePixelRatio || 1
    const width = Math.max(200, canvas.clientWidth)
    const height = 96
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio)
      canvas.height = Math.round(height * ratio)
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    ctx.clearRect(0, 0, width, height)
    const analyser = analyserRef.current
    if (analyser && phaseRef.current === 'recording') {
      const values = new Uint8Array(analyser.fftSize)
      analyser.getByteTimeDomainData(values)
      let sum = 0
      for (let i = 0; i < values.length; i++) {
        const value = (values[i] - 128) / 128
        sum += value * value
      }
      const rms = Math.sqrt(sum / values.length)
      samplesRef.current.shift()
      samplesRef.current.push(Math.min(1, Math.max(0.06, rms * 5.5)))
    }
    const gap = 3
    const bar = (width - (BARS - 1) * gap) / BARS
    for (let i = 0; i < BARS; i++) {
      const power = samplesRef.current[i]
      const h = Math.max(5, power * 74)
      const x = i * (bar + gap)
      const y = (height - h) / 2
      ctx.fillStyle = phaseRef.current === 'recording' ? '#2563eb' : '#93b4d9'
      ctx.beginPath()
      ctx.roundRect(x, y, Math.max(2, bar), h, 3)
      ctx.fill()
    }
    if (phaseRef.current === 'recording') frameRef.current = requestAnimationFrame(draw)
  }, [])

  useEffect(() => {
    liveRef.current = true
    return () => {
      liveRef.current = false
      stopClock()
      recorderRef.current?.state !== 'inactive' && recorderRef.current?.stop()
      releaseMic()
      playbackRef.current?.pause()
      if (urlRef.current) URL.revokeObjectURL(urlRef.current)
    }
  }, [releaseMic])

  useEffect(() => { draw() }, [phase, draw])

  const start = async () => {
    if (disabled || busy || phase === 'recording') return
    setError('')
    setBusy(true)
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Your browser does not support microphone recording.')
      clearPreview()
      samplesRef.current = Array(BARS).fill(0.06)
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      streamRef.current = stream
      const AudioContext = window.AudioContext || window.webkitAudioContext
      if (AudioContext) {
        const context = new AudioContext()
        audioContextRef.current = context
        const input = context.createMediaStreamSource(stream)
        const analyser = context.createAnalyser()
        analyser.fftSize = 1024
        input.connect(analyser)
        analyserRef.current = analyser
        if (context.state === 'suspended') await context.resume()
      }
      const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg'].find(t => MediaRecorder.isTypeSupported(t))
      const recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined)
      recorderRef.current = recorder
      chunksRef.current = []
      elapsedRef.current = 0
      clockRef.current = performance.now()
      setSeconds(0)
      durationRef.current = 0
      recorder.ondataavailable = (e) => { if (e.data.size) chunksRef.current.push(e.data) }
      recorder.onstop = () => {
        releaseMic()
        if (!liveRef.current) return
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || type || 'audio/webm' })
        if (!blob.size) { setError('No audio was captured. Please record again.'); setPhase('idle'); return }
        blobRef.current = blob
        const url = URL.createObjectURL(blob)
        urlRef.current = url
        if (playbackRef.current) playbackRef.current.src = url
        setPhase('ready')
      }
      recorder.onerror = () => { setError('Recording failed. Please try again.'); stopClock(); releaseMic(); setPhase('idle') }
      recorder.start(250)
      phaseRef.current = 'recording'
      setPhase('recording')
      frameRef.current = requestAnimationFrame(draw)
      tickRef.current = setInterval(() => setSeconds((elapsedRef.current + performance.now() - clockRef.current) / 1000), 120)
    } catch (e) {
      releaseMic()
      setError(e?.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow microphone access in your browser.' : (e?.message || 'Could not start recording.'))
    } finally { if (liveRef.current) setBusy(false) }
  }

  const pauseOrResume = () => {
    const rec = recorderRef.current
    if (!rec) return
    if (rec.state === 'recording') {
      elapsedRef.current += performance.now() - clockRef.current
      rec.pause()
      stopClock()
      setSeconds(elapsedRef.current / 1000)
      phaseRef.current = 'paused'
      setPhase('paused')
      draw()
    } else if (rec.state === 'paused') {
      rec.resume()
      clockRef.current = performance.now()
      phaseRef.current = 'recording'
      setPhase('recording')
      tickRef.current = setInterval(() => setSeconds((elapsedRef.current + performance.now() - clockRef.current) / 1000), 120)
      frameRef.current = requestAnimationFrame(draw)
    }
  }

  const stop = () => {
    const rec = recorderRef.current
    if (!rec || rec.state === 'inactive') return
    durationRef.current = Math.max(0.1, phase === 'paused' ? elapsedRef.current / 1000 : (elapsedRef.current + performance.now() - clockRef.current) / 1000)
    setSeconds(durationRef.current)
    stopClock()
    phaseRef.current = 'ready'
    rec.stop()
  }

  const discard = () => {
    clearPreview()
    durationRef.current = 0
    setSeconds(0)
    samplesRef.current = Array(BARS).fill(0.06)
    setPhase('idle')
    setError('')
  }

  const useAudio = async () => {
    if (disabled || !blobRef.current || busy) return
    setBusy(true)
    const extension = blobRef.current.type.includes('ogg') ? 'ogg' : 'webm'
    const file = new File([blobRef.current], `meeting-recording-${Date.now()}.${extension}`, { type: blobRef.current.type })
    try { await onRecorded(file) } finally { if (liveRef.current) setBusy(false) }
  }

  const seekTo = (newValue) => {
    const player = playbackRef.current
    const time = Number(newValue)
    setPosition(time)
    if (player && Number.isFinite(player.duration) && player.duration > 0) player.currentTime = time
    else if (player) { try { player.currentTime = time } catch {} }
  }

  return (
    <div className="w-full max-w-2xl space-y-4">
      <div className="relative overflow-hidden rounded-2xl border border-blue-100 bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
            <span className={`h-2.5 w-2.5 rounded-full ${phase === 'recording' ? 'animate-pulse bg-red-500' : phase === 'paused' ? 'bg-amber-400' : 'bg-blue-400'}`} />
            {phase === 'recording' ? 'Recording live' : phase === 'paused' ? 'Recording paused' : phase === 'ready' ? 'Recording ready' : 'Microphone ready'}
          </div>
          <span className="font-mono text-base font-semibold tabular-nums text-slate-800">{fmt(seconds)}</span>
        </div>
        <canvas ref={canvasRef} aria-label="Live voice waveform" role="img" className="block h-24 w-full" />
        <p className="mt-2 text-center text-xs text-slate-400">{phase === 'recording' ? 'Waveform responds to your voice' : phase === 'paused' ? 'Recording paused — resume when ready' : 'Your voice activity appears here during recording'}</p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {phase === 'idle' && <button type="button" disabled={disabled || busy} onClick={start} className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-5 py-3 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50"><Mic2 size={17} /> {busy ? 'Opening microphone…' : 'Start recording'}</button>}
          {(phase === 'recording' || phase === 'paused') && <>
            <button type="button" onClick={pauseOrResume} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50">{phase === 'paused' ? <Play size={16} /> : <Pause size={16} />}{phase === 'paused' ? 'Resume' : 'Pause'}</button>
            <button type="button" onClick={stop} className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-red-700"><Square size={16} /> Stop</button>
          </>}
          {phase === 'ready' && <>
            <button type="button" onClick={discard} disabled={busy || disabled} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"><RotateCcw size={16} /> Discard</button>
            <button type="button" disabled={disabled || busy} onClick={useAudio} className="inline-flex items-center gap-2 rounded-xl bg-blue-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50"><UploadCloud size={16} /> {busy ? 'Submitting…' : 'Use this recording'}</button>
          </>}
        </div>
      </div>
      {phase === 'ready' && <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500"><Volume2 size={15} /> Preview before submitting</div>
        <audio ref={playbackRef} src={urlRef.current || undefined} preload="auto" className="hidden" onTimeUpdate={e => setPosition(e.currentTarget.currentTime || 0)} onEnded={() => { setPlaying(false); setPosition(0) }} onPause={() => setPlaying(false)} onPlay={() => setPlaying(true)} />
        <div className="flex items-center gap-3">
          <button type="button" aria-label={playing ? 'Pause preview' : 'Play preview'} onClick={() => { const p = playbackRef.current; if (!p) return; if (p.paused) p.play().catch(() => setError('Playback unavailable in this browser.')); else p.pause() }} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-700 text-white hover:bg-blue-800">{playing ? <Pause size={18} /> : <Play size={18} />}</button>
          <span className="min-w-10 font-mono text-xs tabular-nums text-slate-600">{fmt(position)}</span>
          <input type="range" min="0" max={Math.max(0.1, durationRef.current)} step="0.1" value={Math.min(position, durationRef.current)} onChange={e => seekTo(e.target.value)} aria-label="Playback position" className="min-w-0 flex-1 accent-blue-700" />
          <span className="min-w-10 font-mono text-xs tabular-nums text-slate-600">{fmt(durationRef.current)}</span>
        </div>
        <p className="mt-2 text-xs text-slate-500">The duration is measured by the recorder; browsers may omit duration metadata from WebM previews.</p>
      </div>}
      {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
    </div>
  )
}
