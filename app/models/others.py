import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, JSON, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class JobDependency(Base):
   
    __tablename__ = "job_dependency"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_definition.id"), nullable=False
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_definition.id"), nullable=False
    )

    # Relationships
    job: Mapped["JobDefinition"] = relationship(
        "JobDefinition", foreign_keys=[job_id], back_populates="dependencies"
    )
    depends_on: Mapped["JobDefinition"] = relationship(
        "JobDefinition", foreign_keys=[depends_on_id], back_populates="dependents"
    )

    def __repr__(self) -> str:
        return f"<JobDependency {self.job_id} depends on {self.depends_on_id}>"


class DeadLetter(Base):
   
    __tablename__ = "dead_letter"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_instance.id"), nullable=False, unique=True
    )
    job_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_definition.id"), nullable=False
    )

    # Why it ended up here
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    last_error: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    job_instance: Mapped["JobInstance"] = relationship(
        "JobInstance", back_populates="dead_letter"
    )
    job_definition: Mapped["JobDefinition"] = relationship("JobDefinition")

    def __repr__(self) -> str:
        return f"<DeadLetter instance={self.job_instance_id}>"


class AlertLog(Base):
  
    __tablename__ = "alert_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_instance.id"), nullable=False
    )

    # "FAILED", "TIMEOUT"
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # "webhook", "slack", "email"
    channel: Mapped[str] = mapped_column(String(50), nullable=False)

    # HTTP response code from the alert endpoint
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    job_instance: Mapped["JobInstance"] = relationship(
        "JobInstance", back_populates="alert_logs"
    )

    def __repr__(self) -> str:
        return f"<AlertLog {self.event_type} via {self.channel}>"
