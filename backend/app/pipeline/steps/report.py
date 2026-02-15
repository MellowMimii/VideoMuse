import json
import logging
from datetime import datetime, timezone

from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import PipelineStep

logger = logging.getLogger(__name__)


class ReportStep(PipelineStep):
    name = "report"

    async def execute(self, context: PipelineContext) -> None:
        # Build structured JSON
        context.report_json = {
            "query": context.query,
            "platform": context.platform,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "video_count": len(context.video_results),
            "videos": [
                {
                    "title": vr.info.title,
                    "author": vr.info.author,
                    "url": vr.info.url,
                    "duration": vr.info.duration,
                    "summary": vr.summary,
                }
                for vr in context.video_results
                if vr.summary
            ],
        }

        # Build markdown report
        lines = [context.consolidated_summary]
        lines.append("\n\n---\n")
        lines.append(f"*本报告基于 {len(context.video_results)} 个视频自动生成*\n")
        lines.append(f"*搜索关键词：{context.query} | 平台：{context.platform}*\n")

        context.report_markdown = "\n".join(lines)
        logger.info("Report generated, markdown length: %d", len(context.report_markdown))
