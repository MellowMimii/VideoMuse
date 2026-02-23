import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listTasks, deleteTask, type Task } from "../api/client";

const statusLabel: Record<string, string> = {
  pending: "等待中",
  running: "分析中",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const statusClass: Record<string, string> = {
  pending: "status-pending",
  running: "status-running",
  done: "status-done",
  failed: "status-failed",
  cancelled: "status-failed",
};

function formatTime(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function History() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchTasks = async () => {
    try {
      const { data } = await listTasks(0, 50);
      setTasks(data.tasks);
      setTotal(data.total);
    } catch (err) {
      console.error("Failed to fetch tasks:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
  }, []);

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm("确定要删除这个任务吗？")) return;
    try {
      await deleteTask(id);
      setTasks((prev) => prev.filter((t) => t.id !== id));
      setTotal((prev) => prev - 1);
    } catch (err) {
      console.error("Failed to delete task:", err);
    }
  };

  if (loading) {
    return (
      <div className="page-container">
        <div className="empty-state">
          <div className="spinner" />
        </div>
      </div>
    );
  }

  return (
    <div className="page-container">
      <div className="section-header">
        <h2>历史任务</h2>
        <span style={{ color: "#888", fontSize: 14 }}>共 {total} 个任务</span>
      </div>

      {tasks.length === 0 ? (
        <div className="empty-state">
          <h3>暂无任务</h3>
          <p>
            <Link to="/">去创建第一个分析任务</Link>
          </p>
        </div>
      ) : (
        <div className="task-list">
          {tasks.map((task) => (
            <Link to={`/tasks/${task.id}`} key={task.id} className="card task-item">
              <div className="task-item-left">
                <h3>{task.query}</h3>
                <span className="meta">
                  {task.platform} &middot; {task.max_videos} 个视频 &middot;{" "}
                  {formatTime(task.created_at)}
                </span>
              </div>
              <div className="task-item-right">
                <span className={`status-badge ${statusClass[task.status] || ""}`}>
                  {statusLabel[task.status] ?? task.status}
                </span>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={(e) => handleDelete(task.id, e)}
                  title="删除"
                >
                  删除
                </button>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
