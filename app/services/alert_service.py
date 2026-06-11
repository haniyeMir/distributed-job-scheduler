import logging
import requests
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import JobInstance, JobDefinition, AlertLog

logger = logging.getLogger(__name__)


class AlertService:

    def __init__(self, db: Session):
        self.db = db

    def send_alert(
        self,
        instance: JobInstance,
        job: JobDefinition,
        event_type: str,
    ):
   
        if not job.alert_webhook:
            return

        payload = {
            "event": event_type,
            "job_name": job.name,
            "job_id": str(job.id),
            "instance_id": str(instance.id),
            "attempt": instance.attempt,
            "error": instance.error_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._post_webhook(instance, job.alert_webhook, event_type, payload)

    def _post_webhook(
        self,
        instance: JobInstance,
        url: str,
        event_type: str,
        payload: dict,
    ):
        status_code = None
        try:
            response = requests.post(url, json=payload, timeout=5)
            status_code = response.status_code
            logger.info(
                f"Alert sent for {event_type} — "
                f"instance {instance.id} → {url} [{status_code}]"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Alert delivery failed: {e}")

        # Always log the attempt 
        log = AlertLog(
            job_instance_id=instance.id,
            event_type=event_type,
            channel="webhook",
            status_code=status_code,
            sent_at=datetime.now(timezone.utc),
        )
        self.db.add(log)
        self.db.commit()