"""Agent loop — LangChain ReAct agent with async callback-based event tracking.

Uses LangChain's create_react_agent + AgentExecutor with text-based
tool calling (Thought / Action / Action Input / Observation format).
No API-level ``tools`` parameter needed — works with any LLM endpoint.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI

from app.agent.context import AgentContext
from app.agent.tools import do_generate_report, get_all_tools, set_context
from app.config import settings

logger = logging.getLogger(__name__)

# ── Safety limits ────────────────────────────────────────────────────────
MAX_ITERATIONS = 40
AGENT_TIMEOUT = 900  # seconds


# ── Agent event (kept for DB persistence & frontend display) ─────────────

@dataclass
class AgentEvent:
    """A single event in the agent's execution history."""

    event_type: str  # "thinking" | "tool_call" | "tool_result" | "error" | "complete"
    timestamp: float = field(default_factory=time.time)
    content: str = ""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_result_preview: str = ""


# ── ReAct prompt template ────────────────────────────────────────────────

REACT_PROMPT = PromptTemplate.from_template(
    """\
你是 VideoMuse 智能分析助手，负责从视频平台搜索和分析视频内容，为用户生成综合研究报告。

你可以使用以下工具：

{tools}

请严格按照以下格式回复（关键词必须用英文）：

Thought: 思考下一步应该做什么
Action: 要使用的工具名，必须是 [{tool_names}] 之一
Action Input: 工具的输入参数（字符串）
Observation: 工具返回的结果（系统自动填入，你不要写这行）

可以重复多次 Thought/Action/Action Input/Observation。

当分析完成后，使用：
Thought: 分析已完成，报告已生成
Final Answer: 报告生成完成

重要规则：
- 你必须严格按照用户指定的「目标视频数量」来工作，尽可能分析到足够数量的视频
- 如果某个视频字幕提取失败，立即尝试下一个视频，不要放弃
- 只有当已成功生成摘要的视频数量达到目标数量，或者已经尝试了所有搜索到的视频后，才能调用 generate_report
- 如果第一次搜索的视频不够用（很多提取失败），请用不同关键词再次搜索

工作流程：
1. 用 search_videos 搜索相关视频（一次搜索返回最多10个）
2. 依次用 extract_subtitle 提取视频字幕（失败则跳过，继续下一个）
3. 每提取成功一个字幕后，立即用 summarize_video 生成摘要
4. 重复步骤2-3，直到成功生成摘要的视频数量达到目标数量
5. 达到目标数量后，用 generate_report 生成最终综合报告

Question: {input}
Thought:{agent_scratchpad}"""
)


# ── Callback handler for event tracking ──────────────────────────────────


class AgentEventHandler(AsyncCallbackHandler):
    """Translate LangChain agent callbacks into AgentEvents for the frontend."""

    def __init__(self, ctx: AgentContext):
        super().__init__()
        self.ctx = ctx
        self._last_tool_name: str = ""

    async def on_agent_action(
        self, action: Any, *, run_id: Any, parent_run_id: Any = None, **kwargs: Any
    ) -> None:
        # Extract "Thought: ..." from the raw LLM log
        thought = ""
        if hasattr(action, "log") and action.log:
            match = re.search(
                r"Thought:\s*(.+?)(?=\nAction:)", action.log, re.DOTALL
            )
            if match:
                thought = match.group(1).strip()

        if thought:
            await self.ctx.add_event(
                AgentEvent(event_type="thinking", content=thought)
            )

        self._last_tool_name = action.tool

        # Map single-string input to the expected field name for each tool
        tool_input = action.tool_input
        if isinstance(tool_input, dict):
            tool_args = tool_input
        else:
            input_str = str(tool_input).strip()
            arg_key_map = {
                "search_videos": "query",
                "extract_subtitle": "video_id",
                "summarize_video": "video_id",
                "generate_report": "title",
            }
            key = arg_key_map.get(action.tool, "input")
            tool_args = {key: input_str}

        await self.ctx.add_event(
            AgentEvent(
                event_type="tool_call",
                tool_name=action.tool,
                tool_args=tool_args,
                content=f"调用工具: {action.tool}",
            )
        )

    async def on_tool_end(
        self, output: Any, *, run_id: Any, parent_run_id: Any = None, **kwargs: Any
    ) -> None:
        result_str = str(output)[:500]
        await self.ctx.add_event(
            AgentEvent(
                event_type="tool_result",
                tool_name=self._last_tool_name,
                content=result_str,
                tool_result_preview=result_str[:200],
            )
        )
        await self._update_progress(self._last_tool_name)

    async def on_agent_finish(
        self, finish: Any, *, run_id: Any, parent_run_id: Any = None, **kwargs: Any
    ) -> None:
        if self.ctx.report_markdown:
            await self.ctx.add_event(
                AgentEvent(event_type="complete", content="分析完成")
            )

    # ── Progress heuristic ───────────────────────────────────────────────

    async def _update_progress(self, tool_name: str) -> None:
        ctx = self.ctx
        target = max(ctx.max_videos, 1)

        extracted = sum(
            1 for v in ctx.video_data.values() if v.get("transcript")
        )
        summarized = sum(
            1 for v in ctx.video_data.values() if v.get("summary")
        )

        if tool_name == "search_videos":
            new = 10.0
        elif tool_name == "extract_subtitle":
            new = 15.0 + min(extracted / target, 1.0) * 35.0
        elif tool_name == "summarize_video":
            new = 50.0 + min(summarized / target, 1.0) * 30.0
        elif tool_name == "generate_report":
            new = 90.0
        else:
            new = ctx.progress

        new = max(ctx.progress, new)
        await ctx.set_progress(new)


# ── Core entry point ─────────────────────────────────────────────────────


async def run_agent(ctx: AgentContext) -> None:
    """Run the LangChain ReAct agent loop."""

    # Bind context so tools can access shared state
    set_context(ctx)

    llm = ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=0.3,
        max_tokens=4096,
        request_timeout=120,
    )

    tools = get_all_tools()
    agent = create_react_agent(llm, tools, REACT_PROMPT)

    handler = AgentEventHandler(ctx)

    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        max_iterations=MAX_ITERATIONS,
        max_execution_time=AGENT_TIMEOUT,
        handle_parsing_errors="请严格按照 Thought/Action/Action Input 格式输出。",
        verbose=True,
        callbacks=[handler],
    )

    try:
        result = await executor.ainvoke(
            {
                "input": (
                    f"请在{ctx.platform}平台搜索并分析关于「{ctx.query}」的视频。"
                    f"你必须成功分析至少 {ctx.max_videos} 个视频后才能生成报告。"
                    f"如果字幕提取失败就跳过换下一个，直到凑够 {ctx.max_videos} 个有效摘要。"
                ),
            },
        )
        logger.info(
            "Agent finished: %s", str(result.get("output", ""))[:200]
        )
    except Exception as e:
        logger.exception("Agent execution failed")
        await ctx.add_event(
            AgentEvent(event_type="error", content=f"Agent 执行失败: {e}")
        )

    # Backfill: if the agent didn't reach the target, programmatically fill the gap
    await _backfill_videos(ctx)

    # If no report was generated, force-generate one
    if not ctx.report_markdown:
        await _force_generate_report(ctx)


# ── Programmatic backfill ────────────────────────────────────────────────


async def _backfill_videos(ctx: AgentContext) -> None:
    """Programmatically extract subtitles and summarize remaining videos
    if the agent didn't reach the target count."""
    import asyncio as _asyncio

    from app.llm import get_llm_provider
    from app.llm.prompts import SINGLE_VIDEO_SUMMARY
    from app.platforms import PlatformRegistry

    summarized_count = sum(1 for v in ctx.video_data.values() if v.get("summary"))
    target = ctx.max_videos

    if summarized_count >= target:
        return

    gap = target - summarized_count
    logger.info(
        "[backfill] Agent produced %d/%d summaries, need %d more",
        summarized_count, target, gap,
    )

    await ctx.add_event(
        AgentEvent(
            event_type="thinking",
            content=f"自动补充分析：已有 {summarized_count} 个摘要，目标 {target} 个，正在补充剩余视频...",
        )
    )

    # Collect candidate video IDs that haven't been summarized yet
    candidates = []
    for vi in ctx.search_results:
        data = ctx.video_data.get(vi.video_id, {})
        if not data.get("summary"):
            candidates.append(vi.video_id)

    adapter = PlatformRegistry.get(ctx.platform)
    llm = get_llm_provider()
    filled = 0

    for video_id in candidates:
        if filled >= gap:
            break

        # Extract subtitle if not already done
        data = ctx.video_data.get(video_id, {})
        if not data.get("transcript"):
            await ctx.add_event(
                AgentEvent(
                    event_type="tool_call",
                    tool_name="extract_subtitle",
                    tool_args={"video_id": video_id},
                    content=f"[自动补充] 提取字幕: {video_id}",
                )
            )
            await _asyncio.sleep(1.5)
            text = await adapter.get_subtitles(video_id)
            if not text:
                logger.info("[backfill] No subtitles for %s, skipping", video_id)
                await ctx.add_event(
                    AgentEvent(
                        event_type="tool_result",
                        tool_name="extract_subtitle",
                        content=f"字幕提取失败，跳过 {video_id}",
                        tool_result_preview=f"字幕提取失败，跳过 {video_id}",
                    )
                )
                continue

            if video_id not in ctx.video_data:
                ctx.video_data[video_id] = {"info": ctx.get_video_info(video_id)}
            ctx.video_data[video_id]["transcript"] = text

            await ctx.add_event(
                AgentEvent(
                    event_type="tool_result",
                    tool_name="extract_subtitle",
                    content=f"成功提取字幕，共 {len(text)} 字符",
                    tool_result_preview=f"成功提取字幕，共 {len(text)} 字符",
                )
            )

        # Summarize
        data = ctx.video_data[video_id]
        info = data.get("info")
        transcript = data["transcript"][:20000]
        title = info.title if info else video_id
        author = info.author if info else "未知"
        duration = info.duration if info else 0
        dur_str = f"{duration // 60}分{duration % 60}秒"

        await ctx.add_event(
            AgentEvent(
                event_type="tool_call",
                tool_name="summarize_video",
                tool_args={"video_id": video_id},
                content=f"[自动补充] 生成摘要: {title}",
            )
        )

        prompt = SINGLE_VIDEO_SUMMARY.format(
            title=title, author=author, duration=dur_str, transcript=transcript
        )
        summary = await llm.chat(
            [
                {"role": "system", "content": "你是一个专业的视频内容分析师。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        ctx.video_data[video_id]["summary"] = summary
        filled += 1

        await ctx.add_event(
            AgentEvent(
                event_type="tool_result",
                tool_name="summarize_video",
                content=f"摘要生成完成: {title}",
                tool_result_preview=summary[:200],
            )
        )

        # Update progress
        total_summarized = sum(1 for v in ctx.video_data.values() if v.get("summary"))
        pct = 50.0 + min(total_summarized / max(target, 1), 1.0) * 30.0
        await ctx.set_progress(max(ctx.progress, pct))

    total_final = sum(1 for v in ctx.video_data.values() if v.get("summary"))
    logger.info("[backfill] Done. Total summaries: %d/%d", total_final, target)

    # If we backfilled and the agent already generated a report, regenerate it
    if filled > 0 and ctx.report_markdown:
        logger.info("[backfill] Regenerating report with %d videos", total_final)
        ctx.report_markdown = ""
        await do_generate_report(ctx, "综合分析报告")


async def _force_generate_report(ctx: AgentContext) -> None:
    """Force-generate a report with whatever data we have."""
    if ctx.report_markdown:
        return

    has_summaries = any(v.get("summary") for v in ctx.video_data.values())
    if has_summaries:
        try:
            await do_generate_report(ctx, "综合分析报告")
        except Exception:
            logger.exception("Force generate report failed")
            ctx.report_markdown = (
                f"# {ctx.query}\n\n"
                "分析未能完成：报告生成失败。\n"
            )
    else:
        ctx.report_markdown = (
            f"# {ctx.query}\n\n"
            "分析未能完成：未能成功获取和分析足够的视频内容。\n"
        )
