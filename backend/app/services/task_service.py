"""Task service — orchestrates agent execution and result persistence."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from app.agent import AgentCancelledError, AgentContext, AgentEvent, run_agent
from app.db.session import async_session
from app.llm.prompts import AGENT_SYSTEM_PROMPT
from app.models import AgentEventLog, Report, Task, TaskStatus, Video

logger = logging.getLogger(__name__)

# Registry of active agent contexts for cancellation support
_active_contexts: dict[int, AgentContext] = {}


def get_active_context(task_id: int) -> AgentContext | None:
    """Get the AgentContext for a running task (used by cancel endpoint)."""
    return _active_contexts.get(task_id)


# ── Callbacks ────────────────────────────────────────────────────────────


async def update_task_progress(task_id: int, progress: float) -> None:
    """Persist task progress to the database."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task:
            task.progress = progress
            task.status = TaskStatus.RUNNING
            await session.commit()


async def persist_agent_event(task_id: int, event: AgentEvent) -> None:
    """Persist an agent event to the database for frontend display."""
    async with async_session() as session:
        db_event = AgentEventLog(
            task_id=task_id,
            event_type=event.event_type,
            content=event.content[:5000],
            tool_name=event.tool_name or None,
            tool_args_json=(
                json.dumps(event.tool_args, ensure_ascii=False)
                if event.tool_args
                else None
            ),
            tool_result_preview=(
                event.tool_result_preview[:2000]
                if event.tool_result_preview
                else None
            ),
            timestamp=event.timestamp,
        )
        session.add(db_event)
        await session.commit()


# ── Result persistence ───────────────────────────────────────────────────


async def persist_final_results(ctx: AgentContext) -> None:
    """Persist videos and report from agent context to the database."""
    task_id = ctx.task_id
    if not task_id:
        return

    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            return

        # Delete existing videos
        existing = await session.execute(
            select(Video).where(Video.task_id == task_id)
        )
        for v in existing.scalars().all():
            await session.delete(v)

        # Save only videos that have actual content (transcript or summary)
        for vid, data in ctx.video_data.items():
            info = data.get("info")
            if not info:
                continue
            # Skip videos that were only searched but never extracted
            if not data.get("transcript") and not data.get("summary"):
                continue
            video = Video(
                task_id=task_id,
                platform=info.platform,
                video_id=info.video_id,
                title=info.title,
                author=info.author,
                url=info.url,
                duration=info.duration,
                cover_url=info.cover_url,
                subtitle_text=(data.get("transcript") or "")[:10000],
                summary=data.get("summary"),
            )
            session.add(video)

        # Delete existing report
        existing_report = await session.execute(
            select(Report).where(Report.task_id == task_id)
        )
        old = existing_report.scalar_one_or_none()
        if old:
            await session.delete(old)

        # Save new report
        if ctx.report_markdown:
            report = Report(
                task_id=task_id,
                content_json=json.dumps(ctx.report_json, ensure_ascii=False),
                content_markdown=ctx.report_markdown,
            )
            session.add(report)

        task.completed_step = "report"
        await session.commit()

    logger.info("Persisted final results for task %d", task_id)


# ── Main entry point ─────────────────────────────────────────────────────


async def run_analysis_task(task_id: int) -> None:
    """Execute the agent-based analysis for a task."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            logger.error("Task %d not found", task_id)
            return
        task.status = TaskStatus.RUNNING
        await session.commit()

    # Read task data for context construction
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            return
        query = task.query
        platform = task.platform
        max_videos = task.max_videos

    # Build agent context
    system_prompt = AGENT_SYSTEM_PROMPT.format(
        query=query,
        platform=platform,
        max_videos=max_videos,
    )

    ctx = AgentContext(
        query=query,
        platform=platform,
        max_videos=max_videos,
        task_id=task_id,
        system_prompt=system_prompt,
        _progress_callback=update_task_progress,
        _event_callback=persist_agent_event,
    )

    _active_contexts[task_id] = ctx

    try:
        await run_agent(ctx)

        # Persist final results
        await persist_final_results(ctx)

        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = TaskStatus.DONE
                task.progress = 100.0
                await session.commit()

        logger.info("Task %d completed successfully", task_id)

    except AgentCancelledError:
        logger.info("Task %d was cancelled", task_id)
        # Persist whatever we collected so far
        await persist_final_results(ctx)
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = TaskStatus.CANCELLED
                task.error_message = "任务已被用户取消"
                await session.commit()

    except Exception as e:
        logger.exception("Task %d failed", task_id)
        # Still try to persist partial results
        try:
            await persist_final_results(ctx)
        except Exception:
            logger.exception("Failed to persist partial results for task %d", task_id)
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                await session.commit()

    finally:
        _active_contexts.pop(task_id, None)
