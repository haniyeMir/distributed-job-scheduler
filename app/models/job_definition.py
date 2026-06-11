import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, JSON, Enum, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import ScheduleType, JobStatus, Priority


class JobDefinition(Base):
    
    __tablename__ = "job_definition"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)

    # periodic or one_time
    schedule_type: Mapped[ScheduleType] = mapped_column(
        Enum(ScheduleType), nullable=False
    )
    # cron expression 
    cron_expression: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # JSON payload passed to the worker on each execution
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Execution config
    priority: Mapped[Priority] = mapped_column(
        Enum(Priority), nullable=False, default=Priority.NORMAL
    )
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_execution_time: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300  # seconds
    )
    # max parallel instances of this job type allowed at once
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # auto-pause if failure rate exceeds this 
    failure_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )

    # Job registry status
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), nullable=False, default=JobStatus.ACTIVE
    )

    # Where to POST alerts on FAILED or TIMEOUT
    alert_webhook: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    instances: Mapped[list["JobInstance"]] = relationship(
        "JobInstance", back_populates="job_definition", cascade="all, delete-orphan"
    )
    dependencies: Mapped[list["JobDependency"]] = relationship(
        "JobDependency",
        foreign_keys="JobDependency.job_id",
        back_populates="job",
        cascade="all, delete-orphan",
    )
    dependents: Mapped[list["JobDependency"]] = relationship(
        "JobDependency",
        foreign_keys="JobDependency.depends_on_id",
        back_populates="depends_on",
    )

    def __repr__(self) -> str:
        return f"<JobDefinition {self.name} [{self.status}]>"
