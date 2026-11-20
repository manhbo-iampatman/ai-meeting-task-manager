// Tất cả lời gọi API gom về 1 chỗ: component chỉ gọi hàm, không cần nhớ URL.
import { api } from './client'
import type {
  BoardBrief,
  BoardDetail,
  Column,
  Comment,
  DraftInput,
  Meeting,
  MeetingDetail,
  Member,
  MyTask,
  NameClaim,
  Notification,
  NotificationList,
  PendingName,
  Priority,
  Room,
  RoomJoin,
  Segment,
  Task,
  TaskDetail,
  TokenResponse,
  User,
  WorkspaceDetail,
  WorkspaceSummary,
} from './types'

const data = <T,>(p: Promise<{ data: T }>) => p.then((r) => r.data)

// ---- Xác thực ----
export const register = (body: { email: string; password: string; full_name: string }) =>
  data(api.post<TokenResponse>('/auth/register', body))
export const login = (body: { email: string; password: string }) =>
  data(api.post<TokenResponse>('/auth/login', body))
export const updateMe = (body: { full_name?: string }) => data(api.patch<User>('/auth/me', body))

// ---- Nhóm ----
export const listWorkspaces = () => data(api.get<WorkspaceSummary[]>('/workspaces'))
export const createWorkspace = (name: string) => data(api.post<WorkspaceDetail>('/workspaces', { name }))
export const getWorkspace = (id: number) => data(api.get<WorkspaceDetail>(`/workspaces/${id}`))
export const renameWorkspace = (id: number, name: string) =>
  data(api.patch<WorkspaceDetail>(`/workspaces/${id}`, { name }))
export const deleteWorkspace = (id: number) => api.delete(`/workspaces/${id}`)
export const regenerateInvite = (id: number) => data(api.post<WorkspaceDetail>(`/workspaces/${id}/invite-code`))
export const joinWorkspace = (invite_code: string) =>
  data(api.post<WorkspaceDetail>('/workspaces/join', { invite_code }))
export const addMember = (id: number, email: string) =>
  data(api.post<WorkspaceDetail>(`/workspaces/${id}/members`, { email }))
export const updateMember = (id: number, userId: number, nicknames: string[]) =>
  data(api.patch<Member>(`/workspaces/${id}/members/${userId}`, { nicknames }))
export const removeMember = (id: number, userId: number) => api.delete(`/workspaces/${id}/members/${userId}`)

// ---- Bảng & cột ----
export const createBoard = (workspaceId: number, name: string) =>
  data(api.post<BoardBrief>(`/workspaces/${workspaceId}/boards`, { name }))
export const getBoard = (id: number) => data(api.get<BoardDetail>(`/boards/${id}`))
export const renameBoard = (id: number, name: string) => data(api.patch<BoardBrief>(`/boards/${id}`, { name }))
export const deleteBoard = (id: number) => api.delete(`/boards/${id}`)
export const createColumn = (boardId: number, name: string) =>
  data(api.post<Column>(`/boards/${boardId}/columns`, { name }))
export const updateColumn = (id: number, body: { name?: string; is_done?: boolean }) =>
  data(api.patch<Column>(`/columns/${id}`, body))
export const deleteColumn = (id: number) => api.delete(`/columns/${id}`)

// ---- Công việc ----
export type TaskInput = {
  title?: string
  description?: string | null
  assignee_id?: number | null
  /** F20: giao theo tên chữ khi người đó chưa có tài khoản */
  assignee_name?: string | null
  due_date?: string | null
  priority?: Priority
}
export const createTask = (boardId: number, body: TaskInput & { column_id: number; title: string }) =>
  data(api.post<Task>(`/boards/${boardId}/tasks`, body))
export const getTask = (id: number) => data(api.get<TaskDetail>(`/tasks/${id}`))
export const updateTask = (id: number, body: TaskInput) => data(api.patch<TaskDetail>(`/tasks/${id}`, body))
export const moveTask = (id: number, column_id: number, index: number) =>
  data(api.post<Task>(`/tasks/${id}/move`, { column_id, index }))
export const deleteTask = (id: number) => api.delete(`/tasks/${id}`)
export const addComment = (taskId: number, content: string) =>
  data(api.post<Comment>(`/tasks/${taskId}/comments`, { content }))
export const deleteComment = (id: number) => api.delete(`/comments/${id}`)
export const myTasks = (includeDone = false) =>
  data(api.get<MyTask[]>('/me/tasks', { params: { include_done: includeDone } }))

// ---- Thông báo ----
export const listNotifications = () => data(api.get<NotificationList>('/notifications'))
export const markNotificationRead = (id: number) => data(api.post<Notification>(`/notifications/${id}/read`))
export const markAllRead = () => api.post('/notifications/read-all')

// ---- Cuộc họp ----
export const listMeetings = (workspaceId: number) =>
  data(api.get<Meeting[]>(`/workspaces/${workspaceId}/meetings`))
export const createMeeting = (
  workspaceId: number,
  form: { title: string; meeting_date: string; file?: File | null; text?: string; recorded?: boolean },
  onUploadProgress?: (pct: number) => void,
) => {
  const fd = new FormData()
  fd.append('title', form.title)
  fd.append('meeting_date', form.meeting_date)
  if (form.file) fd.append('file', form.file)
  if (form.text) fd.append('text', form.text)
  if (form.recorded) fd.append('recorded', 'true')
  return data(
    api.post<MeetingDetail>(`/workspaces/${workspaceId}/meetings`, fd, {
      onUploadProgress: (e) => e.total && onUploadProgress?.(Math.round((e.loaded / e.total) * 100)),
    }),
  )
}
export const getMeeting = (id: number) => data(api.get<MeetingDetail>(`/meetings/${id}`))
export const updateMeeting = (id: number, body: { title?: string; meeting_date?: string }) =>
  data(api.patch<MeetingDetail>(`/meetings/${id}`, body))
export const deleteMeeting = (id: number) => api.delete(`/meetings/${id}`)
export const retryMeeting = (id: number) => data(api.post<MeetingDetail>(`/meetings/${id}/retry`))
/** Nhờ AI tóm tắt + tách đầu việc. Trả về ngay (status = summarizing), worker xử lý nền. */
export const summarizeMeeting = (id: number) => data(api.post<MeetingDetail>(`/meetings/${id}/summarize`))
// ---- Giai đoạn 5: duyệt + đẩy lên bảng (F17) ----
export const updateDraft = (id: number, body: DraftInput) =>
  data(api.patch<MeetingDetail>(`/extracted-tasks/${id}`, body))
export const pushToBoard = (meetingId: number, boardId: number) =>
  data(api.post<MeetingDetail>(`/meetings/${meetingId}/push`, { board_id: boardId }))

// ---- F21: tự nhận tên ----
export const listPendingNames = (workspaceId: number) =>
  data(api.get<PendingName[]>(`/workspaces/${workspaceId}/pending-names`))
export const claimName = (workspaceId: number, key: string) =>
  data(api.post<NameClaim>(`/workspaces/${workspaceId}/pending-names/claim`, { key }))
export const undoClaim = (claimId: number) => data(api.post<NameClaim>(`/name-claims/${claimId}/undo`))
export const updateTranscript = (id: number, segments: Segment[]) =>
  data(api.put<MeetingDetail>(`/meetings/${id}/transcript`, { segments }))
/** Online Meeting: đưa ghi âm đến muộn của một người vào bản ghi (khi bản ghi đã sửa tay / đã tóm tắt). */
export const mergeLateTrack = (meetingId: number, trackId: number) =>
  data(api.post<MeetingDetail>(`/meetings/${meetingId}/tracks/${trackId}/merge`))

// ---- Giai đoạn 6: phòng họp trực tuyến "Online Meeting" ----
/** Phòng đang mở của nhóm (null = chưa có). */
export const getOpenRoom = (workspaceId: number) => data(api.get<Room | null>(`/workspaces/${workspaceId}/room`))
/** Mở phòng. Nhóm đang có phòng mở thì trả về chính phòng đó. */
export const openRoom = (workspaceId: number) => data(api.post<Room>(`/workspaces/${workspaceId}/room`, {}))
export const getRoom = (code: string) => data(api.get<Room>(`/rooms/${code}`))
/** Lấy vé vào phòng (chưa ở trong nhóm thì được tự thêm vào nhóm). */
export const joinRoom = (code: string) => data(api.post<RoomJoin>(`/rooms/${code}/join`))
export const startRoomRecording = (code: string) => data(api.post<Room>(`/rooms/${code}/recording/start`))
export const stopRoomRecording = (code: string) => data(api.post<Room>(`/rooms/${code}/recording/stop`))
/** "Chỉ mình tôi rời". Chủ phòng rời thì quyền chuyển cho người vào sớm nhất còn lại; không còn ai thì phòng kết thúc. */
export const leaveRoom = (code: string) => data(api.post<{ room: Room; meeting_id: number | null }>(`/rooms/${code}/leave`))
export const endRoom = (code: string) => data(api.post<{ room: Room; meeting_id: number | null }>(`/rooms/${code}/end`))
// Ghi âm của từng người: mở track → gửi từng khúc → báo xong
export const createRoomTrack = (code: string, body: { mime: string; elapsed_ms: number }) =>
  data(api.post<{ track_id: number; next_seq: number }>(`/rooms/${code}/tracks`, body))
export const uploadTrackChunk = (trackId: number, seq: number, chunk: Blob) =>
  data(
    api.put<{ track_id: number; next_seq: number }>(`/room-tracks/${trackId}/chunks/${seq}`, chunk, {
      headers: { 'Content-Type': 'application/octet-stream' },
      timeout: 30000,
    }),
  )
export const finishRoomTrack = (trackId: number) => data(api.post(`/room-tracks/${trackId}/finish`))

/** Thẻ <audio> không gửi được header → xin "vé" chỉ nghe được file này (hết hạn sau 12 giờ),
 * trả về link đã kèm vé. Không đặt token đăng nhập lên link (link bị ghi vào log server). */
export const getMeetingAudioUrl = (id: number) =>
  data(api.get<{ url: string }>(`/meetings/${id}/audio-ticket`)).then((r) => r.url)
