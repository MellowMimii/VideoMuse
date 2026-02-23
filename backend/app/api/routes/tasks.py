from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import AgentEventLog, Report, Task, TaskStatus, Video
from app.schemas import (
    AgentEventResponse,
    ReportResponse,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    VideoResponse,
)
from app.services.task_service import get_active_context, run_analysis_task

router = APIRouter()


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    body: TaskCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = Task(
        query=body.query,
        platform=body.platform,
        max_videos=body.max_videos,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Launch agent in background
    background_tasks.add_task(run_analysis_task, task.id)

    return task


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    total_result = await db.execute(select(func.count(Task.id)))
    total = total_result.scalar() or 0

    result = await db.execute(
        select(Task).order_by(Task.created_at.desc()).offset(skip).limit(limit)
    )
    tasks = result.scalars().all()

    return TaskListResponse(tasks=tasks, total=total)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/tasks/{task_id}/videos", response_model=list[VideoResponse])
async def get_task_videos(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = await db.execute(select(Video).where(Video.task_id == task_id))
    return result.scalars().all()


@router.get("/tasks/{task_id}/report", response_model=ReportResponse)
async def get_task_report(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).where(Report.task_id == task_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/tasks/{task_id}/events", response_model=list[AgentEventResponse])
async def get_task_events(
    task_id: int,
    since_id: int = Query(0, ge=0, description="Only return events with id > since_id"),
    db: AsyncSession = Depends(get_db),
):
    """Get agent events for a task, with incremental loading support."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    stmt = (
        select(AgentEventLog)
        .where(AgentEventLog.task_id == task_id, AgentEventLog.id > since_id)
        .order_by(AgentEventLog.id.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # If the task is running, cancel it first
    ctx = get_active_context(task_id)
    if ctx:
        ctx.cancel()

    await db.delete(task)
    await db.commit()


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """Cancel a running or pending task."""
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING):
        raise HTTPException(status_code=400, detail="Only running or pending tasks can be cancelled")

    # Signal the agent to cancel
    ctx = get_active_context(task_id)
    if ctx:
        ctx.cancel()
    else:
        # Task is PENDING and hasn't started yet
        task.status = TaskStatus.CANCELLED
        task.error_message = "任务已被用户取消"
        await db.commit()
        await db.refresh(task)

    return task


@router.post("/tasks/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
        raise HTTPException(status_code=400, detail="Only failed or cancelled tasks can be retried")

    # Agent mode: always start from scratch
    task.status = TaskStatus.PENDING
    task.progress = 0.0
    task.error_message = None
    task.completed_step = None
    await db.commit()
    await db.refresh(task)

    background_tasks.add_task(run_analysis_task, task.id)

    return task
