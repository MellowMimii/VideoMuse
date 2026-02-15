import json
import logging

from app.models import Report, Task, TaskStatus, Video
from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.steps.consolidate import ConsolidateStep
from app.pipeline.steps.extract import ExtractStep
from app.pipeline.steps.report import ReportStep
from app.pipeline.steps.search import SearchStep
from app.pipeline.steps.summarize import SummarizeStep
from app.db.session import async_session

logger = logging.getLogger(__name__)


def build_pipeline() -> PipelineOrchestrator:
    """Build the standard 5-step analysis pipeline."""
    return PipelineOrchestrator(steps=[
        SearchStep(),
        ExtractStep(),
        SummarizeStep(),
        ConsolidateStep(),
        ReportStep(),
    ])


async def update_task_progress(task_id: int, progress: float, step: str):
    """Callback to persist task progress to the database."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if task:
            task.progress = progress
            task.status = TaskStatus.RUNNING
            await session.commit()


async def run_analysis_task(task_id: int):
    """Execute the full analysis pipeline for a task. Designed to run as a background task."""
    async with async_session() as session:
        task = await session.get(Task, task_id)
        if not task:
            logger.error("Task %d not found", task_id)
            return

        task.status = TaskStatus.RUNNING
        await session.commit()

    try:
        context = PipelineContext(
            query=task.query,
            platform=task.platform,
            max_videos=task.max_videos,
            task_id=task_id,
            _progress_callback=update_task_progress,
        )

        pipeline = build_pipeline()
        context = await pipeline.run(context)

        # Persist results to database
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if not task:
                return

            # Save videos
            for vr in context.video_results:
                video = Video(
                    task_id=task_id,
                    platform=vr.info.platform,
                    video_id=vr.info.video_id,
                    title=vr.info.title,
                    author=vr.info.author,
                    url=vr.info.url,
                    duration=vr.info.duration,
                    cover_url=vr.info.cover_url,
                    subtitle_text=vr.transcript[:10000] if vr.transcript else None,
                    summary=vr.summary,
                )
                session.add(video)

            # Save report
            report = Report(
                task_id=task_id,
                content_json=json.dumps(context.report_json, ensure_ascii=False),
                content_markdown=context.report_markdown,
            )
            session.add(report)

            task.status = TaskStatus.DONE
            task.progress = 100.0
            await session.commit()

        logger.info("Task %d completed successfully", task_id)

    except Exception as e:
        logger.exception("Task %d failed", task_id)
        async with async_session() as session:
            task = await session.get(Task, task_id)
            if task:
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                await session.commit()
