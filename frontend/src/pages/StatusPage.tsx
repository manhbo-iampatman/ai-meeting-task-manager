import { useQuery } from '@tanstack/react-query'
import { getHealth, type ComponentStatus } from '../api/client'

// Trang kiểm tra hệ thống (Giai đoạn 0): xem backend, CSDL, Redis, GPU đã chạy chưa.
// useQuery tự gọi API, tự gọi lại mỗi 5 giây (refetchInterval).

const LABELS: Record<string, string> = {
  backend: 'Backend (FastAPI)',
  database: 'Cơ sở dữ liệu (PostgreSQL)',
  redis: 'Hàng đợi (Redis)',
  gpu: 'GPU (CUDA)',
}

function Badge({ s }: { s: ComponentStatus['status'] }) {
  const style = {
    ok: 'bg-emerald-100 text-emerald-700',
    error: 'bg-rose-100 text-rose-700',
    not_installed: 'bg-amber-100 text-amber-700',
  }[s]
  const text = { ok: 'Hoạt động', error: 'Lỗi', not_installed: 'Chưa cài' }[s]
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}>
      <span className={`size-1.5 rounded-full bg-current ${s === 'ok' ? 'animate-pulse' : ''}`} aria-hidden="true" />
      {text}
    </span>
  )
}

export default function StatusPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 5000,
  })

  return (
    <div className="mx-auto max-w-xl px-4 py-12">
      <h1 className="text-gradient text-3xl font-bold tracking-tight">MeetFlow</h1>
      <p className="mt-1 text-sm text-slate-500">
        Quản lý công việc nhóm · AI tóm tắt cuộc họp và tạo đầu việc
      </p>

      <div className="glass mt-8 animate-page overflow-hidden rounded-2xl border">
        <div className="border-b border-slate-200 px-5 py-3 font-semibold">Trạng thái hệ thống</div>

        {isLoading && <p className="px-5 py-4 text-sm text-slate-500">Đang kiểm tra…</p>}

        {isError && (
          <p className="px-5 py-4 text-sm text-rose-600">
            Không kết nối được backend. Hãy chạy: <code>uvicorn app.main:app --reload</code>
          </p>
        )}

        {data && (
          <ul className="divide-y divide-slate-100">
            {(['backend', 'database', 'redis', 'gpu'] as const).map((key) => (
              <li key={key} className="flex items-center justify-between gap-4 px-5 py-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium">{LABELS[key]}</div>
                  {data[key].detail && (
                    <div className="truncate text-xs text-slate-500">{data[key].detail}</div>
                  )}
                </div>
                <Badge s={data[key].status} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {data && (
        <p className="mt-4 text-xs text-slate-500">
          Cấu hình AI: STT = {data.ai_config.stt} ({data.ai_config.whisper_model}) · LLM = {data.ai_config.llm}
        </p>
      )}
    </div>
  )
}
