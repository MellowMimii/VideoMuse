import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createTask } from "../api/client";

export default function Home() {
  const [query, setQuery] = useState("");
  const [maxVideos, setMaxVideos] = useState(10);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async () => {
    if (!query.trim() || loading) return;

    setLoading(true);
    try {
      const { data } = await createTask({
        query: query.trim(),
        platform: "bilibili",
        max_videos: maxVideos,
      });
      navigate(`/tasks/${data.id}`);
    } catch (err) {
      console.error("Failed to create task:", err);
      alert("创建任务失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSubmit();
  };

  return (
    <div className="home-hero">
      <h1>VideoMuse</h1>
      <p className="subtitle">
        输入你感兴趣的话题，AI 自动分析多个视频并生成结构化报告
      </p>

      <div className="search-form">
        <input
          type="text"
          className="input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="例如：拉萨旅游攻略、Python 入门教程"
        />
        <button
          type="button"
          disabled={loading || !query.trim()}
          className="btn btn-primary"
          style={{ padding: "10px 28px", fontSize: 15 }}
          onClick={handleSubmit}
        >
          {loading ? (
            <>
              <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
              提交中...
            </>
          ) : (
            "开始分析"
          )}
        </button>
      </div>

      <div className="search-options">
        <label>
          分析视频数：
          <select
            className="select"
            value={maxVideos}
            onChange={(e) => setMaxVideos(Number(e.target.value))}
            style={{ marginLeft: 4 }}
          >
            <option value={5}>5 个</option>
            <option value={10}>10 个</option>
            <option value={20}>20 个</option>
          </select>
        </label>
        <span>平台：Bilibili</span>
      </div>
    </div>
  );
}
