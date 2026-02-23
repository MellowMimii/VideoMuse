import axios from "axios";

const api = axios.create({
  baseURL: "/api",
});

export interface TaskCreate {
  query: string;
  platform?: string;
  max_videos?: number;
}

export interface Task {
  id: number;
  query: string;
  platform: string;
  max_videos: number;
  status: string;
  progress: number;
  error_message: string | null;
  completed_step: string | null;
  created_at: string;
  updated_at: string;
}

export interface Video {
  id: number;
  platform: string;
  video_id: string;
  title: string;
  author: string;
  url: string;
  duration: number;
  cover_url: string;
  summary: string | null;
}

export interface Report {
  id: number;
  task_id: number;
  content_markdown: string;
  created_at: string;
}

export interface AgentEvent {
  id: number;
  event_type: "thinking" | "tool_call" | "tool_result" | "error" | "complete";
  content: string;
  tool_name: string | null;
  tool_args_json: string | null;
  tool_result_preview: string | null;
  timestamp: number;
}

export const createTask = (data: TaskCreate) =>
  api.post<Task>("/tasks", data);

export const getTask = (id: number) =>
  api.get<Task>(`/tasks/${id}`);

export const getTaskVideos = (id: number) =>
  api.get<Video[]>(`/tasks/${id}/videos`);

export const getTaskReport = (id: number) =>
  api.get<Report>(`/tasks/${id}/report`);

export const listTasks = (skip = 0, limit = 20) =>
  api.get<{ tasks: Task[]; total: number }>("/tasks", { params: { skip, limit } });

export const deleteTask = (id: number) =>
  api.delete(`/tasks/${id}`);

export const retryTask = (id: number) =>
  api.post<Task>(`/tasks/${id}/retry`);

export const cancelTask = (id: number) =>
  api.post<Task>(`/tasks/${id}/cancel`);

export const getTaskEvents = (id: number, sinceId = 0) =>
  api.get<AgentEvent[]>(`/tasks/${id}/events`, { params: { since_id: sinceId } });
