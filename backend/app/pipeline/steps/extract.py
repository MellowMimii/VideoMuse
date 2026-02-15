import asyncio
import logging

from app.pipeline.context import PipelineContext, VideoResult
from app.pipeline.orchestrator import PipelineStep
from app.platforms import PlatformRegistry

logger = logging.getLogger(__name__)


class ExtractStep(PipelineStep):
    name = "extract"

    async def execute(self, context: PipelineContext) -> None:
        adapter = PlatformRegistry.get(context.platform)

        async def extract_one(video_info):
            # Try subtitles first
            text = await adapter.get_subtitles(video_info.video_id)
            method = "subtitle"

            if not text:
                # TODO: Whisper fallback — download audio and transcribe
                logger.info(
                    "No subtitles for %s, Whisper fallback not yet implemented",
                    video_info.video_id,
                )
                method = "none"
                text = ""

            return VideoResult(
                info=video_info,
                transcript=text,
                extraction_method=method,
            )

        # Extract concurrently with a concurrency limit
        semaphore = asyncio.Semaphore(5)

        async def limited_extract(v):
            async with semaphore:
                return await extract_one(v)

        results = await asyncio.gather(
            *[limited_extract(v) for v in context.videos],
            return_exceptions=True,
        )

        context.video_results = [
            r for r in results if isinstance(r, VideoResult) and r.transcript
        ]
        logger.info(
            "Extracted transcripts for %d/%d videos",
            len(context.video_results),
            len(context.videos),
        )
