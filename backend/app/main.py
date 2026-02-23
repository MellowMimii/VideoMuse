import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes.health import router as health_router
from app.api.routes.tasks import router as tasks_router
from app.db.session import async_session, engine
from app.models import Base, Task, TaskStatus

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Reset any tasks stuck in RUNNING/PENDING state from a previous crash
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(Task.status.in_([TaskStatus.RUNNING, TaskStatus.PENDING]))
        )
        stuck_tasks = result.scalars().all()
        if stuck_tasks:
            for task in stuck_tasks:
                task.status = TaskStatus.FAILED
                task.error_message = "服务重启，任务中断。请点击重试继续分析。"
            await session.commit()
            logger.warning(
                "Reset %d stuck tasks (RUNNING/PENDING) to FAILED on startup",
                len(stuck_tasks),
            )

    yield
    await engine.dispose()


app = FastAPI(
    title="VideoMuse",
    description="AI-powered multi-video content analysis and report generation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(tasks_router, prefix="/api", tags=["tasks"])
