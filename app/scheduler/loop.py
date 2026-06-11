import logging
import time
from datetime import datetime, timezone

import redis
from croniter import croniter
from sqlalchemy import and_

from app.database import SessionLocal
from app.models import (
    JobDefinition, JobInstance,
    JobStatus, InstanceStatus, ScheduleType
)
from config import Config

logger = logging.getLogger(__name__)

# Redis client for distributed lock
redis_client = redis.Redis(
    host=Config.REDIS_HOST,
    port=Config.REDIS_PORT,
    db=0,
    decode_responses=True,
)

SCHEDULER_LOCK_KEY = "scheduler:master_lock"
SCHEDULER_LOCK_TTL = 30   # seconds — lock auto-expires if scheduler crashes
POLL_INTERVAL = 10         # seconds between each scheduling cycle


# DISTRIBUTED LOCK

def acquire_lock() -> bool:
   
    return bool(
        redis_client.set(SCHEDULER_LOCK_KEY, "1", nx=True, ex=SCHEDULER_LOCK_TTL)
    )


def release_lock():
    redis_client.delete(SCHEDULER_LOCK_KEY)


# DUE JOB DETECTION

def get_due_jobs(db) -> list[JobDefinition]:
   
    now = datetime.now(timezone.utc)
    active_jobs = db.query(JobDefinition).filter(
        JobDefinition.status == JobStatus.ACTIVE
    ).all()

    due = []
    for job in active_jobs:
        if job.schedule_type == ScheduleType.PERIODIC and _is_periodic_due(job, db, now):
            due.append(job)
        elif job.schedule_type == ScheduleType.ONE_TIME and _is_one_time_due(job, db, now):
            due.append(job)

    return due


def _is_periodic_due(job: JobDefinition, db, now: datetime) -> bool:
   
    last = db.query(JobInstance).filter(
        JobInstance.job_definition_id == job.id,
        JobInstance.status.in_([
            InstanceStatus.SUCCESS,
            InstanceStatus.RUNNING,
            InstanceStatus.QUEUED,
            InstanceStatus.FAILED,
        ])
    ).order_by(JobInstance.created_at.desc()).first()

    if not last:
        # No previous execution 
        return True

    base_time = last.scheduled_at or last.created_at
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=timezone.utc)

    cron = croniter(job.cron_expression, base_time)
    next_run = cron.get_next(datetime)

    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)

    return now >= next_run


def _is_one_time_due(job: JobDefinition, db, now: datetime) -> bool:
   
    return db.query(JobInstance).filter(
        and_(
            JobInstance.job_definition_id == job.id,
            JobInstance.status == InstanceStatus.PENDING,
            JobInstance.scheduled_at <= now,
        )
    ).first() is not None


# ENQUEUE

def enqueue_job(job: JobDefinition, db) -> bool:
  

    from app.services.dag_service import DAGService
    dag = DAGService(db)
    if not dag.are_dependencies_met(str(job.id)):
        logger.info(
            f"Skipping {job.name} — dependencies not yet satisfied"
        )
        return False

    from app.tasks.job_tasks import execute_job

    now = datetime.now(timezone.utc)

    if job.schedule_type == ScheduleType.PERIODIC:
        # Create a fresh instance 
        instance = JobInstance(
            job_definition_id=job.id,
            status=InstanceStatus.QUEUED,
            priority=job.priority,
            payload_snapshot=job.payload,
            scheduled_at=now,
            queued_at=now,
            attempt=0,
        )
        db.add(instance)
        db.flush()  # get the ID before commit

    else:
        # Find and lock the PENDING one-time instance
        instance = db.query(JobInstance).filter(
            JobInstance.job_definition_id == job.id,
            JobInstance.status == InstanceStatus.PENDING,
        ).with_for_update(skip_locked=True).first()
 

        if not instance:
            return False

        instance.status = InstanceStatus.QUEUED
        instance.queued_at = now
        db.flush()

    # Send to RabbitMQ via Celery 
    execute_job.apply_async(
        args=[str(instance.id)],
        queue=job.priority.value,  
    )

    db.commit()
    logger.info(f"Enqueued: {job.name} → instance {instance.id} [{job.priority.value} queue]")
    return True



# MAIN LOOP

def run_scheduler():
   
    logger.info(f"Scheduler started — polling every {POLL_INTERVAL}s")

    while True:
        try:
            if acquire_lock():
                logger.debug("Lock acquired — running scheduling cycle")
                try:
                    db = SessionLocal()
                    try:
                        due_jobs = get_due_jobs(db)
                        if due_jobs:
                            logger.info(f"Found {len(due_jobs)} due job(s)")
                        for job in due_jobs:
                            try:
                                enqueue_job(job, db)
                            except Exception as e:
                                logger.error(f"Error enqueuing {job.name}: {e}")
                                db.rollback()
                    finally:
                        db.close()
                finally:
                    release_lock()
                    logger.debug("Lock released")
            else:
                logger.debug("Lock busy — another scheduler is running, skipping cycle")

        except Exception as e:
            logger.error(f"Scheduler cycle error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [SCHEDULER] %(levelname)s: %(message)s"
    )
    run_scheduler()