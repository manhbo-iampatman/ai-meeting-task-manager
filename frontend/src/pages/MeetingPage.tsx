import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Check, Hourglass, RotateCw, Sparkles } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteMeeting,
  getMeeting,
  getMeetingAudioUrl,
  getWorkspace,
  mergeLateTrack,
  retryMeeting,
  summarizeMeeting,
  updateMeeting,
  updateTranscript,
} from '../api/endpoints'
import type { MeetingDetail, Segment } from '../api/types'
import ExtractedTasksView from '../components/meeting/ExtractedTasksView'
import MeetingStatusBadge from '../components/meeting/MeetingStatusBadge'
import { SourceLabel } from '../components/meeting/SourceIcon'
import SummaryView from '../components/meeting/SummaryView'
import TranscriptView from '../components/meeting/TranscriptView'
import { Button, ErrorText, Spinner } from '../components/ui'
import { useWorkspaceSocket } from '../hooks/useWorkspaceSocket'
import { errorMessage, formatBytes, formatClock, formatDate, formatDateTime } from '../lib/utils'

const PROCESSING = new Set(['queued', 'transcribing', 'summarizing'])

/** Các bước xử lý — hiển thị dạng "đường đi" để người dùng biết hệ thống đang ở đâu. */
function Pipeline({ m }: { m: MeetingDetail }) {
  const [waitedLong, setWaitedLong] = useState(false)
  useEffect(() => {
    setWaitedLong(false)
    // Đứng ở hàng đợi quá 15 giây → có thể worker chưa chạy.
    // AI tóm tắt quá 20 giây (bình thường 3–20 giây) → có thể Gemini đang quá tải.
    const ms = m.status === 'queued' ? 15000 : m.status === 'summarizing' ? 20000 : 0
    if (!ms) return
    const t = setTimeout(() => setWaitedLong(true), ms)
    return () => clearTimeout(t)
  }, [m.status])

  const hasTranscript = m.status === 'transcribed' || m.status === 'summarizing' || m.status === 'review'
  const online = m.source_type === 'online'
  const steps = [
    {
      key: 'upload',
      label: m.source_type === 'text' ? 'Nhận văn bản' : online ? 'Nhận ghi âm riêng của từng người' : 'Tải file lên',
      state: 'done',
    },
    {
      key: 'queue',
      label: 'Chờ trong hàng đợi',
      state: m.status === 'queued' ? 'active' : m.status === 'transcribing' || hasTranscript ? 'done' : 'idle',
    },
    {
      key: 'stt',
      label:
        m.source_type === 'text'
          ? 'Bản ghi (văn bản có sẵn)'
          : online
            ? 'Chuyển giọng nói → văn bản, lần lượt từng người (Whisper), ghép theo thời gian'
            : 'Chuyển giọng nói → văn bản (Whisper)',
      state: m.status === 'transcribing' ? 'active' : hasTranscript ? 'done' : m.status === 'failed' ? 'error' : 'idle',
    },
    {
      key: 'llm',
      label: 'AI tóm tắt & tách đầu việc (LLM)',
      state: m.status === 'summarizing' ? 'active' : m.status === 'review' ? 'done' : 'idle',
    },
  ]
  const dot = {
    done: 'bg-emerald-500 text-white',
    active: 'bg-brand-500 text-white animate-pulse',
    error: 'bg-rose-500 text-white',
    idle: 'bg-slate-200 text-slate-500',
  } as const

  return (
    <div className="glass rounded-2xl border p-5">
      <ol className="space-y-3">
        {steps.map((s, i) => (
          <li key={s.key} className="flex items-center gap-3">
            <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${dot[s.state as keyof typeof dot]}`}>
              {s.state === 'done' ? <Check className="size-3.5" aria-hidden="true" /> : s.state === 'error' ? '!' : i + 1}
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
            <div className="h-full rounded-full bg-brand-500 transition-all duration-700" style={{ width: `${Math.max(3, m.progress)}%` }} />
          </div>
          <p className="mt-2 text-xs text-slate-500">Bạn có thể rời trang này — hệ thống vẫn xử lý và tự cập nhật khi xong.</p>
        </div>
      )}
      {m.status === 'summarizing' && (
        <div className="mt-5">
          <div className="mb-1 flex justify-between text-xs text-slate-600">
            <span>AI đang đọc bản ghi để viết biên bản và tách đầu việc…</span>
            <span>{m.progress}%</span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full animate-pulse rounded-full bg-violet-500 transition-all duration-700" style={{ width: `${Math.max(8, m.progress)}%` }} />
          </div>
          <p className="mt-2 text-xs text-slate-500">Thường mất 10–30 giây. Bạn có thể rời trang này — hệ thống tự cập nhật khi xong.</p>
          {m.status_note ? (
            <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">{m.status_note}</p>
          ) : (
            waitedLong && (
              <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                Gemini đang trả lời chậm hơn bình thường (có thể đang quá tải). Nếu quá thời gian chờ, hệ thống sẽ tự
                chuyển sang mô hình dự phòng.
              </p>
            )
          )}
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
  const qc = useQueryClient()
  const navigate = useNavigate()
  const audioRef = useRef<HTMLAudioElement>(null)

  const { data: m, isLoading, error } = useQuery({
    queryKey: ['meeting', id],
    queryFn: () => getMeeting(id),
    // Dự phòng khi mất WebSocket: đang xử lý (hoặc Online Meeting đang chờ ghi âm gửi về) thì cứ 5 giây hỏi lại 1 lần
    refetchInterval: (q) => {
      const d = q.state.data
      return d && (PROCESSING.has(d.status) || (d.source_type === 'online' && d.status === 'uploaded')) ? 5000 : false
    },
  })
  // Link nghe lại ghi âm kèm "vé" riêng (hết hạn sau 12 giờ). Giữ nguyên link suốt lúc xem trang
  // (staleTime: Infinity): đổi link giữa chừng thì thẻ <audio> sẽ phát lại từ đầu.
  const { data: audioUrl } = useQuery({
    queryKey: ['meeting-audio', id],
    queryFn: () => getMeetingAudioUrl(id),
    enabled: !!m?.has_audio,
    staleTime: Infinity,
  })
  const live = useWorkspaceSocket(m?.workspace_id)
  // Thành viên + bảng của nhóm: để chọn người làm và chọn bảng khi duyệt đầu việc (GĐ5)
  const { data: ws } = useQuery({
    queryKey: ['workspace', m?.workspace_id],
    queryFn: () => getWorkspace(m!.workspace_id),
    enabled: !!m?.can_review,
  })

  const setData = (d: MeetingDetail) => {
    qc.setQueryData(['meeting', id], d)
    qc.invalidateQueries({ queryKey: ['meetings', d.workspace_id] })
  }
  const retry = useMutation({ mutationFn: () => retryMeeting(id), onSuccess: setData })
  const summarize = useMutation({ mutationFn: () => summarizeMeeting(id), onSuccess: setData })
  const rename = useMutation({ mutationFn: (title: string) => updateMeeting(id, { title }), onSuccess: setData })
  const save = useMutation({ mutationFn: (segs: Segment[]) => updateTranscript(id, segs), onSuccess: setData })
  const mergeTrack = useMutation({ mutationFn: (trackId: number) => mergeLateTrack(id, trackId), onSuccess: setData })
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
  // Đang chuyển giọng nói thì chưa có bản ghi để hiện; đang tóm tắt thì vẫn hiện (chỉ khóa nút sửa)
  const transcribing = m.status === 'queued' || m.status === 'transcribing'
  // Lỗi ở bước tóm tắt: bản ghi vẫn còn, trạng thái quay về "đã có bản ghi" / "chờ duyệt" kèm thông báo lỗi
  const summarizeError = m.status !== 'failed' && !processing ? m.error : null
  const speed = tr?.duration_sec && tr?.processing_sec ? tr.duration_sec / tr.processing_sec : null
  // Online Meeting: người có ghi âm nhưng trình duyệt chưa báo "gửi xong" → bản ghi có thể thiếu lời của họ
  const missingTracks = (m.tracks ?? []).filter((t) => t.has_audio && !t.finished)

  const copyText = async () => {
    if (tr) await navigator.clipboard.writeText(tr.full_text)
  }
  const downloadText = () => {
    if (!tr) return
    const lines = tr.segments.map((s) => {
      const text = s.speaker ? `${s.speaker}: ${s.text}` : s.text
      return s.start != null ? `[${formatClock(s.start)}] ${text}` : text
    })
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
        <ArrowLeft className="mr-1 inline size-4 align-[-3px]" aria-hidden="true" />
        Về trang nhóm
      </Link>

      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight">{m.title}</h1>
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
            <div className="glass rounded-2xl border p-3">
              {/* Chưa có link thì vẫn hiện thẻ <audio> (không src) để thanh phát không "nhảy" bố cục */}
              <audio ref={audioRef} controls preload="metadata" src={audioUrl} className="w-full" />
            </div>
          )}

          {m.status === 'failed' && (
            <div className="space-y-3 rounded-xl border border-rose-200 bg-rose-50 p-4">
              <p className="text-sm font-medium text-rose-700">Xử lý ghi âm thất bại</p>
              <p className="break-words text-sm text-rose-700">{m.error}</p>
              {m.source_type !== 'text' && (
                <Button onClick={() => retry.mutate()} disabled={retry.isPending}>
                  <RotateCw aria-hidden="true" /> Thử lại
                </Button>
              )}
              <ErrorText>{retry.error && errorMessage(retry.error)}</ErrorText>
            </div>
          )}

          {/* Online Meeting vừa kết thúc: chờ trình duyệt của mọi người gửi nốt ghi âm (tối đa 2 phút) */}
          {m.source_type === 'online' && m.status === 'uploaded' && (
            <div className="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-800">
              <p className="font-medium">
                <Hourglass className="mr-1 inline size-4 align-[-3px]" aria-hidden="true" />
                {m.status_note ?? 'Đang chờ ghi âm của mọi người gửi về…'}</p>
              <p className="mt-1 text-xs">
                Mỗi người ghi âm bằng mic của mình. Đủ ghi âm của mọi người (hoặc sau tối đa 2 phút) hệ thống sẽ tự chuyển
                thành bản ghi có tên người nói.
              </p>
              {m.tracks.length > 0 && (
                <p className="mt-2 text-xs">
                  {m.tracks.map((t) => `${t.speaker_name} ${t.finished ? '✓' : '…'}`).join(' · ')}
                </p>
              )}
            </div>
          )}

          {(processing || (m.status === 'failed' && !tr)) && <Pipeline m={m} />}

          {/* Online Meeting: ghi âm của ai đó chưa về đủ, hoặc về muộn đang chờ đưa vào bản ghi */}
          {m.source_type === 'online' && m.status !== 'uploaded' && !transcribing && (
            <>
              {missingTracks.length > 0 && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
                  <p className="font-medium">Thiếu ghi âm của {missingTracks.map((t) => t.speaker_name).join(', ')}</p>
                  <p className="mt-1 text-xs">
                    Trình duyệt của người này chưa gửi hết (rớt mạng hoặc đóng tab đột ngột), nên bản ghi có thể thiếu lời của
                    họ. Khi họ mở lại MeetFlow, phần còn lại sẽ tự được gửi lên và bổ sung.
                  </p>
                </div>
              )}
              {m.tracks
                .filter((t) => t.pending)
                .map((t) => (
                  <div key={t.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-brand-200 bg-brand-50 p-4 text-sm text-brand-900">
                    <p className="min-w-0 flex-1">
                      <b>Ghi âm đến muộn của {t.speaker_name} đã về.</b> Bản ghi đã được sửa tay hoặc đã tóm tắt nên hệ thống
                      không tự thêm vào.
                    </p>
                    {m.can_review && (
                      <Button
                        disabled={mergeTrack.isPending || processing}
                        onClick={() =>
                          confirm(
                            `Đưa lời của ${t.speaker_name} vào bản ghi? Câu của những người khác (kể cả chỗ đã sửa tay) được giữ nguyên. ` +
                              'Nếu đã tóm tắt, bạn nên bấm tóm tắt lại sau đó.',
                          ) && mergeTrack.mutate(t.id)
                        }
                      >
                        Bổ sung ghi âm của {t.speaker_name}
                      </Button>
                    )}
                  </div>
                ))}
              <ErrorText>{mergeTrack.error && errorMessage(mergeTrack.error)}</ErrorText>
            </>
          )}

          {summarizeError && (
            <div className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-sm font-medium text-amber-800">AI chưa tóm tắt được cuộc họp</p>
              <p className="break-words text-sm text-amber-800">{summarizeError}</p>
              <p className="text-xs text-amber-700">
                Bản ghi vẫn còn nguyên{m.summary ? ', kết quả tóm tắt lần trước vẫn được giữ' : ''}. Bấm nút tóm tắt ở cột bên phải để thử lại.
              </p>
            </div>
          )}

          {m.summary && !transcribing && (
            <>
              <SummaryView summary={m.summary} />
              <ExtractedTasksView
                meeting={m}
                members={ws?.members.map((x) => x.user) ?? []}
                boards={ws?.boards ?? []}
                audioRef={audioRef}
                onChange={setData}
              />
            </>
          )}

          {tr && !transcribing && (
            <TranscriptView
              segments={tr.segments}
              audioRef={audioRef}
              editable={!processing}
              saving={save.isPending}
              onSave={(segs) => save.mutateAsync(segs)}
            />
          )}
          <ErrorText>{save.error && errorMessage(save.error)}</ErrorText>
        </div>

        <aside className="space-y-4">
          <div className="glass rounded-2xl border p-4 text-sm">
            <h3 className="mb-2 font-semibold">Thông tin</h3>
            <dl className="space-y-1.5 text-slate-600">
              <div className="flex justify-between gap-2">
                <dt>Nguồn</dt>
                <dd className="text-right">
                  <SourceLabel type={m.source_type} />
                </dd>
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

          {tr && !transcribing && (
            <div className="rounded-xl border border-dashed border-brand-200 bg-brand-50/50 p-4 text-sm">
              <h3 className="font-semibold text-brand-800">{m.summary ? 'Tóm tắt bằng AI' : 'Bước tiếp theo'}</h3>
              <p className="mt-1 text-brand-900/70">
                {m.summary ? (
                  <>
                    Đã có biên bản,{' '}
                    <b>{m.extracted_tasks.filter((t) => t.status !== 'accepted').length} đầu việc chờ duyệt</b>
                    {m.extracted_tasks.some((t) => t.status === 'accepted') && (
                      <> và {m.extracted_tasks.filter((t) => t.status === 'accepted').length} việc đã lên bảng</>
                    )}
                    . Sửa bản ghi rồi tóm tắt lại nếu thấy AI hiểu sai.
                  </>
                ) : (
                  <>
                    Kiểm tra bản ghi (nhất là <b>tên người</b> và <b>ngày tháng</b>), rồi để AI tóm tắt và tách danh sách{' '}
                    <b>Ai làm – Làm gì – Hạn chót</b>.
                  </>
                )}
              </p>
              <Button
                className="mt-3 w-full"
                variant={m.summary ? 'secondary' : 'primary'}
                disabled={processing || summarize.isPending}
                onClick={() => {
                  if (
                    m.summary &&
                    !confirm(
                      'Tóm tắt lại? Biên bản và các đầu việc CHƯA đẩy sẽ được thay bằng kết quả mới. ' +
                        'Việc đã lên bảng được giữ nguyên; việc mới trùng với chúng sẽ được bỏ tick sẵn.',
                    )
                  )
                    return
                  summarize.mutate()
                }}
              >
                {m.status === 'summarizing' ? (
                  'AI đang tóm tắt…'
                ) : m.summary ? (
                  <>
                    <RotateCw aria-hidden="true" /> Tóm tắt lại
                  </>
                ) : (
                  <>
                    <Sparkles aria-hidden="true" /> Tóm tắt & tạo đầu việc
                  </>
                )}
              </Button>
              <div className="mt-2">
                <ErrorText>{summarize.error && errorMessage(summarize.error)}</ErrorText>
              </div>
            </div>
          )}

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
