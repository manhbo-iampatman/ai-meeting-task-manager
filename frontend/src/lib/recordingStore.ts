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
const DB_VERSION = 1

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
      }
      req.onsuccess = () => resolve(req.result)
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

/** Đuôi file tương ứng với định dạng trình duyệt ghi ra. */
export function extForMime(mime: string): string {
  if (mime.includes('webm')) return '.webm'
  if (mime.includes('ogg')) return '.ogg'
  if (mime.includes('mp4') || mime.includes('aac')) return '.m4a'
  return '.webm'
}
