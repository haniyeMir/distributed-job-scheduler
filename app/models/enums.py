import enum


class ScheduleType(str, enum.Enum):
    PERIODIC = "periodic"
    ONE_TIME = "one_time"


class JobStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Priority(str, enum.Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class InstanceStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


# Valid state machine transitions r
VALID_TRANSITIONS = {
    InstanceStatus.PENDING:  {InstanceStatus.QUEUED},
    InstanceStatus.QUEUED:   {InstanceStatus.RUNNING},
    InstanceStatus.RUNNING:  {InstanceStatus.SUCCESS, InstanceStatus.FAILED, InstanceStatus.TIMEOUT},
    InstanceStatus.FAILED:   {InstanceStatus.QUEUED},   # on retry
    InstanceStatus.TIMEOUT:  {InstanceStatus.QUEUED},   # on retry
    InstanceStatus.SUCCESS:  set(),                     # terminal
}


def is_valid_transition(current: InstanceStatus, next_status: InstanceStatus) -> bool:
    return next_status in VALID_TRANSITIONS.get(current, set())
