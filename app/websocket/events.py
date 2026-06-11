import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def register_events(socketio):
    @socketio.on("connect")
    def handle_connect():
        logger.info("Dashboard client connected")

    @socketio.on("disconnect")
    def handle_disconnect():
        logger.info("Dashboard client disconnected")


def start_background_pusher(socketio):
  
    def push_loop():
        while True:
            socketio.sleep(3)
            try:
                stats = _get_live_stats()
                socketio.emit("stats_update", stats)
            except Exception as e:
                logger.error(f"Background push error: {e}")

    socketio.start_background_task(push_loop)


def _get_live_stats() -> dict:
    from app.database import SessionLocal
    from app.models import JobInstance, JobDefinition, InstanceStatus, JobStatus

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        last_24h = now - timedelta(hours=24)

        recent = db.query(JobInstance).filter(
            JobInstance.created_at >= last_24h
        ).all()

        return {
            "total_jobs": db.query(JobDefinition).count(),
            "active_jobs": db.query(JobDefinition).filter(
                JobDefinition.status == JobStatus.ACTIVE
            ).count(),
            "currently_running": db.query(JobInstance).filter(
                JobInstance.status == InstanceStatus.RUNNING
            ).count(),
            "total_executions": db.query(JobInstance).count(),
            "success_24h": sum(
                1 for i in recent if i.status == InstanceStatus.SUCCESS
            ),
            "failed_24h": sum(
                1 for i in recent
                if i.status in (InstanceStatus.FAILED, InstanceStatus.TIMEOUT)
            ),
            "timestamp": now.isoformat(),
        }
    finally:
        db.close()


def emit_job_event(event_type: str, data: dict):
    try:
        from app import socketio
        socketio.emit("job_event", {"type": event_type, **data})
    except Exception as e:
        logger.error(f"Failed to emit job event: {e}")