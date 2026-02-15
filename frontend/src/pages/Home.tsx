import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createTask } from "../api/client";

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    try {
      const { data } = await createTask({ query: query.trim() });
      navigate(`/tasks/${data.id}`);
    } catch (err) {
      console.error("Failed to create task:", err);
      alert("创建任务失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: "60px 20px", textAlign: "center" }}>
      <h1 style={{ fontSize: 48, marginBottom: 8 }}>VideoMuse</h1>
      <p style={{ color: "#666", marginBottom: 40 }}>
        输入你感兴趣的话题，AI 自动分析多个视频并生成结构化报告
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", gap: 12, justifyContent: "center" }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="例如：拉萨旅游攻略"
          style={{
            flex: 1,
            maxWidth: 500,
            padding: "12px 16px",
            fontSize: 16,
            border: "1px solid #ddd",
            borderRadius: 8,
          }}
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          style={{
            padding: "12px 24px",
            fontSize: 16,
            background: loading ? "#ccc" : "#1677ff",
            color: "#fff",
            border: "none",
            borderRadius: 8,
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "提交中..." : "开始分析"}
        </button>
      </form>
    </div>
  );
}
