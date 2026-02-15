import asyncio
import logging

from app.llm import get_llm_provider
from app.llm.prompts import SINGLE_VIDEO_SUMMARY
from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import PipelineStep

logger = logging.getLogger(__name__)


class SummarizeStep(PipelineStep):
    name = "summarize"

    async def execute(self, context: PipelineContext) -> None:
        llm = get_llm_provider()

        async def summarize_one(vr):
            # Truncate long transcripts to fit context window
            transcript = vr.transcript[:8000]

            duration_min = vr.info.duration // 60
            duration_str = f"{duration_min}分{vr.info.duration % 60}秒"

            prompt = SINGLE_VIDEO_SUMMARY.format(
                title=vr.info.title,
                author=vr.info.author,
                duration=duration_str,
                transcript=transcript,
            )
            messages = [
                {"role": "system", "content": "你是一个专业的视频内容分析师。"},
                {"role": "user", "content": prompt},
            ]
            vr.summary = await llm.chat(messages, temperature=0.3)

        semaphore = asyncio.Semaphore(3)

        async def limited_summarize(vr):
            async with semaphore:
                try:
                    await summarize_one(vr)
                except Exception:
                    logger.exception("Failed to summarize video %s", vr.info.video_id)
                    vr.summary = ""

        await asyncio.gather(*[
            limited_summarize(vr) for vr in context.video_results
        ])

        summarized = sum(1 for vr in context.video_results if vr.summary)
        logger.info("Summarized %d/%d videos", summarized, len(context.video_results))
