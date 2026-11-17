import { useCallback, useEffect, useRef, useState } from 'react'
import { addChunk, saveMeta, type RecordingMeta } from '../lib/recordingStore'

export type RecorderState = 'idle' | 'requesting' | 'recording' | 'paused' | 'stopped' | 'error'

/** Chọn định dạng trình duyệt hỗ trợ: Chrome/Edge/Firefox → webm/opus, Safari → mp4/aac. */
function pickMimeType(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  return candidates.find((t) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) ?? ''
}

function micErrorMessage(e: unknown): string {
  const name = (e as DOMException)?.name
  if (name === 'NotAllowedError') return 'Bạn đã chặn quyền dùng micro. Bấm biểu tượng 🔒 trên thanh địa chỉ để cho phép rồi thử lại.'
  if (name === 'NotFoundError') return 'Không tìm thấy micro trên máy.'
  if (name === 'NotReadableError') return 'Micro đang bị ứng dụng khác sử dụng (Zoom, Meet…).'
  if (!window.isSecureContext) return 'Trình duyệt chỉ cho ghi âm trên trang https hoặc localhost.'
  return 'Không mở được micro.'
}

/**
 * Ghi âm bằng MediaRecorder API của trình duyệt.
 *
 * - getUserMedia: xin quyền dùng micro (bật khử tiếng vọng, giảm ồn, tự cân bằng âm lượng).
 * - MediaRecorder.start(1000): cứ 1 giây trả về 1 khúc dữ liệu → lưu ngay vào IndexedDB.
 * - AnalyserNode (Web Audio API): đo âm lượng để vẽ thanh "đang nghe thấy tiếng".
 * - Wake Lock: giữ màn hình không tự tắt khi đang ghi (máy tắt màn hình có thể dừng ghi).
 */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>('idle')
  const [elapsed, setElapsed] = useState(0) // giây
  const [level, setLevel] = useState(0) // 0..1
  const [error, setError] = useState('')
  const [recordingId, setRecordingId] = useState<string | null>(null)
  const [saveFailed, setSaveFailed] = useState(false)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const rafRef = useRef<number>(0)
  const timerRef = useRef<number>(0)
  const seqRef = useRef(0)
  const metaRef = useRef<RecordingMeta | null>(null)
  const elapsedRef = useRef(0)
  const wakeLockRef = useRef<{ release: () => Promise<void> } | null>(null)
  const pendingWrites = useRef<Promise<unknown>[]>([])

  const cleanup = useCallback(() => {
    cancelAnimationFrame(rafRef.current)
    clearInterval(timerRef.current)
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    audioCtxRef.current?.close().catch(() => {})
    audioCtxRef.current = null
    wakeLockRef.current?.release().catch(() => {})
    wakeLockRef.current = null
    setLevel(0)
  }, [])

  useEffect(() => cleanup, [cleanup])

  // Cảnh báo khi đóng tab lúc đang ghi
  useEffect(() => {
    if (state !== 'recording' && state !== 'paused') return
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [state])

  const start = useCallback(
    async (info: { workspaceId: number; title: string; meetingDate: string }) => {
      setError('')
      setSaveFailed(false)
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        setState('error')
        setError('Trình duyệt này không hỗ trợ ghi âm. Hãy dùng Chrome, Edge hoặc Firefox bản mới.')
        return
      }
      setState('requesting')
      let stream: MediaStream
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
        })
      } catch (e) {
        setState('error')
        setError(micErrorMessage(e))
        return
      }
      streamRef.current = stream

      const mimeType = pickMimeType()
      const rec = new MediaRecorder(stream, { ...(mimeType ? { mimeType } : {}), audioBitsPerSecond: 64000 })
      const id = `rec-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      const meta: RecordingMeta = {
        id,
        workspaceId: info.workspaceId,
        title: info.title,
        meetingDate: info.meetingDate,
        mimeType: rec.mimeType || mimeType || 'audio/webm',
        startedAt: Date.now(),
        durationSec: 0,
        status: 'recording',
      }
      metaRef.current = meta
      seqRef.current = 0
      elapsedRef.current = 0
      setElapsed(0)
      setRecordingId(id)
      await saveMeta(meta)

      // Mỗi khúc dữ liệu → lưu ngay vào IndexedDB
      rec.ondataavailable = (ev) => {
        if (!ev.data || ev.data.size === 0) return
        const p = addChunk(id, seqRef.current++, ev.data).catch(() => setSaveFailed(true))
        pendingWrites.current.push(p)
      }
      rec.onerror = () => {
        setError('Ghi âm bị lỗi giữa chừng. Phần đã ghi vẫn được giữ lại.')
      }
      // Micro bị rút ra / bị ứng dụng khác chiếm → dừng ghi, giữ phần đã ghi
      stream.getAudioTracks()[0]?.addEventListener('ended', () => {
        if (rec.state !== 'inactive') {
          setError('Micro bị ngắt. Phần đã ghi vẫn được giữ lại.')
          rec.stop()
        }
      })

      // Đo âm lượng để vẽ thanh mức âm
      try {
        const ctx = new AudioContext()
        const analyser = ctx.createAnalyser()
        analyser.fftSize = 512
        ctx.createMediaStreamSource(stream).connect(analyser)
        audioCtxRef.current = ctx
        const buf = new Uint8Array(analyser.fftSize)
        const loop = () => {
          analyser.getByteTimeDomainData(buf)
          let sum = 0
          for (const v of buf) sum += ((v - 128) / 128) ** 2
          setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4))
          rafRef.current = requestAnimationFrame(loop)
        }
        loop()
      } catch {
        /* không đo được âm lượng thì vẫn ghi bình thường */
      }

      try {
        const wl = (navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<{ release: () => Promise<void> }> } }).wakeLock
        wakeLockRef.current = (await wl?.request('screen')) ?? null
      } catch {
        /* không giữ được màn hình sáng cũng không sao */
      }

      timerRef.current = window.setInterval(() => {
        if (recorderRef.current?.state === 'recording') {
          elapsedRef.current += 1
          setElapsed(elapsedRef.current)
          if (metaRef.current && elapsedRef.current % 10 === 0) {
            metaRef.current.durationSec = elapsedRef.current
            void saveMeta(metaRef.current)
          }
        }
      }, 1000)

      recorderRef.current = rec
      rec.start(1000)
      setState('recording')
    },
    [],
  )

  const pause = useCallback(() => {
    if (recorderRef.current?.state === 'recording') {
      recorderRef.current.pause()
      setState('paused')
    }
  }, [])

  const resume = useCallback(() => {
    if (recorderRef.current?.state === 'paused') {
      recorderRef.current.resume()
      setState('recording')
    }
  }, [])

  /** Dừng ghi, đợi lưu hết các khúc vào IndexedDB, trả về thông tin bản ghi. */
  const stop = useCallback(async (): Promise<RecordingMeta | null> => {
    const rec = recorderRef.current
    if (!rec || !metaRef.current) return null
    if (rec.state !== 'inactive') {
      await new Promise<void>((resolve) => {
        rec.addEventListener('stop', () => resolve(), { once: true })
        rec.stop()
      })
    }
    await Promise.allSettled(pendingWrites.current)
    pendingWrites.current = []
    cleanup()
    const meta = { ...metaRef.current, status: 'ready' as const, durationSec: elapsedRef.current }
    metaRef.current = meta
    await saveMeta(meta)
    setState('stopped')
    return meta
  }, [cleanup])

  return { state, elapsed, level, error, recordingId, saveFailed, start, pause, resume, stop }
}
