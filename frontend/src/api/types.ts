// Kiểu dữ liệu khớp với schema (Pydantic) ở backend

export type User = {
  id: number
  email: string
  full_name: string
  avatar_url: string | null
}

export type TokenResponse = { access_token: string; token_type: string; user: User }

export type Priority = 'low' | 'medium' | 'high'

export type Member = {
  user: User
  role: 'owner' | 'member'
  nicknames: string[]
  joined_at: string
}

export type BoardBrief = { id: number; name: string }

export type WorkspaceSummary = {
  id: number
  name: string
  my_role: 'owner' | 'member'
  member_count: number
  board_count: number
}

export type WorkspaceDetail = {
  id: number
  name: string
  owner_id: number
  invite_code: string
  my_role: 'owner' | 'member'
  members: Member[]
  boards: BoardBrief[]
}

export type Task = {
  id: number
  board_id: number
  column_id: number
  title: string
  description: string | null
  assignee: User | null
  due_date: string | null // "YYYY-MM-DD"
  priority: Priority
  position: number
  created_by: number | null
  created_at: string
  updated_at: string
  comment_count: number
}

export type Column = {
  id: number
  name: string
  position: number
  is_done: boolean
  tasks: Task[]
}

export type BoardDetail = {
  id: number
  workspace_id: number
  workspace_name: string
  name: string
  columns: Column[]
  members: User[]
}

export type Comment = {
  id: number
  task_id: number
  user: User
  content: string
  created_at: string
}

export type TaskDetail = Task & { comments: Comment[]; column_name: string }

export type MyTask = Task & {
  board_name: string
  workspace_id: number
  workspace_name: string
  column_name: string
  is_done: boolean
}

export type Notification = {
  id: number
  type: 'task_assigned' | 'task_due_soon' | 'task_overdue'
  payload: {
    task_id: number
    task_title: string
    board_id: number
    board_name: string
    workspace_id: number
    actor_name?: string
    due_date?: string | null
  }
  is_read: boolean
  created_at: string
}

export type NotificationList = { unread_count: number; items: Notification[] }

// ---- Cuộc họp (Giai đoạn 3) ----
export type MeetingStatus = 'uploaded' | 'queued' | 'transcribing' | 'transcribed' | 'summarizing' | 'review' | 'failed'

export type Segment = { start: number | null; end: number | null; text: string }

export type Transcript = {
  full_text: string
  segments: Segment[]
  language: string | null
  stt_model: string | null
  duration_sec: number | null
  processing_sec: number | null
  edited: boolean
  updated_at: string
}

export type Meeting = {
  id: number
  workspace_id: number
  title: string
  meeting_date: string
  source_type: 'audio' | 'recording' | 'text'
  status: MeetingStatus
  progress: number
  error: string | null
  /** Thông báo phụ trong lúc xử lý, vd. "Mô hình … quá tải, đã chuyển sang mô hình dự phòng…" */
  status_note: string | null
  audio_filename: string | null
  audio_size: number | null
  created_by: number | null
  created_at: string
  duration_sec: number | null
}

// ---- Tóm tắt & đầu việc do AI trích xuất (Giai đoạn 4) ----
export type MeetingSummary = {
  topic: string
  key_points: string[]
  decisions: string[]
  open_issues: string[]
  /** Mô hình THỰC SỰ đã viết biên bản */
  llm_model: string | null
  /** Mô hình chính bị bỏ qua vì quá tải / hết hạn mức → biên bản do mô hình dự phòng viết. null = bình thường */
  fallback_from: string | null
  chunk_count: number
  processing_sec: number | null
  created_at: string
  /** Bản ghi đã bị sửa sau khi tóm tắt → biên bản có thể không còn khớp */
  stale: boolean
}

/** Kết quả ghép tên: khớp hẳn / khớp khi bỏ dấu / gần giống / trùng nhiều người / người nói tự nhận / cả nhóm / không khớp */
export type AssigneeMatch = 'exact' | 'no_accent' | 'fuzzy' | 'ambiguous' | 'self' | 'group' | 'none'

export type ExtractedTask = {
  id: number
  position: number
  title: string
  raw_assignee: string | null
  assignee: User | null
  assignee_match: AssigneeMatch
  assignee_score: number
  assignee_candidates: number[]
  due_text: string | null
  due_date: string | null
  due_approximate: boolean
  priority: Priority
  evidence_quote: string
  evidence_found: boolean
  evidence_segment: number | null
  evidence_start: number | null
  status: 'pending' | 'accepted' | 'rejected'
}

export type MeetingDetail = Meeting & {
  has_audio: boolean
  transcript: Transcript | null
  summary: MeetingSummary | null
  extracted_tasks: ExtractedTask[]
}
