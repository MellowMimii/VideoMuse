import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getTask,
  getTaskReport,
  getTaskVideos,
  getTaskEvents,
  retryTask,
  cancelTask,
  type Task,
  type Report,
  type Video,
  type AgentEvent,
} from "../api/client";

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

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const TERMINAL_STATES = ["done", "failed", "cancelled"];

const TOOL_LABELS: Record<string, string> = {
  search_videos: "搜索视频",
  extract_subtitle: "提取字幕",
  summarize_video: "视频摘要",
  generate_report: "生成报告",
};

function formatToolArgs(toolName: string | null, argsJson: string | null): string {
  if (!argsJson) return "";
  try {
    const args = JSON.parse(argsJson);
    if (toolName === "search_videos") return ` "${args.query}"`;
    if (toolName === "extract_subtitle") return ` ${args.video_id}`;
    if (toolName === "summarize_video") return ` ${args.video_id}`;
    if (toolName === "generate_report") return ` "${args.title}"`;
    return "";
  } catch {
    return "";
  }
}

// ── Phase detection & stats from events ────────────────────────────

const PHASES = [
  { key: "search_videos", label: "搜索视频", activeText: "正在搜索相关视频..." },
  { key: "extract_subtitle", label: "提取字幕", activeText: "正在提取视频字幕..." },
  { key: "summarize_video", label: "生成摘要", activeText: "正在生成视频摘要..." },
  { key: "generate_report", label: "生成报告", activeText: "正在生成综合报告..." },
];

function getPhaseFromEvents(events: AgentEvent[]): number {
  let phase = -1; // -1 = not started
  for (const evt of events) {
    if (evt.event_type !== "tool_call" && evt.event_type !== "tool_result") continue;
    const name = evt.tool_name || "";
    if (name === "generate_report" && phase < 3) phase = 3;
    else if (name === "summarize_video" && phase < 2) phase = 2;
    else if (name === "extract_subtitle" && phase < 1) phase = 1;
    else if (name === "search_videos" && phase < 0) phase = 0;
  }
  return phase;
}

function getStatsFromEvents(events: AgentEvent[]): {
  searched: number;
  extracted: number;
  summarized: number;
} {
  let searched = 0;
  let extracted = 0;
  let summarized = 0;
  for (const evt of events) {
    if (evt.event_type !== "tool_result") continue;
    const name = evt.tool_name || "";
    const content = evt.content || "";
    if (name === "search_videos" && content.includes("找到")) {
      const m = content.match(/找到\s*(\d+)\s*个/);
      if (m) searched += parseInt(m[1], 10);
    } else if (name === "extract_subtitle" && content.includes("成功")) {
      extracted++;
    } else if (name === "summarize_video" && content.includes("完成")) {
      summarized++;
    }
  }
  return { searched, extracted, summarized };
}

// ── Sub-components ──────────────────────────────────────────────────

function StepIndicator({ currentPhase }: { currentPhase: number }) {
  return (
    <div className="step-indicator">
      {PHASES.map((phase, i) => {
        let status: "done" | "active" | "pending";
        if (i < currentPhase) status = "done";
        else if (i === currentPhase) status = "active";
        else status = "pending";

        return (
          <div key={phase.key} className="step-indicator-item">
            {i > 0 && <div className={`step-line step-line-${i <= currentPhase ? "done" : "pending"}`} />}
            <div className={`step-circle step-circle-${status}`}>
              {status === "done" ? (
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M2.5 6L5 8.5L9.5 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <span className="step-number">{i + 1}</span>
              )}
            </div>
            <span className={`step-label step-label-${status}`}>{phase.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function StatsBar({ stats }: { stats: { searched: number; extracted: number; summarized: number } }) {
  if (stats.searched === 0 && stats.extracted === 0 && stats.summarized === 0) {
    return null;
  }
  return (
    <div className="stats-bar">
      <div className="stats-item">
        <span className="stats-number">{stats.searched}</span>
        <span className="stats-label">个视频已搜索</span>
      </div>
      <div className="stats-divider" />
      <div className="stats-item">
        <span className="stats-number">{stats.extracted}</span>
        <span className="stats-label">个字幕已提取</span>
      </div>
      <div className="stats-divider" />
      <div className="stats-item">
        <span className="stats-number">{stats.summarized}</span>
        <span className="stats-label">个摘要已生成</span>
      </div>
    </div>
  );
}

function AgentActivityFeed({
  events,
  progress,
  cancelling,
  onCancel,
}: {
  events: AgentEvent[];
  progress: number;
  cancelling: boolean;
  onCancel: () => void;
}) {
  const feedEndRef = useRef<HTMLDivElement>(null);

  const currentPhase = useMemo(() => getPhaseFromEvents(events), [events]);
  const stats = useMemo(() => getStatsFromEvents(events), [events]);
  const filteredEvents = useMemo(
    () => events.filter((e) => e.event_type !== "tool_result"),
    [events]
  );

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [filteredEvents.length]);

  const phaseText = currentPhase >= 0 ? PHASES[currentPhase].activeText : "AI Agent 正在启动...";

  return (
    <div className="agent-feed-card">
      {/* Step indicator */}
      <StepIndicator currentPhase={currentPhase} />

      {/* Progress bar */}
      <div className="progress-bar">
        <div
          className="progress-bar-fill"
          style={{ width: `${Math.max(progress, 3)}%` }}
        />
      </div>

      {/* Stats */}
      <StatsBar stats={stats} />

      {/* Event timeline */}
      <div className="agent-feed-list">
        {filteredEvents.map((evt) => (
          <div
            key={evt.id}
            className={`agent-event agent-event-${evt.event_type}`}
          >
            <div className="agent-event-icon">
              {evt.event_type === "thinking" && <span className="icon-thinking" />}
              {evt.event_type === "tool_call" && <span className="icon-tool" />}
              {evt.event_type === "error" && <span className="icon-error" />}
              {evt.event_type === "complete" && <span className="icon-complete" />}
            </div>
            <div className="agent-event-body">
              {evt.event_type === "thinking" && (
                <p className="agent-thinking">{evt.content}</p>
              )}
              {evt.event_type === "tool_call" && (
                <p className="agent-tool-call">
                  {">> "}
                  <strong>{TOOL_LABELS[evt.tool_name || ""] || evt.tool_name}</strong>
                  <span className="tool-args">
                    {formatToolArgs(evt.tool_name, evt.tool_args_json)}
                  </span>
                </p>
              )}
              {evt.event_type === "error" && (
                <p className="agent-error">{evt.content}</p>
              )}
              {evt.event_type === "complete" && (
                <p className="agent-complete">{evt.content}</p>
              )}
            </div>
          </div>
        ))}
        {events.length === 0 && (
          <div className="agent-waiting">
            <div className="typing-dots">
              <span /><span /><span />
            </div>
            <p>AI Agent 正在启动，即将开始分析...</p>
          </div>
        )}
        <div ref={feedEndRef} />
      </div>

      {/* Info row */}
      <div className="pipeline-info">
        <div className="pipeline-status-text">
          <div className="spinner" />
          <span>{phaseText}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span className="pipeline-percent">{Math.round(progress)}%</span>
          <button
            className="btn btn-outline btn-sm"
            onClick={onCancel}
            disabled={cancelling}
          >
            {cancelling ? "取消中..." : "取消"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const lastEventIdRef = useRef(0);
  const [retrying, setRetrying] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [toast, setToast] = useState("");
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 2500);
  };

  const fetchData = useCallback(async () => {
    if (!id) return;
    const taskId = Number(id);
    try {
      const { data } = await getTask(taskId);
      setTask(data);

      // Fetch new agent events incrementally
      if (
        data.status === "running" ||
        data.status === "pending" ||
        data.status === "done"
      ) {
        try {
          const eventsRes = await getTaskEvents(taskId, lastEventIdRef.current);
          if (eventsRes.data.length > 0) {
            setEvents((prev) => [...prev, ...eventsRes.data]);
            lastEventIdRef.current =
              eventsRes.data[eventsRes.data.length - 1].id;
          }
        } catch {
          // Events endpoint may not be available yet
        }
      }

      if (data.status === "done") {
        const [reportRes, videosRes] = await Promise.all([
          getTaskReport(taskId),
          getTaskVideos(taskId),
        ]);
        setReport(reportRes.data);
        setVideos(videosRes.data);
      }

      // Stop polling on terminal state
      if (TERMINAL_STATES.includes(data.status) && timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    } catch (err) {
      console.error("Failed to fetch task:", err);
    }
  }, [id]);

  useEffect(() => {
    fetchData();
    timerRef.current = setInterval(fetchData, 3000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchData]);

  const handleRetry = async () => {
    if (!task) return;
    setRetrying(true);
    try {
      const { data } = await retryTask(task.id);
      setTask(data);
      setReport(null);
      setVideos([]);
      setEvents([]);
      lastEventIdRef.current = 0;
      // Restart polling
      if (!timerRef.current) {
        timerRef.current = setInterval(fetchData, 3000);
      }
    } catch (err) {
      console.error("Failed to retry task:", err);
      showToast("重试失败，请稍后再试");
    } finally {
      setRetrying(false);
    }
  };

  const handleCancel = async () => {
    if (!task) return;
    setCancelling(true);
    try {
      const { data } = await cancelTask(task.id);
      setTask(data);
      showToast("正在取消任务...");
    } catch (err) {
      console.error("Failed to cancel task:", err);
      showToast("取消失败");
    } finally {
      setCancelling(false);
    }
  };

  const handleCopy = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report.content_markdown);
      showToast("已复制到剪贴板");
    } catch {
      showToast("复制失败");
    }
  };

  const handleDownload = () => {
    if (!report || !task) return;
    const blob = new Blob([report.content_markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${task.query}-报告.md`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("开始下载");
  };

  if (!task) {
    return (
      <div className="page-container">
        <div className="empty-state">
          <div className="spinner" />
          <p style={{ marginTop: 12 }}>加载中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container">
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <Link to="/history" style={{ fontSize: 14, color: "#888" }}>
          &larr; 返回任务列表
        </Link>
        <h2 style={{ marginTop: 8, fontSize: 24 }}>{task.query}</h2>
        <div
          style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}
        >
          <span className={`status-badge ${statusClass[task.status] || ""}`}>
            {statusLabel[task.status] ?? task.status}
          </span>
          <span style={{ color: "#888", fontSize: 14 }}>
            {task.platform} &middot; {task.max_videos} 个视频
          </span>
        </div>
      </div>

      {/* Agent Activity Feed */}
      {(task.status === "running" || task.status === "pending") && (
        <AgentActivityFeed
          events={events}
          progress={task.progress}
          cancelling={cancelling}
          onCancel={handleCancel}
        />
      )}

      {/* Error */}
      {(task.status === "failed" || task.status === "cancelled") && (
        <div className="error-box" style={{ marginBottom: 24 }}>
          <p style={{ fontWeight: 600, marginBottom: 8 }}>
            {task.status === "cancelled" ? "任务已取消" : "任务失败"}
          </p>
          {task.error_message && (
            <p style={{ fontSize: 14 }}>{task.error_message}</p>
          )}
          <button
            className="btn btn-primary btn-sm"
            style={{ marginTop: 12 }}
            onClick={handleRetry}
            disabled={retrying}
          >
            {retrying ? "重试中..." : "重新分析"}
          </button>
        </div>
      )}

      {/* Report */}
      {report && (
        <div className="report-section">
          <div className="report-actions">
            <button className="btn btn-outline btn-sm" onClick={handleCopy}>
              复制报告
            </button>
            <button className="btn btn-outline btn-sm" onClick={handleDownload}>
              下载 Markdown
            </button>
          </div>
          <div className="report-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {report.content_markdown}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* Video Cards */}
      {videos.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <div className="section-header">
            <h2>分析的视频 ({videos.length})</h2>
          </div>
          <div className="video-grid">
            {videos.map((video) => (
              <a
                key={video.id}
                href={video.url}
                target="_blank"
                rel="noopener noreferrer"
                className="card video-card"
                style={{ textDecoration: "none", color: "inherit" }}
              >
                {video.cover_url && (
                  <img
                    src={video.cover_url}
                    alt={video.title}
                    loading="lazy"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none";
                    }}
                  />
                )}
                <div className="video-card-body">
                  <h4>{video.title}</h4>
                  <p className="author">
                    {video.author} &middot; {formatDuration(video.duration)}
                  </p>
                  {video.summary && <p className="summary">{video.summary}</p>}
                </div>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Agent Event Log (collapsed, shown after completion) */}
      {TERMINAL_STATES.includes(task.status) && events.length > 0 && (
        <details style={{ marginTop: 32 }}>
          <summary
            style={{
              cursor: "pointer",
              fontSize: 14,
              color: "#888",
              marginBottom: 12,
            }}
          >
            查看 Agent 分析过程 ({events.length} 个步骤)
          </summary>
          <div
            className="agent-feed-card"
            style={{ maxHeight: 400, overflowY: "auto" }}
          >
            <div className="agent-feed-list" style={{ maxHeight: "none" }}>
              {events.map((evt) => (
                <div
                  key={evt.id}
                  className={`agent-event agent-event-${evt.event_type}`}
                >
                  <div className="agent-event-icon">
                    {evt.event_type === "thinking" && (
                      <span className="icon-thinking" />
                    )}
                    {evt.event_type === "tool_call" && (
                      <span className="icon-tool" />
                    )}
                    {evt.event_type === "tool_result" && (
                      <span className="icon-result" />
                    )}
                    {evt.event_type === "error" && (
                      <span className="icon-error" />
                    )}
                    {evt.event_type === "complete" && (
                      <span className="icon-complete" />
                    )}
                  </div>
                  <div className="agent-event-body">
                    {evt.event_type === "thinking" && (
                      <p className="agent-thinking">{evt.content}</p>
                    )}
                    {evt.event_type === "tool_call" && (
                      <p className="agent-tool-call">
                        {">> "}
                        <strong>
                          {TOOL_LABELS[evt.tool_name || ""] || evt.tool_name}
                        </strong>
                        <span className="tool-args">
                          {formatToolArgs(evt.tool_name, evt.tool_args_json)}
                        </span>
                      </p>
                    )}
                    {evt.event_type === "tool_result" && (
                      <p className="agent-tool-result">{evt.content}</p>
                    )}
                    {evt.event_type === "error" && (
                      <p className="agent-error">{evt.content}</p>
                    )}
                    {evt.event_type === "complete" && (
                      <p className="agent-complete">{evt.content}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </details>
      )}

      {/* Toast */}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
