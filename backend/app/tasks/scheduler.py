from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.tasks import jobs


class SchedulerWrapper:
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._job_id = "process_messages"
        self._sync_job_id = "sync_projects_daily"
        self._is_configured = False

    def _configure_jobs(self) -> None:
        if self._is_configured:
            return
        
        # 项目同步任务（每天00:00执行）
        self._scheduler.add_job(
            jobs.sync_projects_job,
            "cron",
            hour=0,
            minute=0,
            id=self._sync_job_id,
            replace_existing=True,
        )
        
        self._is_configured = True

    async def start(self) -> None:
        if not self._scheduler.running:
            self._configure_jobs()
            self._scheduler.start()

    async def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)


scheduler = SchedulerWrapper()
