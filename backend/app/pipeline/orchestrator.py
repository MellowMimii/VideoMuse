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
        context.total_steps = len(self.steps)

        # Determine which steps to skip when resuming
        skip_until_after = context.resume_after_step
        skipping = skip_until_after is not None

        for i, step in enumerate(self.steps):
            step_name = step.name

            # Skip already-completed steps on resume
            if skipping:
                if step_name == skip_until_after:
                    skipping = False
                    logger.info("Skipping already-completed step: %s", step_name)
                else:
                    logger.info("Skipping already-completed step: %s", step_name)
                continue

            # Check for cancellation before each step
            context.check_cancelled()

            logger.info("Running step %d/%d: %s", i + 1, context.total_steps, step_name)

            base_progress = (i / context.total_steps) * 100
            await context.set_progress(base_progress, step_name)

            try:
                await step.execute(context)
            except Exception:
                logger.exception("Step '%s' failed", step_name)
                raise

            # Persist intermediate results after each step
            if context._step_complete_callback:
                await context._step_complete_callback(context, step_name)

            await context.set_progress(((i + 1) / context.total_steps) * 100, step_name)
            logger.info("Completed step: %s", step_name)

        return context
