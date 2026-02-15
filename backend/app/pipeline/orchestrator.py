from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)


class PipelineStep(ABC):
    """Abstract base class for a pipeline step."""

    name: str = "unnamed_step"

    @abstractmethod
    async def execute(self, context: PipelineContext) -> None:
        """Execute this step, reading from and writing to the context."""
        ...


class PipelineOrchestrator:
    """Orchestrates the execution of pipeline steps in sequence."""

    def __init__(self, steps: list[PipelineStep] | None = None):
        self.steps = steps or []

    def add_step(self, step: PipelineStep):
        self.steps.append(step)

    async def run(self, context: PipelineContext) -> PipelineContext:
        total_steps = len(self.steps)
        for i, step in enumerate(self.steps):
            step_name = step.name
            logger.info("Running step %d/%d: %s", i + 1, total_steps, step_name)

            base_progress = (i / total_steps) * 100
            context.set_progress(base_progress, step_name)

            try:
                await step.execute(context)
            except Exception:
                logger.exception("Step '%s' failed", step_name)
                raise

            context.set_progress(((i + 1) / total_steps) * 100, step_name)
            logger.info("Completed step: %s", step_name)

        return context
