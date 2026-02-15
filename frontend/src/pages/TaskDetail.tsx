import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { getTask, getTaskReport, type Task, type Report } from "../api/client";

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    if (!id) return;
    const taskId = Number(id);

    const poll = async () => {
      try {
        const { data } = await getTask(taskId);
        setTask(data);
        if (data.status === "done") {
          const { data: r } = await getTaskReport(taskId);
          setReport(r);
        }
      } catch (err) {
        console.error("Failed to fetch task:", err);
      }
    };

    poll();
    const timer = setInterval(poll, 3000);
    return () => clearInterval(timer);
  }, [id]);

  if (!task) return <div style={{ padding: 40, textAlign: "center" }}>加载中...</div>;

  const statusLabel: Record<string, string> = {
    pending: "等待中",
    running: "分析中",
    done: "已完成",
    failed: "失败",
    cancelled: "已取消",
  };

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "40px 20px" }}>
      <h2>任务：{task.query}</h2>
      <p>
        状态：<strong>{statusLabel[task.status] ?? task.status}</strong>
        {task.status === "running" && ` (${Math.round(task.progress)}%)`}
      </p>

      {task.status === "running" && (
        <div style={{ background: "#f0f0f0", borderRadius: 8, overflow: "hidden", height: 8, marginBottom: 24 }}>
          <div
            style={{
              width: `${task.progress}%`,
              height: "100%",
              background: "#1677ff",
              transition: "width 0.3s",
            }}
          />
        </div>
      )}

      {task.status === "failed" && (
        <p style={{ color: "red" }}>错误信息：{task.error_message}</p>
      )}

      {report && (
        <div style={{ marginTop: 24, lineHeight: 1.8 }}>
          <ReactMarkdown>{report.content_markdown}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
