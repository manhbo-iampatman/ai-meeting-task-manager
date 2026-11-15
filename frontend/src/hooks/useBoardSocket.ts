import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../stores/auth'

/**
 * Mở kết nối WebSocket tới phòng của bảng. Khi server báo có thay đổi
 * (người khác thêm / kéo / sửa thẻ), đánh dấu dữ liệu cũ → React Query tự tải lại.
 * Mất kết nối thì tự kết nối lại sau vài giây.
 */
export function useBoardSocket(boardId: number) {
  const qc = useQueryClient()
  const token = useAuth((s) => s.token)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!token || !boardId) return
    let ws: WebSocket | null = null
    let retry: number | undefined
    let ping: number | undefined
    let closedByUs = false
    let attempt = 0

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/api/ws/boards/${boardId}?token=${encodeURIComponent(token)}`)
      ws.onopen = () => {
        attempt = 0
        setConnected(true)
        ping = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 25000)
      }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'board_updated' || msg.type === 'board_deleted') {
          qc.invalidateQueries({ queryKey: ['board', boardId] })
          qc.invalidateQueries({ queryKey: ['task'] })
          qc.invalidateQueries({ queryKey: ['notifications'] })
        }
      }
      ws.onclose = () => {
        setConnected(false)
        window.clearInterval(ping)
        if (!closedByUs) {
          attempt += 1
          retry = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, 15000))
        }
      }
    }
    connect()

    return () => {
      closedByUs = true
      window.clearTimeout(retry)
      window.clearInterval(ping)
      ws?.close()
    }
  }, [boardId, token, qc])

  return connected
}
