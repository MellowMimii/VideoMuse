import logging

from app.llm import get_llm_provider
from app.llm.prompts import MULTI_VIDEO_CONSOLIDATION
from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import PipelineStep

logger = logging.getLogger(__name__)


class ConsolidateStep(PipelineStep):
    name = "consolidate"

    async def execute(self, context: PipelineContext) -> None:
        llm = get_llm_provider()

        # Build summaries block
        summaries_parts = []
        for i, vr in enumerate(context.video_results, 1):
            if not vr.summary:
                continue
            summaries_parts.append(
                f"### 视频 {i}：{vr.info.title}\n"
                f"**作者**：{vr.info.author}\n"
                f"**链接**：{vr.info.url}\n\n"
                f"{vr.summary}\n"
            )

        if not summaries_parts:
            context.consolidated_summary = "未能成功提取和总结任何视频内容。"
            return

        summaries_text = "\n---\n".join(summaries_parts)

        prompt = MULTI_VIDEO_CONSOLIDATION.format(
            query=context.query,
            summaries=summaries_text,
        )
        messages = [
            {"role": "system", "content": "你是一个专业的内容分析师，擅长多源信息整合与对比分析。"},
            {"role": "user", "content": prompt},
        ]

        context.consolidated_summary = await llm.chat(
            messages, temperature=0.3, max_tokens=8192
        )
        logger.info("Consolidation complete, length: %d", len(context.consolidated_summary))
