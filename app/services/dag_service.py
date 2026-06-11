import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.models import JobDefinition, JobDependency, JobInstance, InstanceStatus

logger = logging.getLogger(__name__)


class DAGService:

    def __init__(self, db: Session):
        self.db = db

  
    # CYCLE DETECTION

    def has_cycle(self, job_id: str, depends_on_id: str) -> bool:
     
        visited = set()

        def dfs(current_id: str) -> bool:
            if current_id == job_id:
                # We reached the starting job 
                return True
            if current_id in visited:
                return False
            visited.add(current_id)

            # Get all jobs that current_id depends on
            dependencies = self.db.query(JobDependency).filter(
                JobDependency.job_id == current_id
            ).all()

            for dep in dependencies:
                if dfs(str(dep.depends_on_id)):
                    return True
            return False

        return dfs(depends_on_id)

    # ADD DEPENDENCY

    def add_dependency(self, job_id: str, depends_on_id: str) -> JobDependency:
    
        # Validate both jobs exist
        job = self.db.query(JobDefinition).filter(
            JobDefinition.id == job_id
        ).first()
        depends_on = self.db.query(JobDefinition).filter(
            JobDefinition.id == depends_on_id
        ).first()

        if not job:
            raise ValueError(f"Job {job_id} not found")
        if not depends_on:
            raise ValueError(f"Dependency job {depends_on_id} not found")
        if job_id == depends_on_id:
            raise ValueError("A job cannot depend on itself")

        # Check for duplicate
        existing = self.db.query(JobDependency).filter(
            JobDependency.job_id == job_id,
            JobDependency.depends_on_id == depends_on_id,
        ).first()
        if existing:
            raise ValueError("This dependency already exists")

        # Check for cycle 
        if self.has_cycle(job_id, depends_on_id):
            raise ValueError(
                f"Adding this dependency would create a cycle: "
                f"{job.name} → {depends_on.name} creates a circular dependency"
            )

        dep = JobDependency(
            job_id=job_id,
            depends_on_id=depends_on_id,
        )
        self.db.add(dep)
        self.db.commit()

        logger.info(f"Dependency added: {job.name} depends on {depends_on.name}")
        return dep

    # GET DEPENDENCIES
    
    def get_dependencies(self, job_id: str) -> list:
        """Returns all jobs that job_id depends on."""
        return self.db.query(JobDependency).filter(
            JobDependency.job_id == job_id
        ).all()

    def get_dependents(self, job_id: str) -> list:
        """Returns all jobs that depend on job_id."""
        return self.db.query(JobDependency).filter(
            JobDependency.depends_on_id == job_id
        ).all()

    # DEPENDENCY SATISFACTION CHECK

    def are_dependencies_met(self, job_id: str) -> bool:
      
        dependencies = self.get_dependencies(job_id)

        if not dependencies:
            # No dependencies 
            return True

        for dep in dependencies:
            # Find the most recent instance of the dependency job
            latest = self.db.query(JobInstance).filter(
                JobInstance.job_definition_id == dep.depends_on_id,
            ).order_by(JobInstance.created_at.desc()).first()

            if not latest or latest.status != InstanceStatus.SUCCESS:
                logger.debug(
                    f"Dependency not met: job {dep.depends_on_id} "
                    f"has not completed successfully yet"
                )
                return False

        return True

    # REMOVE DEPENDENCY

    def remove_dependency(self, job_id: str, depends_on_id: str) -> bool:
        dep = self.db.query(JobDependency).filter(
            JobDependency.job_id == job_id,
            JobDependency.depends_on_id == depends_on_id,
        ).first()

        if not dep:
            return False

        self.db.delete(dep)
        self.db.commit()
        return True