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
