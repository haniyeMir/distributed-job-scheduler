from celery import Celery
from config import Config

celery_app = Celery(
    "scheduler",
    broker=Config.CELERY_BROKER_URL,
    backend=Config.REDIS_URL,
    include=["app.tasks.job_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)