from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "eas",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.celery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "daily-audit-report": {
            "task": "app.tasks.celery_tasks.generate_daily_report",
            "schedule": crontab(hour=22, minute=0),  # 10 PM UTC daily
        },
        "fetch-git-events": {
            "task": "app.tasks.celery_tasks.fetch_git_events",
            "schedule": crontab(minute="*/30"),  # every 30 min
        },
    },
)
