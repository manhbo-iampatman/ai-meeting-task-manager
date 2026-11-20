import { useEffect, useLayoutEffect, useRef, useState } from 'react'

/** Kích thước thật của một phần tử, cập nhật khi đổi cỡ cửa sổ / xoay điện thoại. */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, size] as const
}

/** true khi màn hình hẹp (điện thoại). */
export function useIsNarrow(maxWidth = 767) {
  const query = `(max-width: ${maxWidth}px)`
  const [narrow, setNarrow] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = () => setNarrow(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return narrow
}

/**
 * Chia `n` ô cùng tỉ lệ `aspect` (rộng / cao) vào khung W × H sao cho Ô TO NHẤT có thể và
 * KHÔNG phải cuộn (giống Google Meet). Thử mọi số cột 1..n, giữ cách cho ô rộng nhất.
 *
 * Ví dụ khung 1200 × 640, 3 người, 16:9 → 2 cột × 2 hàng (ô 584 × 316) to hơn 3 cột × 1 hàng.
 */
export function fitGrid(n: number, width: number, height: number, gap: number, aspect: number) {
  let best = { cols: 1, w: 0, h: 0 }
  if (n <= 0 || width <= 0 || height <= 0) return best
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols)
    const maxW = (width - gap * (cols - 1)) / cols
    const maxH = (height - gap * (rows - 1)) / rows
    const w = Math.min(maxW, maxH * aspect)
    if (w > best.w) best = { cols, w: Math.floor(w), h: Math.floor(w / aspect) }
  }
  return best
}

/** Màu vòng tròn avatar theo người (ổn định: cùng người luôn cùng màu). */
const AVATAR_COLORS = ['#2563eb', '#7c3aed', '#059669', '#d97706', '#db2777', '#0891b2', '#4f46e5', '#65a30d']
export function avatarColor(identity: string) {
  let h = 0
  for (const ch of identity) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}

/** Chữ cái đại diện: chữ đầu của TÊN GỌI (chữ cuối của họ tên Việt) — "Trần Thị Lan" → "L". */
export function initialOf(name: string) {
  const parts = name.trim().split(/\s+/)
  return (parts[parts.length - 1]?.[0] ?? '?').toUpperCase()
}

/** "10:35" theo giờ máy, cập nhật mỗi 20 giây. */
export function useClock() {
  const fmt = () => new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
  const [now, setNow] = useState(fmt)
  useEffect(() => {
    const t = window.setInterval(() => setNow(fmt()), 20000)
    return () => window.clearInterval(t)
  }, [])
  return now
}
