"""Progress reporting for a background job.

Everything here writes to the `pipeline_jobs` row, because that row - not an
in-memory handle - is what a status poll reads. A stage transition is a few
extra UPDATEs per run, which is nothing next to the LLM calls they are
reporting on, and it buys a run that survives the browser closing.

Two stages can be running at once now: the completeness scan starts alongside
extraction (see `pipeline/prescan.py`). Everything below that used to assume a
single running stage - one progress fraction, and "current stage" meaning
whichever stage reported last - is per-stage or derived instead.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db_schema import PipelineJob
from models.enums import JobStageStatus

from .stages import StageDefinition

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


class JobCancelled(Exception):
    """A cancel was requested and the runner stopped at a stage boundary."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def initial_stage_snapshot(stages: tuple[StageDefinition, ...]) -> list[dict]:
    """The stage list as first written to the job row.

    `started_at`/`finished_at` are stamped as the run goes, so afterwards the
    row itself answers where the time went. Without them the only record of a
    stage's duration was a log line, and a log line has rotated away by the time
    anyone asks why an offer took ten minutes.
    """
    return [
        {
            "id": stage.id,
            "label": stage.label,
            "weight": stage.weight,
            "status": JobStageStatus.PENDING.value,
            "detail": None,
            # How much of ITS OWN weight a running stage has earned.
            "fraction": 0.0,
            "started_at": None,
            "finished_at": None,
        }
        for stage in stages
    ]


def compute_percent(snapshot: list[dict]) -> int:
    """Weighted completion, 0-100.

    A stage that is running contributes its own `fraction` of its own weight, so
    extraction - the long one - can move the bar as its chunks land instead of
    sitting at one number for ten minutes.

    The fraction is per stage, which is load-bearing now that two of them run at
    once: a single fraction applied to every ACTIVE stage meant the completeness
    scan reporting "5 of 5 excerpts read" also credited extraction's whole
    44-point weight, so the bar jumped forward and then fell back on
    extraction's next update.

    Capped at 99 while anything is still running: 100 belongs to a finished job,
    and a bar that reads 100% while the UI still says "in progress" reads as a
    bug.

    A SKIPPED stage earns nothing. Skipping only ever happens when a run has
    already failed or been cancelled, so crediting it would send a job that
    died at the first stage out at nearly 100% - which is exactly what it did
    before this was fixed.
    """
    total_weight = sum(stage.get("weight", 0) for stage in snapshot) or 100
    earned = 0.0
    running = False
    for stage in snapshot:
        weight = stage.get("weight", 0)
        status = stage.get("status")
        if status == JobStageStatus.DONE.value:
            earned += weight
        elif status == JobStageStatus.ACTIVE.value:
            fraction = stage.get("fraction") or 0.0
            earned += weight * max(0.0, min(1.0, fraction))
            running = True
        elif status == JobStageStatus.ERROR.value:
            # A failed stage earns nothing further, but the bar must not go
            # backwards - the stages before it keep what they earned.
            pass
    percent = int(round(100 * earned / total_weight))
    if running:
        percent = min(percent, 99)
    return max(0, min(100, percent))


def headline_stage(snapshot: list[dict]) -> str | None:
    """Which stage a run should be reported as being in, or None if none is.

    The FIRST running stage in list order, not whichever one reported last.
    That distinction only appeared when the completeness scan started running
    alongside extraction: `pipeline.runner` reads this back off the row to
    decide which stage to mark as the one that failed, so "last to report" would
    record an extraction failure against completeness and show the reviewer the
    wrong failed step. The frontend picks its headline label the same way, so
    the two always agree.
    """
    for stage in snapshot:
        if stage.get("status") == JobStageStatus.ACTIVE.value:
            return stage["id"]
    return None


class JobProgress:
    """Records what a running job is doing.

    Opens its own short-lived session per update rather than borrowing the
    runner's: the runner holds a session across a stage that can run for
    minutes, and a long-open transaction would keep every progress write
    invisible to the polling endpoint until the stage finished - which is
    exactly the opposite of the point.
    """

    def __init__(
        self,
        *,
        job_id: uuid.UUID,
        session_factory: SessionFactory,
        stages: tuple[StageDefinition, ...],
    ):
        self.job_id = job_id
        self._session_factory = session_factory
        self._snapshot = initial_stage_snapshot(stages)
        # Changing the snapshot and writing it out is one operation, and two
        # stages report concurrently now. Without this, a reporter could read
        # the snapshot, be overtaken by another that changed AND committed, and
        # then commit its own older copy over the top - a stage row or a percent
        # that has visibly gone backwards in the UI for no reason the reviewer
        # can see.
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        """Adopts whatever the job row already says about its stages.

        Load-bearing, not a nicety: `create_job` marks the stages that happened
        inside the request itself (upload) as already done. Starting from a
        fresh all-pending snapshot would write that over on the first flush,
        and the reviewer would watch a file they have already uploaded travel
        from pending to skipped.
        """
        async with self._lock, self._session_factory() as db:
            job = await db.get(PipelineJob, self.job_id)
            if job is None or not job.stages:
                return
            saved = {stage.get("id"): stage for stage in job.stages}
            self._snapshot = [
                {**stage, **{
                    key: saved[stage["id"]][key]
                    for key in ("status", "detail")
                    if stage["id"] in saved and key in saved[stage["id"]]
                }}
                for stage in self._snapshot
            ]

    @property
    def snapshot(self) -> list[dict]:
        return [dict(stage) for stage in self._snapshot]

    def _stage(self, stage_id: str) -> dict | None:
        return next((stage for stage in self._snapshot if stage["id"] == stage_id), None)

    def _set(self, stage_id: str, **fields) -> None:
        self._snapshot = [
            {**stage, **fields} if stage["id"] == stage_id else stage for stage in self._snapshot
        ]

    async def _flush(self, *, current_stage: str | None = None) -> None:
        async with self._session_factory() as db:
            job = await db.get(PipelineJob, self.job_id)
            if job is None:
                return
            # A fresh list, not an in-place mutation: SQLAlchemy does not track
            # changes inside a JSONB value, so mutating the existing list would
            # write nothing and the UI would never move.
            job.stages = self.snapshot
            job.progress_percent = compute_percent(self._snapshot)
            # Derived rather than "whoever flushed last", which two concurrent
            # stages would flip between. An explicit value - a stage that has
            # just failed - wins over the derived one; when nothing is running
            # the column keeps what it had, because the runner reads it back
            # after a failure to name the stage that died.
            current = current_stage or headline_stage(self._snapshot)
            if current is not None:
                job.current_stage = current
            await db.commit()

    async def start_stage(self, stage_id: str, detail: str | None = None) -> None:
        """Marks a stage running, and stamps when it started.

        Starting a stage that is ALREADY running is neither a no-op nor a
        restart: the completeness scan marks its stage active while extraction
        is still going, and the completeness node picks that same stage up when
        its own turn comes. Only the detail changes then - the stage keeps its
        start time and the share of itself it has already earned, so the bar
        never dips at the handover.
        """
        async with self._lock:
            stage = self._stage(stage_id)
            if stage is not None and stage.get("status") == JobStageStatus.ACTIVE.value:
                self._set(stage_id, detail=detail)
            else:
                self._set(
                    stage_id,
                    status=JobStageStatus.ACTIVE.value,
                    detail=detail,
                    fraction=0.0,
                    started_at=utc_now().isoformat(),
                    finished_at=None,
                )
            await self._flush()

    async def update_detail(
        self, stage_id: str, detail: str, *, fraction: float = 0.0
    ) -> None:
        async with self._lock:
            self._set(stage_id, detail=detail, fraction=fraction)
            await self._flush()

    async def finish_stage(self, stage_id: str, detail: str | None = None) -> None:
        async with self._lock:
            self._set(
                stage_id,
                status=JobStageStatus.DONE.value,
                detail=detail,
                finished_at=utc_now().isoformat(),
            )
            await self._flush()

    async def skip_stage(self, stage_id: str, detail: str | None = None) -> None:
        async with self._lock:
            self._set(
                stage_id,
                status=JobStageStatus.SKIPPED.value,
                detail=detail,
                finished_at=utc_now().isoformat(),
            )
            await self._flush()

    async def fail_stage(self, stage_id: str, detail: str) -> None:
        async with self._lock:
            self._set(
                stage_id,
                status=JobStageStatus.ERROR.value,
                detail=detail,
                finished_at=utc_now().isoformat(),
            )
            # Pinned explicitly: the stage is no longer ACTIVE, so nothing would
            # derive it, and a sibling stage still running must not inherit the
            # blame for it.
            await self._flush(current_stage=stage_id)

    async def mark_remaining_skipped(self) -> None:
        """Closes out a run that stopped early.

        Includes the ACTIVE stages, not just the pending ones: a cancelled job
        would otherwise leave its current stage spinning forever in the UI. On
        the failure path that stage has already been set to ERROR by
        `fail_stage`, so it is untouched here.
        """
        stopped = {JobStageStatus.PENDING.value, JobStageStatus.ACTIVE.value}
        now = utc_now().isoformat()
        async with self._lock:
            self._snapshot = [
                {
                    **stage,
                    "status": JobStageStatus.SKIPPED.value,
                    # A stage that never started has no finish worth recording;
                    # the one that was running when the run stopped does.
                    "finished_at": now if stage.get("started_at") else stage.get("finished_at"),
                }
                if stage["status"] in stopped
                else stage
                for stage in self._snapshot
            ]
            await self._flush()

    async def is_cancel_requested(self) -> bool:
        async with self._session_factory() as db:
            result = await db.execute(
                select(PipelineJob.cancel_requested).where(PipelineJob.job_id == self.job_id)
            )
            return bool(result.scalar_one_or_none())

    async def raise_if_cancelled(self) -> None:
        if await self.is_cancel_requested():
            raise JobCancelled()
