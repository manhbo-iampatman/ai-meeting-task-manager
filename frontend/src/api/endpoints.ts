// Tất cả lời gọi API gom về 1 chỗ: component chỉ gọi hàm, không cần nhớ URL.
import { api } from './client'
import type {
  BoardBrief,
  BoardDetail,
  Column,
  Comment,
  Member,
  MyTask,
  Notification,
  NotificationList,
  Priority,
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
