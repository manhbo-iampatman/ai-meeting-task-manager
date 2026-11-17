import type { MeetingSummary } from '../../api/types'
import { formatDateTime } from '../../lib/utils'

function Block({ icon, title, items, empty }: { icon: string; title: string; items: string[]; empty: string }) {
  return (
    <div>
      <h3 className="mb-1.5 text-sm font-semibold text-slate-700">
        {icon} {title} <span className="font-normal text-slate-400">({items.length})</span>
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-slate-400">{empty}</p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed text-slate-700">
          {items.map((x, i) => (
            <li key={i}>{x}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** F13: biên bản do AI viết — chủ đề, ý chính, quyết định đã chốt, vấn đề còn mở. */
export default function SummaryView({ summary }: { summary: MeetingSummary }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-3">
        <h2 className="font-semibold">Biên bản cuộc họp</h2>
        <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700">AI viết</span>
        {summary.fallback_from && (
          <span
            className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800"
            title={`Mô hình chính ${summary.fallback_from} đang quá tải hoặc hết hạn mức, nên hệ thống dùng mô hình dự phòng ${summary.llm_model ?? ''}. Mô hình dự phòng nhỏ hơn — hãy kiểm tra kỹ biên bản và đầu việc trước khi duyệt.`}
          >
            mô hình dự phòng
          </span>
        )}
      </div>

      {summary.stale && (
        <p className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          Bản ghi đã được sửa sau khi tóm tắt. Biên bản và đầu việc bên dưới có thể không còn khớp — hãy bấm <b>Tóm tắt lại</b>.
        </p>
      )}

      <div className="space-y-4 p-4">
        <p className="text-sm leading-relaxed text-slate-800">
          <span className="font-semibold">Chủ đề: </span>
          {summary.topic || <span className="text-slate-400">(AI không nêu chủ đề)</span>}
        </p>
        <Block icon="💬" title="Ý chính đã thảo luận" items={summary.key_points} empty="Không có." />
        <Block icon="✅" title="Quyết định đã chốt" items={summary.decisions} empty="Cuộc họp chưa chốt quyết định nào." />
        <Block icon="❓" title="Vấn đề còn mở" items={summary.open_issues} empty="Không còn vấn đề nào bỏ ngỏ." />
      </div>

      <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-400">
        {summary.llm_model}
        {summary.fallback_from && ` (dự phòng thay cho ${summary.fallback_from})`}
        {summary.processing_sec != null && ` · ${summary.processing_sec.toFixed(1)} giây`}
        {summary.chunk_count > 1 && ` · bản ghi dài, chia ${summary.chunk_count} đoạn`}
        {` · ${formatDateTime(summary.created_at)}`}
      </p>
    </div>
  )
}
