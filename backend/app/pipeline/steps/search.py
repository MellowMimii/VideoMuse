import logging

from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import PipelineStep
from app.platforms import PlatformRegistry

logger = logging.getLogger(__name__)


class SearchStep(PipelineStep):
    name = "search"

    async def execute(self, context: PipelineContext) -> None:
        adapter = PlatformRegistry.get(context.platform)
        context.videos = await adapter.search_videos(
            context.query, context.max_videos
        )
        logger.info("Search found %d videos", len(context.videos))
