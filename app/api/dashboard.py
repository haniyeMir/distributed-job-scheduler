from flask import Blueprint, jsonify, request, render_template
from datetime import datetime, timezone, timedelta

from app.database import SessionLocal
from app.models import JobInstance, JobDefinition, InstanceStatus, JobStatus

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/")
def index():
    return render_template("dashboard.html")


# STATS

@dashboard.route("/api/dashboard/stats")
def get_stats():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        last_24h = now - timedelta(hours=24)
        recent = db.query(JobInstance).filter(
            JobInstance.created_at >= last_24h
        ).all()

        return jsonify({
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
        })
    finally:
        db.close()


# CHART — success vs failure per hour over last 24h

@dashboard.route("/api/dashboard/chart")
def get_chart_data():
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        hours = []

        for i in range(23, -1, -1):
            start = now - timedelta(hours=i + 1)
            end = now - timedelta(hours=i)
            instances = db.query(JobInstance).filter(
                JobInstance.created_at >= start,
                JobInstance.created_at < end,
            ).all()

            hours.append({
                "hour": start.strftime("%H:%M"),
                "success": sum(
                    1 for inst in instances
                    if inst.status == InstanceStatus.SUCCESS
                ),
                "failed": sum(
                    1 for inst in instances
                    if inst.status in (
                        InstanceStatus.FAILED, InstanceStatus.TIMEOUT
                    )
                ),
            })

        return jsonify({"data": hours})
    finally:
        db.close()



# INSTANCES TABLE — filterable

@dashboard.route("/api/dashboard/instances")
def get_instances():
    db = SessionLocal()
    try:
        status = request.args.get("status")
        job_type = request.args.get("job_type")
        hours = int(request.args.get("hours", 24))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        query = db.query(JobInstance).filter(
            JobInstance.created_at >= cutoff
        )
        if status:
            try:
                query = query.filter(
                    JobInstance.status == InstanceStatus(status)
                )
            except ValueError:
                pass

        instances = query.order_by(
            JobInstance.created_at.desc()
        ).limit(100).all()

        result = []
        for inst in instances:
            job = db.query(JobDefinition).filter(
                JobDefinition.id == inst.job_definition_id
            ).first()
            if job_type and job and job.job_type != job_type:
                continue
            result.append({
                "id": str(inst.id),
                "job_name": job.name if job else "Unknown",
                "job_type": job.job_type if job else "Unknown",
                "status": inst.status.value,
                "attempt": inst.attempt,
                "worker_id": inst.worker_id,
                "started_at": inst.started_at.isoformat() if inst.started_at else None,
                "finished_at": inst.finished_at.isoformat() if inst.finished_at else None,
                "duration_seconds": inst.duration_seconds,
                "error_message": inst.error_message,
            })

        return jsonify({"instances": result})
    finally:
        db.close()



# WORKER HEALTH

@dashboard.route("/api/dashboard/workers")
def get_workers():
    try:
        from app.tasks.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=2)
        active = inspect.active() or {}
        registered = inspect.registered() or {}

        workers = []
        all_names = set(active.keys()) | set(registered.keys())

        for name in all_names:
            tasks = active.get(name, [])
            workers.append({
                "name": name,
                "status": "active" if tasks else "idle",
                "active_tasks": len(tasks),
            })

        return jsonify({"workers": workers})
    except Exception as e:
        return jsonify({"workers": [], "error": str(e)})


# QUEUE DEPTH

@dashboard.route("/api/dashboard/queues")
def get_queue_depth():
    try:
        import requests as req
        from config import Config

        resp = req.get(
            f"http://{Config.RABBITMQ_HOST}:15672/api/queues",
            auth=(Config.RABBITMQ_USER, Config.RABBITMQ_PASSWORD),
            timeout=3,
        )
        data = resp.json()
        queues = {
            q["name"]: q.get("messages", 0)
            for q in data
            if q.get("name") in ("high", "normal", "low")
        }
        for name in ("high", "normal", "low"):
            queues.setdefault(name, 0)

        return jsonify({"queues": queues})
    except Exception as e:
        return jsonify({
            "queues": {"high": 0, "normal": 0, "low": 0},
            "error": str(e),
        })



# GANTT TIMELINE

@dashboard.route("/api/dashboard/timeline")
def get_timeline():
    db = SessionLocal()
    try:
        instances = db.query(JobInstance).filter(
            JobInstance.started_at.isnot(None),
            JobInstance.finished_at.isnot(None),
        ).order_by(JobInstance.started_at.desc()).limit(20).all()

        result = []
        for inst in instances:
            job = db.query(JobDefinition).filter(
                JobDefinition.id == inst.job_definition_id
            ).first()
            result.append({
                "id": str(inst.id),
                "job_name": job.name if job else "Unknown",
                "status": inst.status.value,
                "started_at": inst.started_at.isoformat(),
                "finished_at": inst.finished_at.isoformat(),
                "duration_seconds": inst.duration_seconds,
                "worker_id": inst.worker_id,
            })

        return jsonify({"timeline": result})
    finally:
        db.close()