import { useRef, useState, type DragEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { createMeeting } from '../../api/endpoints'
import { errorMessage, formatBytes, formatDate, todayISO } from '../../lib/utils'
import Modal from '../Modal'
import { Button, ErrorText, Input, Label } from '../ui'

const ACCEPT = '.mp3,.m4a,.wav,.webm,.ogg,.oga,.opus,.aac,.flac,.mp4,.mpeg,.amr,.wma,.txt,audio/*'
const MAX_MB = 300

/** F09–F10: tạo cuộc họp từ file ghi âm / file .txt / văn bản dán vào. */
export default function UploadMeetingModal({ workspaceId, onClose }: { workspaceId: number; onClose: () => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<'file' | 'text'>('file')
  const [date, setDate] = useState(todayISO())
  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [text, setText] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const [error, setError] = useState('')

  const pickFile = (f: File | undefined | null) => {
    setError('')
    if (!f) return
    if (f.size > MAX_MB * 1024 * 1024) {
      setError(`File quá lớn (tối đa ${MAX_MB}MB)`)
      return
    }
    setFile(f)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    pickFile(e.dataTransfer.files?.[0])
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    if (mode === 'file' && !file) return setError('Hãy chọn file ghi âm')
    if (mode === 'text' && !text.trim()) return setError('Hãy dán nội dung cuộc họp')
    setUploadPct(0)
    try {
      const m = await createMeeting(
        workspaceId,
        {
          title: title.trim() || `Họp ngày ${formatDate(date)}`,
          meeting_date: date,
          file: mode === 'file' ? file : null,
          text: mode === 'text' ? text : undefined,
        },
        setUploadPct,
      )
      qc.invalidateQueries({ queryKey: ['meetings', workspaceId] })
      navigate(`/meetings/${m.id}`)
    } catch (err) {
      setError(errorMessage(err, 'Tải lên thất bại'))
      setUploadPct(null)
    }
  }

  const busy = uploadPct !== null
  const tabCls = (active: boolean) =>
    `flex-1 rounded-md px-3 py-1.5 text-sm font-medium ${active ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-600'}`

  return (
    <Modal open onClose={busy ? () => {} : onClose}>
      <form onSubmit={onSubmit} className="space-y-4 p-6">
        <div>
          <h2 className="text-lg font-semibold">Thêm cuộc họp</h2>
          <p className="text-sm text-slate-500">Tải ghi âm lên, hệ thống sẽ tự chuyển thành văn bản.</p>
        </div>

        <div className="grid grid-cols-[1fr_auto] gap-3">
          <div>
            <Label>Tên cuộc họp</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`Họp ngày ${formatDate(date)}`} />
          </div>
          <div>
            <Label>Ngày họp</Label>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </div>
        </div>

        <div className="flex gap-1 rounded-lg bg-slate-100 p-1">
          <button type="button" className={tabCls(mode === 'file')} onClick={() => setMode('file')}>
            🎙️ Tải file ghi âm
          </button>
          <button type="button" className={tabCls(mode === 'text')} onClick={() => setMode('text')}>
            📝 Dán văn bản
          </button>
        </div>

        {mode === 'file' ? (
          <div
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => !busy && inputRef.current?.click()}
            className={`cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition ${
              dragOver ? 'border-indigo-400 bg-indigo-50' : 'border-slate-300 hover:border-indigo-300'
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
            {file ? (
              <div>
                <p className="font-medium text-slate-800">{file.name}</p>
                <p className="text-xs text-slate-500">
                  {formatBytes(file.size)} · bấm để chọn file khác
                </p>
              </div>
            ) : (
              <div>
                <p className="text-sm text-slate-700">Kéo thả file vào đây, hoặc bấm để chọn</p>
                <p className="mt-1 text-xs text-slate-500">mp3, m4a, wav, webm, ogg, aac, flac, mp4 · hoặc .txt · tối đa {MAX_MB}MB</p>
              </div>
            )}
          </div>
        ) : (
          <textarea
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={'Dán biên bản / bản ghi cuộc họp vào đây. Mỗi dòng là 1 đoạn.\nVD:\nNam: Tuần này anh làm phần cơ sở dữ liệu, thứ Sáu xong.\nLan: Em chuẩn bị slide cho buổi demo.'}
            className="w-full rounded-lg border border-slate-300 p-3 text-sm outline-none focus:border-indigo-500"
          />
        )}

        {busy && (
          <div>
            <div className="mb-1 flex justify-between text-xs text-slate-600">
              <span>{uploadPct! < 100 ? 'Đang tải lên…' : 'Đang lưu…'}</span>
              <span>{uploadPct}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full bg-indigo-500 transition-all" style={{ width: `${uploadPct}%` }} />
            </div>
          </div>
        )}
        <ErrorText>{error}</ErrorText>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
            Hủy
          </Button>
          <Button type="submit" disabled={busy}>
            {mode === 'file' ? 'Tải lên & xử lý' : 'Tạo cuộc họp'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
