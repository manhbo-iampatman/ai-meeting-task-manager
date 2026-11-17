import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteMeeting,
  getMeeting,
  meetingAudioUrl,
  retryMeeting,
  updateMeeting,
  updateTranscript,
} from '../api/endpoints'
import type { MeetingDetail, Segment } from '../api/types'
import MeetingStatusBadge from '../components/meeting/MeetingStatusBadge'
import TranscriptView from '../components/meeting/TranscriptView'
import { Button, ErrorText, Spinner } from '../components/ui'
import { useWorkspaceSocket } from '../hooks/useWorkspaceSocket'
import { errorMessage, formatBytes, formatClock, formatDate, formatDateTime } from '../lib/utils'
import { useAuth } from '../stores/auth'

const PROCESSING = new Set(['queued', 'transcribing'])

/** Các bước xử lý — hiển thị dạng "đường đi" để người dùng biết hệ thống đang ở đâu. */
function Pipeline({ m }: { m: MeetingDetail }) {
  const [waitedLong, setWaitedLong] = useState(false)
  useEffect(() => {
    setWaitedLong(false)
    if (m.status !== 'queued') return
    const t = setTimeout(() => setWaitedLong(true), 15000)
    return () => clearTimeout(t)
  }, [m.status])

  const steps = [
    { key: 'upload', label: 'Tải file lên', state: 'done' },
    {
      key: 'queue',
      label: 'Chờ trong hàng đợi',
      state: m.status === 'queued' ? 'active' : m.status === 'transcribing' || m.status === 'transcribed' ? 'done' : 'idle',
    },
    {
      key: 'stt',
      label: 'Chuyển giọng nói → văn bản (Whisper)',
      state: m.status === 'transcribing' ? 'active' : m.status === 'transcribed' ? 'done' : m.status === 'failed' ? 'error' : 'idle',
    },
    { key: 'llm', label: 'Tóm tắt & tạo đầu việc (Giai đoạn 4)', state: 'idle' },
  ]
  const dot = {
    done: 'bg-emerald-500 text-white',
    active: 'bg-indigo-500 text-white animate-pulse',
    error: 'bg-rose-500 text-white',
    idle: 'bg-slate-200 text-slate-500',
  } as const

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.key} className="flex items-center gap-3">
            <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${dot[s.state as keyof typeof dot]}`}>
              {s.state === 'done' ? '✓' : s.state === 'error' ? '!' : i + 1}
            </span>
            <span className={`text-sm ${s.state === 'idle' ? 'text-slate-400' : 'text-slate-700'}`}>{s.label}</span>
          </li>
        ))}
      </ol>

      {m.status === 'transcribing' && (
        <div className="mt-5">
          <div className="mb-1 flex justify-between text-xs text-slate-600">
            <span>Đang nhận dạng giọng nói trên GPU…</span>
            <span>{m.progress}%</span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-indigo-500 transition-all duration-700" style={{ width: `${Math.max(3, m.progress)}%` }} />
          </div>
          <p className="mt-2 text-xs text-slate-500">Bạn có thể rời trang này — hệ thống vẫn xử lý và tự cập nhật khi xong.</p>
        </div>
      )}
      {m.status === 'queued' && waitedLong && (
        <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Đứng chờ hơi lâu? Có thể <b>worker AI chưa chạy</b>. Mở terminal trong thư mục <code>backend</code> và chạy{' '}
          <code className="rounded bg-amber-100 px-1">python -m app.workers.worker</code>
        </p>
      )}
    </div>
  )
}

export default function MeetingPage() {
  const id = Number(useParams().id)
  const token = useAuth((s) => s.token)!
  const qc = useQueryClient()
  const navigate = useNavigate()
  const audioRef = useRef<HTMLAudioElement>(null)

  const { data: m, isLoading, error } = useQuery({
    queryKey: ['meeting', id],
    queryFn: () => getMeeting(id),
    // Dự phòng khi mất WebSocket: đang xử lý thì cứ 5 giây hỏi lại 1 lần
    refetchInterval: (q) => (q.state.data && PROCESSING.has(q.state.data.status) ? 5000 : false),
  })
  const live = useWorkspaceSocket(m?.workspace_id)

  const setData = (d: MeetingDetail) => {
    qc.setQueryData(['meeting', id], d)
    qc.invalidateQueries({ queryKey: ['meetings', d.workspace_id] })
  }
  const retry = useMutation({ mutationFn: () => retryMeeting(id), onSuccess: setData })
  const rename = useMutation({ mutationFn: (title: string) => updateMeeting(id, { title }), onSuccess: setData })
  const save = useMutation({ mutationFn: (segs: Segment[]) => updateTranscript(id, segs), onSuccess: setData })
  const remove = useMutation({
    mutationFn: () => deleteMeeting(id),
    onSuccess: () => {
      if (m) qc.invalidateQueries({ queryKey: ['meetings', m.workspace_id] })
      navigate(m ? `/workspaces/${m.workspace_id}` : '/')
    },
  })

  if (isLoading) return <Spinner />
  if (error || !m) return <p className="p-8 text-center text-rose-600">{errorMessage(error, 'Không tìm thấy cuộc họp')}</p>

  const tr = m.transcript
  const processing = PROCESSING.has(m.status)
  const speed = tr?.duration_sec && tr?.processing_sec ? tr.duration_sec / tr.processing_sec : null

  const copyText = async () => {
    if (tr) await navigator.clipboard.writeText(tr.full_text)
  }
  const downloadText = () => {
    if (!tr) return
    const lines = tr.segments.map((s) => (s.start != null ? `[${formatClock(s.start)}] ${s.text}` : s.text))
    const blob = new Blob([`${m.title} — ${formatDate(m.meeting_date)}\n\n${lines.join('\n')}\n`], { type: 'text/plain;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${m.title}.txt`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8">
      <Link to={`/workspaces/${m.workspace_id}`} className="text-sm text-slate-500 hover:underline">
        ← Về trang nhóm
      </Link>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{m.title}</h1>
        <MeetingStatusBadge status={m.status} progress={m.progress} />
        <span
          className={`flex items-center gap-1 text-xs ${live ? 'text-emerald-600' : 'text-slate-400'}`}
          title={live ? 'Tiến độ cập nhật theo thời gian thực' : 'Mất kết nối realtime — đang hỏi lại mỗi 5 giây'}
        >
          <span className={`h-2 w-2 rounded-full ${live ? 'bg-emerald-500' : 'bg-slate-300'}`} />
          {live ? 'Trực tuyến' : 'Ngoại tuyến'}
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Ngày họp {formatDate(m.meeting_date)} · tạo lúc {formatDateTime(m.created_at)}
      </p>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_300px]">
        <div className="min-w-0 space-y-4">
          {m.has_audio && (
            <div className="rounded-xl border border-slate-200 bg-white p-3">
              <audio ref={audioRef} controls preload="metadata" src={meetingAudioUrl(m.id, token)} className="w-full" />
            </div>
          )}

          {m.status === 'failed' && (
            <div className="space-y-3 rounded-xl border border-rose-200 bg-rose-50 p-4">
              <p className="text-sm font-medium text-rose-700">Xử lý ghi âm thất bại</p>
              <p className="break-words text-sm text-rose-700">{m.error}</p>
              {m.source_type !== 'text' && (
                <Button onClick={() => retry.mutate()} disabled={retry.isPending}>
                  ↻ Thử lại
                </Button>
              )}
              <ErrorText>{retry.error && errorMessage(retry.error)}</ErrorText>
            </div>
          )}

          {(processing || (m.status === 'failed' && !tr)) && <Pipeline m={m} />}

          {tr && !processing && (
            <TranscriptView
              segments={tr.segments}
              audioRef={audioRef}
              editable
              saving={save.isPending}
              onSave={(segs) => save.mutateAsync(segs)}
            />
          )}
          <ErrorText>{save.error && errorMessage(save.error)}</ErrorText>
        </div>

        <aside className="space-y-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
            <h3 className="mb-2 font-semibold">Thông tin</h3>
            <dl className="space-y-1.5 text-slate-600">
              <div className="flex justify-between gap-2">
                <dt>Nguồn</dt>
                <dd className="text-right">{{ audio: '🎙️ Tải file ghi âm', recording: '🔴 Ghi trực tiếp', text: '📝 Văn bản' }[m.source_type]}</dd>
              </div>
              {m.audio_filename && (
                <div className="flex justify-between gap-2">
                  <dt>File</dt>
                  <dd className="truncate text-right" title={m.audio_filename}>
                    {m.audio_filename} <span className="text-slate-400">({formatBytes(m.audio_size)})</span>
                  </dd>
                </div>
              )}
              {tr?.duration_sec != null && (
                <div className="flex justify-between gap-2">
                  <dt>Thời lượng</dt>
                  <dd>{formatClock(tr.duration_sec)}</dd>
                </div>
              )}
              {tr?.processing_sec != null && (
                <div className="flex justify-between gap-2">
                  <dt>Thời gian xử lý</dt>
                  <dd>
                    {tr.processing_sec.toFixed(1)} giây{speed && <span className="text-slate-400"> (×{speed.toFixed(1)})</span>}
                  </dd>
                </div>
              )}
              {tr?.stt_model && (
                <div className="flex justify-between gap-2">
                  <dt>Mô hình</dt>
                  <dd className="truncate text-right">{tr.stt_model}</dd>
                </div>
              )}
              {tr?.edited && (
                <div className="flex justify-between gap-2">
                  <dt>Chỉnh sửa</dt>
                  <dd className="text-amber-600">Đã sửa tay</dd>
                </div>
              )}
            </dl>
            {tr && (
              <div className="mt-3 flex gap-2">
                <Button variant="secondary" className="flex-1" onClick={copyText}>
                  Sao chép
                </Button>
                <Button variant="secondary" className="flex-1" onClick={downloadText}>
                  Tải .txt
                </Button>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-dashed border-indigo-200 bg-indigo-50/50 p-4 text-sm">
            <h3 className="font-semibold text-indigo-800">Bước tiếp theo</h3>
            <p className="mt-1 text-indigo-900/70">
              AI tóm tắt cuộc họp và tách danh sách <b>Ai làm – Làm gì – Hạn chót</b>.
            </p>
            <Button className="mt-3 w-full" disabled>
              ✨ Tóm tắt & tạo đầu việc (Giai đoạn 4)
            </Button>
          </div>

          <div className="flex flex-col items-start gap-1">
            <button
              className="text-sm text-slate-600 hover:underline"
              onClick={() => {
                const t = prompt('Tên cuộc họp', m.title)
                if (t?.trim()) rename.mutate(t.trim())
              }}
            >
              Đổi tên
            </button>
            {m.source_type !== 'text' && !processing && m.status !== 'failed' && (
              <button
                className="text-sm text-slate-600 hover:underline"
                onClick={() => confirm('Chạy lại nhận dạng giọng nói? Các chỉnh sửa tay trên bản ghi sẽ bị thay thế.') && retry.mutate()}
              >
                Nhận dạng lại
              </button>
            )}
            <button
              className="text-sm text-rose-600 hover:underline"
              onClick={() => confirm(`Xóa cuộc họp “${m.title}” và file ghi âm?`) && remove.mutate()}
            >
              Xóa cuộc họp
            </button>
          </div>
        </aside>
      </div>
    </div>
  )
}
