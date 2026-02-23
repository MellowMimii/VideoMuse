import asyncio
import logging

from app.llm import get_llm_provider
from app.llm.prompts import SINGLE_VIDEO_SUMMARY
from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import PipelineStep

logger = logging.getLogger(__name__)

# Step index in the 5-step pipeline (0-based)
STEP_INDEX = 2


class SummarizeStep(PipelineStep):
    name = "summarize"

    async def execute(self, context: PipelineContext) -> None:
        llm = get_llm_provider()
        total = len(context.video_results)
        completed = 0

        async def summarize_one(vr):
            # Truncate long transcripts to fit context window
            transcript = vr.transcript[:20000]

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
            nonlocal completed
            async with semaphore:
                context.check_cancelled()
                try:
                    await summarize_one(vr)
                except Exception:
                    logger.exception("Failed to summarize video %s", vr.info.video_id)
                    vr.summary = ""
                completed += 1
                sub_progress = completed / total if total else 1.0
                await context.set_progress(
                    context.get_step_progress(STEP_INDEX, sub_progress),
                    f"summarize ({completed}/{total})",
                )

        await asyncio.gather(*[
            limited_summarize(vr) for vr in context.video_results
        ])

        summarized = sum(1 for vr in context.video_results if vr.summary)
        if summarized == 0:
            raise RuntimeError(
                f"所有 {total} 个视频的摘要生成均失败，请检查 LLM 配置或稍后重试。"
            )

        logger.info("Summarized %d/%d videos", summarized, len(context.video_results))
