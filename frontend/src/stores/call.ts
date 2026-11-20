import { create } from 'zustand'
// Chỉ lấy KIỂU dữ liệu (bị xóa khi build) → trang chính không phải tải thư viện LiveKit
import type { LocalUserChoices } from '@livekit/components-react'
import type { Room } from '../api/types'

/** Cuộc họp đang tham gia: vé vào LiveKit + mic / cam đã chọn ở màn hình chờ + thông tin phòng lúc vào. */
export type CallSession = { code: string; token: string; choices: LocalUserChoices; room: Room }

/** left: mình bấm rời · ended: buổi họp bị kết thúc · lost: mất kết nối */
export type CallEndReason = 'left' | 'ended' | 'lost'
export type CallEnd = { code: string; title: string; reason: CallEndReason; message?: string }

/** Vị trí ô họp thu nhỏ: khoảng cách (px) tới mép phải và mép dưới màn hình. */
export type MiniPos = { right: number; bottom: number }

type CallState = {
  session: CallSession | null
  /** Cuộc họp vừa kết thúc / rời / rớt mạng — để báo cho người dùng ở trang đang mở */
  ended: CallEnd | null
  miniPos: MiniPos | null
  start: (s: CallSession) => void
  finish: (e: CallEnd | null) => void
  clearEnded: () => void
  setMiniPos: (p: MiniPos) => void
}

/**
 * Cuộc họp Online Meeting đang diễn ra (phương án B).
 *
 * Kết nối LiveKit KHÔNG gắn với trang phòng họp nữa mà gắn với cả ứng dụng (xem `CallHost`):
 * đổi sang trang khác (vuốt / bấm Quay lại, mở bảng Kanban…) thì cuộc họp vẫn chạy, chỉ thu nhỏ thành
 * ô nổi ở góc màn hình. Cố ý KHÔNG lưu xuống trình duyệt: tải lại trang là rời phòng (vé chỉ dùng một lần).
 */
export const useCall = create<CallState>()((set) => ({
  session: null,
  ended: null,
  miniPos: null,
  start: (session) => set({ session, ended: null }),
  finish: (ended) => set({ session: null, ended }),
  clearEnded: () => set({ ended: null }),
  setMiniPos: (miniPos) => set({ miniPos }),
}))
