import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getOpenRoom } from '../../api/endpoints'
import { Button } from '../ui'

/**
 * Nút vào phòng họp trực tuyến trên trang nhóm.
 *
 * Mỗi nhóm chỉ có MỘT phòng mở:
 *   - Chưa có phòng → "📹 Online Meeting": sang màn hình chờ. Phòng CHƯA được tạo ở bước này — chỉ khi
 *     bấm "Vào phòng" mới tạo (bấm nhầm rồi quay lại không để lại phòng trống).
 *   - Đã có phòng   → "📹 Tham gia phòng": vào thẳng phòng đang họp (không tạo phòng thứ hai).
 * Trạng thái tự cập nhật khi có người mở / kết thúc phòng (sự kiện "room_updated", xem useWorkspaceSocket).
 */
export default function OnlineMeetingButton({ workspaceId }: { workspaceId: number }) {
  const navigate = useNavigate()
  const { data: room } = useQuery({ queryKey: ['room', workspaceId], queryFn: () => getOpenRoom(workspaceId) })

  if (room) {
    return (
      <Button onClick={() => navigate(`/room/${room.code}`)} title={`${room.title} · chủ phòng ${room.host?.full_name ?? ''}`}>
        <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-300" />
        📹 Tham gia phòng
        {room.recording === 'on' && <span className="rounded bg-rose-500 px-1 text-[10px]">đang ghi</span>}
      </Button>
    )
  }
  return <Button onClick={() => navigate(`/room/new?ws=${workspaceId}`)}>📹 Online Meeting</Button>
}
