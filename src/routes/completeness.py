import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import (
    CompletenessController,
    DocumentValidationError,
    JobController,
    UploadController,
)
from db import get_db
from dependencies import governed_user, require_admin
from helpers import get_settings, sanitize_filename, unique_storage_name
from helpers.completeness_gaps import is_mandatory_gap
from helpers.offer_events import record_completeness_rechecked
from helpers.visibility import visible_offer
from models.db_schema import CompletenessEvidence, CompletenessRequirement, Offer, User
from models.enums import (
    CompletenessVerdict,
    EvidenceKind,
    JobKind,
    RequirementGroup,
    ResponseSignal,
)
from pipeline import runner
from schema.completeness import (
    CompletenessEvidenceOut,
    CompletenessOverrideRequest,
    CompletenessResultOut,
    CompletenessSummary,
    OfferCompletenessResponse,
    RequirementOut,
    RequirementUpdateRequest,
)
from schema.jobs import JobOut, JobStage

logger = logging.getLogger(__name__)

completeness_router = APIRouter(
    prefix="/api/v1",
    tags=["completeness"],
    dependencies=[Depends(governed_user)],
)

# Extensions that are accepted when the browser reports a generic content type.
# Outlook .msg in particular arrives as application/octet-stream from most
# browsers, and it is the client's primary evidence format - refusing it would
# make the override rule unusable in practice.
_GENERIC_TYPE_EXTENSIONS = {".msg", ".eml"}


def _to_result_out(row, evidence_names: dict[uuid.UUID, str]) -> CompletenessResultOut:
    return CompletenessResultOut(
        result_id=row.result_id,
        requirement_code=row.requirement_code,
        requirement_label=row.requirement_label,
        requirement_group=RequirementGroup(row.requirement_group),
        was_mandatory=row.was_mandatory,
        sort_order=row.sort_order,
        verdict=CompletenessVerdict(row.verdict),
        extracted_value=row.extracted_value,
        normalized_value=row.normalized_value,
        evidence_quote=row.evidence_quote,
        source_document_id=row.source_document_id,
        source_filename=row.source_filename,
        source_page_number=row.source_page_number,
        reasoning=row.reasoning,
        is_overridden=row.is_overridden,
        override_verdict=(
            CompletenessVerdict(row.override_verdict) if row.override_verdict else None
        ),
        override_value=row.override_value,
        override_note=row.override_note,
        override_evidence_id=row.override_evidence_id,
        override_evidence_filename=evidence_names.get(row.override_evidence_id),
        overridden_at=row.overridden_at,
        effective_verdict=CompletenessVerdict(row.effective_verdict),
        effective_value=row.effective_value,
        checked_at=row.checked_at,
    )


def _summarize(results: list[CompletenessResultOut]) -> CompletenessSummary:
    counts = {verdict: 0 for verdict in CompletenessVerdict}
    for result in results:
        counts[result.effective_verdict] += 1
    return CompletenessSummary(
        total=len(results),
        present=counts[CompletenessVerdict.PRESENT],
        missing=counts[CompletenessVerdict.MISSING],
        unclear=counts[CompletenessVerdict.UNCLEAR],
        not_applicable=counts[CompletenessVerdict.NOT_APPLICABLE],
        # The number that actually means "go back to the supplier": a term that
        # was required and is either absent or too vague to act on. Shared with
        # the offers list and the offer header, so the badge and the section can
        # never disagree about how many gaps an offer has.
        mandatory_gaps=sum(
            1
            for result in results
            if is_mandatory_gap(
                was_mandatory=result.was_mandatory,
                effective_verdict=result.effective_verdict.value,
            )
        ),
        overridden=sum(1 for result in results if result.is_overridden),
    )


@completeness_router.get(
    "/offers/{offer_id}/completeness",
    response_model=OfferCompletenessResponse,
    dependencies=[Depends(visible_offer)],
)
async def get_completeness(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
) -> OfferCompletenessResponse:
    """What this offer states, and - the point of the whole feature - what it
    does not."""
    controller = CompletenessController(db)
    rows = await controller.get_results(offer_id)
    evidence = await controller.get_evidence(offer_id)
    evidence_names = {item.evidence_id: item.original_filename for item in evidence}

    results = [_to_result_out(row, evidence_names) for row in rows]
    return OfferCompletenessResponse(
        signal=ResponseSignal.COMPLETENESS_COMPLETED,
        offer_id=offer_id,
        checked_at=min((row.checked_at for row in rows), default=None),
        summary=_summarize(results),
        results=results,
        evidence=[CompletenessEvidenceOut.model_validate(item) for item in evidence],
    )


@completeness_router.post(
    "/offers/{offer_id}/completeness/recheck",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(visible_offer)],
)
async def recheck_completeness(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> JobOut:
    """Runs the check again over the offer as it now stands.

    Re-runnable by design, and this is what makes it useful: run it again when a
    late technical file arrives for an existing offer, when a reviewer records
    an override, or when a v2 supersedes a v1. It never touches the offer
    itself - reviewer overrides and their evidence survive every re-run.
    """
    offer = await db.get(Offer, offer_id)
    # None only if the offer was discarded mid-request, and only unfinished
    # offers can be discarded - so "not finished" is the right answer for it.
    if offer is None or offer.persisted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This offer has not finished processing yet, so there is nothing to check.",
        )

    job = await JobController(db).create_job(
        kind=JobKind.COMPLETENESS, offer_id=offer_id, user=user
    )
    # "Tarek Nour re-ran the completeness check". Written here rather than in
    # the node that does the work, because this is the only place that knows
    # who asked for it - the run itself happens on a background task with no
    # request behind it.
    await record_completeness_rechecked(offer_id=offer_id, actor=user)
    runner.start_job(job.job_id, JobKind.COMPLETENESS, offer_id, [])
    return JobOut(
        job_id=job.job_id,
        kind=JobKind.COMPLETENESS,
        status=job.status,
        offer_id=offer_id,
        stages=[JobStage.model_validate(stage) for stage in (job.stages or [])],
        current_stage=job.current_stage,
        progress_percent=job.progress_percent,
        created_at=job.created_at,
        updated_at=job.updated_at,
        offer_persisted=True,
    )


@completeness_router.post(
    "/offers/{offer_id}/completeness/evidence",
    response_model=CompletenessEvidenceOut,
    dependencies=[Depends(visible_offer)],
)
async def upload_evidence(
    offer_id: int,
    requirement_code: str = Form(...),
    evidence_kind: EvidenceKind = Form(EvidenceKind.EMAIL),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> CompletenessEvidenceOut:
    """Attaches the document behind an override.

    Stored separately from the offer's own documents, deliberately. Two reasons,
    both of which would otherwise bite: `documents.file_checksum` is globally
    unique, so a forwarded email already seen on another offer would come back
    as a duplicate and the attachment would appear to fail for no reason; and
    everything under an offer's documents is fed to extraction as source text,
    so evidence filed there would end up being read as part of the offer it is
    commenting on.
    """
    settings = get_settings()

    filename = file.filename or "evidence"
    suffix = Path(filename).suffix.lower()
    if (
        file.content_type == "application/octet-stream"
        and suffix not in _GENERIC_TYPE_EXTENSIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "This file's type could not be identified. Attach a saved email (.eml or .msg), "
                "a PDF, an image, or a Word document."
            ),
        )

    upload_controller = UploadController(db)
    try:
        content, checksum, size = await upload_controller.validate_and_buffer(
            file, allowed_types=settings.EVIDENCE_ALLOWED_TYPES
        )
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc

    evidence_dir = Path(upload_controller.files_dir) / str(offer_id) / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    storage_filename = unique_storage_name(evidence_dir, sanitize_filename(filename))
    (evidence_dir / storage_filename).write_bytes(content)

    evidence = CompletenessEvidence(
        offer_id=offer_id,
        requirement_code=requirement_code,
        evidence_kind=evidence_kind.value,
        original_filename=filename,
        storage_path=f"assets/offers/{offer_id}/evidence/{storage_filename}",
        file_type=file.content_type or "application/octet-stream",
        file_size=size,
        file_checksum=checksum,
        uploaded_by_user_id=user.id,
    )
    db.add(evidence)
    await db.commit()
    await db.refresh(evidence)
    return CompletenessEvidenceOut.model_validate(evidence)


@completeness_router.get(
    "/offers/{offer_id}/completeness/evidence/{evidence_id}",
    dependencies=[Depends(visible_offer)],
)
async def download_evidence(
    offer_id: int,
    evidence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    # The evidence is looked up by offer AND id, which is what ties it to the
    # offer the guard just checked - an id from another offer finds nothing.
    controller = CompletenessController(db)
    evidence = await controller.get_evidence_file(offer_id, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found.")

    absolute = Path(controller.base_dir) / evidence.storage_path
    if not absolute.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This evidence file is recorded but is no longer on disk.",
        )
    return FileResponse(
        absolute, filename=evidence.original_filename, media_type=evidence.file_type
    )


@completeness_router.post(
    "/offers/{offer_id}/completeness/{requirement_code}/override",
    response_model=CompletenessResultOut,
    dependencies=[Depends(visible_offer)],
)
async def override_result(
    offer_id: int,
    requirement_code: str,
    body: CompletenessOverrideRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> CompletenessResultOut:
    """Records a reviewer's correction to one verdict.

    Requires attached evidence, and the requirement is enforced in three places
    on purpose - the request schema has no default for it, this handler checks
    the file really belongs to this offer, and the table carries a CHECK
    constraint. The client was unambiguous: "I called him on the phone" is not
    an override.
    """
    controller = CompletenessController(db)

    result = await controller.get_result(offer_id, requirement_code)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No completeness result for '{requirement_code}' on this offer. "
                "Run the completeness check first."
            ),
        )

    evidence = await controller.get_evidence_file(offer_id, body.evidence_id)
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That evidence file does not belong to this offer. Attach the document first.",
        )

    result = await controller.apply_override(
        result=result,
        verdict=body.verdict.value,
        value=body.value,
        note=body.note,
        evidence=evidence,
        user=user,
    )
    return _to_result_out(result, {evidence.evidence_id: evidence.original_filename})


@completeness_router.post(
    "/offers/{offer_id}/completeness/{requirement_code}/override/clear",
    response_model=CompletenessResultOut,
    dependencies=[Depends(visible_offer)],
)
async def clear_result_override(
    offer_id: int,
    requirement_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(governed_user),
) -> CompletenessResultOut:
    """Removes a correction, showing the machine verdict again. The evidence
    file itself is kept - it is a record of what was asked and answered."""
    controller = CompletenessController(db)
    result = await controller.get_result(offer_id, requirement_code)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found.")
    # The signed-in user is passed through so the activity log can name who
    # undid the correction - an undo is as much a change to what this offer
    # reports as the correction was.
    result = await controller.clear_override(result, user)
    return _to_result_out(result, {})


@completeness_router.get("/completeness/requirements", response_model=list[RequirementOut])
async def list_requirements(db: AsyncSession = Depends(get_db)) -> list[RequirementOut]:
    """The checklist itself. Readable by anyone signed in - a reviewer should be
    able to see the rule a verdict was judged under."""
    rows = (
        await db.execute(
            select(CompletenessRequirement).order_by(
                CompletenessRequirement.sort_order, CompletenessRequirement.code
            )
        )
    ).scalars().all()
    return [RequirementOut.model_validate(row) for row in rows]


@completeness_router.post(
    "/completeness/requirements/{code}",
    response_model=RequirementOut,
    dependencies=[Depends(require_admin)],
)
async def update_requirement(
    code: str,
    body: RequirementUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> RequirementOut:
    """Admin edit of one checklist row.

    `code` is not editable: results are recorded against it, and changing it
    would orphan every verdict already judged under that rule. Past results keep
    the label and mandatory flag they were judged under regardless, because each
    result row snapshots them.
    """
    row = (
        await db.execute(select(CompletenessRequirement).where(CompletenessRequirement.code == code))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No requirement with code '{code}'."
        )

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return RequirementOut.model_validate(row)
