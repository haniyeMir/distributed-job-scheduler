from datetime import datetime
from typing import Optional
from croniter import croniter
from sqlalchemy.orm import Session

from app.models import (
    JobDefinition, JobInstance,
    InstanceStatus, JobStatus,
    ScheduleType, Priority
)


class JobService:

    def __init__(self, db: Session):
        self.db = db

    # CREATE

    def create_job(self, data: dict) -> JobDefinition:
       
        # Validate: periodic jobs MUST have a cron expression
        if data["schedule_type"] == "periodic" and not data.get("cron_expression"):
            raise ValueError("Periodic jobs require a cron_expression")

        # Validate: one_time jobs must NOT have a cron expression
        if data["schedule_type"] == "one_time" and data.get("cron_expression"):
            raise ValueError("One-time jobs cannot have a cron_expression")

        job = JobDefinition(
            name=data["name"],
            job_type=data["job_type"],
            schedule_type=ScheduleType(data["schedule_type"]),
            cron_expression=data.get("cron_expression"),
            payload=data.get("payload"),
            priority=Priority(data.get("priority", "normal")),
            max_retries=data.get("max_retries", 3),
            max_execution_time=data.get("max_execution_time", 300),
            max_concurrency=data.get("max_concurrency", 1),
            failure_threshold=data.get("failure_threshold", 0.5),
            alert_webhook=data.get("alert_webhook"),
            status=JobStatus.ACTIVE,
        )
        self.db.add(job)
        self.db.flush()  # gets the ID without committing yet

        # For one_time jobs, create the first pending instance immediately
        if job.schedule_type == ScheduleType.ONE_TIME:
            self._create_instance(job, scheduled_at=datetime.utcnow())

        self.db.commit()
        self.db.refresh(job)
        return job

    # READ

    def get_all_jobs(self, status: Optional[str] = None) -> list:
        query = self.db.query(JobDefinition)
        if status:
            query = query.filter(JobDefinition.status == JobStatus(status))
        return query.order_by(JobDefinition.created_at.desc()).all()

    def get_job_by_id(self, job_id: str) -> Optional[JobDefinition]:
        return self.db.query(JobDefinition).filter(
            JobDefinition.id == job_id
        ).first()

    # UPDATE

    def update_job(self, job_id: str, data: dict) -> Optional[JobDefinition]:
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        for key, value in data.items():
            setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # PAUSE / RESUME / ARCHIVE

    def pause_job(self, job_id: str) -> Optional[JobDefinition]:
       
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        if job.status != JobStatus.ACTIVE:
            raise ValueError(f"Only active jobs can be paused. Current status: {job.status}")
        job.status = JobStatus.PAUSED
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def resume_job(self, job_id: str) -> Optional[JobDefinition]:
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        if job.status != JobStatus.PAUSED:
            raise ValueError(f"Only paused jobs can be resumed. Current status: {job.status}")
        job.status = JobStatus.ACTIVE
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    def archive_job(self, job_id: str) -> Optional[JobDefinition]:
        
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        job.status = JobStatus.ARCHIVED
        job.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(job)
        return job

    # MANUAL TRIGGER

    def trigger_job(self, job_id: str) -> Optional[JobInstance]:
      
        job = self.get_job_by_id(job_id)
        if not job:
            return None
        if job.status != JobStatus.ACTIVE:
            raise ValueError("Only active jobs can be triggered manually")
        instance = self._create_instance(job, scheduled_at=datetime.utcnow())
        self.db.commit()
        return instance

    # INTERNAL HELPERS

    def _create_instance(
        self, job: JobDefinition, scheduled_at: datetime
    ) -> JobInstance:
     
        instance = JobInstance(
            job_definition_id=job.id,
            status=InstanceStatus.PENDING,
            priority=job.priority,
            payload_snapshot=job.payload,  # snapshot at creation time
            scheduled_at=scheduled_at,
            attempt=0,
        )
        self.db.add(instance)
        return instance

    def _get_next_run_time(self, cron_expression: str) -> datetime:
        cron = croniter(cron_expression, datetime.utcnow())
        return cron.get_next(datetime)