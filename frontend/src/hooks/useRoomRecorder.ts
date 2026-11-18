import { useEffect, useRef, useState } from 'react'
import { createRoomTrack } from '../api/endpoints'
import type { RecordingState } from '../api/types'
import { TrackUploader } from '../lib/roomTrackUploader'

/** idle: không ghi · recording: đang ghi mic của mình · error: không ghi được (trình duyệt không hỗ trợ…) */
export type RoomRecorderState = 'idle' | 'recording' | 'error'

const CHUNK_MS = 3000 // cứ 3 giây đóng một khúc và gửi lên máy chủ

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
    const early: Blob[] = [] // các khúc ghi được trong lúc chờ máy chủ mở track
    let startedAt = 0

    rec.ondataavailable = (ev) => {
      if (!ev.data || ev.data.size === 0) return
      if (uploader) uploader.push(ev.data)
      else early.push(ev.data)
    }
    rec.onstart = () => {
      startedAt = performance.now()
      // Báo máy chủ: "máy ghi của tôi đã chạy được X mili giây" → máy chủ suy ra thời điểm bắt đầu
      // theo đồng hồ CỦA NÓ. Mọi người đều quy về một đồng hồ nên lời nói xếp đúng thứ tự.
      createRoomTrack(code, { mime: rec.mimeType || mimeType || 'audio/webm', elapsed_ms: Math.round(performance.now() - startedAt) })
        .then((res) => {
          uploader = new TrackUploader({ trackId: res.track_id, roomCode: code, acked: 0, closed: false, createdAt: Date.now() })
          early.splice(0).forEach((b) => uploader!.push(b))
          if (cancelled) void uploader.close()
        })
        .catch(() => {
          // Phòng vừa dừng ghi / kết thúc đúng lúc mình bắt đầu → không có gì để gửi
          if (rec.state !== 'inactive') rec.stop()
          setState('idle')
        })
    }
    rec.onerror = () => setState('error')
    void ctxRef.current?.resume().catch(() => {})
    rec.start(CHUNK_MS)
    setState('recording')

    return () => {
      cancelled = true
      const finish = () => void uploader?.close()
      if (rec.state !== 'inactive') {
        rec.addEventListener('stop', finish, { once: true }) // khúc cuối được đẩy ra TRƯỚC sự kiện stop
        rec.stop()
      } else {
        finish()
      }
      setState('idle')
    }
  }, [code, recording])

  return state
}
