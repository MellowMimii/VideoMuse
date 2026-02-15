from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import Report, Task, TaskStatus, Video
from app.schemas import (
    ReportResponse,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    VideoResponse,
)
from app.services.task_service import run_analysis_task

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

    # Launch pipeline in background
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


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await db.delete(task)
    await db.commit()
