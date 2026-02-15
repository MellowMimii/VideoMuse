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
