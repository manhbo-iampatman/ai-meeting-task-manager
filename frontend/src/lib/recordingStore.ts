/**
 * Lưu tạm bản ghi âm vào IndexedDB — bộ nhớ của trình duyệt, KHÔNG mất khi
 * tải lại trang, tắt trình duyệt hay tắt máy.
 *
 * Vì sao cần? Ghi âm trực tiếp 1 tiếng mà lỡ đóng tab / hết pin / mất mạng lúc tải lên
 * → mất cả buổi họp. Nên:
 *   - Trong lúc ghi: cứ mỗi giây lưu 1 "khúc" (chunk) vào đây.
 *   - Ghi xong: tải lên server. Thành công mới xóa bản tạm.
 *   - Thất bại (mất mạng): bản ghi vẫn nằm đây, có mạng lại thì tự tải lên.
 *
 * Cấu trúc: store "recordings" (thông tin) + store "chunks" (dữ liệu âm thanh từng khúc).
 */

export type RecordingMeta = {
  id: string
  workspaceId: number
  title: string
  meetingDate: string
  mimeType: string
  startedAt: number
  durationSec: number
  /** recording: đang ghi (hoặc bị gián đoạn giữa chừng) · ready: ghi xong, chờ tải lên */
  status: 'recording' | 'ready'
  lastError?: string
}

const DB_NAME = 'meetflow-recordings'
const DB_VERSION = 2 // v2: thêm store "roomTracks" (ghi âm Online Meeting đang gửi dở)

let dbPromise: Promise<IDBDatabase> | null = null

function openDB(): Promise<IDBDatabase> {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION)
      req.onupgradeneeded = () => {
        const db = req.result
        if (!db.objectStoreNames.contains('recordings')) db.createObjectStore('recordings', { keyPath: 'id' })
        if (!db.objectStoreNames.contains('chunks')) {
          const s = db.createObjectStore('chunks', { autoIncrement: true })
          s.createIndex('byRecording', 'recordingId')
        }
        if (!db.objectStoreNames.contains('roomTracks')) db.createObjectStore('roomTracks', { keyPath: 'trackId' })
      }
      req.onsuccess = () => {
        // Tab khác mở bản web mới hơn (cần nâng cấp CSDL) → nhường, không chặn nó
        req.result.onversionchange = () => {
          req.result.close()
          dbPromise = null
        }
        resolve(req.result)
      }
      req.onerror = () => reject(req.error)
    })
  }
  return dbPromise
}

function tx<T>(stores: string[], mode: IDBTransactionMode, fn: (t: IDBTransaction) => IDBRequest<T> | void): Promise<T> {
  return openDB().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(stores, mode)
        let result: T
        const req = fn(t)
        if (req) req.onsuccess = () => (result = req.result)
        t.oncomplete = () => resolve(result)
        t.onerror = () => reject(t.error)
        t.onabort = () => reject(t.error)
      }),
  )
}

export function saveMeta(meta: RecordingMeta): Promise<unknown> {
  return tx(['recordings'], 'readwrite', (t) => t.objectStore('recordings').put(meta))
}

export function addChunk(recordingId: string, seq: number, data: Blob): Promise<unknown> {
  return tx(['chunks'], 'readwrite', (t) => t.objectStore('chunks').add({ recordingId, seq, data }))
}

export function listRecordings(workspaceId?: number): Promise<RecordingMeta[]> {
  return tx<RecordingMeta[]>(['recordings'], 'readonly', (t) => t.objectStore('recordings').getAll()).then((all) =>
    (all ?? []).filter((r) => workspaceId == null || r.workspaceId === workspaceId).sort((a, b) => b.startedAt - a.startedAt),
  )
}

/** Ghép các khúc (theo đúng thứ tự) thành 1 file hoàn chỉnh. */
export async function getRecordingBlob(meta: RecordingMeta): Promise<Blob> {
  const rows = await tx<{ seq: number; data: Blob }[]>(['chunks'], 'readonly', (t) =>
    t.objectStore('chunks').index('byRecording').getAll(meta.id),
  )
  rows.sort((a, b) => a.seq - b.seq)
  return new Blob(
    rows.map((r) => r.data),
    { type: meta.mimeType },
  )
}

export async function deleteRecording(id: string): Promise<void> {
  const db = await openDB()
  await new Promise<void>((resolve, reject) => {
    const t = db.transaction(['recordings', 'chunks'], 'readwrite')
    t.objectStore('recordings').delete(id)
    const idx = t.objectStore('chunks').index('byRecording')
    const cur = idx.openKeyCursor(IDBKeyRange.only(id))
    cur.onsuccess = () => {
      const c = cur.result
      if (c) {
        t.objectStore('chunks').delete(c.primaryKey)
        c.continue()
      }
    }
    t.oncomplete = () => resolve()
    t.onerror = () => reject(t.error)
  })
}

// ---------- Online Meeting (Giai đoạn 6): ghi âm của mình trong phòng họp, đang gửi dần lên máy chủ ----------

/**
 * Một "track" = ghi âm mic của MÌNH trong một buổi Online Meeting. Các khúc âm thanh nằm chung
 * store "chunks" (recordingId = "track-<id>"), gửi lên máy chủ được khúc nào thì xóa khúc đó.
 * Đóng tab đột ngột / rớt mạng → phần chưa gửi vẫn nằm đây, lần sau mở web sẽ gửi nốt.
 */
export type RoomTrackMeta = {
  trackId: number
  roomCode: string
  /** Số khúc máy chủ đã nhận (= số thứ tự khúc tiếp theo cần gửi) */
  acked: number
  /** Đã ngừng ghi (không còn khúc mới) → gửi hết thì báo "xong" cho máy chủ */
  closed: boolean
  createdAt: number
}

export const trackRecordingId = (trackId: number) => `track-${trackId}`

export function saveTrackMeta(meta: RoomTrackMeta): Promise<unknown> {
  return tx(['roomTracks'], 'readwrite', (t) => t.objectStore('roomTracks').put(meta))
}

export function listTrackMetas(): Promise<RoomTrackMeta[]> {
  return tx<RoomTrackMeta[]>(['roomTracks'], 'readonly', (t) => t.objectStore('roomTracks').getAll()).then((x) => x ?? [])
}

export function deleteTrackMeta(trackId: number): Promise<void> {
  return tx(['roomTracks'], 'readwrite', (t) => t.objectStore('roomTracks').delete(trackId)).then(() =>
    deleteChunks(trackRecordingId(trackId)),
  )
}

/** Các khúc còn lưu của một bản ghi, theo đúng thứ tự. */
export function getChunks(recordingId: string): Promise<{ seq: number; data: Blob }[]> {
  return tx<{ seq: number; data: Blob }[]>(['chunks'], 'readonly', (t) =>
    t.objectStore('chunks').index('byRecording').getAll(recordingId),
  ).then((rows) => (rows ?? []).sort((a, b) => a.seq - b.seq))
}

/** Xóa các khúc của một bản ghi; có `uptoSeq` thì chỉ xóa khúc có số thứ tự ≤ giá trị đó. */
export async function deleteChunks(recordingId: string, uptoSeq?: number): Promise<void> {
  const db = await openDB()
  await new Promise<void>((resolve, reject) => {
    const t = db.transaction(['chunks'], 'readwrite')
    const cur = t.objectStore('chunks').index('byRecording').openCursor(IDBKeyRange.only(recordingId))
    cur.onsuccess = () => {
      const c = cur.result
      if (!c) return
      if (uptoSeq == null || (c.value as { seq: number }).seq <= uptoSeq) c.delete()
      c.continue()
    }
    t.oncomplete = () => resolve()
    t.onerror = () => reject(t.error)
  })
}

/** Đuôi file tương ứng với định dạng trình duyệt ghi ra. */
export function extForMime(mime: string): string {
  if (mime.includes('webm')) return '.webm'
  if (mime.includes('ogg')) return '.ogg'
  if (mime.includes('mp4') || mime.includes('aac')) return '.m4a'
  return '.webm'
}
