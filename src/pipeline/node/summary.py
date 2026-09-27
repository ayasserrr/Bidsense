import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from controllers import CompletenessController
from controllers.OfferController import project_label_of
from helpers.completeness_gaps import is_mandatory_gap
from models.db_schema import Offer, OfferVerifiedFinding, Supplier, SupplierContact
from models.enums import FindingVerdict
from pipeline.progress import JobCancelled, JobProgress
from pipeline.state import PipelineState
from schema.review_summary import ChaseItem, ChaseItemKind

logger = logging.getLogger(__name__)

STAGE_ID = "summary"


async def resolve_supplier_email(db: AsyncSession, supplier_id: int | None) -> str | None:
    """The address the clarification email would go to, resolved FRESH rather
    than stored: extraction of a contact email off a supplier's own
    letterhead is unreliable, a reviewer can correct a contact's email
    independently of this offer, and a stale address cached at generation
    time would then quietly outlive the correction. Called by the route that
    serves `ReviewSummaryOut`, not by `build_review_summary` - nothing about
    it is specific to one offer's chase list.
    """
    if supplier_id is None:
        return None
    result = await db.execute(
        select(SupplierContact)
        .where(SupplierContact.supplier_id == supplier_id, SupplierContact.email.is_not(None))
        .order_by(SupplierContact.contact_id)
        .limit(1)
    )
    contact = result.scalars().first()
    return contact.email if contact else None


async def build_review_summary(db: AsyncSession, offer_id: int) -> dict:
    """Composes the detail screen's chase list and email draft for one offer.

    Every sentence here is built from a row this offer's own pipeline already
    verified - a confirmed mismatch, a mandatory term the checker could not
    find - never a fresh LLM judgement. See `schema/review_summary.py`'s
    module docstring for why. Callable standalone (the `/summary/recheck`
    route) as well as from the pipeline node below, so a reviewer who
    corrects a completeness override can regenerate this without re-reading
    the offer's documents.

    Returns a dict of the five `offers.review_*` column values, ready to
    assign onto a loaded `Offer` row - it does not write or commit itself,
    so the caller controls the transaction (the node commits once with the
    rest of its work; the standalone route commits its own).
    """
    offer = await db.get(Offer, offer_id)

    findings_result = await db.execute(
        select(OfferVerifiedFinding)
        .where(
            OfferVerifiedFinding.offer_id == offer_id,
            OfferVerifiedFinding.finding_verdict == FindingVerdict.CONFIRMED.value,
        )
        .order_by(OfferVerifiedFinding.sort_order, OfferVerifiedFinding.verified_finding_id)
    )
    confirmed_findings = list(findings_result.scalars().all())

    completeness_results = await CompletenessController(db).get_results(offer_id)
    gaps = [
        result
        for result in completeness_results
        if is_mandatory_gap(was_mandatory=result.was_mandatory, effective_verdict=result.effective_verdict)
    ]

    chase_items: list[ChaseItem] = []
    for finding in confirmed_findings:
        # `explanation` is the model's plain-language account of the mismatch;
        # `evidence_quote` is what the document actually says, verbatim. Both
        # matter to a reviewer deciding whether to chase it.
        detail = finding.explanation or finding.reasoning
        if finding.evidence_quote:
            detail = f'{detail} The offer states: "{finding.evidence_quote}"' if detail else (
                f'The offer states: "{finding.evidence_quote}"'
            )
        chase_items.append(
            ChaseItem(
                kind=ChaseItemKind.CONFIRMED_FINDING,
                title=finding.field_path.replace("_", " ").replace(".", " → ").capitalize(),
                detail=detail or "Confirmed against the source document.",
            )
        )
    for gap in gaps:
        verb = "is unclear about" if gap.effective_verdict == "unclear" else "does not state"
        detail = f"The offer {verb} {gap.requirement_label.lower()}."
        if gap.effective_verdict == "unclear" and gap.effective_value:
            detail += f' It says: "{gap.effective_value}".'
        chase_items.append(
            ChaseItem(
                kind=ChaseItemKind.MANDATORY_GAP,
                title=gap.requirement_label,
                detail=detail,
                source_filename=gap.source_filename,
                source_page_number=gap.source_page_number,
            )
        )

    count = len(chase_items)
    if count == 0:
        headline = "Nothing to chase - every required term is stated and no findings were confirmed against the source."
    elif count == 1:
        headline = "One thing to chase before this offer can go to sign-off."
    else:
        headline = f"{count} things to chase before this offer can go to sign-off."

    project_label = project_label_of(offer.project_name_entered, offer.project_name_original)
    subject_scope = " / ".join(part for part in (offer.offer_ref, offer.rfq_number) if part)
    email_subject = (
        f"{subject_scope} — {count} point(s) to confirm before sign-off"
        if subject_scope
        else f"Offer #{offer_id} — {count} point(s) to confirm before sign-off"
    )

    supplier = await db.get(Supplier, offer.supplier_id) if offer.supplier_id is not None else None
    email_body = _compose_email_body(
        offer_ref=offer.offer_ref,
        project_label=project_label,
        supplier_name=supplier.supplier_name if supplier else None,
        chase_items=chase_items,
    )

    return {
        "review_chase_items": [item.model_dump(mode="json") for item in chase_items],
        "review_headline": headline,
        "review_email_subject": email_subject,
        "review_email_body": email_body,
        "review_summary_generated_at": datetime.now(timezone.utc),
    }


def _compose_email_body(
    *,
    offer_ref: str | None,
    project_label: str | None,
    supplier_name: str | None,
    chase_items: list[ChaseItem],
) -> str:
    greeting = "Dear Sir/Madam," if not supplier_name else f"Dear colleagues at {supplier_name},"
    subject_line = offer_ref or "your offer"
    if not chase_items:
        return (
            f"{greeting}\n\n"
            f"Thank you for {subject_line}"
            f"{f' for {project_label}' if project_label else ''}. We have completed our review and "
            "have no outstanding points to raise at this time.\n\n"
            "Kind regards,"
        )
    intro = (
        f"Thank you for {subject_line}"
        f"{f' for {project_label}' if project_label else ''}. Before we can proceed to sign-off, "
        f"could you please confirm the following point{'s' if len(chase_items) > 1 else ''}:\n"
    )
    numbered = "\n".join(f"{i}. {item.title} — {item.detail}" for i, item in enumerate(chase_items, start=1))
    return f"{greeting}\n\n{intro}\n{numbered}\n\nKind regards,"


def make_summary_node(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
) -> Callable[[PipelineState], Awaitable[PipelineState]]:
    """Builds the node that writes the offer's chase list and email draft.

    Runs after taxonomy and completeness, not alongside them: the chase list
    reads their results, and running earlier would mean summarising an offer
    against gaps that had not been checked for yet. No LLM call - see
    `build_review_summary`'s own docstring.

    Runs AFTER persist and swallows its own failures, the same rule
    taxonomy/completeness apply and for the same reason: the offer is already
    saved, and a reviewer can regenerate this alone from the offer page - it
    must never take a successful extraction down with it.
    """

    async def summary_node(state: PipelineState) -> PipelineState:
        offer_id = state["offer_id"]
        await progress.start_stage(STAGE_ID, "composing the summary")

        try:
            async with session_factory() as db:
                offer = await db.get(Offer, offer_id)
                fields = await build_review_summary(db, offer_id)
                for key, value in fields.items():
                    setattr(offer, key, value)
                await db.commit()
        except JobCancelled:
            raise
        except Exception as exc:
            logger.exception("summary stage failed for offer %s", offer_id)
            await progress.fail_stage(
                STAGE_ID,
                f"Could not compose the summary ({exc}). The offer is saved - "
                "re-run this from the offer page.",
            )
            return {}

        item_count = len(fields["review_chase_items"])
        await progress.finish_stage(
            STAGE_ID,
            "nothing to chase" if item_count == 0 else f"{item_count} item(s) to chase",
        )
        return {}

    return summary_node
