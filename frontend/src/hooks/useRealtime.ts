import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../stores/auth'

/**
 * Kết nối WebSocket tới 1 "phòng" (vd. "boards/1", "workspaces/3").
 * Mất kết nối thì tự kết nối lại sau 2, 4, 8… tối đa 15 giây (exponential backoff).
 * Trả về `true/false` = đang kết nối hay không.
 */
export function useRealtime(path: string | null, onMessage: (msg: Record<string, unknown>) => void) {
  const token = useAuth((s) => s.token)
  const [connected, setConnected] = useState(false)
  const handler = useRef(onMessage)
  handler.current = onMessage // luôn dùng hàm mới nhất mà không phải kết nối lại

  useEffect(() => {
    if (!token || !path) return
    let ws: WebSocket | null = null
    let retry: number | undefined
    let ping: number | undefined
    let closedByUs = false
    let attempt = 0

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/api/ws/${path}?token=${encodeURIComponent(token)}`)
      ws.onopen = () => {
        attempt = 0
        setConnected(true)
        ping = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 25000)
      }
      ws.onmessage = (ev) => {
        try {
          handler.current(JSON.parse(ev.data))
        } catch {
          /* bỏ qua tin nhắn lỗi */
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
  }, [path, token])

  return connected
}
