import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, JSON, Text, Enum, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import InstanceStatus, Priority


class JobInstance(Base):
   
    __tablename__ = "job_instance"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_definition.id"), nullable=False
    )

    # State machine status
    status: Mapped[InstanceStatus] = mapped_column(
        Enum(InstanceStatus), nullable=False, default=InstanceStatus.PENDING
    )

    # Which retry attempt this is 
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    priority: Mapped[Priority] = mapped_column(
        Enum(Priority), nullable=False, default=Priority.NORMAL
    )

    # Snapshot of payload at execution time

    payload_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Which Celery worker picked this up 
    worker_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Failure details
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Success output
    output: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Timestamps for each state transition
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Calculated on finish
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    job_definition: Mapped["JobDefinition"] = relationship(
        "JobDefinition", back_populates="instances"
    )
    dead_letter: Mapped[Optional["DeadLetter"]] = relationship(
        "DeadLetter", back_populates="job_instance", uselist=False
    )
    alert_logs: Mapped[list["AlertLog"]] = relationship(
        "AlertLog", back_populates="job_instance", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<JobInstance {self.id} [{self.status}] attempt={self.attempt}>"
