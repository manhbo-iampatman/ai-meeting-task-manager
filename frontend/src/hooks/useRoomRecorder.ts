import axios from 'axios'
import { useEffect, useRef, useState } from 'react'
import { createRoomTrack } from '../api/endpoints'
import type { RecordingState } from '../api/types'
import { TrackUploader } from '../lib/roomTrackUploader'

/** idle: không ghi · recording: đang ghi mic của mình · error: không ghi được (trình duyệt không hỗ trợ hoặc lỗi mạng) */
export type RoomRecorderState = 'idle' | 'recording' | 'error'

const CHUNK_MS = 3000 // cứ 3 giây đóng một khúc và gửi lên máy chủ
const MAX_CREATE_RETRIES = 5 // thử lại tối đa 5 lần (1s, 2s, 4s, 8s, 10s ≈ 25s) khi mạng chập chờn lúc mở track

function pickMimeType(): string {
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  return candidates.find((t) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(t)) ?? ''
}

/**
 * Online Meeting: ghi MIC CỦA CHÍNH MÌNH khi chủ phòng bật ghi âm, gửi dần lên máy chủ.
 *
 * Mỗi người một file riêng → máy chủ biết chắc "ai nói câu nào" mà không cần AI tách người nói.
 *
 * Âm thanh đi qua Web Audio:   mic ──► [nút trộn] ──► MediaRecorder
 *   - Tắt mic: LiveKit chỉ "bịt" đường tiếng (track.enabled = false) → nút trộn vẫn chạy, ghi ra
 *     khoảng lặng. Nhờ vậy file dài đúng bằng thời gian thật, mốc thời gian của mọi người khớp nhau.
 *   - Đổi mic / bật mic lần đầu: LiveKit tạo đường tiếng MỚI → chỉ cần nối nó vào nút trộn,
 *     không phải dừng và mở lại máy ghi.
 *
 * @param code       mã phòng
 * @param recording  trạng thái ghi âm của phòng (do chủ phòng điều khiển)
 * @param micTrack   đường tiếng mic hiện tại của mình trong LiveKit (undefined = chưa bật mic lần nào)
 */
export function useRoomRecorder(code: string, recording: RecordingState, micTrack: MediaStreamTrack | undefined) {
  const [state, setState] = useState<RoomRecorderState>('idle')
  const ctxRef = useRef<AudioContext | null>(null)
  const destRef = useRef<MediaStreamAudioDestinationNode | null>(null)
  const sourceRef = useRef<{ track: MediaStreamTrack; node: MediaStreamAudioSourceNode } | null>(null)

  // Nút trộn tạo MỘT lần khi vào phòng (ngay sau cú bấm "Vào phòng" → trình duyệt cho phép chạy âm thanh)
  useEffect(() => {
    if (typeof AudioContext === 'undefined') return
    const ctx = new AudioContext()
    const dest = ctx.createMediaStreamDestination()
    dest.channelCount = 1
    // Nguồn "im lặng" luôn chạy → khi chưa có mic, máy ghi vẫn nhận được khoảng lặng liên tục
    const silence = ctx.createConstantSource()
    const mute = ctx.createGain()
    mute.gain.value = 0
    silence.connect(mute).connect(dest)
    silence.start()
    void ctx.resume().catch(() => {})
    ctxRef.current = ctx
    destRef.current = dest
    return () => {
      sourceRef.current = null
      ctxRef.current = null
      destRef.current = null
      void ctx.close().catch(() => {})
    }
  }, [])

  // Nối mic hiện tại vào nút trộn; mic đổi thì gỡ cái cũ, nối cái mới
  useEffect(() => {
    const ctx = ctxRef.current
    const dest = destRef.current
    if (!ctx || !dest) return
    if (sourceRef.current?.track === micTrack) return
    sourceRef.current?.node.disconnect()
    sourceRef.current = null
    if (micTrack) {
      const node = ctx.createMediaStreamSource(new MediaStream([micTrack]))
      node.connect(dest)
      sourceRef.current = { track: micTrack, node }
    }
  }, [micTrack])

  // Chủ phòng bật ghi → bắt đầu ghi; dừng ghi / rời phòng → đóng máy ghi, gửi nốt phần còn lại
  useEffect(() => {
    if (recording !== 'on') return
    const dest = destRef.current
    if (!dest || typeof MediaRecorder === 'undefined') {
      setState('error')
      return
    }
    const mimeType = pickMimeType()
    let rec: MediaRecorder
    try {
      rec = new MediaRecorder(dest.stream, { ...(mimeType ? { mimeType } : {}), audioBitsPerSecond: 48000 })
    } catch {
      setState('error')
      return
    }

    let uploader: TrackUploader | null = null
    let cancelled = false // đã dừng trước khi máy chủ kịp mở track
    let recStopped = false // MediaRecorder đã dừng hẳn và phát xong khúc cuối
    let retryTimer: number | null = null
    const early: Blob[] = [] // các khúc ghi được trong lúc chờ máy chủ mở track
    let startedAt = 0

    const stopRecorder = () => {
      if (rec.state !== 'inactive') rec.stop()
      else recStopped = true
    }

    rec.ondataavailable = (ev) => {
      if (!ev.data || ev.data.size === 0) return
      if (uploader) uploader.push(ev.data)
      else early.push(ev.data)
    }
    rec.onstop = () => {
      recStopped = true
      void uploader?.close()
    }
    rec.onstart = () => {
      startedAt = performance.now()
      const openTrack = (attempt: number) => {
        if (cancelled) return
        // Báo máy chủ: "máy ghi của tôi đã chạy được X mili giây" → máy chủ suy ra thời điểm bắt đầu
        // theo đồng hồ CỦA NÓ. Tính lại ngay trước mỗi lần thử (kể cả khi retry) để không lệch giờ.
        const elapsedMs = Math.round(performance.now() - startedAt)
        createRoomTrack(code, { mime: rec.mimeType || mimeType || 'audio/webm', elapsed_ms: elapsedMs })
          .then((res) => {
            uploader = new TrackUploader({ trackId: res.track_id, roomCode: code, acked: 0, closed: false, createdAt: Date.now() })
            early.splice(0).forEach((b) => uploader!.push(b))
            // Chỉ đóng uploader nếu MediaRecorder ĐÃ phát xong khúc cuối; ngược lại `onstop` sẽ đóng
            if (recStopped) void uploader.close()
          })
          .catch((err) => {
            if (cancelled) return
            const status = axios.isAxiosError(err) ? err.response?.status : undefined
            if (status === 409 || status === 410) {
              // Phòng vừa dừng ghi / kết thúc đúng lúc mình bắt đầu → dừng nhẹ nhàng, không báo lỗi
              early.length = 0
              stopRecorder()
              setState('idle')
              return
            }
            if (status === 401 || status === 403 || status === 404 || attempt >= MAX_CREATE_RETRIES) {
              // Lỗi quyền hoặc mạng đứt quá lâu → dừng và hiện cảnh báo để người dùng biết
              early.length = 0
              stopRecorder()
              setState('error')
              return
            }
            const delay = Math.min(1000 * 2 ** attempt, 10000)
            retryTimer = window.setTimeout(() => {
              retryTimer = null
              openTrack(attempt + 1)
            }, delay)
          })
      }
      openTrack(0)
    }
    rec.onerror = () => setState('error')
    void ctxRef.current?.resume().catch(() => {})
    rec.start(CHUNK_MS)
    setState('recording')

    return () => {
      cancelled = true
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer)
        retryTimer = null
      }
      if (rec.state !== 'inactive') {
        rec.stop() // khúc cuối được đẩy ra TRƯỚC sự kiện stop → `onstop` đóng uploader
      } else {
        recStopped = true
        void uploader?.close()
      }
      setState('idle')
    }
  }, [code, recording])

  return state
}
