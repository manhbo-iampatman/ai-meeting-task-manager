import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Hộp thoại.
 *
 * - Vẽ thẳng vào <body> (portal): phần tử có `backdrop-filter` (thẻ kính mờ) biến thành "khung chứa"
 *   của mọi phần tử `position: fixed` bên trong nó, nên nếu vẽ tại chỗ hộp thoại sẽ bị lệch / cắt.
 * - Giữ tiêu điểm bàn phím trong hộp thoại (Tab không lọt ra trang phía sau), Esc để đóng,
 *   đóng xong trả tiêu điểm về nút đã mở nó — yêu cầu của WCAG với hộp thoại.
 */
export default function Modal({
  open,
  onClose,
  children,
  wide = false,
  label,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
  wide?: boolean
  /** Tên hộp thoại cho trình đọc màn hình */
  label?: string
}) {
  const panel = useRef<HTMLDivElement>(null)
  // Nơi gọi thường truyền hàm onClose mới ở mỗi lần vẽ lại → giữ trong ref để hiệu ứng bên dưới
  // chỉ chạy khi mở / đóng (nếu chạy lại liên tục, tiêu điểm sẽ bị giật khỏi ô đang gõ)
  const close = useRef(onClose)
  close.current = onClose

  useEffect(() => {
    if (!open) return
    const onClose = () => close.current()
    const opener = document.activeElement as HTMLElement | null
    // Đưa tiêu điểm vào hộp thoại (ưu tiên ô có autoFocus do component con tự đặt)
    if (panel.current && !panel.current.contains(document.activeElement)) panel.current.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab' || !panel.current) return
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => el.offsetParent !== null)
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    const scroll = document.body.style.overflow
    document.body.style.overflow = 'hidden' // trang phía sau không cuộn theo
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = scroll
      opener?.focus?.()
    }
  }, [open])

  if (!open) return null
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-fade items-start justify-center overflow-y-auto bg-overlay px-4 py-10 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        ref={panel}
        tabIndex={-1}
        className={`glass-blur w-full animate-pop ${wide ? 'max-w-3xl' : 'max-w-md'} rounded-2xl border outline-none`}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={label}
      >
        {children}
      </div>
    </div>,
    document.body,
  )
}
