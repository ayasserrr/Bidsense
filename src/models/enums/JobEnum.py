from enum import Enum


class JobKind(str, Enum):
    """What a background job is doing.

    `offer_pipeline` is the long one - parse through persist for a freshly
    uploaded offer. The others re-run a single post-persist analysis over an
    offer that is already saved, which is why they can be repeated as often as
    a reviewer likes without risking the offer itself.
    """

    OFFER_PIPELINE = "offer_pipeline"
    COMPLETENESS = "completeness"
    TAXONOMY = "taxonomy"
    SUMMARY = "summary"


class JobStatus(str, Enum):
    """Lifecycle of one background job.

    `queued` exists for the short window between the row being written and the
    worker actually picking it up. A job left `queued` or `running` after a
    server restart is stale - nothing resumes it - and `JobController.reap_
    stale_jobs` fails it explicitly at startup rather than letting the UI poll
    something that will never move again.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}


class JobStageStatus(str, Enum):
    """Per-stage status inside a job, mirroring what the progress list shows."""

    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"
