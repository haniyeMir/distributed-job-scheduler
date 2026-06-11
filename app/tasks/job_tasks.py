import logging
import traceback
import threading
from datetime import datetime, timezone, timedelta
import random

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models import (
    JobInstance, JobDefinition,
    DeadLetter, InstanceStatus
)
from app.models.enums import is_valid_transition

logger = logging.getLogger(__name__)


# CONCURRENCY CONTROL

def _check_concurrency(job: JobDefinition, db) -> bool:
   
    running_count = db.query(JobInstance).filter(
        JobInstance.job_definition_id == job.id,
        JobInstance.status == InstanceStatus.RUNNING,
    ).count()

    if running_count >= job.max_concurrency:
        logger.warning(
            f"Job {job.name} at concurrency limit "
            f"({running_count}/{job.max_concurrency}) — requeueing"
        )
        return False
    return True


# TIMEOUT ENFORCEMENT

def _run_with_timeout(fn, timeout_seconds: int) -> dict:
    result = {"output": None, "error": None, "timed_out": False}

    def target():
        try:
            result["output"] = fn()
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        result["timed_out"] = True

    return result


# ACTUAL JOB LOGIC

def _execute_job_logic(instance: JobInstance) -> dict:
    import time
    time.sleep(1)
    return {
        "message": "executed successfully",
        "job_type": instance.payload_snapshot,
    }


# RETRY HELPERS

def _schedule_retry(instance: JobInstance, job: JobDefinition, db):
    instance.attempt += 1
    delay = (2 ** instance.attempt) + random.random()

    instance.status = InstanceStatus.QUEUED
    instance.scheduled_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    instance.queued_at = datetime.now(timezone.utc)
    instance.error_message = None  # clear for retry

    execute_job.apply_async(
        args=[str(instance.id)],
        queue=job.priority.value,
        countdown=int(delay),
    )
    logger.info(
        f"Retry scheduled: {job.name} instance {instance.id} "
        f"attempt {instance.attempt}/{job.max_retries} in {delay:.1f}s"
    )


def _move_to_dead_letter(instance: JobInstance, db):
    instance.status = InstanceStatus.FAILED
    instance.finished_at = datetime.now(timezone.utc)

    # Avoid duplicate dead letter entries
    from sqlalchemy import exists
    already_exists = db.query(
        exists().where(DeadLetter.job_instance_id == instance.id)
    ).scalar()

    if not already_exists:
        dead = DeadLetter(
            job_instance_id=instance.id,
            job_definition_id=instance.job_definition_id,
            reason="Max retries exhausted",
            last_error={
                "message": instance.error_message,
                "traceback": instance.traceback,
                "final_attempt": instance.attempt,
            },
        )
        db.add(dead)
        logger.warning(
            f"Dead letter: {instance.id} after {instance.attempt} attempts"
        )


# MAIN CELERY TASK
        
@celery_app.task(bind=True, name="execute_job", max_retries=0)
def execute_job(self, instance_id: str):
    db = SessionLocal()
    try:

        instance = db.query(JobInstance).filter(
            JobInstance.id == instance_id
        ).with_for_update().first()

        if not instance:
            logger.error(f"Instance {instance_id} not found — discarding")
            return

        if not is_valid_transition(instance.status, InstanceStatus.RUNNING):
            logger.warning(
                f"Skipping {instance_id}: invalid transition "
                f"{instance.status} → RUNNING (already processed)"
            )
            return

        # --- CONCURRENCY CHECK ---
        job = db.query(JobDefinition).filter(
            JobDefinition.id == instance.job_definition_id
        ).first()

        if not job:
            logger.error(f"JobDefinition not found for instance {instance_id}")
            return

        if not _check_concurrency(job, db):
            # Requeue for later 
            instance.status = InstanceStatus.QUEUED
            instance.queued_at = datetime.now(timezone.utc)
            db.commit()
            execute_job.apply_async(
                args=[str(instance.id)],
                queue=job.priority.value,
                countdown=30,  # retry concurrency check in 30s
            )
            return

        # --- TRANSITION TO RUNNING ---
        instance.status = InstanceStatus.RUNNING
        instance.started_at = datetime.now(timezone.utc)
        instance.worker_id = self.request.hostname
        db.commit()

        logger.info(
            f"[{self.request.hostname}] Running {job.name} "
            f"instance {instance_id} (attempt {instance.attempt})"
        )

        # --- EXECUTE WITH TIMEOUT ---
        result = _run_with_timeout(
            fn=lambda: _execute_job_logic(instance),
            timeout_seconds=job.max_execution_time,
        )

        now = datetime.now(timezone.utc)

        if result["timed_out"]:
            # --- TIMEOUT HANDLING ---
            logger.warning(
                f"Instance {instance_id} timed out "
                f"after {job.max_execution_time}s"
            )
            instance.status = InstanceStatus.TIMEOUT
            instance.finished_at = now
            instance.error_message = (
                f"Exceeded max_execution_time of {job.max_execution_time}s"
            )
            db.commit()

            # Timeout counts as a failure — retry or dead letter
            if instance.attempt < job.max_retries:
                _schedule_retry(instance, job, db)
            else:
                _move_to_dead_letter(instance, db)

                from app.services.alert_service import AlertService
                AlertService(db).send_alert(instance, job, "TIMEOUT")
            db.commit()

        elif result["error"]:
            # --- FAILURE HANDLING ---
            raise result["error"]

        else:
            # --- SUCCESS ---
            instance.status = InstanceStatus.SUCCESS
            instance.finished_at = now
            instance.duration_seconds = (
                now - instance.started_at
            ).total_seconds()
            instance.output = result["output"]
            db.commit()
            logger.info(
                f"Instance {instance_id} succeeded "
                f"in {instance.duration_seconds:.2f}s"
            )

            # Check failure threshold — auto-pause if too many failures
            _check_failure_threshold(job, db)

    except Exception as e:
        logger.error(f"Instance {instance_id} failed: {e}")
        db.rollback()

        instance = db.query(JobInstance).filter(
            JobInstance.id == instance_id
        ).first()

        if instance:
            job = db.query(JobDefinition).filter(
                JobDefinition.id == instance.job_definition_id
            ).first()

            instance.error_message = str(e)
            instance.traceback = traceback.format_exc()
            instance.finished_at = datetime.now(timezone.utc)

            if job and instance.attempt < job.max_retries:
                _schedule_retry(instance, job, db)
            else:
                _move_to_dead_letter(instance, db)

                from app.services.alert_service import AlertService
                AlertService(db).send_alert(instance, job, "FAILED")
            db.commit()
    finally:
        db.close()


# FAILURE THRESHOLD (Phase 3 feature — wired in now)

def _check_failure_threshold(job: JobDefinition, db):

    from app.models import JobStatus

    recent = db.query(JobInstance).filter(
        JobInstance.job_definition_id == job.id,
        JobInstance.status.in_([
            InstanceStatus.SUCCESS,
            InstanceStatus.FAILED,
            InstanceStatus.TIMEOUT,
        ])
    ).order_by(JobInstance.created_at.desc()).limit(20).all()

    if len(recent) < 5:
        return  # not enough data yet

    failures = sum(
        1 for i in recent
        if i.status in (InstanceStatus.FAILED, InstanceStatus.TIMEOUT)
    )
    rate = failures / len(recent)

    if rate > job.failure_threshold:
        logger.warning(
            f"Auto-pausing {job.name}: "
            f"failure rate {rate:.0%} exceeds threshold {job.failure_threshold:.0%}"
        )
        job.status = JobStatus.PAUSED
        db.commit()