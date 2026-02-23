import asyncio
import logging

from app.pipeline.context import PipelineContext, VideoResult
from app.pipeline.orchestrator import PipelineStep
from app.platforms import PlatformRegistry

logger = logging.getLogger(__name__)

# Step index in the 5-step pipeline (0-based)
STEP_INDEX = 1

# Delay between subtitle extraction requests (seconds).
# Each video may already incur internal retries (up to ~12s) due to
# Bilibili's anti-crawling returning wrong data; the inter-video delay
# further reduces the chance of triggering rate limits.
REQUEST_DELAY = 1.5


class ExtractStep(PipelineStep):
    name = "extract"

    async def execute(self, context: PipelineContext) -> None:
        adapter = PlatformRegistry.get(context.platform)
        target = context.max_videos  # desired number of successful results
        pool_size = len(context.videos)
        results: list[VideoResult] = []
        success_count = 0

        for i, video_info in enumerate(context.videos):
            context.check_cancelled()

            # Early stop: already collected enough successful results
            if success_count >= target:
                logger.info(
                    "Reached target of %d successful extractions, "
                    "stopping early (%d/%d candidates processed)",
                    target,
                    i,
                    pool_size,
                )
                break

            try:
                text = await adapter.get_subtitles(video_info.video_id)
                method = "subtitle"

                if text:
                    success_count += 1
                    preview = text[:60].replace("\n", " ")
                    logger.info(
                        "Subtitle OK [%d/%d] for [%s] %s -> \"%s...\"",
                        success_count,
                        target,
                        video_info.video_id,
                        video_info.title[:30],
                        preview,
                    )
                else:
                    logger.info(
                        "No subtitles for %s (%s), skipping",
                        video_info.video_id,
                        video_info.title[:30],
                    )
                    method = "none"
                    text = ""

                results.append(VideoResult(
                    info=video_info,
                    transcript=text,
                    extraction_method=method,
                ))

            except Exception:
                logger.exception("Exception extracting subtitles for %s", video_info.video_id)
                results.append(VideoResult(
                    info=video_info,
                    transcript="",
                    extraction_method="error",
                ))

            # Update progress — show success count vs target
            sub_progress = min((i + 1) / pool_size, success_count / target if target else 1)
            await context.set_progress(
                context.get_step_progress(STEP_INDEX, sub_progress),
                f"提取字幕 ({success_count}/{target})",
            )

            # Delay between requests (skip if early-stopping on next iteration)
            if i < pool_size - 1 and success_count < target:
                await asyncio.sleep(REQUEST_DELAY)

        context.video_results = [r for r in results if r.transcript]

        # Trim context.videos to only the videos we actually processed
        # (downstream steps and DB should reflect what was used, not the
        # full over-fetched search pool).
        processed_ids = {r.info.video_id for r in results}
        context.videos = [v for v in context.videos if v.video_id in processed_ids]

        if not context.video_results:
            raise RuntimeError(
                f"所有 {len(results)} 个视频均未能提取到字幕文本，无法继续分析。"
                "可能原因：视频无字幕、平台访问受限。"
            )

        logger.info(
            "Extracted transcripts for %d/%d videos (target was %d, pool was %d)",
            len(context.video_results),
            len(results),
            target,
            pool_size,
        )
