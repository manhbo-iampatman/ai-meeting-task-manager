import axios from 'axios'
import { finishRoomTrack, uploadTrackChunk } from '../api/endpoints'
import {
  addChunk,
  deleteChunks,
  deleteTrackMeta,
  getChunks,
  listTrackMetas,
  saveTrackMeta,
  trackRecordingId,
  type RoomTrackMeta,
} from './recordingStore'

/**
 * Gửi ghi âm của MÌNH trong phòng Online Meeting lên máy chủ, TỪNG KHÚC, ngay trong lúc họp.
 *
 * Vì sao gửi dần chứ không đợi họp xong mới gửi cả file?
 *   - Họp xong là máy chủ có gần đủ ghi âm của mọi người → nhận dạng được ngay.
 *   - Ai đó đóng tab đột ngột thì chỉ mất vài giây cuối, không mất cả buổi.
 *
 * Bảo đảm không mất, không trùng, không lộn thứ tự:
 *   - Mỗi khúc có số thứ tự (seq). Gửi LẦN LƯỢT: khúc trước được máy chủ nhận rồi mới gửi khúc sau.
 *   - Khúc nào cũng được lưu vào IndexedDB trước khi gửi; máy chủ nhận xong mới xóa.
 *   - Mất mạng → thử lại sau 1, 2, 4… tối đa 15 giây. Máy chủ bỏ qua khúc gửi trùng (idempotent).
 *   - Đóng tab giữa chừng → lần sau mở web, `resumePendingTracks()` gửi nốt phần còn lại.
 */
export class TrackUploader {
  private chunks = new Map<number, Blob>() // các khúc chưa được máy chủ nhận
  private nextSeq: number // số thứ tự cho khúc mới ghi
  private pumping = false
  private stopped = false
  private resolveDone!: () => void
  /** Xong khi máy chủ đã nhận hết và đã được báo "gửi xong" (hoặc track không còn tồn tại). */
  readonly done: Promise<void>

  private meta: RoomTrackMeta

  constructor(meta: RoomTrackMeta, restored: { seq: number; data: Blob }[] = []) {
    this.meta = meta
    for (const c of restored) if (c.seq >= meta.acked) this.chunks.set(c.seq, c.data)
    this.nextSeq = Math.max(meta.acked, ...restored.map((c) => c.seq + 1))
    this.done = new Promise((resolve) => (this.resolveDone = resolve))
    active.set(meta.trackId, this)
    void saveTrackMeta(meta)
  }

  get trackId(): number {
    return this.meta.trackId
  }

  /** Số khúc còn chờ gửi. */
  get pending(): number {
    return this.chunks.size
  }

  /** Thêm một khúc vừa ghi. */
  push(data: Blob): void {
    if (this.meta.closed || data.size === 0) return
    const seq = this.nextSeq++
    this.chunks.set(seq, data)
    void addChunk(trackRecordingId(this.meta.trackId), seq, data).catch(() => {}) // bản dự phòng nếu tab bị đóng
    void this.pump()
  }

  /** Đã ngừng ghi: gửi hết phần còn lại rồi báo máy chủ "xong". */
  close(): Promise<void> {
    if (!this.meta.closed) {
      this.meta.closed = true
      void saveTrackMeta(this.meta)
    }
    void this.pump()
    return this.done
  }

  private finishLocal(): void {
    this.stopped = true
    active.delete(this.meta.trackId)
    void deleteTrackMeta(this.meta.trackId).catch(() => {})
    this.resolveDone()
  }

  private async pump(): Promise<void> {
    if (this.pumping || this.stopped) return
    this.pumping = true
    let attempt = 0
    try {
      while (!this.stopped) {
        const seq = this.meta.acked
        const chunk = this.chunks.get(seq)
        try {
          if (chunk) {
            const res = await uploadTrackChunk(this.meta.trackId, seq, chunk)
            this.ack(res.next_seq)
          } else if (this.meta.closed && seq >= this.nextSeq) {
            await finishRoomTrack(this.meta.trackId)
            this.finishLocal()
            return
          } else {
            return // chưa có khúc mới → chờ lần push() kế tiếp
          }
          attempt = 0
        } catch (err) {
          const status = axios.isAxiosError(err) ? err.response?.status : undefined
          const expected = axios.isAxiosError(err) ? (err.response?.data?.detail?.expected_seq as number | undefined) : undefined
          if (status === 409 && typeof expected === 'number') {
            this.ack(expected) // máy chủ đang chờ khúc khác (vd. đã nhận rồi nhưng mình chưa kịp biết)
            if (!this.chunks.has(expected) && expected < this.nextSeq) {
              this.finishLocal() // khúc máy chủ cần không còn ở đây, không cứu được → dừng, giữ phần máy chủ đã có
              return
            }
            continue
          }
          if (status === 404 || status === 401 || status === 413) {
            this.finishLocal() // track đã bị xóa / hết phiên đăng nhập / quá lớn → không gửi được nữa
            return
          }
          // Mất mạng hoặc máy chủ lỗi tạm thời → chờ rồi thử lại, KHÔNG bỏ khúc nào
          attempt += 1
          await new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** (attempt - 1), 15000)))
        }
      }
    } finally {
      this.pumping = false
    }
  }

  private ack(nextSeq: number): void {
    for (const s of [...this.chunks.keys()]) if (s < nextSeq) this.chunks.delete(s)
    this.meta.acked = nextSeq
    void saveTrackMeta(this.meta)
    void deleteChunks(trackRecordingId(this.meta.trackId), nextSeq - 1).catch(() => {})
  }
}

/** Các track đang được gửi trong tab này (để không gửi trùng khi "gửi nốt"). */
const active = new Map<number, TrackUploader>()

/** Còn ghi âm chưa gửi xong không (để cảnh báo khi đóng tab). */
export function hasUnsentAudio(): boolean {
  return [...active.values()].some((u) => u.pending > 0)
}

/**
 * Gửi nốt ghi âm còn dở từ lần trước (tab bị đóng, rớt mạng lâu). Gọi khi mở web và khi có mạng lại.
 * Máy chủ nhận được sẽ tự bổ sung lời của mình vào bản ghi cuộc họp.
 */
export async function resumePendingTracks(): Promise<void> {
  let metas: RoomTrackMeta[]
  try {
    metas = await listTrackMetas()
  } catch {
    return // trình duyệt không cho dùng IndexedDB (chế độ riêng tư…)
  }
  for (const meta of metas) {
    if (active.has(meta.trackId)) continue
    const restored = await getChunks(trackRecordingId(meta.trackId))
    void new TrackUploader({ ...meta, closed: true }, restored).close()
  }
}
