from flask import Blueprint, jsonify, request
from marshmallow import ValidationError

from app.database import SessionLocal
from app.models import JobInstance, InstanceStatus
from app.api.schemas import CreateJobSchema, UpdateJobSchema
from app.services.job_service import JobService

api = Blueprint("api", __name__)

create_schema = CreateJobSchema()
update_schema = UpdateJobSchema()


# HEALTH + STATS

@api.route("/health")
def health():
    return jsonify({"status": "ok", "message": "Scheduler is running"})


@api.route("/stats")
def stats():
    db = SessionLocal()
    try:
        from app.models import JobDefinition
        return jsonify({
            "job_definitions": db.query(JobDefinition).count(),
            "total_executions": db.query(JobInstance).count(),
            "currently_running": db.query(JobInstance).filter(
                JobInstance.status == InstanceStatus.RUNNING
            ).count(),
            "failed": db.query(JobInstance).filter(
                JobInstance.status == InstanceStatus.FAILED
            ).count(),
        })
    finally:
        db.close()


# JOB CRUD
        
@api.route("/jobs", methods=["GET"])
def list_jobs():
    db = SessionLocal()
    try:
        status = request.args.get("status")  # ?status=active
        service = JobService(db)
        jobs = service.get_all_jobs(status=status)
        return jsonify({"jobs": [_serialize_job(j) for j in jobs]})
    finally:
        db.close()


@api.route("/jobs", methods=["POST"])
def create_job():
    db = SessionLocal()
    try:
        # Step 1: validate incoming JSON
        data = create_schema.load(request.get_json() or {})
    except ValidationError as e:
        return jsonify({"error": "Validation failed", "details": e.messages}), 400

    try:
        service = JobService(db)
        job = service.create_job(data)
        return jsonify(_serialize_job(job)), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


@api.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    db = SessionLocal()
    try:
        job = JobService(db).get_job_by_id(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(_serialize_job(job))
    finally:
        db.close()


@api.route("/jobs/<job_id>", methods=["PUT"])
def update_job(job_id):
    db = SessionLocal()
    try:
        data = update_schema.load(request.get_json() or {})
    except ValidationError as e:
        return jsonify({"error": "Validation failed", "details": e.messages}), 400

    try:
        job = JobService(db).update_job(job_id, data)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(_serialize_job(job))
    finally:
        db.close()


# JOB ACTIONS

@api.route("/jobs/<job_id>/pause", methods=["POST"])
def pause_job(job_id):
    db = SessionLocal()
    try:
        job = JobService(db).pause_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(_serialize_job(job))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


@api.route("/jobs/<job_id>/resume", methods=["POST"])
def resume_job(job_id):
    db = SessionLocal()
    try:
        job = JobService(db).resume_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(_serialize_job(job))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


@api.route("/jobs/<job_id>/archive", methods=["POST"])
def archive_job(job_id):
    db = SessionLocal()
    try:
        job = JobService(db).archive_job(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(_serialize_job(job))
    finally:
        db.close()


@api.route("/jobs/<job_id>/trigger", methods=["POST"])
def trigger_job(job_id):
    """Manually execute a job immediately, outside its schedule."""
    db = SessionLocal()
    try:
        instance = JobService(db).trigger_job(job_id)
        if not instance:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({
            "message": "Job triggered successfully",
            "instance_id": str(instance.id),
            "status": instance.status.value,
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


# DEPENDENCY MANAGEMENT

@api.route("/jobs/<job_id>/dependencies", methods=["GET"])
def get_dependencies(job_id):
    db = SessionLocal()
    try:
        from app.services.dag_service import DAGService
        dag = DAGService(db)
        deps = dag.get_dependencies(job_id)
        return jsonify({
            "job_id": job_id,
            "depends_on": [str(d.depends_on_id) for d in deps],
        })
    finally:
        db.close()


@api.route("/jobs/<job_id>/dependencies", methods=["POST"])
def add_dependency(job_id):
    db = SessionLocal()
    try:
        data = request.get_json() or {}
        depends_on_id = data.get("depends_on_id")
        if not depends_on_id:
            return jsonify({"error": "depends_on_id is required"}), 400

        from app.services.dag_service import DAGService
        dep = DAGService(db).add_dependency(job_id, depends_on_id)
        return jsonify({
            "message": "Dependency added",
            "job_id": job_id,
            "depends_on_id": depends_on_id,
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


@api.route("/jobs/<job_id>/dependencies/<depends_on_id>", methods=["DELETE"])
def remove_dependency(job_id, depends_on_id):
    db = SessionLocal()
    try:
        from app.services.dag_service import DAGService
        removed = DAGService(db).remove_dependency(job_id, depends_on_id)
        if not removed:
            return jsonify({"error": "Dependency not found"}), 404
        return jsonify({"message": "Dependency removed"})
    finally:
        db.close()

# HEALTH CHECKS 

@api.route("/health/api")
def health_api():
    """Flask API health check"""
    return jsonify({"service": "api", "status": "ok"})


@api.route("/health/worker")
def health_worker():
    """Check if at least one Celery worker is reachable"""
    try:
        from app.tasks.celery_app import celery_app
        result = celery_app.control.inspect(timeout=2).ping()
        if result:
            return jsonify({"service": "worker", "status": "ok", "workers": list(result.keys())})
        return jsonify({"service": "worker", "status": "no workers"}), 503
    except Exception as e:
        return jsonify({"service": "worker", "status": "error", "detail": str(e)}), 503


@api.route("/health/scheduler")
def health_scheduler():
    """Check if scheduler lock is active in Redis"""
    try:
        import redis
        from config import Config
        r = redis.Redis(host=Config.REDIS_HOST, port=Config.REDIS_PORT, db=0)
        r.ping()
        return jsonify({"service": "scheduler", "status": "ok"})
    except Exception as e:
        return jsonify({"service": "scheduler", "status": "error", "detail": str(e)}), 503


# SERIALIZER

def _serialize_job(job) -> dict:
 
    return {
        "id": str(job.id),
        "name": job.name,
        "job_type": job.job_type,
        "schedule_type": job.schedule_type.value,
        "cron_expression": job.cron_expression,
        "status": job.status.value,
        "priority": job.priority.value,
        "max_retries": job.max_retries,
        "max_execution_time": job.max_execution_time,
        "max_concurrency": job.max_concurrency,
        "failure_threshold": job.failure_threshold,
        "alert_webhook": job.alert_webhook,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }