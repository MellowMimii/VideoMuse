"""Agent tools — LangChain tool definitions wrapping platform adapters and LLM calls."""

from __future__ import annotations

import asyncio
import logging

from langchain_core.tools import tool

from app.agent.context import AgentContext
from app.llm import get_llm_provider
from app.llm.prompts import MULTI_VIDEO_CONSOLIDATION, SINGLE_VIDEO_SUMMARY
from app.platforms import PlatformRegistry

logger = logging.getLogger(__name__)

EXTRACT_DELAY = 1.5

# ── Module-level context (set before each agent run) ────────────────────

_ctx: AgentContext | None = None


def set_context(ctx: AgentContext) -> None:
    global _ctx
    _ctx = ctx


def get_context() -> AgentContext:
    if _ctx is None:
        raise RuntimeError("AgentContext not set — call set_context() first")
    return _ctx


# ── LangChain tools ─────────────────────────────────────────────────────


@tool
async def search_videos(query: str) -> str:
    """在视频平台搜索视频，返回最多10个相关视频。输入搜索关键词。"""
    query = query.strip()
    ctx = get_context()
    adapter = PlatformRegistry.get(ctx.platform)

    videos = await adapter.search_videos(query, 10)
    if not videos:
        return f'搜索 "{query}" 未找到任何视频。请尝试其他关键词。'

    for vi in videos:
        if vi.video_id not in ctx.video_data:
            ctx.video_data[vi.video_id] = {"info": vi}
    ctx.search_results.extend(videos)

    lines = [f'搜索 "{query}" 找到 {len(videos)} 个视频：\n']
    for i, v in enumerate(videos, 1):
        dur_min = v.duration // 60
        dur_sec = v.duration % 60
        lines.append(
            f"{i}. [{v.video_id}] {v.title}\n"
            f"   作者: {v.author} | 时长: {dur_min}分{dur_sec}秒 | {v.url}"
        )
    return "\n".join(lines)


@tool
async def extract_subtitle(video_id: str) -> str:
    """提取指定视频的字幕文本。输入视频ID（如B站BV号），需先通过search_videos获取。"""
    video_id = video_id.strip()
    ctx = get_context()

    if video_id in ctx.video_data and ctx.video_data[video_id].get("transcript"):
        t = ctx.video_data[video_id]["transcript"]
        return f"视频 {video_id} 的字幕已经提取过了。字幕长度: {len(t)} 字符。"

    adapter = PlatformRegistry.get(ctx.platform)
    await asyncio.sleep(EXTRACT_DELAY)

    text = await adapter.get_subtitles(video_id)
    if not text:
        return (
            f"视频 {video_id} 无法提取字幕（可能无字幕或平台限制）。"
            "请尝试其他视频。"
        )

    if video_id not in ctx.video_data:
        info = ctx.get_video_info(video_id)
        ctx.video_data[video_id] = {"info": info}

    ctx.video_data[video_id]["transcript"] = text

    preview = text[:15000]
    truncated = "（已截断）" if len(text) > 15000 else ""

    return (
        f"成功提取字幕，共 {len(text)} 字符{truncated}。\n\n"
        f"字幕内容：\n{preview}"
    )


@tool
async def summarize_video(video_id: str) -> str:
    """为已提取字幕的视频生成结构化摘要。输入视频ID，必须已用extract_subtitle提取字幕。"""
    video_id = video_id.strip()
    ctx = get_context()
    data = ctx.video_data.get(video_id)
    if not data or not data.get("transcript"):
        return (
            f"错误：视频 {video_id} 尚未提取字幕，"
            "请先调用 extract_subtitle。"
        )

    if data.get("summary"):
        return f'视频 {video_id} 已有摘要：\n{data["summary"][:500]}...'

    llm = get_llm_provider()
    info = data.get("info")
    transcript = data["transcript"][:20000]

    title = info.title if info else video_id
    author = info.author if info else "未知"
    duration = info.duration if info else 0
    dur_str = f"{duration // 60}分{duration % 60}秒"

    prompt = SINGLE_VIDEO_SUMMARY.format(
        title=title,
        author=author,
        duration=dur_str,
        transcript=transcript,
    )
    messages = [
        {"role": "system", "content": "你是一个专业的视频内容分析师。"},
        {"role": "user", "content": prompt},
    ]
    summary = await llm.chat(messages, temperature=0.3)

    ctx.video_data[video_id]["summary"] = summary
    return f'视频 "{title}" 摘要生成完成：\n\n{summary}'


@tool
async def generate_report(title: str) -> str:
    """生成最终综合分析报告。在收集足够视频摘要后调用。输入报告标题。"""
    title = title.strip()
    ctx = get_context()
    return await do_generate_report(ctx, title)


# ── Standalone report generation (also used by force-generate) ──────────


async def do_generate_report(
    ctx: AgentContext,
    title: str = "综合分析报告",
) -> str:
    """Core report generation logic — callable outside LangChain too."""
    summarized = []
    for vid, data in ctx.video_data.items():
        if data.get("summary"):
            info = data.get("info")
            summarized.append(
                {
                    "video_id": vid,
                    "title": info.title if info else vid,
                    "author": info.author if info else "未知",
                    "url": info.url if info else "",
                    "duration": info.duration if info else 0,
                    "summary": data["summary"],
                }
            )

    if not summarized:
        return "错误：没有任何已摘要的视频。请先搜索、提取字幕并生成摘要。"

    parts = []
    for i, s in enumerate(summarized, 1):
        parts.append(
            f"### 视频 {i}：{s['title']}\n"
            f"**作者**：{s['author']}\n"
            f"**链接**：{s['url']}\n\n"
            f"{s['summary']}\n"
        )
    summaries_text = "\n---\n".join(parts)

    if len(summaries_text) > 60000:
        summaries_text = (
            summaries_text[:60000]
            + "\n\n...(部分摘要因长度限制被截断)"
        )

    llm = get_llm_provider()
    prompt = MULTI_VIDEO_CONSOLIDATION.format(
        query=ctx.query,
        summaries=summaries_text,
    )
    messages = [
        {
            "role": "system",
            "content": "你是一个专业的内容分析师，擅长多源信息整合与对比分析。",
        },
        {"role": "user", "content": prompt},
    ]

    consolidated = await llm.chat(messages, temperature=0.3, max_tokens=8192)

    report_lines = [consolidated]
    report_lines.append("\n\n---\n")
    report_lines.append(f"*本报告基于 {len(summarized)} 个视频自动生成*\n")
    report_lines.append(f"*搜索关键词：{ctx.query} | 平台：{ctx.platform}*\n")

    ctx.report_markdown = "\n".join(report_lines)
    ctx.report_json = {
        "query": ctx.query,
        "platform": ctx.platform,
        "video_count": len(summarized),
        "videos": [
            {
                "title": s["title"],
                "author": s["author"],
                "url": s["url"],
                "duration": s["duration"],
                "summary": s["summary"],
            }
            for s in summarized
        ],
    }

    return (
        f"综合分析报告已生成，包含 {len(summarized)} 个视频的分析。"
        f"报告长度: {len(ctx.report_markdown)} 字符。"
    )


def get_all_tools() -> list:
    """Return all LangChain tools for the agent."""
    return [search_videos, extract_subtitle, summarize_video, generate_report]
