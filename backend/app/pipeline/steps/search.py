import logging

from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import PipelineStep
from app.platforms import PlatformRegistry

logger = logging.getLogger(__name__)


class SearchStep(PipelineStep):
    name = "search"

    async def execute(self, context: PipelineContext) -> None:
        adapter = PlatformRegistry.get(context.platform)

        # Over-fetch: search for more candidates than the user requested
        # so that the extract step has enough headroom to reach the target
        # even when some videos fail subtitle extraction.
        search_count = min(context.max_videos * 2, 50)

        context.videos = await adapter.search_videos(
            context.query, search_count
        )
        if not context.videos:
            raise RuntimeError(
                f"搜索 \"{context.query}\" 未找到任何视频，请尝试更换关键词"
            )
        logger.info(
            "Search found %d videos (target %d, over-fetched %d)",
            len(context.videos),
            context.max_videos,
            search_count,
        )
